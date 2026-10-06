#!/usr/bin/env python3
"""Build the word list and the website's list from a gallery round.

Every entry in the round becomes one spinner string, filled to WIDTH columns
(the first of the strings the Claude preview shows for it). Writes:

    spinner-verbs.json   what install.sh puts in Claude Code's settings
    docs/entries.js      the same strings with their effect names, for the website

Run from the project folder:
    python3 tools/build.py              # newest round, 76 columns
    python3 tools/build.py --round 2 --width 76
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gallery"))
import claude_gallery as cg  # noqa: E402

# 76 columns: with Claude's glyph, a space and the "…" the line is 79 wide,
# so it fills a standard 80-column terminal without wrapping.
WIDTH = 76

# Shown in the GIF and at the top of the website, in this order (entry ids).
FEATURED = [1, 47, 85, 61, 89, 13, 105, 97]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--round", type=int, help="gallery round to build from (default: the newest)")
    ap.add_argument("--width", type=int, default=WIDTH, help="columns each string fills (default %d)" % WIDTH)
    args = ap.parse_args()

    rnd = args.round or cg.rounds()[-1]
    entries = cg.load_entries(cg.round_file(rnd))
    rows = []
    for e in entries:
        rows.append({"id": e["id"], "fx": cg.g.entry_name(e), "src": cg.g.entry_source(e)[0],
                     "v": cg.verbs_of(e, args.width)[0]})
    verbs = list(dict.fromkeys(r["v"] for r in rows))
    missing = [i for i in FEATURED if i not in {r["id"] for r in rows}]
    assert not missing, "featured ids not in round %d: %s" % (rnd, missing)

    with open(os.path.join(ROOT, "spinner-verbs.json"), "w", encoding="utf-8") as f:
        json.dump({"mode": "replace", "verbs": verbs}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(os.path.join(ROOT, "docs", "entries.js"), "w", encoding="utf-8") as f:
        f.write("// Made by tools/build.py from gallery round %d. Don't edit by hand.\n" % rnd)
        f.write("window.FEATURED = %s;\n" % json.dumps(FEATURED))
        f.write("window.ENTRIES = [\n")
        f.write(",\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
        f.write("\n];\n")
    print("Round %d: %d entries → %d strings, %d columns wide. Wrote spinner-verbs.json and docs/entries.js."
          % (rnd, len(entries), len(verbs), args.width))


if __name__ == "__main__":
    main()
