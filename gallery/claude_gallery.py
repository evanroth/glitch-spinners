#!/usr/bin/env python3
"""Claude preview: glitch spinner words exactly as Claude Code would show them.

The real spinnerVerbs setting holds plain strings. Claude Code picks one per
wait, draws its own spinning glyph in front and sweeps a shimmer across it.
So here every entry is frozen into the plain strings it would export, and
color, flashing and motion only come from Claude's own glyph and shimmer.

Every string is grown or trimmed to fill the line (the terminal width, or
--width N).

It works in rounds. Round 1 is built from what you liked in glitch_gallery.py
(color-only layers removed). Each next round carries over the previous
round's likes, plus mutations, breeds and new combos weighted toward the
effect families, params and noise sources liked so far. Each round has its
own state file, and the newest round opens by default.

    python3 gallery/claude_gallery.py              # resume the newest round
    python3 gallery/claude_gallery.py --next-round # build the next round from this round's likes
    python3 gallery/claude_gallery.py --round 1    # go back to an earlier round
    python3 gallery/claude_gallery.py --print 20   # print 20 entries once, no UI

Standard library only (Python 3.9+), macOS/Linux terminals.
"""
import argparse
import glob
import json
import os
import random
import shutil
import sys
import time
import unicodedata
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glitch_gallery as g  # noqa: E402

HERE = g.HERE
LIKES_FILE = g.STATE_FILE  # glitch_gallery.py's state, read only


def round_file(n):
    return os.path.join(HERE, "claude-state.json" if n == 1 else "claude-round-%d.json" % n)


def rounds():
    found = [1] if os.path.exists(round_file(1)) else []
    for f in glob.glob(os.path.join(HERE, "claude-round-*.json")):
        try:
            found.append(int(os.path.basename(f)[13:-5]))
        except ValueError:
            pass
    return sorted(found)

ORANGE, SHINE, GRAY = 173, 216, 244  # Claude's spinner orange, its shimmer, the timer
GLYPHS = "·✢✳✶✻✽✽✻✶✳✢·"             # Claude Code's spinner cycle
FPS = 10                              # glyph moves every 2 ticks (200 ms), shimmer 1.5 cells a tick
STYLE_ONLY = {"color", "bg", "attrs", "flash"}  # nothing left of these in a plain string
CHAR_FX = [f for f in g.FX if f not in STYLE_ONLY]


# --------------------------------------------------------------------------
# What Claude would show
# --------------------------------------------------------------------------

def cluster_width(c):
    if "\ufe0f" in c:
        return 2
    cat = unicodedata.category(c[0])
    if cat in ("Mn", "Me", "Cf"):
        return 0
    return 2 if unicodedata.east_asian_width(c[0]) in "WF" else 1


def width(s):
    return sum(cluster_width(c) for c in clusters(s))


def fill(e, reseed, t, cols):
    """Grow the entry's noise string until the glitched result fills cols, then trim to fit."""
    src = g.entry_source(e)[0]
    n, v = 12, ""
    for _ in range(8):
        text = g.source_text(src, e["seed"] + reseed, n)
        v = g.plain(g.frame_cells(e, text, t, calm=True)).strip()
        w = width(v)
        if cols - 2 <= w <= cols:
            break
        m = max(1, round(n * cols / max(w, 1)))
        n = m if m != n else n + (1 if w < cols else -1)
    cs = clusters(v)
    while cs and sum(map(cluster_width, cs)) > cols:
        cs.pop()
    return "".join(cs).strip()


def verbs_of(e, cols=0, _cache={}):
    """The plain strings an entry exports: 3 noise strings x 3 frozen frames.
    cols > 0 fills that many columns, otherwise the entry's own length."""
    key = (e["id"], cols)
    if key not in _cache:
        vs = []
        for reseed in range(3):
            text = g.entry_text(e, None, reseed)
            for t in (0, 7, 19):
                v = fill(e, reseed, t, cols) if cols else g.plain(g.frame_cells(e, text, t, calm=True)).strip()
                if v and v not in vs:
                    vs.append(v)
        _cache[key] = vs or ["·"]
    return _cache[key]


