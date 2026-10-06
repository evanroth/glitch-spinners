#!/usr/bin/env python3
"""Glitch gallery: scroll through animated, broken-looking spinner text for
Claude Code, and mark what you like.

    python3 gallery/glitch_gallery.py              # resume where you left off
    python3 gallery/glitch_gallery.py --fresh      # start a new gallery
    python3 gallery/glitch_gallery.py --text "Pondering"
    python3 gallery/glitch_gallery.py --print 20   # print 20 entries once, no UI

Press ? inside for the keys. WARNING: contains fast flashing and strobing.
Press s for calm mode (slower, no strobe).

Standard library only (Python 3.9+), macOS/Linux terminals.
"""
import argparse
import json
import os
import random
import re
import select
import shutil
import sys
import termios
import time
import tty
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE_FILE = os.path.join(HERE, "gallery-state.json")
EXPORT_FILE = os.path.join(ROOT, "spinner-verbs.json")
EXPORT_NOTES = os.path.join(HERE, "liked-frames.txt")

ORANGE, SHINE, GRAY, DARK = 173, 216, 244, 238
# The words Claude Code ships with. Only used to drop them from old state files:
# the gallery never shows readable words, each entry glitches a string of noise.
OLD_SAMPLE_TEXTS = ["Thinking", "Pondering", "Spelunking", "Combobulating",
                    "Reticulating splines", "Confidently making things up"]


# --------------------------------------------------------------------------
# Cells: one visible character (plus any combining marks) and its style
# --------------------------------------------------------------------------

class Cell:
    __slots__ = ("ch", "fg", "bg", "at")

    def __init__(self, ch, fg=None, bg=None, at=()):
        self.ch, self.fg, self.bg, self.at = ch, fg, bg, at

    def copy(self, **kw):
        c = Cell(self.ch, self.fg, self.bg, self.at)
        for k, v in kw.items():
            setattr(c, k, v)
        return c


def render(cells):
    """Cells -> string with 256-color ANSI codes."""
    out, last = [], None
    for c in cells:
        key = (c.fg, c.bg, c.at)
        if key != last:
            codes = ["0"]
            if c.fg is not None:
                codes.append("38;5;%d" % c.fg)
            if c.bg is not None:
                codes.append("48;5;%d" % c.bg)
            codes += [str(a) for a in c.at]
            out.append("\x1b[" + ";".join(codes) + "m")
            last = key
        out.append(c.ch)
    out.append("\x1b[0m")
    return "".join(out)


def plain(cells):
    return "".join(c.ch for c in cells)


# --------------------------------------------------------------------------
# Character data
# --------------------------------------------------------------------------

def _r(a, b):
    return [chr(c) for c in range(a, b + 1)]


MARKS_UP = _r(0x300, 0x315) + [chr(c) for c in (0x33D, 0x33E, 0x33F, 0x346, 0x34A, 0x34B, 0x34C,
                                                 0x350, 0x351, 0x352, 0x357, 0x35B)] + _r(0x363, 0x36F)
MARKS_DOWN = _r(0x316, 0x333) + _r(0x339, 0x33C) + [chr(c) for c in (
    0x345, 0x347, 0x348, 0x349, 0x34D, 0x34E, 0x353, 0x354, 0x355, 0x356, 0x359, 0x35A)]
MARKS_MID = _r(0x334, 0x338)
DRIP_MARKS = ["̩", "̧", "̨", "̣", "̤", "̱", "̲"]

CHARSETS = {
    "braille": _r(0x2801, 0x28FF),
    "katakana": _r(0xFF66, 0xFF9D),
    "box": list("─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬╳╱╲╭╮╯╰"),
    "blocks": list("█▓▒░▀▄▌▐▖▗▘▝▚▞▙▛▜▟"),
    "noise": list("¤§¶†‡※‽⁂⌁⌂⌇⌖⌘⍰⍾⎔⏚⏛␀␛␡�¿¡ǂǁʘ"),
    "binary": list("01"),
    "hex": list("0123456789ABCDEF"),
    "cjk": _r(0x4E00, 0x4FFF),
    "math": list("∀∁∂∃∄∅∆∇∈∉∊∋∌∍∎∏∐∑∓∔∖∗∘√∛∜∝∞∟∠∡∢∣∤∥∦∧∨∩∪∫∬∭∮∯∰∱∲∳∴∵∶∷∸∹∺∻∼∽∾∿≀≁"),
    "runes": _r(0x16A0, 0x16EA),
    "geometric": list("◆◇◈◉◊○◌◍◎●◐◑◒◓◔◕◖◗◘◙◚◛◜◝◞◟◠◡◢◣◤◥◦◧◨◩◪◫◬◭◮◯"),
}


def _math(upper, lower, digits=None):
    def f(ch):
        if "A" <= ch <= "Z":
            cp = upper + ord(ch) - 65
        elif "a" <= ch <= "z":
            cp = lower + ord(ch) - 97
        elif digits and "0" <= ch <= "9":
            cp = digits + ord(ch) - 48
        else:
            return ch
        try:
            unicodedata.name(chr(cp))  # skip holes in the math alphabets
            return chr(cp)
        except ValueError:
            return ch
    return f


def _table(src, dst):
    assert len(src) == len(dst), (src, dst)
    return dict(zip(src, dst))


SMALLCAPS = _table("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ")
UPSIDE = _table("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.,!?",
                "ɐqɔpǝɟƃɥᴉɾʞlɯuodbɹsʇnʌʍxʎz∀ꓭƆꓷƎℲ⅁HIſꓘ˥WNOԀꝹꓤSꓕՈΛMX⅄Z˙'¡¿")
HOMOGLYPHS = {"a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "i": "і",
              "j": "ј", "s": "ѕ", "h": "һ", "d": "ԁ", "g": "ɡ", "l": "ӏ", "n": "ո", "u": "υ",
              "v": "ν", "w": "ԝ", "A": "Α", "B": "Β", "C": "С", "E": "Ε", "H": "Η", "I": "Ι",
              "K": "Κ", "M": "Μ", "N": "Ν", "O": "Ο", "P": "Ρ", "T": "Τ", "X": "Χ", "Y": "Υ", "Z": "Ζ"}

