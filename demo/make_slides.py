#!/usr/bin/env python3
"""Generate the live-demo deck -> demo/autopilot-slides.pptx (6 slides).
Demo-oriented: problem -> pain -> use case -> fix -> demo flow -> proof.
Numbers are the real measured eval results. Run with the venv that has python-pptx."""

from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

BG = RGBColor(0x0A, 0x0C, 0x14)
PANEL = RGBColor(0x10, 0x13, 0x1E)
FG = RGBColor(0xE8, 0xEA, 0xF2)
MUTED = RGBColor(0x9A, 0xA0, 0xB6)
TEAL = RGBColor(0x2D, 0xD4, 0xA7)
VIOLET = RGBColor(0xA7, 0x8B, 0xFA)
BLUE = RGBColor(0x4A, 0xA8, 0xFF)
ORANGE = RGBColor(0xFF, 0x78, 0x49)

W, H = Inches(13.333), Inches(7.5)
prs = Presentation(); prs.slide_width = W; prs.slide_height = H
BLANK = prs.slide_layouts[6]
PAGE = [0]


def slide(footer=True):
    s = prs.slides.add_slide(BLANK)
    r = s.shapes.add_shape(1, 0, 0, W, H)
    r.fill.solid(); r.fill.fore_color.rgb = BG; r.line.fill.background(); r.shadow.inherit = False
    s.shapes._spTree.remove(r._element); s.shapes._spTree.insert(2, r._element)
    bar = s.shapes.add_shape(1, 0, 0, Inches(0.14), H)
    bar.fill.solid(); bar.fill.fore_color.rgb = TEAL; bar.line.fill.background(); bar.shadow.inherit = False
    PAGE[0] += 1
    if footer:
        tf = s.shapes.add_textbox(Inches(0.6), Inches(7.0), Inches(12.2), Inches(0.4)).text_frame
        p = tf.paragraphs[0]
        run = p.add_run(); run.text = "EverMind + Butterbase: LIVE  ·  app_b197i2548pk2  ·  build0530"
        run.font.size = Pt(10); run.font.color.rgb = MUTED
        run2 = p.add_run(); run2.text = f"        {PAGE[0]}/7"; run2.font.size = Pt(10); run2.font.color.rgb = MUTED
    return s


def tb(s, x, y, w, h):
    return s.shapes.add_textbox(x, y, w, h).text_frame


def txt(tf, text, size, color=FG, bold=False, align=PP_ALIGN.LEFT, space=6):
    p = tf.add_paragraph() if (tf.paragraphs[0].runs or tf.paragraphs[0].text) else tf.paragraphs[0]
    p.alignment = align; p.space_after = Pt(space)
    r = p.add_run(); r.text = text
    r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = color; r.font.name = "Helvetica Neue"
    return p


def eyebrow(s, text, color=TEAL):
    txt(tb(s, Inches(0.6), Inches(0.55), Inches(12), Inches(0.5)), text, 15, color, bold=True)


def panel(s, x, y, w, h, accent):
    sp = s.shapes.add_shape(5, x, y, w, h)
    sp.fill.solid(); sp.fill.fore_color.rgb = PANEL; sp.line.color.rgb = accent; sp.line.width = Pt(1.25)
    sp.shadow.inherit = False
    return sp


def flowbox(s, x, y, w, h, title, sub, color):
    sp = panel(s, x, y, w, h, color)
    tf = sp.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Inches(0.1); tf.margin_right = Inches(0.1)
    txt(tf, title, 13, color, bold=True, align=PP_ALIGN.CENTER, space=2)
    if sub:
        txt(tf, sub, 10.5, FG, align=PP_ALIGN.CENTER, space=0)
    return sp


def arrow(s, x, y):
    txt(tb(s, x, y, Inches(0.4), Inches(0.4)), "→", 20, MUTED, bold=True, align=PP_ALIGN.CENTER)


def band(s, items, y, label, lblcolor, h=1.3, gap=0.45):
    txt(tb(s, Inches(0.6), Inches(y - 0.45), Inches(12), Inches(0.4)), label, 13, lblcolor, bold=True)
    n = len(items); bw = (12.1 - (n - 1) * gap) / n
    for i, (title, sub, col) in enumerate(items):
        x = 0.6 + i * (bw + gap)
        flowbox(s, Inches(x), Inches(y), Inches(bw), Inches(h), title, sub, col)
        if i < n - 1:
            arrow(s, Inches(x + bw + (gap - 0.4) / 2), Inches(y + h / 2 - 0.2))