def clusters(s):
    """Split into what the shimmer moves over: a base char plus its marks and joiners."""
    out = []
    for ch in s:
        if out and (unicodedata.category(ch) in ("Mn", "Me") or ch in "‍️"
                    or out[-1].endswith("‍") or 0x1F3FB <= ord(ch) <= 0x1F3FF):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def claude_line(verb, tick, chrome=False, seconds=12):
    """Glyph, the verb with a moving shimmer, and optionally the timer."""
    word = clusters(verb) + ["…"]
    hot = int(tick * 1.5) % (len(word) + 12) - 4
    out = [g.sgr(0, 38, 5, ORANGE) + GLYPHS[(tick // 2) % len(GLYPHS)] + " "]
    last = None
    for i, ch in enumerate(word):
        color = SHINE if abs(i - hot) <= 1 else ORANGE
        if color != last:
            out.append(g.sgr(0, 38, 5, color))
            last = color
        out.append(ch)
    if chrome:
        out.append(g.sgr(0, 38, 5, GRAY) + " (%ds · esc to interrupt)" % seconds)
    return "".join(out) + g.sgr(0)


# --------------------------------------------------------------------------
# Leaning into what was liked
# --------------------------------------------------------------------------

def char_layers(e):
    return [l for l in e["layers"] if l["fx"] in CHAR_FX]


class Profile:
    def __init__(self, liked):
        self.fam, self.src, self.params = Counter(), Counter(), defaultdict(list)
        for e in liked:
            for l in char_layers(e):
                self.fam[l["fx"]] += 1
                self.params[l["fx"]].append(l["p"])
            self.src[g.entry_source(e)[0]] += 1

    def pick_fx(self, rng, exclude=()):
        names = [f for f in CHAR_FX if f not in exclude]
        return rng.choices(names, [self.fam[f] * 3 + 0.4 for f in names])[0]

    def layer(self, rng, name):
        spec = g.FX[name]["spec"]
        if self.params[name] and rng.random() < 0.8:
            p = g.mutate_params(spec, rng.choice(self.params[name]), rng)
        else:
            p = g.rand_params(spec, rng)
        return {"fx": name, "p": p}

    def pick_src(self, rng, layers):
        if any(l["fx"] in g.LETTER_FX for l in layers) and rng.random() < 0.6:
            return rng.choice(["consonants", "mixed"])
        names = list(g.SOURCES)
        return rng.choices(names, [self.src[n] * 3 + 0.3 for n in names])[0]


class Gallery(g.Gallery):
    profile = Profile([])

    def new(self, rng, layers, origin, parent=None, glyph=None, src=None, n=None):
        layers = [l for l in layers if l["fx"] in CHAR_FX] or [self.profile.layer(rng, self.profile.pick_fx(rng))]
        return super().new(rng, layers, origin, parent, "claude",
                           src or self.profile.pick_src(rng, layers), n)

    def random_combo(self, rng):
        names = []
        for _ in range(rng.choice([1, 2, 2, 3, 3, 4])):
            names.append(self.profile.pick_fx(rng, names))
        return self.new(rng, [self.profile.layer(rng, n) for n in names], "combo")

    def mutate(self, e, rng):
        layers = [{"fx": l["fx"], "p": g.mutate_params(g.FX[l["fx"]]["spec"], l["p"], rng)} for l in char_layers(e)]
        if rng.random() < 0.3:
            name = self.profile.pick_fx(rng, [l["fx"] for l in layers])
            layers.insert(rng.randrange(len(layers) + 1), self.profile.layer(rng, name))
        if len(layers) > 1 and rng.random() < 0.2:
            layers.pop(rng.randrange(len(layers)))
        src, n = g.entry_source(e)
        if rng.random() < 0.25:
            src = self.profile.pick_src(rng, layers)
        n = max(3, min(16, n + rng.randint(-3, 3)))
        return self.new(rng, layers, "mutation", parent=e["id"], src=src, n=n)

    def build(self, liked, rng, prev_round, mutations=2, combos=30, breeds=20):
        """The previous round's likes (style layers dropped), mutations of each, then new ones."""
        skipped = []
        for old in liked:
            if not char_layers(old):
                skipped.append(old["id"])
                continue
            src, n = g.entry_source(old)
            e = self.new(rng, char_layers(old), "liked", src=src, n=n)
            e.update(seed=old["seed"], rating=1, was=old["id"], was_round=prev_round)
            self.entries += [e] + [self.mutate(e, rng) for _ in range(mutations)]
        mine = [e for e in self.entries if e["rating"] > 0]
        if mine:
            self.entries += [self.breed(rng.choice(mine), rng.choice(mine), rng) for _ in range(breeds)]
        self.entries += [self.random_combo(rng) for _ in range(combos)]
        return skipped


def load_entries(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return g.Gallery.from_json(json.load(f)).entries


def all_likes(upto):
    """Liked entries from the first gallery and rounds before upto (carried-over copies count once)."""
    liked = [e for e in load_entries(LIKES_FILE) if e["rating"] > 0]
    for n in rounds():
        if n < upto:
            liked += [e for e in load_entries(round_file(n)) if e["rating"] > 0 and not e.get("was")]
    return liked


def save(gallery, path, extra):
    data = gallery.to_json()
    data.update(extra)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def export_liked(gallery, cols):
    liked = [e for e in gallery.entries if e["rating"] > 0]
    verbs, notes = [], []
    for e in liked:
        notes.append("#%d %s on %s" % (e["id"], g.entry_name(e), g.entry_source(e)[0]))
        for v in verbs_of(e, cols):
            if v not in verbs:
                verbs.append(v)
                notes.append("    " + v)
    with open(g.EXPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"mode": "replace", "verbs": verbs}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(g.EXPORT_NOTES, "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")
    return len(liked), len(verbs)


# --------------------------------------------------------------------------
# Terminal UI (the run loop, key reading and mouse handling come from glitch_gallery)
# --------------------------------------------------------------------------

HELP = """
  CLAUDE PREVIEW: keys

  ↑ ↓  j k  scroll wheel     move              enter / →     focus view (← back)
  PgUp PgDn  u d             page              click         select
  space  f                   like ★            x             nope ✗ (dims it)
  r                          next wait: every row shows another of its strings
  m                          mutate: 6 variations of this one, added below it
  L                          breed: 8 new ones mixed from everything you liked
  n                          8 new combos, weighted toward what you liked
  o                          filter: all / liked / hide noped
  c                          show / hide the timer after the word
  < >                        shorter / longer lines (default: fill the terminal)
  p                          pause
  e                          export liked ones to spinner-verbs.json
  ?                          this help                q   quit (saves)

  Everything here is a plain string, the way spinnerVerbs stores it. The
  orange, the spinning glyph and the shimmer are Claude Code's own. Claude
  picks one string per wait (as far as we know), so a row only changes when
  you press r. Each entry exports up to 9 strings (focus view lists them).
  Strings are grown or trimmed to the line width shown in the title bar,
  and export uses that width too.

  Ratings are saved per round (gallery/claude-state.json is round 1,
  then claude-round-2.json…). --next-round builds the next one.

  Press any key.
"""


class UI:
    calm = False

    def __init__(self, gallery, wait=0, rnd=1, cols=None):
        self.g = gallery
        self.round = rnd
        self.fixed_cols = cols
        self.fps = FPS
        self.paused = False
        self.clock = 0.0
        self.sel = self.top = 0
        self.wait = wait
        self.filter = "all"
        self.view = "list"
        self.chrome = False
        self.msg = "? for keys · r = next wait · enter = every string this entry exports"
        self.msg_until = time.time() + 8
        self.running = True
        self.rng = random.Random()
        self.row_map = {}

    def visible(self):
        es = self.g.entries
        if self.filter == "liked":
            return [i for i, e in enumerate(es) if e["rating"] > 0]
        if self.filter == "hide":
            return [i for i, e in enumerate(es) if e["rating"] >= 0]
        return list(range(len(es)))

    def current(self):
        vis = self.visible()
        if not vis:
            return None, vis
        self.sel = max(0, min(self.sel, len(vis) - 1))
        return self.g.entries[vis[self.sel]], vis

    def say(self, msg):
        self.msg, self.msg_until = msg, time.time() + 4

    def cols(self):
        """Width the strings fill: the terminal minus Claude's glyph, space and ellipsis."""
        if self.fixed_cols:
            return self.fixed_cols
        return max(10, shutil.get_terminal_size((100, 30)).columns - 5)

    def verb(self, e):
        vs = verbs_of(e, self.cols())
        return vs[(self.wait + e["id"]) % len(vs)]

    def persist(self):
        save(self.g, round_file(self.round), {"wait": self.wait, "round": self.round})

    def adopt_likes(self):
        """Keep breeding toward everything liked so far, this round and before."""
        Gallery.profile = Profile(all_likes(self.round) + [e for e in self.g.entries if e["rating"] > 0])

    def key(self, k):
        if self.view == "help":
            self.view = "list"
            return
        e, vis = self.current()
        page = max(1, shutil.get_terminal_size((100, 30)).lines // 2 - 3)
        if isinstance(k, tuple):
            _, b, x, y, kind = k
            if b == 64:
                self.sel -= 1
            elif b == 65:
                self.sel += 1
            elif b == 0 and kind == "M" and self.view == "list" and y in self.row_map:
                self.sel = self.row_map[y]
            return
        if k == "q":
            self.running = False
        elif k in ("up", "k"):
            self.sel -= 1
        elif k in ("down", "j"):
            self.sel += 1
        elif k in ("pgup", "u"):
            self.sel -= page
        elif k in ("pgdn", "d"):
            self.sel += page
        elif k == "home":
            self.sel = 0
        elif k == "end":
            self.sel = len(vis) - 1
        elif k in ("\n", "\r", "right") and self.view == "list":
            self.view = "focus"
        elif k in ("esc", "left") and self.view == "focus":
            self.view = "list"
        elif k == "?":
            self.view = "help"
        elif k in (" ", "f") and e:
            e["rating"] = 0 if e["rating"] > 0 else 1
            self.say("★ liked #%d" % e["id"] if e["rating"] > 0 else "unliked #%d" % e["id"])
            self.persist()
        elif k == "x" and e:
            e["rating"] = 0 if e["rating"] < 0 else -1
            self.say("✗ noped #%d" % e["id"] if e["rating"] < 0 else "un-noped #%d" % e["id"])
            self.persist()
        elif k == "r":
            self.wait += 1
            self.say("wait %d: every row picked another of its strings" % self.wait)
        elif k == "m" and e:
            self.adopt_likes()
            pos = self.g.entries.index(e) + 1
            self.g.entries[pos:pos] = [self.g.mutate(e, self.rng) for _ in range(6)]
            self.filter = "all" if self.filter == "liked" else self.filter
            self.sel = self.visible().index(pos)
            self.say("6 mutations of #%d added below it" % e["id"])
            self.persist()
        elif k == "L":
            liked = [x for x in self.g.entries if x["rating"] > 0]
            if not liked:
                self.say("Like a few first (space), then L breeds new ones from them")
                return
            self.adopt_likes()
            self.g.entries += [self.g.breed(self.rng.choice(liked), self.rng.choice(liked), self.rng) for _ in range(8)]
            self.filter = "all"
            self.sel = len(self.g.entries) - 8
            self.say("8 new ones bred from %d liked" % len(liked))
            self.persist()
        elif k == "n":
            self.adopt_likes()
            self.g.entries += [self.g.random_combo(self.rng) for _ in range(8)]
            self.filter = "all"
            self.sel = len(self.g.entries) - 8
            self.say("8 new combos, weighted toward your likes")
            self.persist()
        elif k == "o":
            self.filter = {"all": "liked", "liked": "hide", "hide": "all"}[self.filter]
            self.sel = 0
            self.say({"all": "showing all", "liked": "showing liked only", "hide": "hiding noped"}[self.filter])
        elif k == "c":
            self.chrome = not self.chrome
        elif k in ("<", ">"):
            self.fixed_cols = max(10, self.cols() + (-8 if k == "<" else 8))
            self.say("lines %d columns wide" % self.fixed_cols)
        elif k == "p":
            self.paused = not self.paused
            self.say("paused" if self.paused else "playing")
        elif k == "e":
            n, v = export_liked(self.g, self.cols())
            self.say("exported %d liked → %d strings in spinner-verbs.json (see gallery/liked-frames.txt)" % (n, v))

    def draw(self, out):
        cols, lines = shutil.get_terminal_size((100, 30))
        tick = int(self.clock * self.fps)
        e, vis = self.current()
        liked = sum(1 for x in self.g.entries if x["rating"] > 0)
        title = " CLAUDE PREVIEW  round %d  %d entries  ★ %d liked  wait %d  lines %d cols%s " % (
            self.round, len(self.g.entries), liked, self.wait, self.cols(), "  PAUSED" if self.paused else "")
        rows = [g.sgr(0, 7, 1) + title.ljust(cols) + g.sgr(0),
                g.sgr(0, 2) + " ↑↓ scroll · space like · x nope · r next wait · m mutate · L breed · enter focus · ? help · q quit" + g.sgr(0)]
        self.row_map = {}
        if self.view == "help":
            rows += [g.sgr(0) + l for l in HELP.split("\n")]
        elif not vis:
            rows += ["", "  Nothing to show with this filter. Press o."]
        elif self.view == "focus":
            rows += self.focus_rows(e, tick, cols)
        else:
            rows += self.list_rows(vis, tick, lines)
        while len(rows) < lines - 1:
            rows.append("")
        rows = rows[:lines - 1]
        if time.time() < self.msg_until:
            status = g.sgr(0, 33) + " " + self.msg
        elif e:
            status = g.sgr(0, 2) + " #%d  %s  on %s  %s%s" % (
                e["id"], g.entry_name(e), g.entry_source(e)[0], e.get("origin", ""),
                was(e))
        else:
            status = ""
        rows.append(status + g.sgr(0))
        buf = ["\x1b[?2026h"]
        for i, r in enumerate(rows):
            buf.append("\x1b[%d;1H\x1b[2K%s" % (i + 1, r))
        buf.append(g.sgr(0) + "\x1b[?2026l")
        out.write("".join(buf))
        out.flush()

    def list_rows(self, vis, tick, lines):
        n = max(1, (lines - 4) // 2)
        if self.sel < self.top:
            self.top = self.sel
        if self.sel >= self.top + n:
            self.top = self.sel - n + 1
        self.top = max(0, min(self.top, max(0, len(vis) - n)))
        rows = [""]
        for vi in range(self.top, min(len(vis), self.top + n)):
            e = self.g.entries[vis[vi]]
            is_sel = vi == self.sel
            mark = g.sgr(0, 1, 97) + "▶" if is_sel else " "
            rate = (g.sgr(0, 38, 5, 226) + "★" if e["rating"] > 0 else
                    g.sgr(0, 38, 5, 160) + "✗" if e["rating"] < 0 else " ")
            style = g.sgr(0, 1, 97) if is_sel else (g.sgr(0, 2) if e["rating"] < 0 else g.sgr(0, 38, 5, 250))
            label = mark + rate + style + "%4d %s" % (e["id"], g.entry_name(e)) + g.sgr(0, 2) + "  " + g.entry_source(e)[0] + g.sgr(0)
            if e["rating"] < 0 and not is_sel:
                line = g.sgr(0, 2) + GLYPHS[0] + " " + self.verb(e) + "…" + g.sgr(0)
            else:
                line = claude_line(self.verb(e), tick + e["id"] * 5, self.chrome)
            for r in (label, "  " + line):
                self.row_map[len(rows) + 1] = vi
                rows.append(r)
        return rows

    def focus_rows(self, e, tick, cols):
        star = "★ liked" if e["rating"] > 0 else ("✗ noped" if e["rating"] < 0 else "")
        rows = ["", g.sgr(0, 1) + "  #%d  %s  " % (e["id"], g.entry_name(e)) + g.sgr(0, 38, 5, 226) + star + g.sgr(0),
                g.sgr(0, 2) + "  origin: %s%s · source: %s" % (
                    e.get("origin", ""), " of #%s" % e["parent"] if e.get("parent") else was(e),
                    g.entry_source(e)[0]) + g.sgr(0)]
        for l in e["layers"]:
            ps = ", ".join("%s=%s" % (k, v) for k, v in l["p"].items())
            rows.append(g.sgr(0, 2) + "    %-10s " % l["fx"] + g.sgr(0) + ps[:cols - 20])
        w = min(60, cols - 6)
        rows += ["", g.sgr(0, 38, 5, 75) + "  ~/code/my-app " + g.sgr(0, 38, 5, 114) + "$ " + g.sgr(0) + "claude", "",
                 g.sgr(0, 2) + "  > fix the failing tests" + g.sgr(0), "",
                 "  ● I'll run the test suite first to see what's failing.", "",
                 "  " + claude_line(self.verb(e), tick, True, 7 + tick // FPS), "",
                 g.sgr(0, 38, 5, 242) + "  ╭" + "─" * w + "╮" + g.sgr(0),
                 g.sgr(0, 38, 5, 242) + "  │ " + g.sgr(0) + "> " + g.sgr(0, 38, 5, 242) + " " * (w - 3) + "│" + g.sgr(0),
                 g.sgr(0, 38, 5, 242) + "  ╰" + "─" * w + "╯" + g.sgr(0), "",
                 g.sgr(0, 1) + "  Every string this entry exports (Claude picks one per wait)" + g.sgr(0)]
        for i, v in enumerate(verbs_of(e, self.cols())):
            rows.append("  " + claude_line(v, tick + i * 4))
        rows += ["", g.sgr(0, 2) + "  ← back · ↑↓ previous/next · space like · x nope · m mutate · r next wait" + g.sgr(0)]
        return rows


def was(e):
    if not e.get("was"):
        return ""
    r = e.get("was_round", 0)
    return " (#%d in %s)" % (e["was"], "round %d" % r if r else "the first gallery")


def main():
    ap = argparse.ArgumentParser(description="Preview glitch spinner words the way Claude Code shows them.")
    ap.add_argument("--next-round", action="store_true", help="build a new round from the newest round's likes")
    ap.add_argument("--round", type=int, help="open this round instead of the newest")
    ap.add_argument("--width", type=int, help="fill this many columns (default: the terminal width)")
    ap.add_argument("--seed", type=int, help="seed for building a round")
    ap.add_argument("--print", type=int, metavar="N", help="print N entries once and exit (no UI)")
    ap.add_argument("--plain", action="store_true", help="with --print: no color codes")
    args = ap.parse_args()

    have = rounds()
    rnd = args.round or (have[-1] if have else 1)
    if args.next_round or not have:
        prev = rnd if have else 0
        rnd = prev + 1
        if os.path.exists(round_file(rnd)):
            sys.exit("Round %d already exists. Open it with --round %d." % (rnd, rnd))
        carry = [e for e in (load_entries(round_file(prev)) if prev else load_entries(LIKES_FILE)) if e["rating"] > 0]
        if not carry:
            sys.exit("No likes to build round %d from." % rnd)
        Gallery.profile = Profile(all_likes(rnd))
        gallery = Gallery()
        if prev:
            skipped = gallery.build(carry, random.Random(args.seed), prev, mutations=1, combos=40, breeds=40)
        else:
            skipped = gallery.build(carry, random.Random(args.seed), prev)
        save(gallery, round_file(rnd), {"wait": 0, "round": rnd})
        print("Built round %d: %d entries from %d likes." % (rnd, len(gallery.entries), len(carry)))
        if skipped:
            print("Left out (color only, nothing survives as plain text): #" + ", #".join(map(str, skipped)))
        wait = 0
    else:
        if rnd not in have:
            sys.exit("No round %d. Rounds: %s" % (rnd, ", ".join(map(str, have))))
        with open(round_file(rnd), encoding="utf-8") as f:
            data = json.load(f)
        gallery, wait = Gallery.from_json(data), data.get("wait", 0)
    Gallery.profile = Profile(all_likes(rnd) + [e for e in gallery.entries if e["rating"] > 0])

    if args.print:
        cols = args.width or shutil.get_terminal_size((100, 30)).columns - 5
        for e in gallery.entries[:args.print]:
            vs = verbs_of(e, cols)
            v = vs[(wait + e["id"]) % len(vs)]
            print("%4d %s %s" % (e["id"], "★" if e["rating"] > 0 else " ", g.entry_name(e)))
            print("     " + (GLYPHS[4] + " " + v + "…" if args.plain else claude_line(v, 3)))
        return
    if not sys.stdin.isatty():
        if args.next_round:
            return
        sys.exit("Run this in a terminal (or use --print N).")
    g.run(UI(gallery, wait, rnd, args.width))


if __name__ == "__main__":
    main()
