"""autopilot CLI — the operator surface over the pipeline.

    autopilot export        read local Claude Code / Codex logs -> dataset
    autopilot build         dataset -> SFT examples + RL tasks + eval split
    autopilot train-sft     Stage A: LoRA warm-up on the student (needs [train])
    autopilot train-rl      Stage B: verifiable-reward GRPO (needs [rl])
    autopilot serve         deploy the Modal/vLLM endpoint (needs [serve])
    autopilot route         dry-run the routing policy over built tasks
    autopilot plan          print the model/serve/economics plan + receipts

The offline subcommands (export/build/route/plan) run with zero heavy deps.
Training/serving subcommands import their deps lazily and print install hints if
missing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import Config, DEFAULT


def _cmd_export(args: argparse.Namespace) -> int:
    from .export.exporter import export

    cfg = DEFAULT
    if args.claude_home:
        cfg.paths.claude_home = Path(args.claude_home)
    if args.codex_home:
        cfg.paths.codex_home = Path(args.codex_home)
    sources = tuple(args.sources.split(",")) if args.sources else ("claude_code", "codex")
    result = export(cfg, sources=sources, limit=args.limit)
    out = Path(args.out) if args.out else cfg.paths.dataset
    result.write(out)
    print(json.dumps(result.summary, indent=2))
    print(f"\nWrote dataset to {out}")
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    from .types import CodingTrace, MemoryProfile
    from .dataset.build_sft import build_sft_examples, to_chat_format
    from .dataset.build_tasks import build_tasks
    from .dataset.split import split

    ds = Path(args.dataset) if args.dataset else DEFAULT.paths.dataset
    traces = [CodingTrace(**r) for r in _read_jsonl(ds / "traces.jsonl")]
    # FileEdit dicts need rehydrating
    for t in traces:
        from .types import FileEdit
        t.edits = [FileEdit(**e) if isinstance(e, dict) else e for e in t.edits]
    accepted = [t for t in traces if t.patch_accepted and t.edits]
    mem_raw = json.loads((ds / "memory.json").read_text())
    memory = MemoryProfile(**mem_raw)

    rejected_by_session = {t.session_id: t for t in traces if t.edits and not t.patch_accepted}
    sft = build_sft_examples(accepted, memory, rejected_by_session)
    tasks = build_tasks(traces, memory, only_personal_ok=DEFAULT.risk.personal_ok)

    sft_train, sft_eval = split(sft, key_fn=lambda e: e.instruction, eval_frac=args.eval_frac)
    task_train, task_eval = split(tasks, key_fn=lambda t: t.id, eval_frac=args.eval_frac)

    out = ds
    _write_jsonl(out / "sft_train.jsonl", (to_chat_format(e) for e in sft_train))
    _write_jsonl(out / "sft_eval.jsonl", (to_chat_format(e) for e in sft_eval))
    _write_jsonl(out / "rl_train.jsonl", (t.to_dict() for t in task_train))
    _write_jsonl(out / "rl_eval.jsonl", (t.to_dict() for t in task_eval))
    summary = {
        "sft_examples": len(sft),
        "sft_train": len(sft_train),
        "sft_eval": len(sft_eval),
        "rl_tasks": len(tasks),
        "rl_train": len(task_train),
        "rl_eval": len(task_eval),
        "small_data_warning": (
            f"{len(sft)} SFT examples — below the comfortable 500-1000 band; "
            "expect style/convention adaptation, not new capability. Strong "
            "regularization + held-out eval applied."
            if len(sft) < 500
            else "dataset size adequate"
        ),
    }
    print(json.dumps(summary, indent=2))
    return 0


def _cmd_route(args: argparse.Namespace) -> int:
    from .serve.router import CodingTask, route_task

    ds = Path(args.dataset) if args.dataset else DEFAULT.paths.dataset
    rows = list(_read_jsonl(ds / "rl_eval.jsonl")) or list(_read_jsonl(ds / "traces.jsonl"))
    # demo eval pass rates per task type (replace with real eval output)
    demo_rates = {
        "react_ui_edit": 0.91, "typescript_fix": 0.88, "test_generation": 0.84,
        "api_scaffold": 0.82, "schema_migration": 0.61, "architecture_refactor": 0.44,
    }
    routed = {"personal": 0, "fallback": 0}
    for r in rows:
        task = CodingTask(
            id=r.get("id", ""),
            prompt=r.get("prompt", ""),
            task_type=r.get("task_type", "other"),
            risk=r.get("risk_level", "medium"),
            files_touched=r.get("files_touched", r.get("repo_context", [])),
            eval_pass_rate=demo_rates.get(r.get("task_type", ""), 0.0),
        )
        res = route_task(
            task, DEFAULT.risk,
            run_personal=lambda t: ("<personal patch>", True, True),
            run_fallback=lambda t: "<fallback patch>",
        )
        routed[res.decision.route] += 1
    total = sum(routed.values()) or 1
    print(json.dumps({
        "tasks": total,
        "routed_personal": routed["personal"],
        "routed_fallback": routed["fallback"],
        "personal_share_pct": round(100 * routed["personal"] / total, 1),
        "note": "savings accrue only vs metered API spend, not a flat subscription",
    }, indent=2))
    return 0


def _cmd_train_sft(args: argparse.Namespace) -> int:
    try:
        from .train.sft_lora import run_sft
    except ImportError as e:
        print(f"train deps missing ({e}). Install: pip install -e '.[train]'", file=sys.stderr)
        return 2
    return run_sft(Path(args.dataset) if args.dataset else DEFAULT.paths.dataset, model=args.model)


def _cmd_train_rl(args: argparse.Namespace) -> int:
    try:
        from .train.grpo import run_grpo
    except ImportError as e:
        print(f"rl deps missing ({e}). Install: pip install -e '.[rl]'", file=sys.stderr)
        return 2
    return run_grpo(Path(args.dataset) if args.dataset else DEFAULT.paths.dataset, model=args.model)


def _cmd_serve(args: argparse.Namespace) -> int:
    print("Serving is a Modal app. Deploy with:\n")
    print("  modal deploy autopilot/serve/modal_app.py\n")
    print("This provisions a serverless (scale-to-zero) GPU + vLLM OpenAI endpoint.")
    print("See autopilot/serve/modal_app.py and RECEIPTS.md cluster 3/7 for the economics.")
    return 0


def _cmd_distill(args: argparse.Namespace) -> int:
    """Offline GLM-5.1 -> MLX-student distillation (separate offline process)."""
    from .distill.pipeline import run_distill

    ds = Path(args.dataset) if args.dataset else DEFAULT.paths.dataset
    return run_distill(
        ds,
        model=args.model,
        max_tasks=args.max_tasks,
        print_only=not args.run,
    )


def _cmd_mlx_serve(args: argparse.Namespace) -> int:
    """Serve the distilled student locally (OpenAI-compatible) via mlx_lm.server."""
    from .mlx_serve.server import main as serve_main

    argv = []
    if args.model:
        argv += ["--model", args.model]
    if args.adapter_path:
        argv += ["--adapter-path", args.adapter_path]
    if args.print_only:
        argv += ["--print-only"]
    return serve_main(argv)


def _cmd_review(args: argparse.Namespace) -> int:
    """Multi-subagent engineering review: 6 RLM checks -> compact evidence -> gate."""
    from .checks.orchestrator import run_review, pretty

    backend = args.sub_lm or DEFAULT.checks.sub_lm
    checks = tuple(args.checks.split(",")) if args.checks else None
    report = run_review(args.repo, checks=checks, sub_lm_backend=backend)
    print(pretty(report))
    if args.json:
        print(json.dumps(report, indent=2))
    # exit code reflects the gate so CI can use it
    return {"pass": 0, "warn": 0, "fail": 1, "unknown": 0}.get(report["gate"]["gate"], 0)


def _cmd_eval(args: argparse.Namespace) -> int:
    """Run the eval harness: local_first vs frontier_baseline on seeded tasks."""
    import tempfile
    from .evals import bundled_tasks, run_suite, compare, pretty

    base = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="autopilot_eval_"))
    tasks = bundled_tasks(base)
    metrics = run_suite(tasks, backend=args.backend or "stub")
    cmp = compare(metrics)
    print(pretty(metrics, cmp))
    if args.json:
        print(json.dumps({"metrics": [m.to_dict() for m in metrics], "comparison": cmp}, indent=2))
    return 0


def _cmd_index(args: argparse.Namespace) -> int:
    """Build the full .autopilot/ bundle: entrypoint SKILL.md linking the
    versioned DAG (ARCHITECTURE.md), dag.json, and verify/ scripts ($0, local)."""
    from .repo import build_bundle

    res = build_bundle(args.repo, max_commits=args.max_commits)
    print(json.dumps(res, indent=2))
    return 0


def _cmd_submit(args: argparse.Namespace) -> int:
    """Hackathon submission: Butterbase (backend + judging) + EverMind (memory)."""
    from .hackathon import submit
    from .hackathon.submit import write_submission_md

    plan = submit(args.repo, dry_run=(True if args.dry_run else None))
    md = write_submission_md(Path(args.repo), plan)
    print(json.dumps({k: v for k, v in plan.items() if k != "eval"}, indent=2, default=str))
    print(f"\nSUBMISSION.md -> {md}")
    print(f"Submit via Butterbase MCP with code: {plan['submission_code']}")
    return 0


def _cmd_dag(args: argparse.Namespace) -> int:
    """Deterministic, commit-versioned code DAG -> .autopilot/ARCHITECTURE.md + dag.json."""
    from .repo.dag import DAGBuilder

    b = DAGBuilder(args.repo)
    dag = b.build(max_commits=args.max_commits)
    md, js = b.write(dag)
    print(json.dumps({
        "version": dag.version, "generated_at": dag.generated_at,
        "files": len(dag.files), "functions": len(dag.functions),
        "import_edges": len(dag.import_edges), "call_edges": len(dag.call_edges),
        "commits": len(dag.commits),
        "architecture_md": str(md), "dag_json": str(js),
    }, indent=2))
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    """Real-time: re-index + regenerate SKILL.md on every change ($0, local)."""
    from .repo import RepoWatcher

    w = RepoWatcher(args.repo)

    def on_change(res):
        ch = res.get("changed") or []
        print(f"[reindex] files={res['n_files']} symbols={res['n_symbols']} "
              f"changed={len(ch)} -> {res['skill_md']} "
              f"(local $0; frontier rediscovery ${res['cost']['frontier_rediscovery_cost_usd']})")

    w.watch(interval=args.interval, max_iterations=args.max_iterations, on_change=on_change)
    return 0


def _cmd_repo_context(args: argparse.Namespace) -> int:
    """Selective repo-context retrieval for one query (the local context layer)."""
    from .repo import RepoContextLayer
    from .agent.local import LocalModel
    from .agent.memory_backend import make_memory_backend

    layer = RepoContextLayer(args.repo, local_model=LocalModel("stub"),
                             memory_backend=make_memory_backend(DEFAULT))
    res = layer.answer(args.query, top_k=args.top_k)
    print(json.dumps({
        "should_retrieve": res.should_retrieve,
        "retrieved": [{"path": f.path, "score": f.score, "why": f.why} for f in res.retrieved],
        "skills_used": res.skills_used,
        "memory_used": res.memory_used,
        "context_chars": res.context_chars,
        "compact_chars": res.compact_chars,
        "compression_ratio": res.compression_ratio,
    }, indent=2))
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    cfg = DEFAULT
    plan = {
        "models": {
            "student_now": cfg.models.student,
            "target": cfg.models.target,
            "target_small": cfg.models.target_small,
            "teacher_fallback": cfg.models.fallback,
        },
        "stages": [
            "export local traces -> dataset + memory",
            "build SFT examples + verifiable RL tasks + held-out eval",
            "Stage A: LoRA SFT warm-up on student",
            "Stage B: GRPO with verifiable rewards (verifiers + prime-rl)",
            "serve LoRA on Modal serverless vLLM (scale-to-zero)",
            "route: low-risk+verified -> personal, else Claude/Codex fallback",
        ],
        "reward": cfg.reward.__dict__,
        "economics_honesty": (
            "Savings accrue against METERED API / Agent-SDK-credit spend (post "
            "Jun 15 2026 split), NOT a flat $20/$100/$200 subscription. Serverless "
            "scale-to-zero is the only solo-volume-viable serving config."
        ),
        "receipts": "see RECEIPTS.md",
    }
    print(json.dumps(plan, indent=2))
    return 0


def _read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="autopilot", description="Context Autopilot")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export", help="read local Claude Code / Codex logs -> dataset")
    e.add_argument("--claude-home")
    e.add_argument("--codex-home")
    e.add_argument("--sources", help="comma list: claude_code,codex")
    e.add_argument("--limit", type=int)
    e.add_argument("--out")
    e.set_defaults(func=_cmd_export)

    b = sub.add_parser("build", help="dataset -> SFT examples + RL tasks + eval split")
    b.add_argument("--dataset")
    b.add_argument("--eval-frac", type=float, default=0.2)
    b.set_defaults(func=_cmd_build)

    r = sub.add_parser("route", help="dry-run the routing policy over built tasks")
    r.add_argument("--dataset")
    r.set_defaults(func=_cmd_route)

    ts = sub.add_parser("train-sft", help="Stage A: LoRA SFT warm-up (needs [train])")
    ts.add_argument("--dataset")
    ts.add_argument("--model")
    ts.set_defaults(func=_cmd_train_sft)

    tr = sub.add_parser("train-rl", help="Stage B: verifiable-reward GRPO (needs [rl])")
    tr.add_argument("--dataset")
    tr.add_argument("--model")
    tr.set_defaults(func=_cmd_train_rl)

    s = sub.add_parser("serve", help="how to deploy the Modal/vLLM endpoint")
    s.set_defaults(func=_cmd_serve)

    pl = sub.add_parser("plan", help="print the model/serve/economics plan")
    pl.set_defaults(func=_cmd_plan)

    d = sub.add_parser("distill", help="offline GLM-5.1 -> MLX student distillation")
    d.add_argument("--dataset")
    d.add_argument("--model", help="MLX student (default: 16GB-safe 3B-4bit)")
    d.add_argument("--max-tasks", type=int)
    d.add_argument("--run", action="store_true", help="actually run MLX (default prints commands)")
    d.set_defaults(func=_cmd_distill)

    ms = sub.add_parser("mlx-serve", help="serve the distilled student locally (OpenAI-compatible)")
    ms.add_argument("--model")
    ms.add_argument("--adapter-path")
    ms.add_argument("--print-only", action="store_true")
    ms.set_defaults(func=_cmd_mlx_serve)

    rv = sub.add_parser("review", help="multi-subagent engineering review (6 RLM checks -> gate)")
    rv.add_argument("repo", nargs="?", default=".")
    rv.add_argument("--checks", help="comma list (default: all six)")
    rv.add_argument("--sub-lm", choices=["mlx", "stub"], help="RLM sub-LM backend (default: mlx)")
    rv.add_argument("--json", action="store_true", help="also print full JSON report")
    rv.set_defaults(func=_cmd_review)

    ev = sub.add_parser("eval", help="run the eval harness (local_first vs frontier_baseline)")
    ev.add_argument("--workdir", help="where to seed the benchmark repos (default: temp)")
    ev.add_argument("--backend", choices=["mlx", "stub"], help="local model backend (default: stub)")
    ev.add_argument("--json", action="store_true", help="also print full JSON metrics")
    ev.set_defaults(func=_cmd_eval)

    rc = sub.add_parser("repo-context", help="selective repo-context retrieval for a query")
    rc.add_argument("query")
    rc.add_argument("--repo", default=".")
    rc.add_argument("--top-k", type=int, default=5)
    rc.set_defaults(func=_cmd_repo_context)

    ix = sub.add_parser("index", help="build the full .autopilot/ bundle (SKILL.md + DAG + verify)")
    ix.add_argument("--repo", default=".")
    ix.add_argument("--max-commits", type=int, default=20)
    ix.set_defaults(func=_cmd_index)

    dg = sub.add_parser("dag", help="build commit-versioned code DAG -> .autopilot/ARCHITECTURE.md")
    dg.add_argument("--repo", default=".")
    dg.add_argument("--max-commits", type=int, default=20)
    dg.set_defaults(func=_cmd_dag)

    su = sub.add_parser("submit", help="hackathon submission: Butterbase + EverMind (code build0530)")
    su.add_argument("--repo", default=".")
    su.add_argument("--dry-run", action="store_true", help="force dry-run even if keys are set")
    su.set_defaults(func=_cmd_submit)

    wa = sub.add_parser("watch", help="real-time: re-index + refresh SKILL.md on every change ($0)")
    wa.add_argument("--repo", default=".")
    wa.add_argument("--interval", type=float, default=2.0)
    wa.add_argument("--max-iterations", type=int, default=None, help="stop after N polls (default: run until Ctrl-C)")
    wa.set_defaults(func=_cmd_watch)

    return p


def _load_dotenv() -> None:
    """Load ./.env into the environment (no external dep). Existing env wins."""
    p = Path(".env")
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
