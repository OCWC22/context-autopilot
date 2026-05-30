"""The eval harness — the real product.

Proves *when* a local repo-context model + skills + memory + selective retrieval
reduce token usage, cost, and frontier calls while preserving task success. For
each task it runs two configs — `frontier_baseline` (send the whole repo to the
frontier model) vs `local_first` (selective retrieval + compression, escalate
only when needed) — and compares ContextBench-style retrieval precision/recall,
tokens, cost, frontier-call count, and test pass/fail.

See CITATIONS.md for the papers each metric/design draws on.
"""

from .harness import EvalTask, run_task, run_suite, compare, pretty  # noqa: F401
from .tasks import bundled_tasks, seed_eval_repo  # noqa: F401
