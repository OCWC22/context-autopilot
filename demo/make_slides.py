#!/usr/bin/env python3
"""Generate the hackathon submission deck (4 slides) -> demo/autopilot-slides.pptx.
Run with the venv that has python-pptx. Numbers are the real measured eval results."""

from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

BG = RGBColor(0x0A, 0x0C, 0x14)
FG = RGBColor(0xE8, 0xEA, 0xF2)
MUTED = RGBColor(0x9A, 0xA0, 0xB6)
TEAL = RGBColor(0x2D, 0xD4, 0xA7)
VIOLET = RGBColor(0xA7, 0x8B, 0xFA)
BLUE = RGBColor(0x4A, 0xA8, 0xFF)
ORANGE = RGBColor(0xFF, 0x78, 0x49)

W, H = Inches(13.333), Inches(7.5)
prs = Presentation()
prs.slide_width = W
prs.slide_height = H
BLANK = prs.slide_layouts[6]


def slide():
    s = prs.slides.add_slide(BLANK)
    r = s.shapes.add_shape(1, 0, 0, W, H)
    r.fill.solid(); r.fill.fore_color.rgb = BG; r.line.fill.background()
    r.shadow.inherit = False
    s.shapes._spTree.remove(r._element); s.shapes._spTree.insert(2, r._element)
    return s


def box(s, x, y, w, h):
    return s.shapes.add_textbox(x, y, w, h).text_frame


def txt(tf, text, size, color=FG, bold=False, align=PP_ALIGN.LEFT, font="Helvetica Neue", space=6):
    if tf.paragraphs[0].runs or tf.paragraphs[0].text:
        p = tf.add_paragraph()
    else:
        p = tf.paragraphs[0]
    p.alignment = align; p.space_after = Pt(space)
    run = p.add_run(); run.text = text
    f = run.font; f.size = Pt(size); f.bold = bold; f.color.rgb = color; f.name = font
    return p


def chip(s, x, y, label, color):
    sp = s.shapes.add_shape(5, x, y, Inches(2.6), Inches(0.5))
    sp.fill.solid(); sp.fill.fore_color.rgb = BG; sp.line.color.rgb = color; sp.line.width = Pt(1.25)
    sp.shadow.inherit = False
    tf = sp.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = label; r.font.size = Pt(12); r.font.color.rgb = color; r.font.bold = True
    return sp


# --- Slide 1: title ---
s = slide()
box(s, Inches(0.9), Inches(0.7), Inches(11), Inches(0.6)).paragraphs  # spacer
tf = box(s, Inches(0.9), Inches(2.1), Inches(11.5), Inches(2.6))
txt(tf, "Personal Coding Model Autopilot", 46, FG, bold=True)
txt(tf, "A $0 local repo-context model + skills + memory + subagents that cuts", 22, MUTED)
txt(tf, "frontier token usage, cost, and latency — with an eval harness that proves it.", 22, MUTED)
tf2 = box(s, Inches(0.9), Inches(5.1), Inches(11.5), Inches(1.5))
txt(tf2, "Touchdown Labs   ·   Beta Fund × EverMind Hackathon", 18, TEAL, bold=True)
txt(tf2, "Track: Next-Gen Infrastructure & Context   ·   github.com/OCWC22/personal-coding-autopilot", 14, MUTED)
chip(s, Inches(0.9), Inches(1.0), "INFERENCE ORCHESTRATION", VIOLET)

# --- Slide 2: problem + team ---
s = slide()
tf = box(s, Inches(0.9), Inches(0.7), Inches(11.5), Inches(1.2))
txt(tf, "The problem", 16, TEAL, bold=True)
txt(tf, "You pay frontier prices to re-discover your repo every session", 34, FG, bold=True)
tf = box(s, Inches(0.9), Inches(2.4), Inches(11.5), Inches(3))
for line in [
    "Coding agents (Claude Code / Codex) re-index the codebase and re-send context every turn.",
    "One request fans into dozens of hidden calls: plan, search, memory, file reads, checks, retries.",
    "On metered plans (the Jun 2026 Agent-SDK credit split), that quietly becomes a real API bill.",
    "The waste isn't the model — it's repeated context reconstruction. An orchestration problem.",
]:
    txt(tf, "•  " + line, 19, FG, space=12)