FONTS = {
    "plain": lambda ch: ch,
    "bold": _math(0x1D400, 0x1D41A, 0x1D7CE),
    "italic": _math(0x1D434, 0x1D44E),
    "bolditalic": _math(0x1D468, 0x1D482),
    "script": _math(0x1D49C, 0x1D4B6),
    "boldscript": _math(0x1D4D0, 0x1D4EA),
    "fraktur": _math(0x1D504, 0x1D51E),
    "double": _math(0x1D538, 0x1D552, 0x1D7D8),
    "boldfraktur": _math(0x1D56C, 0x1D586),
    "sans": _math(0x1D5A0, 0x1D5BA, 0x1D7E2),
    "sansbold": _math(0x1D5D4, 0x1D5EE, 0x1D7EC),
    "mono": _math(0x1D670, 0x1D68A, 0x1D7F6),
    "fullwidth": lambda ch: chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else ch,
    "circled": _math(0x24B6, 0x24D0),
    "negcircled": _math(0x1F150, 0x1F150),
    "squared": _math(0x1F130, 0x1F130),
    "negsquared": _math(0x1F170, 0x1F170),
    "parens": _math(0x1F110, 0x249C),
    "smallcaps": lambda ch: SMALLCAPS.get(ch.lower(), ch) if ch.isalpha() else ch,
}
FONT_POOLS = {
    "math": ["bold", "italic", "bolditalic", "script", "boldscript", "fraktur", "double",
             "boldfraktur", "sans", "sansbold", "mono"],
    "boxes": ["circled", "negcircled", "squared", "negsquared", "parens", "fullwidth"],
    "width": ["plain", "fullwidth"],
    "all": [f for f in FONTS if f != "plain"],
}

EMOJI = {
    "dread": ["💀", "👁️", "🫠", "🕳️", "🩸", "🦷", "🧿", "🪬", "⛓️", "🫥"],
    "bugs": ["🐛", "🪲", "🐞", "🦠", "🕷️", "🪳", "🐜"],
    "eyes": ["👁️", "👀", "🫣", "🧿", "👁️‍🗨️"],
    "faces": ["😵", "🤯", "😵‍💫", "🫨", "🥴", "😶‍🌫️", "🤖", "👾"],
    "warning": ["⚠️", "⛔", "🚫", "☢️", "☣️", "🚨", "❌", "‼️", "⁉️"],
    "tech": ["💾", "📟", "🖥️", "🔌", "🧲", "📡", "🛰️", "🧮", "💿"],
}
EMOJI["mixed"] = [e for v in EMOJI.values() for e in v]

MOJIBAKE = ["Ã¢", "â€™", "â€œ", "Ã©", "Ã", "Â", "ï¿½", "�", "â–ˆ", "Ã¤", "â€¦", "ã‚", "Ð", "Ñ", "Ã¶", "ðŸ"]
ERRORS = ["0x00", "0xFF", "0x7F3A", "-1", "∅", "¯\\_(ツ)_/¯", "^@^@", "\\0", "%%%", "[]", "{}", "<?>",
          "#!", "&&", "���", "/**/", "::", "===", "␀␀", "⌧", "-0", "1e-308", "%s%n", "${}"]
ENCLOSE = {"circle": "⃝", "square": "⃞", "diamond": "⃟", "prohibit": "⃠",
           "screen": "⃢", "keycap": "⃣", "triangle": "⃤"}
INVISIBLE = {"zwsp": "​", "zwj": "‍", "shy": "­", "vs16": "️", "cgj": "͏", "skin": "🏽"}
COLORS = {
    "rainbow": [196, 202, 208, 214, 220, 226, 190, 154, 118, 82, 46, 47, 48, 49, 50, 51, 45, 39, 33, 27,
                21, 57, 93, 129, 165, 201, 200, 199, 198, 197],
    "fire": [196, 202, 208, 214, 220, 226, 160, 124],
    "ice": [51, 45, 39, 33, 123, 159, 195, 231],
    "toxic": [46, 82, 118, 154, 190, 226, 40, 34],
    "corrupt": [201, 51, 46, 226, 196],
}
# What each entry glitches instead of a word. "consonants" has no vowels so it
# can't spell anything, but gives the letter effects (fonts, homoglyph, case,
# regional, upside-down) Latin letters to work on.
SOURCES = {
    "consonants": list("bcdfghjklmnpqrstvwxzbcdfghklmnprstvwxzBCDFGHKLMNPRSTVWXZ"),
    "mixed": list("bcdfghjklmnpqrstvwxzBDFGHKQXZ0123456789#%&*/_-=+<>~^|\\"),
    "symbols": list("#%&*/_-=+<>~^|\\@$!?:;"),
    "digits": list("0123456789"),
    "dots": list("·.:˙⋅∙•‥…⁘⁙⁚"),
}
SOURCES.update(CHARSETS)
SOURCES["emoji"] = EMOJI["mixed"]
SOURCE_WEIGHTS = {"consonants": 6, "mixed": 4}  # the rest get 1
LETTER_FX = {"fonts", "homoglyph", "case", "regional", "flip", "hexleak"}


def source_text(src, seed, n):
    r = random.Random(seed * 31 + 7)
    pool = SOURCES[src]
    return "".join(r.choice(pool) for _ in range(n))


def rand_source(rng, layers=()):
    if any(l["fx"] in LETTER_FX for l in layers) and rng.random() < 0.8:
        return rng.choice(["consonants", "consonants", "mixed"])
    names = list(SOURCES)
    return rng.choices(names, [SOURCE_WEIGHTS.get(n, 1) for n in names])[0]


def entry_source(e):
    if e.get("src") not in SOURCES:  # entries from before sources existed
        e["src"] = rand_source(random.Random(e["seed"]), e["layers"])
        e["len"] = random.Random(e["seed"] + 1).randint(4, 12)
    return e["src"], e["len"]


def entry_text(e, override=None, reseed=0):
    """The string an entry glitches: its own source, another source, or typed text."""
    src, n = entry_source(e)
    if override in SOURCES:
        src = override
    elif override:
        return override
    return source_text(src, e["seed"] + reseed, n)


GLYPHS = {
    "claude": list("·✢✳✶✻✽✽✻✶✳✢·"),
    "braille": list("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"),
    "blocks": list("▖▘▝▗▚▞▙▛▜▟█▓▒░"),
    "geo": list("◐◓◑◒"),
    "chaos": None,
    "eye": ["👁️", "👀", "🫣", "🧿"],
    "warn": ["⚠️", "⛔", "☢️", "☣️", "🚨"],
    "none": [""],
}


# --------------------------------------------------------------------------
# Effects. Each takes (cells, params, frame, rng, seed) and returns cells.
# kind: T = changes the characters (survives as plain spinner text),
#       S = color/style only (needs ANSI), M = motion (needs animation).
# --------------------------------------------------------------------------

