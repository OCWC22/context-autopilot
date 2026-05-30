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
    [("banner", "Index once. Every agent reuses it.", TITLE),
     ("muted", "Context Autopilot — reusable context for local agents", OUT),
     ("blank", "", OUT)],
    # the problem (Hermes / OpenClaw / any agent)
    [("banner", "The problem", TITLE),
     ("warn", "  Hermes, OpenClaw, Claude Code rediscover your project every task —", ORANGE),
     ("warn", "  re-reading the code, docs, and notes they already saw last time.", ORANGE),
     ("muted", "  a 359 KB project ~ 90,000 tokens, reloaded again and again.", OUT)],
    # modular: ANY folder, not just code
    [("cmd", "autopilot index ~/any-folder      # not just code", PROMPT),
     ("good", "  codebases · docs · notes · sales · customer research · project folders", GOOD),
     ("out", "  -> one SKILL.md + DAG: a structured, reusable map of that context", OUT)],
    # reusable memory
    [("banner", "SKILL.md = the agent's project memory", TITLE),
     ("good", "  preloaded once, reused across tasks by Hermes / OpenClaw / Claude Code", GOOD),
     ("muted", "  the agent loads the map instead of re-exploring from scratch", OUT)],
    # how it extends EverMind + connects Butterbase
    [("banner", "Local source of truth x cloud memory", TITLE),
     ("good", "  EverMind: we EXTEND it — the $0 local index is always-fresh personal context", GOOD),
     ("out", "   decisions + lessons flow to EverMind -> long-context memory across sessions", OUT),
     ("blue", "  Butterbase: connects via Data API — task state, traces, evals, artifacts (LIVE)", BLUE)],
    # token before/after
    [("cmd", "# same task, two ways", PROMPT),
     ("warn", "  NORMAL agent        ->  rediscovers context  ->  11,947 tokens", ORANGE),
     ("good", "  WITH SAVED CONTEXT  ->  loads SKILL.md / DAG   ->  299 tokens", GOOD),
     ("metric", "  -98.7% tokens · same result · context preserved", GOOD)],
    [("banner", "Reusable context for any local agent", GOOD),
     ("blue", "  Hermes · OpenClaw · Claude Code  ·  EverMind memory + Butterbase (LIVE)", BLUE),
     ("muted", "  github.com/OCWC22/context-autopilot", OUT)],
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
