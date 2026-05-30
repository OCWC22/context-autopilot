"""Stage A: convert accepted diffs into SFT examples.

Each example pairs the user's instruction with the memory + repo context that
should be retrieved at generation time, and the accepted patch as the target.
Rejected patches (when present) are attached as negative examples.

Honest scope (RECEIPTS.md cluster 5): a few hundred diffs gets style/convention
adaptation, not new capability. We emit clean instruction pairs and let the
trainer apply strong regularization + a held-out eval.
"""

from __future__ import annotations

from ..types import CodingTrace, MemoryProfile, SFTExample


def _patch_text(trace: CodingTrace) -> str:
    parts = []
    for e in trace.edits:
        if e.structured_patch:
            parts.append(f"--- {e.file_path}\n{e.structured_patch}")
        elif e.new_string:
            parts.append(f"--- {e.file_path}\n+ {e.new_string}")
    return "\n\n".join(parts)


def build_sft_examples(
    accepted: list[CodingTrace],
    memory: MemoryProfile,
    rejected_by_session: dict[str, CodingTrace] | None = None,
    max_patch_chars: int = 8000,
) -> list[SFTExample]:
    rejected_by_session = rejected_by_session or {}
    examples: list[SFTExample] = []
    mem_context = (
        memory.coding_preferences[:4]
        + memory.repo_conventions[:4]
    )
    for t in accepted:
        patch = _patch_text(t)
        if not patch:
            continue
        if len(patch) > max_patch_chars:
            patch = patch[:max_patch_chars] + "\n... [truncated]"
        repo_context = [f"Touched: {f}" for f in t.files_touched[:6]]
        repo_context += [f"Read: {f}" for f in t.files_read[:4]]
        neg = rejected_by_session.get(t.session_id)
        examples.append(
            SFTExample(
                instruction=t.user_prompt,
                memory_context=mem_context,
                repo_context=repo_context,
                accepted_patch=patch,
                rejected_patch=_patch_text(neg) if neg else None,
                metadata={
                    "task_type": t.task_type,
                    "tests_passed": t.tests_passed,
                    "lint_passed": t.lint_passed,
                    "typecheck_passed": t.typecheck_passed,
                    "risk_level": t.risk_level,
                    "accept_confidence": t.accept_confidence,
                },
            )
        )
    return examples


def to_chat_format(ex: SFTExample, system_prefix: str = "") -> dict:
    """Render an SFTExample as a chat-format record (messages list) for TRL."""
    context = "\n".join(f"- {m}" for m in ex.memory_context + ex.repo_context)
    user = ex.instruction
    if context:
        user = f"{ex.instruction}\n\nProject memory / context:\n{context}"
    system = system_prefix or (
        "You are a personal coding model fine-tuned on this developer's repo. "
        "Follow the project memory. Make minimal, type-safe diffs; do not touch "
        "unrelated files or add dependencies without being asked."
    )
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": ex.accepted_patch},
        ]
    }