FX = {}


def I(lo, hi):
    return ("int", lo, hi)


def F(lo, hi):
    return ("float", lo, hi)


def C(*choices):
    return ("choice", list(choices))


def fx(_name, _kind, _blurb, **spec):
    def deco(func):
        FX[_name] = {"func": func, "kind": _kind, "blurb": _blurb, "spec": spec}
        return func
    return deco


def static_rng(seed, i):
    return random.Random(seed * 7919 + i * 104729)


@fx("zalgo", "T", "combining marks stacked above, through and below",
    up=I(0, 10), down=I(0, 10), mid=I(0, 2), rate=F(0.2, 1.0), flicker=C(True, False))
def _zalgo(cells, p, t, rng, seed):
    out = []
    for i, c in enumerate(cells):
        r = rng if p["flicker"] else static_rng(seed, i)
        if c.ch.strip() and r.random() < p["rate"]:
            marks = ([r.choice(MARKS_UP) for _ in range(r.randint(0, p["up"]))]
                     + [r.choice(MARKS_MID) for _ in range(r.randint(0, p["mid"]))]
                     + [r.choice(MARKS_DOWN) for _ in range(r.randint(0, p["down"]))])
            c = c.copy(ch=c.ch + "".join(marks))
        out.append(c)
    return out


@fx("fonts", "T", "math, fullwidth, circled and boxed alphabets",
    mode=C("word", "char", "wave", "static"), every=I(1, 6), pool=C(*FONT_POOLS))
def _fonts(cells, p, t, rng, seed):
    pool = [FONTS[n] for n in FONT_POOLS[p["pool"]]]
    step = t // p["every"]
    out = []
    for i, c in enumerate(cells):
        if p["mode"] == "word":
            f = pool[(step + seed) % len(pool)]
        elif p["mode"] == "char":
            f = rng.choice(pool)
        elif p["mode"] == "wave":
            f = pool[(i + step) % len(pool)]
        else:
            f = pool[(seed + i) % len(pool)]
        out.append(c.copy(ch=f(c.ch[:1]) + c.ch[1:]))
    return out


@fx("homoglyph", "T", "Cyrillic and Greek lookalike letters",
    rate=F(0.2, 1.0), flicker=C(True, False))
def _homoglyph(cells, p, t, rng, seed):
    out = []
    for i, c in enumerate(cells):
        r = rng if p["flicker"] else static_rng(seed, i)
        if r.random() < p["rate"] and c.ch[:1] in HOMOGLYPHS:
            c = c.copy(ch=HOMOGLYPHS[c.ch[:1]] + c.ch[1:])
        out.append(c)
    return out


@fx("rot", "T", "letters rot into braille, blocks, katakana, runes",
    rate=F(0.05, 0.8), charset=C(*CHARSETS), flicker=C(True, True, False))
def _rot(cells, p, t, rng, seed):
    cs = CHARSETS[p["charset"]]
    out = []
    for i, c in enumerate(cells):
        r = rng if p["flicker"] else static_rng(seed, i)
        out.append(c.copy(ch=r.choice(cs)) if r.random() < p["rate"] else c)
    return out


@fx("decode", "M", "text resolves out of noise, then dissolves again",
    period=I(8, 40), charset=C(*CHARSETS), color=C(True, False))
def _decode(cells, p, t, rng, seed):
    phase = (t % p["period"]) / p["period"]
    reveal = min(1.0, phase * 1.6) * len(cells)
    cs = CHARSETS[p["charset"]]
    return [c if i < reveal else c.copy(ch=rng.choice(cs), fg=46 if p["color"] else c.fg)
            for i, c in enumerate(cells)]


@fx("stutter", "M", "letters repeat like a skipping record",
    prob=F(0.1, 0.9), reps=I(1, 5), style=C("dash", "repeat", "echo"))
def _stutter(cells, p, t, rng, seed):
    if not cells or rng.random() > p["prob"]:
        return cells
    if p["style"] == "dash":
        k = rng.randint(1, min(3, len(cells)))
        pre = []
        for _ in range(p["reps"]):
            pre += [c.copy() for c in cells[:k]] + [cells[0].copy(ch="-")]
        return pre + cells
    if p["style"] == "repeat":
        i = rng.randrange(len(cells))
        return cells[:i] + [cells[i].copy() for _ in range(p["reps"])] + cells[i:]
    k = rng.randint(1, len(cells))
    pre = []
    for _ in range(p["reps"]):
        pre += [c.copy() for c in cells[:k]] + [cells[0].copy(ch=" ")]
    return pre + cells


def _fill(name, rng, n, like):
    if name == "space":
        return [like.copy(ch=" ") for _ in range(n)]
    return [like.copy(ch=rng.choice(CHARSETS[name])) for _ in range(n)]


@fx("jitter", "M", "the whole line twitches sideways",
    maxoff=I(1, 12), prob=F(0.2, 1.0), fill=C("space", "noise", "blocks", "braille"))
def _jitter(cells, p, t, rng, seed):
    if not cells or rng.random() > p["prob"]:
        return cells
    return _fill(p["fill"], rng, rng.randint(1, p["maxoff"]), cells[0]) + cells


@fx("tear", "M", "the word rips apart, sometimes swapping halves",
    prob=F(0.1, 0.9), gap=I(1, 8), fill=C("space", "noise", "blocks", "box"), swap=C(True, False))
def _tear(cells, p, t, rng, seed):
    if len(cells) < 2 or rng.random() > p["prob"]:
        return cells
    k = rng.randint(1, len(cells) - 1)
    a, b = cells[:k], cells[k:]
    if p["swap"] and rng.random() < 0.4:
        a, b = b, a
    return a + _fill(p["fill"], rng, rng.randint(1, p["gap"]), cells[0]) + b


@fx("shuffle", "M", "neighboring letters swap places",
    rate=F(0.05, 0.6))
def _shuffle(cells, p, t, rng, seed):
    cells = list(cells)
    for i in range(len(cells) - 1):
        if rng.random() < p["rate"]:
            cells[i], cells[i + 1] = cells[i + 1], cells[i]
    return cells


@fx("case", "T", "random upper and lower case",
    rate=F(0.2, 1.0), flicker=C(True, False))
def _case(cells, p, t, rng, seed):
    out = []
    for i, c in enumerate(cells):
        r = rng if p["flicker"] else static_rng(seed, i)
        if r.random() < p["rate"]:
            c = c.copy(ch=c.ch.swapcase())
        out.append(c)
    return out