# 1 — TITLE / WHO / PROBLEM / SOLUTION
s = slide(footer=False)
txt(tb(s, Inches(0.9), Inches(0.55), Inches(11.6), Inches(0.5)), "BETA FUND × EVERMIND  ·  NEXT-GEN INFRASTRUCTURE & CONTEXT", 14, VIOLET, bold=True)
t = tb(s, Inches(0.9), Inches(1.2), Inches(11.6), Inches(1.5))
txt(t, "Personal Coding Model Autopilot", 38, FG, bold=True)
txt(t, "William Chen · Touchdown Labs — vendor-neutral inference-optimization research", 17, TEAL, bold=True)
txt(tb(s, Inches(0.9), Inches(2.75), Inches(11.6), Inches(0.9)),
    "What I'm building: a local-first coding-agent stack — a $0 model that already knows your repo, plus a personal coding model distilled to your codebase and style.", 16, FG)
pp = panel(s, Inches(0.9), Inches(3.85), Inches(5.7), Inches(2.4), ORANGE)
tf = pp.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.TOP
tf.margin_left = Inches(0.28); tf.margin_top = Inches(0.22); tf.margin_right = Inches(0.2)
txt(tf, "The problem", 18, ORANGE, bold=True)
txt(tf, "Claude Code re-reads your repo every session — you pay frontier prices to rediscover structure you already have (≈90K tokens to reload a 359 KB repo, every time).", 15, FG)
ps = panel(s, Inches(7.0), Inches(3.85), Inches(5.7), Inches(2.4), TEAL)
tf2 = ps.text_frame; tf2.word_wrap = True; tf2.vertical_anchor = MSO_ANCHOR.TOP
tf2.margin_left = Inches(0.28); tf2.margin_top = Inches(0.22); tf2.margin_right = Inches(0.2)
txt(tf2, "The solution", 18, TEAL, bold=True)
txt(tf2, "Keep a live local map (SKILL.md + DAG) and a small MLX model for the cheap work; escalate to the frontier only for the hard step — ~99% fewer tokens, same result.", 15, FG)
txt(tb(s, Inches(0.9), Inches(6.5), Inches(11.6), Inches(0.5)), "github.com/OCWC22/personal-coding-autopilot", 15, MUTED, bold=True)

# 2 — THE FULL SYSTEM / ARCHITECTURE
s = slide(); eyebrow(s, "THE FULL SYSTEM")
txt(tb(s, Inches(0.6), Inches(0.95), Inches(12.2), Inches(0.7)), "How SFT, RL, local AI & MLX fit together", 27, FG, bold=True)
txt(tb(s, Inches(0.6), Inches(1.62), Inches(12.2), Inches(0.6)),
    "Goal: cut frontier-model calls & cost while preserving task success — a coding model that learns your repo and style from your own traces.", 14, MUTED)
band(s, [
    ("Your traces + repo", "Claude Code / Codex sessions, accepted diffs", TEAL),
    ("SFT", "distill GLM-5.1 (teacher) → student", BLUE),
    ("RL", "verifiable rewards (GRPO): tests pass", VIOLET),
    ("MLX model", "personal coder · 16 GB Mac · $0", ORANGE),
], y=2.85, label="OFFLINE — build your personal model (cheap, on-device)", lblcolor=TEAL)
band(s, [
    ("Coding task", "question / fix / refactor", TEAL),
    ("Local context + subagents", "$0 DAG / SKILL.md + RLM — runs local", BLUE),
    ("Frontier only when hard", "escalate to Claude / Codex", VIOLET),
], y=4.95, label="ONLINE — every task", lblcolor=TEAL)
txt(tb(s, Inches(0.6), Inches(6.35), Inches(12.2), Inches(0.5)),
    "Substrate:  EverMind = long-term memory   ·   Butterbase = state / backend   ·   eval harness = the proof (−98.7% tokens)", 14, MUTED, bold=True)

# 3 — USE CASE
s = slide(); eyebrow(s, "USE CASE")
txt(tb(s, Inches(0.6), Inches(1.0), Inches(12), Inches(1)), "You, on a real repo, all day", 32, FG, bold=True)
tf = tb(s, Inches(0.6), Inches(2.2), Inches(12), Inches(3.5))
for l in ["Solo founder / small team living in Claude Code or Codex on one codebase.",
          "Asking codebase questions, fixing tests, scaffolding, refactoring — dozens of times a day.",
          "Each ask re-pays for repo discovery. The bill compounds outside the model call.",
          "You want the agent to already know your files, conventions, and prior decisions."]:
    txt(tf, "•  " + l, 19, FG, space=14)

