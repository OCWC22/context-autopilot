---
name: autopilot-export
description: Export this machine's Claude Code (and Codex) coding history into a personal-coding-model dataset — traces, accepted diffs, repo conventions, coding preferences, and verifiable RL/eval tasks. Use when the user says "export my traces", "build my coding dataset", "run autopilot export", or wants to start a personal coding model from their own history.
---

# Autopilot: export your coding history

This skill turns the developer's **own local** Claude Code / Codex logs into a
training dataset for a personal coding model. It reads plaintext JSONL
transcripts that Claude Code already writes to `~/.claude/projects/` (and Codex
to `~/.codex/sessions/`), reconstructs coding traces, infers which edits were
accepted, derives a memory profile (repo conventions + coding preferences), and
emits SFT examples + verifiable RL/eval tasks.

## What it does NOT do

- It does not upload anything. Everything stays on the user's machine.
- It does not have a labeled accept/reject signal — acceptance is **inferred**
  heuristically from interruptions and applied-vs-unapplied edits. Be honest
  about this when reporting results.

## How to run

The real work is done by the bundled scraper, not this prompt. Run:

```bash
python3 skill/export_traces.py --out ./autopilot_out/dataset
```

or, if the `personal-coding-autopilot` package is installed:

```bash
autopilot export --out ./autopilot_out/dataset
autopilot build --dataset ./autopilot_out/dataset
```

Then report the printed summary to the user: traces imported, accepted diffs,
rejected patches, task-type distribution, and the small-data warning if the
dataset is under ~500 SFT examples (expect style/convention adaptation, not new
capability).

## Steps for Claude

1. Confirm the user wants to read their local coding history (it's their own
   data, on their own machine).
2. Run `skill/export_traces.py` (or `autopilot export` then `autopilot build`).
3. Summarize the JSON output. If `sft_examples < 500`, tell the user plainly
   that this gets repo-style adaptation, not a smarter model, and that memory +
   the eval gate carry most of the value at this size.
4. Point them at the next step: `autopilot plan` to see the model + serving +
   economics plan, then Stage A SFT (`autopilot train-sft`).