@fx("color", "S", "rainbow, fire, toxic, strobe and corrupted colors",
    mode=C("rainbow", "random", "strobe", "fire", "ice", "toxic", "corrupt"), speed=I(1, 4), rate=F(0.1, 1.0))
def _color(cells, p, t, rng, seed):
    m = p["mode"]
    if m == "strobe":
        fg = 231 if (t // p["speed"]) % 2 else 196
        return [c.copy(fg=fg) for c in cells]
    out = []
    for i, c in enumerate(cells):
        if m == "rainbow":
            pal = COLORS["rainbow"]
            c = c.copy(fg=pal[(i * 2 + t * p["speed"]) % len(pal)])
        elif rng.random() < p["rate"]:
            c = c.copy(fg=rng.randint(16, 231) if m == "random" else rng.choice(COLORS[m]))
        out.append(c)
    return out


@fx("bg", "S", "background color bars and blocks",
    mode=C("bars", "random", "strobe", "stripes"), rate=F(0.05, 0.6))
def _bg(cells, p, t, rng, seed):
    pal = [196, 21, 46, 201, 226, 51, 231, 16, 93]
    m = p["mode"]
    if m == "strobe":
        bg = 196 if t % 2 else 16
        return [c.copy(bg=bg) for c in cells]
    if m == "stripes":
        return [c.copy(bg=pal[(i + t) % len(pal)]) if (i + t) % 3 == 0 else c for i, c in enumerate(cells)]
    out = [c for c in cells]
    if m == "random":
        return [c.copy(bg=rng.choice(pal)) if rng.random() < p["rate"] else c for c in out]
    if out and rng.random() < p["rate"] * 2:
        s = rng.randrange(len(out))
        bg = rng.choice(pal)
        for i in range(s, min(len(out), s + rng.randint(2, 6))):
            out[i] = out[i].copy(bg=bg)
    return out


@fx("attrs", "S", "blink, reverse, strikethrough, underline per letter",
    rate=F(0.1, 0.9), which=C("mix", "blink", "reverse", "strike", "underline", "italicdim"))
def _attrs(cells, p, t, rng, seed):
    sets = {"mix": [1, 2, 3, 4, 5, 7, 9], "blink": [5], "reverse": [7], "strike": [9],
            "underline": [4], "italicdim": [2, 3]}[p["which"]]
    out = []
    for c in cells:
        if rng.random() < p["rate"]:
            c = c.copy(at=tuple(sorted(set(c.at) | {rng.choice(sets)})))
        out.append(c)
    return out


@fx("flash", "S", "the whole line inverts (strobe)",
    period=I(2, 12), duty=I(1, 3))
def _flash(cells, p, t, rng, seed):
    if t % p["period"] < p["duty"]:
        return [c.copy(at=tuple(sorted(set(c.at) | {7}))) for c in cells]
    return cells


@fx("enclose", "T", "letters trapped in combining circles, boxes, no-signs, keycaps",
    rate=F(0.2, 1.0), mark=C(*(list(ENCLOSE) + ["all"])), flicker=C(True, False))
def _enclose(cells, p, t, rng, seed):
    out = []
    for i, c in enumerate(cells):
        r = rng if p["flicker"] else static_rng(seed, i)
        if c.ch.strip() and r.random() < p["rate"]:
            m = r.choice(list(ENCLOSE.values())) if p["mark"] == "all" else ENCLOSE[p["mark"]]
            c = c.copy(ch=c.ch + m)
        out.append(c)
    return out


@fx("emoji", "T", "emoji replace, invade or trail the word",
    rate=F(0.05, 0.6), mode=C("replace", "insert", "sprinkle", "tail"), set=C(*EMOJI), flicker=C(True, False))
def _emoji(cells, p, t, rng, seed):
    r0 = rng if p["flicker"] else static_rng(seed, 0)
    pool = EMOJI[p["set"]]
    if p["mode"] == "tail":
        return cells + [Cell(r0.choice(pool)) for _ in range(r0.randint(1, 4))]
    if p["mode"] == "sprinkle":
        out = list(cells)
        for _ in range(r0.randint(1, 2)):
            out.insert(r0.randint(0, len(out)), Cell(r0.choice(pool)))
        return out
    out = []
    for i, c in enumerate(cells):
        r = rng if p["flicker"] else static_rng(seed, i)
        if r.random() < p["rate"]:
            if p["mode"] == "replace":
                c = Cell(r.choice(pool))
            else:
                out.append(Cell(r.choice(pool)))
        out.append(c)
    return out


@fx("flip", "M", "flips upside down or backwards for a few frames",
    period=I(3, 20), duty=I(1, 10), how=C("upside", "reverse"))
def _flip(cells, p, t, rng, seed):
    if t % p["period"] >= min(p["duty"], p["period"] - 1):
        return cells
    rev = list(reversed(cells))
    if p["how"] == "upside":
        rev = [c.copy(ch=UPSIDE.get(c.ch[:1], c.ch[:1]) + c.ch[1:]) for c in rev]
    return rev


@fx("regional", "T", "letters become regional indicators (pairs merge into flags)",
    rate=F(0.2, 1.0), flicker=C(True, False))
def _regional(cells, p, t, rng, seed):
    out = []
    for i, c in enumerate(cells):
        r = rng if p["flicker"] else static_rng(seed, i)
        ch = c.ch[:1].lower()
        if "a" <= ch <= "z" and r.random() < p["rate"]:
            c = c.copy(ch=chr(0x1F1E6 + ord(ch) - 97))
        out.append(c)
    return out


@fx("mojibake", "T", "broken text encoding (Ã¢â‚¬)",
    rate=F(0.05, 0.6), flicker=C(True, False))
def _mojibake(cells, p, t, rng, seed):
    out = []
    for i, c in enumerate(cells):
        r = rng if p["flicker"] else static_rng(seed, i)
        out.append(c.copy(ch=r.choice(MOJIBAKE)) if r.random() < p["rate"] else c)
    return out


@fx("hexleak", "T", "letters leak out as escape codes",
    rate=F(0.05, 0.5), style=C("\\x", "%", "U+", "&#"), flicker=C(True, False))
def _hexleak(cells, p, t, rng, seed):
    out = []
    for i, c in enumerate(cells):
        r = rng if p["flicker"] else static_rng(seed, i)
        if c.ch.strip() and r.random() < p["rate"]:
            cp = ord(c.ch[0])
            s = {"\\x": "\\x%02x" % (cp & 0xFF), "%": "%%%02X" % (cp & 0xFF),
                 "U+": "U+%04X" % cp, "&#": "&#%d;" % cp}[p["style"]]
            out += [c.copy(ch=ch, fg=GRAY) for ch in s]
        else:
            out.append(c)
    return out


@fx("errors", "M", "error messages burst into the word",
    prob=F(0.1, 1.0), where=C("insert", "replace", "tail"))
def _errors(cells, p, t, rng, seed):
    if not cells or rng.random() > p["prob"]:
        return cells
    tok = [Cell(ch, 196) for ch in rng.choice(ERRORS)]
    i = rng.randrange(len(cells))
    if p["where"] == "tail":
        return cells + [Cell(" ")] + tok
    if p["where"] == "replace":
        return cells[:i] + tok + cells[i + len(tok):]
    return cells[:i] + tok + cells[i:]


@fx("ghost", "S", "RGB split and echo copies of letters",
    rate=F(0.1, 1.0), mode=C("rgb", "echo", "shadow"))
def _ghost(cells, p, t, rng, seed):
    out = []
    for c in cells:
        if c.ch.strip() and rng.random() < p["rate"]:
            if p["mode"] == "rgb":
                out += [c.copy(fg=196), c.copy(fg=51)]
            elif p["mode"] == "echo":
                out += [c, c.copy(fg=DARK, at=(2,))]
            else:
                out += [c.copy(fg=DARK), c]
        else:
            out.append(c)
    return out


@fx("drip", "M", "marks drip down from the letters",
    length=I(1, 8), speed=I(1, 4))
def _drip(cells, p, t, rng, seed):
    out = []
    for i, c in enumerate(cells):
        n = (t // p["speed"] + i * 3 + seed) % (p["length"] + 1)
        r = static_rng(seed, i)
        out.append(c.copy(ch=c.ch + "".join(r.choice(DRIP_MARKS) for _ in range(n))) if c.ch.strip() else c)
    return out


@fx("smear", "M", "the end of the word smears into a fading trail",
    length=I(2, 16), style=C("char", "blocks", "fade"))
def _smear(cells, p, t, rng, seed):
    if not cells:
        return cells
    n = rng.randint(1, p["length"])
    fades = [ORANGE, 137, 101, 95, 59, 240, 238, 236]
    last = cells[-1]
    if p["style"] == "blocks":
        chars = ["▓", "▒", "░"]
        return cells + [last.copy(ch=chars[min(2, i * 3 // n)], fg=fades[min(7, i)]) for i in range(n)]
    if p["style"] == "fade":
        return cells + [cells[i % len(cells)].copy(fg=fades[min(7, i)]) for i in range(n)]
    return cells + [last.copy(fg=fades[min(7, i)]) for i in range(n)]


@fx("tail", "M", "a stream of noise trails after the word",
    length=I(3, 30), charset=C(*CHARSETS), fade=C(True, False))
def _tail(cells, p, t, rng, seed):
    n = rng.randint(1, p["length"])
    cs = CHARSETS[p["charset"]]
    return cells + [Cell(rng.choice(cs), DARK if p["fade"] else ORANGE) for _ in range(n)]


@fx("invisible", "T", "zero-width joiners, soft hyphens, bidi overrides between letters",
    rate=F(0.1, 0.8), kind=C(*(list(INVISIBLE) + ["bidi", "mix"])))
def _invisible(cells, p, t, rng, seed):
    if p["kind"] == "bidi":
        if len(cells) < 2:
            return cells
        i = static_rng(seed, 0).randrange(1, len(cells))
        return cells[:i] + [Cell("‮")] + cells[i:] + [Cell("‬")]
    out = []
    for i, c in enumerate(cells):
        out.append(c)
        r = static_rng(seed, i)
        if r.random() < p["rate"]:
            k = r.choice(list(INVISIBLE)) if p["kind"] == "mix" else p["kind"]
            out.append(Cell(INVISIBLE[k], c.fg))
    return out


@fx("scan", "M", "a scanline wipes through part of the word",
    prob=F(0.1, 0.9), char=C(" ", "▁", "_", "─", "█", "▀"))
def _scan(cells, p, t, rng, seed):
    if not cells or rng.random() > p["prob"]:
        return cells
    out = list(cells)
    s = rng.randrange(len(out))
    for i in range(s, min(len(out), s + rng.randint(1, 5))):
        out[i] = out[i].copy(ch=p["char"])
    return out


# --------------------------------------------------------------------------
# Entries: a stack of effect layers + a spinner glyph style
# --------------------------------------------------------------------------

def rand_params(spec, rng):
    p = {}
    for k, s in spec.items():
        if s[0] == "int":
            p[k] = rng.randint(s[1], s[2])
        elif s[0] == "float":
            p[k] = round(rng.uniform(s[1], s[2]), 2)
        else:
            p[k] = rng.choice(s[1])
    return p


def mutate_params(spec, p, rng):
    q = dict(p)
    for k, s in spec.items():
        if rng.random() > 0.5:
            continue
        if s[0] == "int":
            step = max(1, (s[2] - s[1]) // 4)
            q[k] = max(s[1], min(s[2], q.get(k, s[1]) + rng.randint(-step, step)))
        elif s[0] == "float":
            q[k] = round(max(s[1], min(s[2], q.get(k, s[1]) + rng.gauss(0, (s[2] - s[1]) * 0.2))), 2)
        else:
            q[k] = rng.choice(s[1])
    return q


def rand_layer(rng, name=None):
    name = name or rng.choice(list(FX))
    return {"fx": name, "p": rand_params(FX[name]["spec"], rng)}


def entry_name(e):
    return " + ".join(l["fx"] for l in e["layers"])


def entry_kinds(e):
    return "".join(k for k in "TSM" if any(FX[l["fx"]]["kind"] == k for l in e["layers"]))


def frame_cells(e, text, t, calm=False):
    cells = [Cell(ch, ORANGE) for ch in text]
    for li, layer in enumerate(e["layers"]):
        if calm and (layer["fx"] == "flash" or layer["p"].get("mode") == "strobe"):
            continue
        rng = random.Random((e["seed"] * 1000003 + t * 101 + li) & 0xFFFFFFFF)
        cells = FX[layer["fx"]]["func"](cells, layer["p"], t, rng, e["seed"] + li)
    return cells


def glyph_cell(e, t):
    g = GLYPHS.get(e.get("glyph", "claude"))
    if g is None:
        rng = random.Random(e["seed"] + t)
        return Cell(rng.choice(rng.choice(list(CHARSETS.values()))), ORANGE)
    return Cell(g[t % len(g)], ORANGE)


def spinner_line(e, text, t, calm=False, chrome=False):
    cells = [glyph_cell(e, t), Cell(" ")] + frame_cells(e, text, t, calm) + [Cell("…", ORANGE)]
    if chrome:
        cells += [Cell(ch, GRAY) for ch in " (12s · esc to interrupt)"]
    return cells


class Gallery:
    def __init__(self, entries=None, next_id=1):
        self.entries = entries or []
        self.next_id = next_id

    def new(self, rng, layers, origin, parent=None, glyph=None, src=None, n=None):
        e = {"id": self.next_id, "seed": rng.randrange(1 << 30), "glyph": glyph or rng.choice(list(GLYPHS)),
             "src": src or rand_source(rng, layers), "len": n or rng.randint(4, 12),
             "layers": layers, "rating": 0, "origin": origin, "parent": parent}
        self.next_id += 1
        return e

    def generate(self, rng, combos=60):
        for name in FX:
            self.entries.append(self.new(rng, [rand_layer(rng, name)], "single", glyph="claude"))
            self.entries.append(self.new(rng, [rand_layer(rng, name)], "single"))
        for _ in range(combos):
            self.entries.append(self.random_combo(rng))

    def random_combo(self, rng):
        names = rng.sample(list(FX), rng.choice([2, 2, 3, 3, 4]))
        return self.new(rng, [rand_layer(rng, n) for n in names], "combo")

    def mutate(self, e, rng):
        layers = [{"fx": l["fx"], "p": mutate_params(FX[l["fx"]]["spec"], l["p"], rng)} for l in e["layers"]]
        if rng.random() < 0.3:
            layers.insert(rng.randrange(len(layers) + 1), rand_layer(rng))
        if len(layers) > 1 and rng.random() < 0.2:
            layers.pop(rng.randrange(len(layers)))
        glyph = e.get("glyph", "claude") if rng.random() < 0.7 else rng.choice(list(GLYPHS))
        src, n = entry_source(e)
        if rng.random() < 0.25:
            src = rand_source(rng, layers)
        n = max(3, min(16, n + rng.randint(-3, 3)))
        return self.new(rng, layers, "mutation", parent=e["id"], glyph=glyph, src=src, n=n)

    def breed(self, a, b, rng):
        pool = [dict(l) for l in a["layers"] + b["layers"]]
        rng.shuffle(pool)
        seen, layers = set(), []
        for l in pool:
            if l["fx"] not in seen and len(layers) < rng.randint(1, 4):
                seen.add(l["fx"])
                layers.append(l)
        src, n = entry_source(rng.choice([a, b]))
        child = self.new(rng, layers or [rand_layer(rng)], "breed", parent=a["id"],
                         glyph=rng.choice([a.get("glyph", "claude"), b.get("glyph", "claude")]), src=src, n=n)
        child["layers"] = self.mutate(child, rng)["layers"] if rng.random() < 0.7 else child["layers"]
        self.next_id = max(self.next_id, child["id"] + 1)
        return child

    def to_json(self):
        return {"version": 1, "next_id": self.next_id, "entries": self.entries}

    @classmethod
    def from_json(cls, d):
        entries = [e for e in d["entries"] if all(l["fx"] in FX for l in e["layers"])]
        return cls(entries, d.get("next_id", len(entries) + 1))


def save(gallery, extra):
    data = gallery.to_json()
    data.update(extra)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def export_liked(gallery, override=None):
    liked = [e for e in gallery.entries if e["rating"] > 0]
    verbs, notes = [], []
    for e in liked:
        notes.append("#%d %s [%s] on %s" % (e["id"], entry_name(e), entry_kinds(e), override or entry_source(e)[0]))
        for reseed in range(3):
            text = entry_text(e, override, reseed)
            for t in (0, 7, 19):
                v = plain(frame_cells(e, text, t, calm=True)).strip()
                if v and v not in verbs:
                    verbs.append(v)
                    notes.append("    " + v)
    with open(EXPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"mode": "replace", "verbs": verbs}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(EXPORT_NOTES, "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")
    return len(liked), len(verbs)


# --------------------------------------------------------------------------
# Terminal UI
# --------------------------------------------------------------------------

ESCAPES = [("\x1b[5~", "pgup"), ("\x1b[6~", "pgdn"), ("\x1b[1~", "home"), ("\x1b[4~", "end"),
           ("\x1b[A", "up"), ("\x1b[B", "down"), ("\x1b[C", "right"), ("\x1b[D", "left"),
           ("\x1b[H", "home"), ("\x1b[F", "end"), ("\x1bOA", "up"), ("\x1bOB", "down"),
           ("\x1bOC", "right"), ("\x1bOD", "left"), ("\x1b", "esc")]
MOUSE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")

HELP = """
  GLITCH GALLERY: keys

  ↑ ↓  j k  scroll wheel     move              enter / →     focus view (← back)
  PgUp PgDn  u d             page              click         select
  space  f                   like ★            x             nope ✗ (dims it)
  m                          mutate: 6 variations of this one, added below it
  L                          breed: 8 new ones mixed from everything you liked
  n                          8 new random combos at the end
  o                          filter: all / liked / hide noped
  t   T                      source: each entry's own noise, then all on
                             one source (braille, runes…) / type your own
  [ ]                        slower / faster          p   pause
  s                          calm mode (8 fps max, no strobe or flash)
  g                          compact / spaced rows
  e                          export liked ones to spinner-verbs.json
  ?                          this help                q   quit (saves)

  Tags: T = changes the characters (works as real spinner text)
        S = needs color/style codes, M = needs motion. The real spinnerVerbs
        setting holds plain strings only: Claude Code adds its own shimmer
        and spinning glyph, but S and M effects won't carry over. Focus view
        shows the plain string you'd actually get.

  Everything you rate is saved to gallery/gallery-state.json.

  Press any key.
"""


def read_keys(fd):
    data = os.read(fd, 4096).decode("utf-8", "ignore")
    keys, i = [], 0
    while i < len(data):
        m = MOUSE.match(data, i)
        if m:
            keys.append(("mouse", int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)))
            i = m.end()
            continue
        for seq, name in ESCAPES:
            if data.startswith(seq, i):
                keys.append(name)
                i += len(seq)
                break
        else:
            keys.append(data[i])
            i += 1
    return keys


def sgr(*codes):
    return "\x1b[" + ";".join(str(c) for c in codes) + "m"


class UI:
    def __init__(self, gallery, typed, fps):
        self.g = gallery
        self.typed = typed  # strings typed with T; off until picked with t
        self.mi = 0
        self.fps = fps
        self.calm = False
        self.paused = False
        self.clock = 0.0
        self.sel = 0
        self.top = 0
        self.filter = "all"
        self.view = "list"
        self.spaced = True
        self.msg = "? for keys · ⚠ fast flashing: press s for calm mode"
        self.msg_until = time.time() + 8
        self.typing = None
        self.running = True
        self.rng = random.Random()
        self.row_map = {}

    # ---- helpers
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

    def modes(self):
        return [None] + list(SOURCES) + self.typed

    def override(self):
        ms = self.modes()
        return ms[self.mi % len(ms)]

    def mode_label(self):
        o = self.override()
        return "own" if o is None else (o if o in SOURCES else '"%s"' % o)

    def text(self, e, reseed=0):
        return entry_text(e, self.override(), reseed)

    def frame(self):
        return int(self.clock * self.fps)

    def persist(self):
        save(self.g, {"texts": self.typed})

    # ---- input
    def key(self, k):
        if self.typing is not None:
            return self.type_key(k)
        if self.view == "help":
            self.view = "list"
            return
        e, vis = self.current()
        rows = self.body_rows()
        per = 2 if self.spaced else 1
        page = max(1, rows // per - 1)
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
        elif k == "m" and e:
            pos = self.g.entries.index(e) + 1
            kids = [self.g.mutate(e, self.rng) for _ in range(6)]
            self.g.entries[pos:pos] = kids
            self.filter = "all" if self.filter == "liked" else self.filter
            self.sel = self.visible().index(pos)
            self.say("6 mutations of #%d added below it" % e["id"])
            self.persist()
        elif k == "L":
            liked = [x for x in self.g.entries if x["rating"] > 0]
            if not liked:
                self.say("Like a few first (space), then L breeds new ones from them")
                return
            kids = [self.g.breed(self.rng.choice(liked), self.rng.choice(liked), self.rng) for _ in range(8)]
            self.g.entries += kids
            self.filter = "all"
            self.sel = len(self.g.entries) - 8
            self.say("8 new ones bred from %d liked" % len(liked))
            self.persist()
        elif k == "n":
            self.g.entries += [self.g.random_combo(self.rng) for _ in range(8)]
            self.filter = "all"
            self.sel = len(self.g.entries) - 8
            self.say("8 new random combos")
            self.persist()
        elif k == "o":
            self.filter = {"all": "liked", "liked": "hide", "hide": "all"}[self.filter]
            self.sel = 0
            self.say({"all": "showing all", "liked": "showing liked only", "hide": "hiding noped"}[self.filter])
        elif k == "t":
            self.mi = (self.mi + 1) % len(self.modes())
            self.say("source: " + ("each entry's own" if self.override() is None else self.mode_label()))
        elif k == "T":
            self.typing = ""
        elif k == "[":
            self.fps = max(1, self.fps - 2)
            self.say("%d fps" % self.fps)
        elif k == "]":
            self.fps = min(60, self.fps + 2)
            self.say("%d fps" % self.fps)
        elif k == "p":
            self.paused = not self.paused
            self.say("paused" if self.paused else "playing")
        elif k == "s":
            self.calm = not self.calm
            self.say("calm mode on: 8 fps max, no strobe/flash" if self.calm else "calm mode off")
        elif k == "g":
            self.spaced = not self.spaced
        elif k == "e":
            n, v = export_liked(self.g, self.override())
            self.say("exported %d liked → %d verbs in spinner-verbs.json (see gallery/liked-frames.txt)" % (n, v))

    def type_key(self, k):
        if k in ("\n", "\r"):
            if self.typing.strip():
                self.typed.insert(0, self.typing.strip())
                self.mi = len(SOURCES) + 1
                self.persist()
            self.typing = None
        elif k == "esc":
            self.typing = None
        elif k in ("\x7f", "\b"):
            self.typing = self.typing[:-1]
        elif isinstance(k, str) and len(k) == 1 and k.isprintable():
            self.typing += k

    # ---- drawing
    def body_rows(self):
        return shutil.get_terminal_size((100, 30)).lines - 4

    def draw(self, out):
        cols, lines = shutil.get_terminal_size((100, 30))
        t = self.frame()
        e, vis = self.current()
        rows = []
        liked = sum(1 for x in self.g.entries if x["rating"] > 0)
        title = " GLITCH GALLERY  %d effects  ★ %d liked  source: %s  %d fps%s%s " % (
            len(self.g.entries), liked, self.mode_label(), min(self.fps, 8) if self.calm else self.fps,
            "  CALM" if self.calm else "", "  PAUSED" if self.paused else "")
        rows.append(sgr(0, 7, 1) + title.ljust(cols) + sgr(0))
        rows.append(sgr(0, 2) + " ↑↓ scroll · space like · x nope · m mutate · L breed liked · enter focus · ? help · q quit" + sgr(0))
        self.row_map = {}
        if self.view == "help":
            rows += [sgr(0) + l for l in HELP.split("\n")]
        elif not vis:
            rows += ["", "  Nothing to show with this filter. Press o."]
        elif self.view == "focus":
            rows += self.focus_rows(e, t, cols)
        else:
            rows += self.list_rows(vis, t, cols, lines)
        while len(rows) < lines - 1:
            rows.append("")
        rows = rows[:lines - 1]
        if self.typing is not None:
            status = sgr(0, 1) + " type your own text: " + sgr(0) + self.typing + "█" + sgr(0, 2) + "   (enter to use, esc to cancel)"
        elif time.time() < self.msg_until:
            status = sgr(0, 33) + " " + self.msg
        elif e:
            status = sgr(0, 2) + " #%d  %s  [%s]  on %s  %s" % (e["id"], entry_name(e), entry_kinds(e),
                                                             entry_source(e)[0], e.get("origin", ""))
        else:
            status = ""
        rows.append(status + sgr(0))
        buf = ["\x1b[?2026h"]
        for i, r in enumerate(rows):
            buf.append("\x1b[%d;1H\x1b[2K%s" % (i + 1, r))
        buf.append(sgr(0) + "\x1b[?2026l")
        out.write("".join(buf))
        out.flush()

    def list_rows(self, vis, t, cols, lines):
        per = 2 if self.spaced else 1
        n = max(1, (lines - 4) // per)
        if self.sel < self.top:
            self.top = self.sel
        if self.sel >= self.top + n:
            self.top = self.sel - n + 1
        self.top = max(0, min(self.top, max(0, len(vis) - n)))
        rows = [""]
        for vi in range(self.top, min(len(vis), self.top + n)):
            e = self.g.entries[vis[vi]]
            is_sel = vi == self.sel
            mark = sgr(0, 1, 97) + "▶" if is_sel else " "
            rate = sgr(0, 38, 5, 226) + "★" if e["rating"] > 0 else (sgr(0, 38, 5, 160) + "✗" if e["rating"] < 0 else " ")
            name_style = sgr(0, 1, 97) if is_sel else (sgr(0, 2) if e["rating"] < 0 else sgr(0, 38, 5, 250))
            label = "%4d %-26.26s %-3s" % (e["id"], entry_name(e), entry_kinds(e))
            line = mark + rate + name_style + label + sgr(0) + "  "
            if e["rating"] < 0 and not is_sel:
                line += sgr(0, 2) + plain(spinner_line(e, self.text(e), 0, True)) + sgr(0)
            else:
                line += render(spinner_line(e, self.text(e), t, self.calm))
            self.row_map[len(rows) + 1] = vi
            rows.append(line)
            if per == 2:
                self.row_map[len(rows) + 1] = vi
                rows.append("")
        return rows

    def focus_rows(self, e, t, cols):
        rows = [""]
        star = "★ liked" if e["rating"] > 0 else ("✗ noped" if e["rating"] < 0 else "")
        rows.append(sgr(0, 1) + "  #%d  %s  " % (e["id"], entry_name(e)) + sgr(0, 38, 5, 226) + star + sgr(0))
        rows.append(sgr(0, 2) + "  origin: %s%s · glyph: %s · source: %s × %d · tags: %s" % (
            e.get("origin", ""), " of #%s" % e["parent"] if e.get("parent") else "", e.get("glyph"),
            entry_source(e)[0], entry_source(e)[1], entry_kinds(e)) + sgr(0))
        for l in e["layers"]:
            ps = ", ".join("%s=%s" % (k, v) for k, v in l["p"].items())
            rows.append(sgr(0, 2) + "    %-10s %s  " % (l["fx"], FX[l["fx"]]["kind"]) + sgr(0) + ps[:cols - 20])
        rows += ["", sgr(0, 38, 5, 75) + "  ~/code/my-app " + sgr(0, 38, 5, 114) + "$ " + sgr(0) + "claude", "",
                 sgr(0, 2) + "  > fix the failing tests" + sgr(0), "",
                 "  ● I'll run the test suite first to see what's failing.", "",
                 "  " + render(spinner_line(e, self.text(e), t, self.calm, chrome=True)), "",
                 sgr(0, 38, 5, 242) + "  ╭" + "─" * min(60, cols - 6) + "╮" + sgr(0),
                 sgr(0, 38, 5, 242) + "  │ " + sgr(0) + "> " + sgr(0, 38, 5, 242) + " " * (min(60, cols - 6) - 3) + "│" + sgr(0),
                 sgr(0, 38, 5, 242) + "  ╰" + "─" * min(60, cols - 6) + "╯" + sgr(0), "",
                 sgr(0, 1) + "  Same effect on other sources" + sgr(0)]
        own = entry_source(e)[0]
        others = [x for x in ("consonants", "braille", "blocks", "runes", "katakana", "emoji", "dots") if x != own][:6]
        for i, src in enumerate(others):
            line = render(spinner_line(e, entry_text(e, src), t + i * 3, self.calm))
            rows.append("  " + line + sgr(0, 2) + "   " + src + sgr(0))
        rows += ["", sgr(0, 1) + "  As a real spinner word (plain text, 3 frozen frames)" + sgr(0)]
        for ft in (0, 7, 19):
            s = plain(frame_cells(e, self.text(e), ft, calm=True))
            rows.append("  " + sgr(0, 38, 5, ORANGE) + s + "…" + sgr(0) + sgr(0, 2) + "   (%d code points)" % len(s) + sgr(0))
        rows += ["", sgr(0, 2) + "  ← back · ↑↓ previous/next · space like · x nope · m mutate" + sgr(0)]
        return rows


def run(ui):
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    out = sys.stdout
    try:
        tty.setcbreak(fd)
        out.write("\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[?1000h\x1b[?1006h")
        out.flush()
        last = time.time()
        while ui.running:
            ui.draw(out)
            fps = min(ui.fps, 8) if ui.calm else ui.fps
            r, _, _ = select.select([fd], [], [], 1.0 / fps)
            if r:
                for k in read_keys(fd):
                    ui.key(k)
            now = time.time()
            if not ui.paused:
                ui.clock += (now - last) * fps / ui.fps
            last = now
    except KeyboardInterrupt:
        pass
    finally:
        out.write("\x1b[?1000l\x1b[?1006l\x1b[?7h\x1b[?25h\x1b[0m\x1b[?1049l")
        out.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        ui.persist()


def main():
    ap = argparse.ArgumentParser(description="Browse glitch spinner effects.")
    ap.add_argument("--fresh", action="store_true", help="start a new gallery (old state is backed up)")
    ap.add_argument("--text", help="glitch this text instead of noise")
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--seed", type=int, help="seed for a fresh gallery")
    ap.add_argument("--print", type=int, metavar="N", help="print N entries once and exit (no UI)")
    ap.add_argument("--plain", action="store_true", help="with --print: no color codes")
    args = ap.parse_args()

    typed = []
    gallery = None
    if os.path.exists(STATE_FILE) and not args.fresh:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        gallery = Gallery.from_json(data)
        typed = [x for x in data.get("texts") or [] if x not in OLD_SAMPLE_TEXTS]
    elif os.path.exists(STATE_FILE):
        os.replace(STATE_FILE, STATE_FILE.replace(".json", "-%s.json" % time.strftime("%Y%m%d-%H%M%S")))
    if gallery is None or not gallery.entries:
        gallery = Gallery()
        gallery.generate(random.Random(args.seed))
    if args.text:
        typed.insert(0, args.text)

    if args.print:
        for e in gallery.entries[:args.print]:
            line = spinner_line(e, entry_text(e, args.text), 5)
            print("%4d %-30.30s %-3s %s" % (e["id"], entry_name(e), entry_kinds(e), plain(line) if args.plain else render(line)))
        return
    if not sys.stdin.isatty():
        sys.exit("Run this in a terminal (or use --print N).")
    ui = UI(gallery, typed, args.fps)
    if args.text:
        ui.mi = len(SOURCES) + 1
    run(ui)


if __name__ == "__main__":
    main()
