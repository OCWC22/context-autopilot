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
    [("banner", "Personal Coding Model Autopilot", TITLE),
     ("muted", "local-first repo context · $0 · Beta Fund x EverMind hackathon", OUT),
     ("blank", "", OUT)],
    [("cmd", "autopilot index", PROMPT),
     ("good", "  ✓ $0 local index -> .autopilot/SKILL.md + ARCHITECTURE.md (commit-versioned DAG)", GOOD),
     ("out", "  83 files · 381 functions · 160 import + 981 call edges · version b26935e9", OUT),
     ("out", "  built in 316 ms — frontier rediscovery would cost ~$0.24 / session", OUT)],
    [("cmd", "python3 .autopilot/verify/verify_dag.py", PROMPT),
     ("good", "  functions(py): claimed=374 actual=374 -> OK   (every claim is verifiable)", GOOD)],
    [("cmd", "autopilot eval     # local-first (indexed) vs normal Claude Code", PROMPT),
     ("out", "  config                  calls  tok_in   F1    tests", OUT),
     ("muted", "  Claude Code (full ctx)    1    11947   0.23  pass", OUT),
     ("blue", "  local-first (indexed)     0      299   0.50  pass", BLUE),
     ("blank", "", OUT),
     ("metric", "  TOKENS -98.7%   TIME -98.0%   COST -93.9%   F1 +0.32   success preserved", GOOD)],
    [("cmd", "autopilot submit   # Butterbase (backend) + EverMind (memory)", PROMPT),
     ("good", "  EverMind/EverOS: memory written  (LIVE — real API)", GOOD),
     ("good", "  Butterbase: app_b197i2548pk2 — 3 tables, 9 rows written (LIVE)", GOOD),
     ("blue", "  submission code build0530 · SUBMISSION.md · 27/27 tests pass", BLUE)],
    [("banner", "-98.7% tokens · -98% time · success preserved", GOOD),
     ("muted", "github.com/OCWC22/personal-coding-autopilot", OUT),
     ("muted", "Built on EverMind memory + Butterbase backend", OUT)],
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
