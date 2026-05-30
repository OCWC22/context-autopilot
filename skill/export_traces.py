#!/usr/bin/env python3
"""Bundled scraper for the autopilot-export skill.

Self-contained entry point: adds the package to sys.path if needed, runs the
exporter against the user's local Claude Code / Codex logs, and writes the
dataset. This is the script the SKILL.md refers to — a SKILL.md alone reads
nothing (see RECEIPTS.md cluster 2).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the package importable whether or not it's pip-installed.
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from autopilot.config import DEFAULT  # noqa: E402
from autopilot.export.exporter import export  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Export local coding traces -> dataset")
    p.add_argument("--claude-home", default=str(DEFAULT.paths.claude_home))
    p.add_argument("--codex-home", default=str(DEFAULT.paths.codex_home))
    p.add_argument("--sources", default="claude_code,codex")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--out", default=str(DEFAULT.paths.dataset))
    args = p.parse_args(argv)

    cfg = DEFAULT
    cfg.paths.claude_home = Path(args.claude_home)
    cfg.paths.codex_home = Path(args.codex_home)
    result = export(cfg, sources=tuple(args.sources.split(",")), limit=args.limit)
    out = Path(args.out)
    result.write(out)
    print(json.dumps(result.summary, indent=2))
    print(f"\nWrote dataset to {out.resolve()}")
    print("Next: `autopilot build` then `autopilot plan`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
