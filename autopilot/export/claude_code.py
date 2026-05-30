"""Parse Claude Code session transcripts.

Claude Code writes one JSONL file per session under
``~/.claude/projects/<encoded-cwd>/<session-id>.jsonl``. Each line is a JSON
object: a user message, an assistant message (which may contain tool_use
blocks), or a tool result. Edits land in ``toolUseResult`` with fields
``type=edit``, ``filePath``, ``oldString``, ``newString``, ``structuredPatch``.

The schema is undocumented and every field is optional, so we read defensively
(``.get`` everywhere) and never assume a key exists. See RECEIPTS.md cluster 2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..types import CodingTrace, FileEdit, RiskLevel
from .classify import classify_task_type, infer_risk


def iter_session_files(claude_home: Path) -> Iterator[Path]:
    projects = claude_home / "projects"
    if not projects.is_dir():
        return
    yield from sorted(projects.glob("*/*.jsonl"))


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _extract_text(message: Any) -> str:
    """Pull plain text out of a message.content that may be a string or a list
    of content blocks."""
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        content = message.get("content")
        return _extract_text(content)
    if isinstance(message, list):
        parts: list[str] = []
        for block in message:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(p for p in parts if p)
    return ""


def _extract_edit(tool_result: Any) -> FileEdit | None:
    if not isinstance(tool_result, dict):
        return None
    if tool_result.get("type") != "edit" and "filePath" not in tool_result:
        return None
    fp = tool_result.get("filePath") or tool_result.get("file_path")
    if not fp:
        return None
    sp = tool_result.get("structuredPatch")
    if isinstance(sp, list):
        # structuredPatch is a list of hunks; flatten the lines back to text
        sp_text = "\n".join(
            "\n".join(h.get("lines", [])) for h in sp if isinstance(h, dict)
        )
    else:
        sp_text = sp if isinstance(sp, str) else ""
    return FileEdit(
        file_path=str(fp),
        old_string=str(tool_result.get("oldString", tool_result.get("old_string", ""))),
        new_string=str(tool_result.get("newString", tool_result.get("new_string", ""))),
        structured_patch=sp_text,
    )


def parse_session(path: Path) -> list[CodingTrace]:
    """Reconstruct coding traces from one session file.

    A "trace" is anchored on a user prompt; the edits / commands / reads that
    follow it until the next user prompt are attributed to it.
    """
    traces: list[CodingTrace] = []
    session_id = path.stem

    cur: CodingTrace | None = None
    interrupted = False

    def finalize(t: CodingTrace | None, was_interrupted: bool) -> None:
        if t is None:
            return
        # Infer acceptance: edits that were applied and not interrupted, with no
        # downstream error, are treated as accepted. This is heuristic.
        if t.edits:
            t.patch_accepted = not was_interrupted
            t.accept_confidence = 0.6 if not was_interrupted else 0.2
        t.task_type = classify_task_type(t.user_prompt, t.files_touched).value
        t.risk_level = infer_risk(t.task_type, t.files_touched).value
        traces.append(t)

    for obj in _read_jsonl(path):
        otype = obj.get("type")
        msg = obj.get("message", obj)
        ts = obj.get("timestamp", "")

        # Detect an interruption / error signal on the previous turn.
        if obj.get("isApiErrorMessage") or obj.get("subtype") == "interrupted":
            interrupted = True

        if otype == "user":
            text = _extract_text(msg)
            # A real user prompt (not a tool result echoed back as a user turn).
            is_tool_echo = isinstance(msg, dict) and isinstance(msg.get("content"), list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in msg["content"]
            )
            if text and not is_tool_echo:
                finalize(cur, interrupted)
                interrupted = False
                cur = CodingTrace(
                    id=f"{session_id}:{len(traces)}",
                    source="claude_code",
                    session_id=session_id,
                    task_title=text.strip().splitlines()[0][:120] if text.strip() else "",
                    task_type="other",
                    user_prompt=text.strip(),
                    timestamp=ts,
                )
            # tool_result user turns may carry the edit payload
            tur = obj.get("toolUseResult")
            edit = _extract_edit(tur)
            if edit and cur is not None:
                cur.edits.append(edit)
                if edit.file_path not in cur.files_touched:
                    cur.files_touched.append(edit.file_path)

        elif otype == "assistant" and cur is not None:
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    name = block.get("name", "")
                    inp = block.get("input", {}) or {}
                    if name in ("Edit", "Write", "MultiEdit") and inp.get("file_path"):
                        fp = inp["file_path"]
                        if fp not in cur.files_touched:
                            cur.files_touched.append(fp)
                    elif name == "Read" and inp.get("file_path"):
                        fp = inp["file_path"]
                        if fp not in cur.files_read:
                            cur.files_read.append(fp)
                    elif name == "Bash" and inp.get("command"):
                        cmd = str(inp["command"])
                        cur.commands_run.append(cmd)
                        _note_check_signals(cur, cmd)

        # tool result objects sometimes appear at top level
        edit = _extract_edit(obj.get("toolUseResult"))
        if edit and cur is not None:
            cur.edits.append(edit)
            if edit.file_path not in cur.files_touched:
                cur.files_touched.append(edit.file_path)

    finalize(cur, interrupted)
    return traces


def _note_check_signals(trace: CodingTrace, command: str) -> None:
    """Heuristically read test/lint/typecheck intent from a bash command."""
    c = command.lower()
    if any(k in c for k in ("pytest", "npm test", "jest", "vitest", "go test", "cargo test")):
        trace.tests_passed = trace.tests_passed if trace.tests_passed is not None else True
    if any(k in c for k in ("tsc", "typecheck", "mypy", "pyright")):
        trace.typecheck_passed = trace.typecheck_passed if trace.typecheck_passed is not None else True
    if any(k in c for k in ("eslint", "ruff", "lint", "flake8", "biome")):
        trace.lint_passed = trace.lint_passed if trace.lint_passed is not None else True


def load_traces(claude_home: Path, limit: int | None = None) -> list[CodingTrace]:
    out: list[CodingTrace] = []
    for f in iter_session_files(claude_home):
        out.extend(parse_session(f))
        if limit and len(out) >= limit:
            return out[:limit]
    return out