# 4 — THE FIX
s = slide(); eyebrow(s, "THE FIX")
txt(tb(s, Inches(0.6), Inches(1.0), Inches(12), Inches(0.9)), "A $0 local map Claude reads instead of the whole repo", 28, FG, bold=True)
tf = tb(s, Inches(0.6), Inches(2.05), Inches(12.1), Inches(3.2))
for name, desc, col in [
    ("SKILL.md + DAG", "commit-versioned: every file, every function, the call graph — refreshed on each change", TEAL),
    ("Selective retrieval", "send only the relevant slice, compressed (8.8× on a real query)", BLUE),
    ("$0 + local", "the index runs on your machine for nothing; frontier is used only for the hard step", VIOLET),
    ("Sponsors", "EverMind = long-term memory (prior decisions) · Butterbase = state/backend + judging", ORANGE),
]:
    pp = txt(tf, name + "  —  ", 19, col, bold=True, space=14)
    r = pp.add_run(); r.text = desc; r.font.size = Pt(17); r.font.color.rgb = FG

# 5 — DEMO FLOW
s = slide(); eyebrow(s, "DEMO FLOW  (what I'll show live)")
txt(tb(s, Inches(0.6), Inches(1.0), Inches(12), Inches(0.8)), "Watch the token meter drop", 30, FG, bold=True)
tf = tb(s, Inches(0.6), Inches(2.0), Inches(12.1), Inches(3.6))
for n, l, col in [
    ("1", "Ask a codebase question the normal way → Claude Code explores files (big token count).", ORANGE),
    ("2", "Run  `autopilot index`  → open .autopilot/SKILL.md + ARCHITECTURE.md (the DAG).", TEAL),
    ("3", "Ask again with that saved context → answer from the right slice (tiny token count).", BLUE),
    ("4", "Compare:  `autopilot eval`  → 11,947 → 299 tokens, −98.7%, tests still pass.", VIOLET),
]:
    pp = txt(tf, n + ".  ", 20, col, bold=True, space=16)
    r = pp.add_run(); r.text = l; r.font.size = Pt(18); r.font.color.rgb = FG

# 6 — PROOF
s = slide(); eyebrow(s, "PROOF  ·  autopilot eval (measured)")
txt(tb(s, Inches(0.6), Inches(1.0), Inches(12), Inches(0.8)), "Same task. Same result. 98.7% fewer tokens.", 28, FG, bold=True)
metrics = [("−98.7%", "tokens", TEAL), ("−98%", "time", BLUE), ("−94%", "cost", VIOLET), ("+0.32", "retrieval F1", ORANGE)]
x = Inches(0.6)
for val, lab, col in metrics:
    sp = panel(s, x, Inches(2.1), Inches(2.95), Inches(1.9), col)
    tfc = sp.text_frame; tfc.vertical_anchor = MSO_ANCHOR.MIDDLE
    txt(tfc, val, 40, col, bold=True, align=PP_ALIGN.CENTER, space=2)
    txt(tfc, lab, 16, MUTED, align=PP_ALIGN.CENTER)
    x = Emu(x + Inches(3.1))
tf = tb(s, Inches(0.6), Inches(4.4), Inches(12.1), Inches(2.2))
txt(tf, "11,947 → 299 tokens · 1 frontier call avoided · task success preserved (tests pass)", 18, FG, bold=True, space=12)
txt(tf, "Live now: Butterbase app app_b197i2548pk2 (real rows) · EverMind memory written · 27/27 tests.", 16, MUTED, space=12)
txt(tf, "Reproduce on stage:  autopilot index  ·  autopilot eval  ·  bash demo/run_demo.sh", 16, TEAL, bold=True)

# 7 — LIVE DEMO (embedded video)
s = slide(); eyebrow(s, "DEMO  ·  the token drop in 30s")
txt(tb(s, Inches(0.6), Inches(1.0), Inches(12), Inches(0.8)),
    "Same task, two ways — watch tokens go 11,947 → 299", 26, FG, bold=True)
_here = Path(__file__).resolve().parent
_vid = _here / "autopilot-demo.mp4"
_poster = _here / "poster.png"
vw, vh = Inches(9.6), Inches(5.4)
vx = Emu(int((W - vw) / 2)); vy = Inches(1.75)
s.shapes.add_movie(str(_vid), vx, vy, vw, vh,
                   poster_frame_image=str(_poster) if _poster.exists() else None,
                   mime_type="video/mp4")

out = _here / "autopilot-slides.pptx"
prs.save(str(out)); print("wrote", out)
