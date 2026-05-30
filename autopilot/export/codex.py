"""Parse Codex CLI rollout transcripts.

Codex stores rollout JSONL under ``~/.codex/sessions/<YYYY>/<MM>/<DD>/`` (path
resolved by the recorder). There is no first-class user-authored Skill on the
Codex side, so this is a standalone scraper (RECEIPTS.md cluster 2). The schema
differs from Claude Code but carries the same essentials: prompts, tool/function
calls, and file patches. Read defensively.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from ..types import CodingTrace, FileEdit
from .classify import classify_task_type, infer_risk


def iter_rollout_files(codex_home: Path) -> Iterator[Path]:
    sessions = codex_home / "sessions"
    if not sessions.is_dir():
        return
    yield from sorted(sessions.glob("**/*.jsonl"))


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return


def parse_rollout(path: Path) -> list[CodingTrace]:
    traces: list[CodingTrace] = []
    session_id = path.stem
    cur: CodingTrace | None = None

    for obj in _read_jsonl(path):
        role = obj.get("role") or obj.get("type")
        content = obj.get("content") or obj.get("text") or ""
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict)
            )

        if role in ("user", "input") and content:
            cur = CodingTrace(
                id=f"{session_id}:{len(traces)}",
                source="codex",
                session_id=session_id,
                task_title=str(content).strip().splitlines()[0][:120],
                task_type="other",
                user_prompt=str(content).strip(),
                timestamp=obj.get("timestamp", ""),
            )
            traces.append(cur)
        elif cur is not None:
            # function/tool calls: apply_patch, shell, etc.
            call = obj.get("function_call") or obj.get("tool_call") or {}
            name = call.get("name", obj.get("name", ""))
            args = call.get("arguments", obj.get("arguments", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if name in ("apply_patch", "edit", "write") and isinstance(args, dict):
                fp = args.get("path") or args.get("file_path") or ""
                patch = args.get("patch") or args.get("diff") or ""
                if fp:
                    cur.files_touched.append(str(fp))
                    cur.edits.append(FileEdit(file_path=str(fp), old_string="", new_string="", structured_patch=str(patch)))
                    cur.patch_accepted = True
                    cur.accept_confidence = 0.5
            elif name in ("shell", "bash", "exec") and isinstance(args, dict):
                cmd = args.get("command") or args.get("cmd") or ""
                if cmd:
                    cur.commands_run.append(str(cmd))

    for t in traces:
        t.task_type = classify_task_type(t.user_prompt, t.files_touched).value
        t.risk_level = infer_risk(t.task_type, t.files_touched).value
    return traces


def load_traces(codex_home: Path, limit: int | None = None) -> list[CodingTrace]:
    out: list[CodingTrace] = []
    for f in iter_rollout_files(codex_home):
        out.extend(parse_rollout(f))
        if limit and len(out) >= limit:
            return out[:limit]
    return out
