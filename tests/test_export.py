"""Tests for the Claude Code transcript parser + classifier (RECEIPTS.md cluster 2).

Claude Code writes one JSONL session file per project under
``~/.claude/projects/<encoded-cwd>/<session>.jsonl``; every Edit lands in a
``toolUseResult`` with ``type=edit`` and a ``structuredPatch``. ``patch_accepted``
is INFERRED, not labeled (cluster 2), so we assert the heuristic only — an
uninterrupted edit is inferred accepted.

All stdlib-only: this is the offline export path, no heavy deps required.
"""

from __future__ import annotations

import json
from pathlib import Path

from autopilot.export.claude_code import parse_session
from autopilot.export.classify import classify_task_type, infer_risk
from autopilot.types import TaskType, RiskLevel


def _write_session(tmp_path: Path) -> Path:
    """Build a minimal but schema-faithful Claude Code session file:
    one real user prompt, one assistant Edit tool_use, and one user turn
    carrying the toolUseResult edit payload with a structuredPatch.
    """
    project_dir = tmp_path / ".claude" / "projects" / "-Users-demo-myrepo"
    project_dir.mkdir(parents=True)
    session = project_dir / "0001-session.jsonl"

    lines: list[dict] = [
        {
            "type": "user",
            "timestamp": "2026-05-30T00:00:00Z",
            "message": {
                "role": "user",
                "content": "add a react component with tailwind for the header",
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-05-30T00:00:01Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Edit",
                        "input": {
                            "file_path": "src/components/Header.tsx",
                            "old_string": "",
                            "new_string": "export const Header = () => null;",
                        },
                    }
                ],
            },
        },
        {
            "type": "user",
            "timestamp": "2026-05-30T00:00:02Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "File updated"}
                ],
            },
            "toolUseResult": {
                "type": "edit",
                "filePath": "src/components/Header.tsx",
                "oldString": "",
                "newString": "export const Header = () => null;",
                "structuredPatch": [
                    {
                        "lines": [
                            "+export const Header = () => null;",
                        ]
                    }
                ],
            },
        },
    ]

    with session.open("w", encoding="utf-8") as fh:
        for obj in lines:
            fh.write(json.dumps(obj) + "\n")
    return session


def test_parse_session_captures_edit_and_infers_acceptance(tmp_path: Path) -> None:
    session = _write_session(tmp_path)

    traces = parse_session(session)

    assert len(traces) >= 1
    trace = traces[0]
    # The edit was captured from the toolUseResult payload.
    assert len(trace.edits) >= 1
    edit = trace.edits[0]
    assert edit.file_path == "src/components/Header.tsx"
    assert "Header" in edit.new_string
    assert edit.structured_patch  # flattened from structuredPatch hunks
    assert "src/components/Header.tsx" in trace.files_touched
    # Uninterrupted edit => acceptance is heuristically inferred True (cluster 2).
    assert trace.patch_accepted is True
    assert trace.accept_confidence > 0.0


def test_classify_react_ui_edit() -> None:
    ttype = classify_task_type("add a react component with tailwind", files_touched=[])
    assert ttype == TaskType.react_ui_edit


def test_classify_typescript_fix() -> None:
    ttype = classify_task_type("fix the type error in the build", files_touched=[])
    assert ttype == TaskType.typescript_fix


def test_infer_risk_high_for_security_change() -> None:
    risk = infer_risk(TaskType.security_change.value, files_touched=[])
    assert risk == RiskLevel.high
