"""Derive a MemoryProfile (repo conventions + coding preferences + repeated
patterns) from traces. Transparent frequency heuristics, not a model — the
memory is meant to be retrieved before generation so the model stops relearning
the repo every session.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath

from ..types import CodingTrace, MemoryProfile, TaskType

# Map directory shapes -> a human-readable convention line.
_DIR_CONVENTIONS = [
    (re.compile(r"app/"), "Next.js App Router (app/ directory)"),
    (re.compile(r"lib/supabase"), "Supabase client in /lib/supabase"),
    (re.compile(r"lib/auth"), "Auth logic in /lib/auth"),
    (re.compile(r"lib/stripe"), "Stripe billing in /lib/stripe"),
    (re.compile(r"components/ui"), "UI primitives in /components/ui"),
    (re.compile(r"app/dashboard"), "Dashboard routes in /app/dashboard"),
    (re.compile(r"prisma/"), "Prisma ORM (prisma/ directory)"),
    (re.compile(r"\.tsx$"), "TypeScript React (.tsx) components"),
]

_PREFERENCE_SIGNALS = [
    (re.compile(r"\bfull file|whole file|entire file\b", re.I), "Prefers complete file outputs"),
    (re.compile(r"don'?t add (a )?dependenc|no new (deps|packages|libraries)", re.I), "Avoids unnecessary dependencies"),
    (re.compile(r"\btype-?safe|strict types|no any\b", re.I), "Prefers type-safe changes"),
    (re.compile(r"tailwind", re.I), "Uses Tailwind"),
    (re.compile(r"shadcn", re.I), "Uses shadcn/ui"),
    (re.compile(r"\bconcise|brief|short\b", re.I), "Wants concise explanations"),
    (re.compile(r"minimal|simple|don'?t over-?engineer", re.I), "Likes minimal abstractions"),
    (re.compile(r"don'?t (touch|change|edit) (other|unrelated)", re.I), "Do not rewrite unrelated files"),
]

_TASK_PATTERN_LABEL = {
    TaskType.react_ui_edit.value: "React component polish",
    TaskType.typescript_fix.value: "TypeScript fixes",
    TaskType.test_generation.value: "Test scaffolding",
    TaskType.api_scaffold.value: "API route cleanup",
}


def build_memory(traces: list[CodingTrace], min_count: int = 2) -> MemoryProfile:
    conv_counter: Counter[str] = Counter()
    pref_counter: Counter[str] = Counter()
    avoid_counter: Counter[str] = Counter()
    task_counter: Counter[str] = Counter()

    for t in traces:
        files = t.files_touched + t.files_read
        for f in files:
            norm = str(PurePosixPath(f.replace("\\", "/")))
            for rx, label in _DIR_CONVENTIONS:
                if rx.search(norm):
                    conv_counter[label] += 1
        for rx, label in _PREFERENCE_SIGNALS:
            if rx.search(t.user_prompt):
                if "Do not" in label or "Avoid" in label:
                    avoid_counter[label] += 1
                else:
                    pref_counter[label] += 1
        label = _TASK_PATTERN_LABEL.get(t.task_type)
        if label:
            task_counter[label] += 1

    def top(counter: Counter[str], floor: int = min_count) -> list[str]:
        return [k for k, v in counter.most_common() if v >= floor] or [
            k for k, _ in counter.most_common(5)
        ]

    return MemoryProfile(
        coding_preferences=top(pref_counter, 1),
        repo_conventions=top(conv_counter),
        repeated_patterns=[k for k, _ in task_counter.most_common(8)],
        avoid_patterns=top(avoid_counter, 1),
        generated_by="heuristic",
    )
