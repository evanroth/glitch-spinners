#!/usr/bin/env python3
"""Render docs/spinner.gif: a terminal running Claude Code, with the spinner
line cycling through the featured glitch strings, a new one every second.

Each frame is an HTML page screenshotted by headless Google Chrome (so zalgo
marks, emoji and fallback fonts render like a browser does), then ffmpeg
makes the GIF. Also writes docs/spinner-poster.png.

Run from the project folder after tools/build.py (macOS; needs Google Chrome,
ffmpeg and Pillow):
    python3 tools/make_gif.py
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gallery"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import claude_gallery as cg  # noqa: E402
from build import FEATURED  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT = os.path.join(ROOT, "docs", "spinner.gif")
FPS = 5                       # 200 ms per frame, like Claude's glyph
FRAMES_PER_STRING = FPS       # a new string every second
W, H = 700, 400               # CSS pixels; screenshots are 2x

MARK = re.compile("[̀-ͯ҃-҉᪰-᫿᷀-᷿⃐-⃿︠-︯]+")
ENCLOSE = re.compile("([⃝-⃤]+)")

PAGE = """<!doctype html><meta charset="utf-8"><style>
body { margin: 0; background: #0b0a10; }
.term { width: %dpx; height: %dpx; background: #14121c; overflow: hidden; }
.bar { display: flex; align-items: center; gap: 8px; padding: 9px 12px; background: #1e1a2a;
       border-bottom: 1px solid #2e2942; font: 12px Menlo, monospace; color: #8d88a6; }
.dot { width: 11px; height: 11px; border-radius: 50%%; background: #ff5f57; }
.dot:nth-child(2) { background: #febc2e; } .dot:nth-child(3) { background: #28c840; }
.bar span:last-child { margin: 0 auto; padding-right: 50px; }
pre { margin: 0; padding: 14px 15px; font: 13.6px/1.6 Menlo, monospace; color: #e9e6f2; white-space: pre; overflow: hidden; }
.d { color: #8d88a6; } .b { color: #4ad8ff; } .g { color: #9dff4a; } .x { color: #2e2942; }
.spin { color: #d77757; } .spin .hot { color: #f4b59c; }
.spin i { font-style: normal; font-family: "Lucida Grande", "Times New Roman", serif; }
.spin i.e { font-family: "STIX Two Math", "Arial Unicode MS", serif; }
</style>
<div class="term"><div class="bar"><span class="dot"></span><span class="dot"></span><span class="dot"></span><span>my-app — claude</span></div>
<pre><span class="b">~/code/my-app</span> <span class="g">$</span> claude

<span class="d">&gt; fix the failing tests</span>

● I'll run the test suite first to see what's failing.

<span class="g">●</span> <b>Bash</b>(npm test)
  <span class="d">⎿  3 failed, 41 passed</span>

<span class="spin">%s</span>

<span class="x">╭──────────────────────────────────────────────────────────────────────────────╮</span>
<span class="x">│</span> ❯                                                                            <span class="x">│</span>
<span class="x">╰──────────────────────────────────────────────────────────────────────────────╯</span>
  <span class="d">esc to interrupt</span></pre></div>
"""


def cell(c, hot):
    """One cluster as HTML, with its marks split into their own run (see docs/index.html)."""
    out, last = [], 0
    for m in MARK.finditer(c):
        out.append(html.escape(c[last:m.start()]))
        for k, part in enumerate(ENCLOSE.split(m.group())):
            if part:
                out.append('<i class="e">%s</i>' % part if k % 2 else "<i>%s</i>" % part)
        last = m.end()
    out.append(html.escape(c[last:]))
    return '<span%s>%s</span>' % (' class="hot"' if hot else "", "".join(out))


def spinner(verb, n):
    word = cg.clusters(verb) + ["…"]
    hot = (n * 3) % (len(word) + 12) - 4
    return cg.GLYPHS[n % len(cg.GLYPHS)] + " " + "".join(cell(c, abs(i - hot) <= 1) for i, c in enumerate(word))


def shoot(args):
    page, png = args
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                    "--window-size=%d,%d" % (W, H), "--screenshot=" + png, "file://" + page],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # headless windows have a minimum width; keep only the terminal
    Image.open(png).crop((0, 0, W * 2, H * 2)).save(png)


def main():
    with open(os.path.join(ROOT, "docs", "entries.js"), encoding="utf-8") as f:
        src = f.read()
    entries = {e["id"]: e for e in json.loads(src[src.index("window.ENTRIES = ") + 17:].rstrip().rstrip(";"))}
    verbs = [entries[i]["v"] for i in FEATURED]

    tmp = tempfile.mkdtemp()
    try:
        jobs = []
        for n in range(len(verbs) * FRAMES_PER_STRING):
            page = os.path.join(tmp, "f%04d.html" % n)
            with open(page, "w", encoding="utf-8") as f:
                f.write(PAGE % (W, H, spinner(verbs[n // FRAMES_PER_STRING], n)))
            jobs.append((page, os.path.join(tmp, "f%04d.png" % n)))
        with ThreadPoolExecutor(6) as pool:
            list(pool.map(shoot, jobs))
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(tmp, "f%04d.png"),
            "-vf", "split[a][b];[a]palettegen=max_colors=96:stats_mode=full[p];[b][p]paletteuse=dither=none",
            "-loop", "0", OUT,
        ], check=True)
        shutil.copy(jobs[4][1], OUT.replace("spinner.gif", "spinner-poster.png"))
    finally:
        shutil.rmtree(tmp)
    print("Wrote docs/spinner.gif (%dx%d, %d KB) and docs/spinner-poster.png"
          % (W * 2, H * 2, os.path.getsize(OUT) // 1024))


if __name__ == "__main__":
    main()
