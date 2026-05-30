"""Trace export: read the user's own local Claude Code / Codex logs and git
history, infer accepted/rejected edits, and emit a clean dataset.

Honest caveat (RECEIPTS.md cluster 2): the JSONL formats are undocumented and
reverse-engineered; accept/reject is not a labeled field, so it is inferred.
"""
