#!/usr/bin/env python3
"""Render a terminal-screencast MP4 of the autopilot demo from the REAL output.
Pillow -> PNG frames -> ffmpeg. No screen-recording permission needed.
Run with the venv that has Pillow; ffmpeg must be on PATH."""

import shutil, subprocess, tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1600, 900, 15
BG = (10, 12, 20)
PROMPT = (45, 212, 167)   # teal
CMD = (232, 234, 242)
OUT = (154, 160, 182)
GOOD = (45, 212, 167)
BLUE = (74, 168, 255)
VIOLET = (167, 139, 250)
ORANGE = (255, 120, 73)
TITLE = (232, 234, 242)
MARGIN, LH, FS = 60, 34, 22

MENLO = "/System/Library/Fonts/Menlo.ttc"
font = ImageFont.truetype(MENLO, FS, index=0)
big = ImageFont.truetype(MENLO, 40, index=0)
small = ImageFont.truetype(MENLO, 18, index=0)

# (kind, text, color). kinds: banner, cmd, out, good, metric, muted, blank
SCENES = [
    [("banner", "Stop paying Claude to re-read your repo", TITLE),
     ("muted", "Personal Coding Model Autopilot — local-first repo context, $0", OUT),
     ("blank", "", OUT)],
    # the pain
    [("banner", "The problem", TITLE),
     ("out", "  Your repo is 359 KB  ~  90,000 tokens.", OUT),
     ("warn", "  Claude Code re-discovers that structure every session — grep, read, repeat.", ORANGE),
     ("muted", "  On agent/metered billing you pay frontier prices to relearn what you already know.", OUT)],
    # the real example, side by side
    [("cmd", "# real task:  \"fix the failing test\"  (same task, two ways)", PROMPT),
     ("warn", "  NORMAL Claude Code   ->  explores files  ->  11,947 tokens sent to the model", ORANGE),
     ("good", "  WITH AUTOPILOT      ->  DAG + SKILL.md already map it  ->  299 tokens (right slice)", GOOD),
     ("muted", "  same patch · tests still pass", OUT)],
    # the headline number
    [("banner", "11,947  ->  299 tokens", GOOD),
     ("metric", "  -98.7% tokens · -98% time · -94% cost · same result", GOOD),
     ("muted", "  retrieval F1 +0.32 · 1 frontier call avoided", OUT)],
    # how — the $0 .md + DAG
    [("cmd", "autopilot index    # the $0 part, runs on every commit", PROMPT),
     ("out", "  builds .autopilot/SKILL.md + ARCHITECTURE.md (DAG):", OUT),
     ("out", "  every file, every function, the call graph — kept fresh, locally, for $0", OUT),
     ("good", "  Claude Code reads THIS saved context, not the whole repo", GOOD)],
    [("banner", "Built on EverMind + Butterbase  (LIVE)", GOOD),
     ("blue", "  Butterbase app_b197i2548pk2 · EverMind memory · code build0530", BLUE),
     ("muted", "  github.com/OCWC22/personal-coding-autopilot", OUT)],
]

frames = Path(tempfile.mkdtemp(prefix="demo_frames_"))
idx = 0
COLORMAP = {"prompt": PROMPT, "blue": BLUE}


def draw(visible, partial=None, cursor=True):
    global idx
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 44], fill=(18, 21, 32))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([20 + i * 26, 14, 36 + i * 26, 30], fill=c)
    d.text((W // 2 - 90, 12), "autopilot — demo", font=small, fill=OUT)
    y = 80
    for kind, text, color in visible:
        if kind == "banner":
            d.text((MARGIN, y), text, font=big, fill=color); y += 60
        elif kind == "metric":
            d.text((MARGIN, y), text, font=font, fill=color); y += LH + 6
        elif kind == "cmd":
            d.text((MARGIN, y), "$ ", font=font, fill=PROMPT)
            d.text((MARGIN + 26, y), text, font=font, fill=CMD); y += LH
        elif kind == "blank":
            y += LH // 2
        else:
            d.text((MARGIN, y), text, font=font, fill=color); y += LH
    if partial is not None:
        kind, text, color = partial
        d.text((MARGIN, y), "$ ", font=font, fill=PROMPT)
        d.text((MARGIN + 26, y), text, font=font, fill=CMD)
        if cursor:
            w = d.textlength("$ " + text, font=font)
            d.rectangle([MARGIN + w, y, MARGIN + w + 11, y + FS], fill=PROMPT)
    img.save(frames / f"{idx:05d}.png"); idx += 1


def hold(visible, n): [draw(visible) for _ in range(n)]


visible = []
for scene in SCENES:
    visible = []
    hold(visible, 4)
    for item in scene:
        if item[0] == "cmd":
            # type the command out
            for j in range(1, len(item[1]) + 1):
                draw(visible, partial=("cmd", item[1][:j], item[2]))
            visible.append(item); hold(visible, 6)
        else:
            visible.append(item); hold(visible, 7)
    hold(visible, 22)

out = Path(__file__).resolve().parent / "autopilot-demo.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                "-i", str(frames / "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(out)], check=True)
shutil.rmtree(frames, ignore_errors=True)
print("wrote", out)