tf = box(s, Inches(0.9), Inches(5.7), Inches(11.5), Inches(1.2))
txt(tf, "Team — Touchdown Labs", 16, VIOLET, bold=True)
txt(tf, "Vendor-neutral inference-optimization research. Problem-fit: this is our daily thesis.", 16, MUTED)

# --- Slide 3: product / architecture ---
s = slide()
tf = box(s, Inches(0.9), Inches(0.7), Inches(11.5), Inches(0.9))
txt(tf, "What we built", 16, TEAL, bold=True)
txt(tf, "Local-first agent stack: cheap work local, frontier only for the hard step", 30, FG, bold=True)
tf = box(s, Inches(0.9), Inches(2.2), Inches(11.6), Inches(3.4))
for line in [
    ("$0 local indexer", "commit-versioned code DAG → SKILL.md bundle, refreshed on every change", TEAL),
    ("Selective retrieval", "Repoformer gate + GraphCoder-style symbol graph + LLavaCode compression", BLUE),
    ("Local subagents + RLM", "routing, search, code checks, summarize — escalate only when needed", VIOLET),
    ("Eval harness", "measures tokens / time / accuracy vs normal Claude Code (the real product)", ORANGE),
]:
    p = txt(tf, line[0] + "  —  ", 20, line[2], bold=True, space=14)
    r = p.add_run(); r.text = line[1]; r.font.size = Pt(18); r.font.color.rgb = FG
tf = box(s, Inches(0.9), Inches(5.8), Inches(11.5), Inches(1.2))
txt(tf, "Sponsors", 16, MUTED, bold=True)
p = txt(tf, "EverMind/EverOS = long-term agent memory (built on it).   ", 17, TEAL)
r = p.add_run(); r.text = "Butterbase = backend + judging surface (build0530)."; r.font.size = Pt(17); r.font.color.rgb = BLUE

# --- Slide 4: proof ---
s = slide()
tf = box(s, Inches(0.9), Inches(0.6), Inches(11.5), Inches(0.9))
txt(tf, "The proof  ·  autopilot eval (measured)", 16, TEAL, bold=True)
txt(tf, "local-first (indexed)  vs  normal Claude Code", 30, FG, bold=True)

metrics = [("−98.7%", "tokens", TEAL), ("−98.0%", "time", BLUE),
           ("−93.9%", "cost", VIOLET), ("+0.32", "retrieval F1", ORANGE)]
x = Inches(0.9)
for val, lab, col in metrics:
    sp = s.shapes.add_shape(5, x, Inches(2.1), Inches(2.85), Inches(1.9))
    sp.fill.solid(); sp.fill.fore_color.rgb = RGBColor(0x10, 0x13, 0x1E)
    sp.line.color.rgb = col; sp.line.width = Pt(1.5); sp.shadow.inherit = False
    tfc = sp.text_frame; tfc.vertical_anchor = MSO_ANCHOR.MIDDLE
    txt(tfc, val, 40, col, bold=True, align=PP_ALIGN.CENTER, space=2)
    txt(tfc, lab, 16, MUTED, align=PP_ALIGN.CENTER)
    x = Emu(x + Inches(3.0))
tf = box(s, Inches(0.9), Inches(4.4), Inches(11.5), Inches(2.2))
txt(tf, "1 frontier call avoided  ·  task success preserved (tests pass)  ·  retrieval recall 1.0", 19, FG, bold=True, space=12)
txt(tf, "Baseline dumps the whole 11,947-token repo; local-first sends ~150 tokens of the right context.", 17, MUTED, space=12)
txt(tf, "Live: EverMind memory written (real API). $0 local index builds in ~300ms. 27/27 tests pass.", 17, MUTED)

out = Path(__file__).resolve().parent / "autopilot-slides.pptx"
prs.save(str(out))
print("wrote", out)
