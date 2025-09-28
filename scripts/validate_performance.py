"""Validate baseline vs optimized DSPy modules with rich tables.

Examples:
  - Validate both tasks with defaults:
      poetry run python scripts/validate_performance.py --task both --threads 4

  - Validate only skeleton with 50 examples:
      poetry run python scripts/validate_performance.py --task skeleton --limit 50

  - Custom checkpoint paths:
      poetry run python scripts/validate_performance.py \
        --skeleton-checkpoint artifacts/gepa_character_skeleton.json \
        --remaining-checkpoint artifacts/gepa_remaining.json

Requirements:
  - GEMINI_API_KEY environment variable for the Gemini models used by the metric/judges.

Notes:
  - This script follows the DSPy evaluation pattern using a per-example loop,
    equivalent to using dspy.Evaluate, but aggregates custom stats and prints
    a comparison table.
"""

from __future__ import annotations

import argparse
import os
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import dspy
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import track
from rich.rule import Rule
from rich.table import Table

from app.config.runtime import configure_dspy
from app.config.settings import get_settings
from app.dspy_modules import CharacterSkeletonModule, GmHintsModule, RemainingSuggestionsModule
from scripts.train_gepa_gm_hints import (
    compute_gm_hints_score_with_feedback,
    load_gm_hints_dataset,
)
from scripts.train_gepa_gm_hints import (
    split_train_val as split_train_val_gm,
)
from scripts.train_gepa_remaining import (
    compute_remaining_score_with_feedback,
    load_remaining_dataset,
)
from scripts.train_gepa_remaining import (
    split_train_val as split_train_val_remaining,
)

# Reuse loaders and metrics from the train scripts to ensure parity
from scripts.train_gepa_skeleton import (
    compute_skeleton_score_with_feedback,
    load_skeleton_dataset,
)
from scripts.train_gepa_skeleton import (
    split_train_val as split_train_val_skeleton,
)

SETTINGS = get_settings()
ARTIFACT_SKELETON = SETTINGS.resolved_artifact_skeleton_path or (SETTINGS.artifacts_dir / "gepa_character_skeleton.json")
ARTIFACT_REMAINING = SETTINGS.resolved_artifact_remaining_path or (SETTINGS.artifacts_dir / "gepa_remaining.json")
ARTIFACT_GM_HINTS = SETTINGS.resolved_artifact_gm_hints_path or (SETTINGS.artifacts_dir / "gepa_gm_hints.json")

DATASET_SKELETON = SETTINGS.dataset_path("dataset_skeleton.json")
DATASET_REMAINING = SETTINGS.dataset_path("dataset_remaining.json")
DATASET_GM_HINTS = SETTINGS.dataset_path("dataset_gm_hints.json")


@dataclass
class EvalResult:
    scores: list[float]
    feedbacks: list[str]
    predictions: list[dspy.Prediction]

    @property
    def mean(self) -> float:
        return float(statistics.fmean(self.scores)) if self.scores else 0.0

    @property
    def count(self) -> int:
        return len(self.scores)


def evaluate_program(
    program: dspy.Module,
    devset: Sequence[dspy.Example],
    metric: Callable[..., dspy.Prediction],
    num_threads: int,
) -> EvalResult:
    # We want raw scores; do a manual loop for per-example stats

    scores: list[float] = []
    feedbacks: list[str] = []
    predictions: list[dspy.Prediction] = []

    # Evaluate returns the mean score, but we want per-example; we'll manually loop
    for example in track(devset, description="Evaluating", transient=True):
        pred = program(**example.inputs())
        scored = metric(example, pred)
        score_val = float(getattr(scored, "score", 0.0))
        fb = (getattr(scored, "feedback", "") or "").strip()
        scores.append(score_val)
        feedbacks.append(fb)
        predictions.append(pred)

    return EvalResult(scores=scores, feedbacks=feedbacks, predictions=predictions)


def _compute_comparison_stats(baseline: EvalResult, optimized: EvalResult) -> dict[str, float]:
    n = min(len(baseline.scores), len(optimized.scores))
    if n == 0:
        return {
            "mean_base": 0.0,
            "mean_opt": 0.0,
            "delta_mean": 0.0,
            "win_rate": 0.0,
            "tie_rate": 0.0,
            "avg_abs_delta": 0.0,
            "count": 0.0,
        }
    wins = 0
    ties = 0
    abs_deltas: list[float] = []
    for i in range(n):
        b = baseline.scores[i]
        o = optimized.scores[i]
        if o > b:
            wins += 1
        elif o == b:
            ties += 1
        abs_deltas.append(abs(o - b))
    mean_base = baseline.mean
    mean_opt = optimized.mean
    delta_mean = mean_opt - mean_base
    win_rate = wins / n
    tie_rate = ties / n
    avg_abs_delta = float(statistics.fmean(abs_deltas)) if abs_deltas else 0.0
    return {
        "mean_base": float(mean_base),
        "mean_opt": float(mean_opt),
        "delta_mean": float(delta_mean),
        "win_rate": float(win_rate),
        "tie_rate": float(tie_rate),
        "avg_abs_delta": float(avg_abs_delta),
        "count": n,
    }


def print_comparison_table(
    console: Console,
    title: str,
    baseline: EvalResult,
    optimized: EvalResult,
) -> None:
    table = Table(show_header=True, header_style="bold magenta")
    count = min(len(baseline.scores), len(optimized.scores))
    table.title = f"{title} - {count} examples"
    table.add_column("Metric", justify="left", style="bold")
    table.add_column("Baseline", justify="right")
    table.add_column("Optimized", justify="right")
    table.add_column("Delta", justify="right")

    def fmt(x: float) -> str:
        return f"{x:.4f}"

    stats = _compute_comparison_stats(baseline, optimized)
    delta_mean = stats["delta_mean"]
    table.add_row(
        "Mean score",
        fmt(stats["mean_base"]),
        fmt(stats["mean_opt"]),
        ("+" if delta_mean >= 0 else "") + fmt(delta_mean),
    )

    console.print(table)


def _build_labels_skeleton(devset: Sequence[dspy.Example]) -> list[str]:
    labels: list[str] = []
    for x in devset:
        idea = (getattr(x, "idea", "") or "").strip()
        labels.append((idea[:40] + ("…" if len(idea) > 40 else "")) or "example")
    return labels


def _build_labels_remaining(devset: Sequence[dspy.Example]) -> list[str]:
    labels: list[str] = []
    for x in devset:
        mode = (getattr(x, "mode", "") or "").strip()
        skill = (getattr(x, "target_skill_name", "") or "").strip()
        action = (getattr(x, "action_type", "") or "").strip()
        label = ":".join(filter(None, [mode, skill or None, action or None]))
        labels.append(label or "example")
    return labels


def _build_labels_gm(devset: Sequence[dspy.Example]) -> list[str]:
    labels: list[str] = []
    for x in devset:
        ttype = (getattr(x, "target_type", "") or "").strip()
        tid = (getattr(x, "target_id", "") or "").strip()
        labels.append(":".join(filter(None, [ttype, tid])) or "example")
    return labels


def print_examples_table(
    console: Console,
    task: str,
    devset: Sequence[dspy.Example],
    labels: list[str],
    base_scores: list[float],
    opt_scores: list[float],
    base_preds: list[dspy.Prediction],
    opt_preds: list[dspy.Prediction],
    top_n: int = 5,
) -> None:
    n = min(len(labels), len(base_scores), len(opt_scores))
    if n == 0:
        return
    deltas = [(i, opt_scores[i] - base_scores[i]) for i in range(n)]
    # Top improvements
    top_improve = sorted(deltas, key=lambda t: t[1], reverse=True)[: max(0, top_n)]

    # Overview table
    overview = Table(show_header=True, header_style="bold cyan")
    overview.title = f"Top {len(top_improve)} improvements"
    overview.add_column("#", justify="right")
    overview.add_column("Example", justify="left")
    overview.add_column("Baseline", justify="right")
    overview.add_column("Optimized", justify="right")
    overview.add_column("Delta", justify="right")
    for idx, _delta in top_improve:
        b = base_scores[idx]
        o = opt_scores[idx]
        delta = o - b
        sign = "+" if delta >= 0 else ""
        overview.add_row(str(idx), labels[idx], f"{b:.4f}", f"{o:.4f}", f"{sign}{delta:.4f}")
    console.print(overview)

    # Detailed panels per example with inputs and outputs
    for idx, _delta in top_improve:
        inp_table = Table(show_header=False)
        inp_table.add_column("Field", style="bold")
        inp_table.add_column("Value")

        if task == "skeleton":
            idea = (getattr(devset[idx], "idea", "") or "").strip()
            setting = (getattr(devset[idx], "setting", "") or "").strip()
            skills = list(getattr(devset[idx], "skill_list", []) or [])
            inp_table.add_row("idea", idea)
            if setting:
                inp_table.add_row("setting", setting)
            if skills:
                inp_table.add_row("skill_list", ", ".join(skills))
        elif task == "remaining":
            mode = (getattr(devset[idx], "mode", "") or "").strip()
            tskill = (getattr(devset[idx], "target_skill_name", "") or "").strip()
            atype = (getattr(devset[idx], "action_type", "") or "").strip()
            state = getattr(devset[idx], "state", None)
            idea = getattr(getattr(state, "meta", None), "idea", "") if state else ""
            setting = getattr(getattr(state, "meta", None), "setting", "") if state else ""
            inp_table.add_row("mode", mode)
            if tskill:
                inp_table.add_row("target_skill_name", tskill)
            if atype:
                inp_table.add_row("action_type", atype)
            if idea:
                inp_table.add_row("state.meta.idea", idea)
            if setting:
                inp_table.add_row("state.meta.setting", setting)
        else:  # gm_hints
            state = getattr(devset[idx], "state", None)
            ttype = (getattr(devset[idx], "target_type", "") or "").strip()
            tid = (getattr(devset[idx], "target_id", "") or "").strip()
            idea = getattr(getattr(state, "meta", None), "idea", "") if state else ""
            setting = getattr(getattr(state, "meta", None), "setting", "") if state else ""
            inp_table.add_row("target_type", ttype)
            inp_table.add_row("target_id", tid)
            if idea:
                inp_table.add_row("state.meta.idea", idea)
            if setting:
                inp_table.add_row("state.meta.setting", setting)

        out_table = Table(show_header=True, header_style="bold yellow")
        out_table.add_column("Field")
        out_table.add_column("Baseline")
        out_table.add_column("Optimized")

        bp = base_preds[idx]
        op = opt_preds[idx]
        if task == "skeleton":
            b_hc = getattr(bp, "high_concept", None) or ""
            o_hc = getattr(op, "high_concept", None) or ""
            b_tr = getattr(bp, "trouble", None) or ""
            o_tr = getattr(op, "trouble", None) or ""
            b_sk = ", ".join(list(getattr(bp, "ranked_skills", []) or [])[:5])
            o_sk = ", ".join(list(getattr(op, "ranked_skills", []) or [])[:5])
            out_table.add_row("High Concept", b_hc, o_hc)
            out_table.add_row("Trouble", b_tr, o_tr)
            out_table.add_row("Top skills", b_sk, o_sk)
        elif task == "remaining":
            b_as = getattr(bp, "aspects", None)
            o_as = getattr(op, "aspects", None)
            b_st = getattr(bp, "stunts", None)
            o_st = getattr(op, "stunts", None)
            if b_as or o_as:
                b_an = getattr(b_as, "name", None) or ""
                o_an = getattr(o_as, "name", None) or ""
                b_ad = getattr(b_as, "description", None) or ""
                o_ad = getattr(o_as, "description", None) or ""
                out_table.add_row("Aspect name", b_an, o_an)
                out_table.add_row("Aspect desc", b_ad, o_ad)
            if b_st or o_st:
                b_sn = getattr(b_st, "name", None) or ""
                o_sn = getattr(o_st, "name", None) or ""
                b_sd = getattr(b_st, "description", None) or ""
                o_sd = getattr(o_st, "description", None) or ""
                out_table.add_row("Stunt name", b_sn, o_sn)
                out_table.add_row("Stunt desc", b_sd, o_sd)
        else:  # gm_hints

            def hints_to_rows(pred: dspy.Prediction) -> list[str]:
                rows: list[str] = []
                hints = list(getattr(pred, "hints", []) or [])
                for h in hints[:3]:
                    if isinstance(h, dict):
                        t = h.get("type") or ""
                        title = h.get("title") or ""
                        mech = h.get("mechanics") or ""
                    else:
                        t = getattr(h, "type", "") or ""
                        title = getattr(h, "title", "") or ""
                        mech = getattr(h, "mechanics", "") or ""
                    rows.append(f"[{t}] {title} — {mech}")
                return rows or [""]

            b_rows = hints_to_rows(bp)
            o_rows = hints_to_rows(op)
            # Align lengths to show side by side
            max_r = max(len(b_rows), len(o_rows))
            while len(b_rows) < max_r:
                b_rows.append("")
            while len(o_rows) < max_r:
                o_rows.append("")
            for i in range(max_r):
                out_table.add_row(f"Hint {i + 1}", b_rows[i], o_rows[i])

        delta = opt_scores[idx] - base_scores[idx]
        sign = "+" if delta >= 0 else ""
        console.print(Panel.fit(inp_table, title=f"Example {idx}: {labels[idx]}", border_style="cyan"))
        console.print(Panel.fit(out_table, title=f"Outputs (Δ {sign}{delta:.4f})", border_style="green"))


def print_distribution_table(console: Console, title: str, base_scores: list[float], opt_scores: list[float]) -> None:
    bins = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0 + 1e-9)]

    def count_in(scores: list[float], lo: float, hi: float) -> int:
        return sum(1 for s in scores if (s >= lo and s < hi))

    table = Table(show_header=True, header_style="bold green")
    table.title = f"{title} • Score distribution"
    table.add_column("Bin", justify="left")
    table.add_column("Baseline (n)", justify="right")
    table.add_column("Optimized (n)", justify="right")
    table.add_column("Delta", justify="right")

    for lo, hi in bins:
        b = count_in(base_scores, lo, hi)
        o = count_in(opt_scores, lo, hi)
        delta = o - b
        label = f"[{lo:.1f}, {min(hi, 1.0):.1f})"
        table.add_row(label, str(b), str(o), ("+" if delta >= 0 else "") + str(delta))

    console.print(table)


def load_optimized(program: dspy.Module, checkpoint_path: str) -> dspy.Module:
    # Each optimized module class should implement .load(path)
    program.load(checkpoint_path)
    return program


def _resolve_dataset(path: str | os.PathLike[str]) -> Path:
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"Dataset not found: {resolved}")
    return resolved


def _resolve_artifact(path: str | os.PathLike[str]) -> Path:
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Checkpoint not found: {resolved}")
    return resolved


def run_skeleton(
    console: Console,
    dataset_path: str | os.PathLike[str],
    checkpoint_path: str | os.PathLike[str],
    limit: int | None,
    num_threads: int,
) -> None:
    dataset_path = _resolve_dataset(dataset_path)
    checkpoint_path = _resolve_artifact(checkpoint_path)
    examples = load_skeleton_dataset(dataset_path)
    _, valset = split_train_val_skeleton(examples, train_ratio=0.35, seed=42)
    if limit is not None:
        valset = valset[: max(1, limit)]

    # Configure LM once; training script uses gemini flash-lite
    configure_dspy(SETTINGS)

    baseline = CharacterSkeletonModule()
    optimized = CharacterSkeletonModule()
    load_optimized(optimized, str(checkpoint_path))

    console.print(Rule("Initial Character Sheet"))

    base_res = evaluate_program(baseline, valset, compute_skeleton_score_with_feedback, num_threads)
    opt_res = evaluate_program(optimized, valset, compute_skeleton_score_with_feedback, num_threads)

    print_comparison_table(console, "Character Sheet Scores", base_res, opt_res)
    labels = _build_labels_skeleton(valset)
    print_examples_table(
        console,
        "skeleton",
        valset,
        labels,
        base_res.scores,
        opt_res.scores,
        base_res.predictions,
        opt_res.predictions,
        top_n=5,
    )


def run_remaining(
    console: Console,
    dataset_path: str | os.PathLike[str],
    checkpoint_path: str | os.PathLike[str],
    limit: int | None,
    num_threads: int,
) -> None:
    dataset_path = _resolve_dataset(dataset_path)
    checkpoint_path = _resolve_artifact(checkpoint_path)
    examples = load_remaining_dataset(dataset_path)
    _, valset = split_train_val_remaining(examples, train_ratio=0.35, seed=42)
    if limit is not None:
        valset = valset[: max(1, limit)]

    configure_dspy(SETTINGS)

    baseline = RemainingSuggestionsModule()
    optimized = RemainingSuggestionsModule()
    load_optimized(optimized, str(checkpoint_path))

    console.print(Rule("Remaining Suggestions"))

    base_res = evaluate_program(baseline, valset, compute_remaining_score_with_feedback, num_threads)
    opt_res = evaluate_program(optimized, valset, compute_remaining_score_with_feedback, num_threads)

    print_comparison_table(console, "Aspects/Stunts Scores", base_res, opt_res)
    labels = _build_labels_remaining(valset)
    print_examples_table(
        console,
        "remaining",
        valset,
        labels,
        base_res.scores,
        opt_res.scores,
        base_res.predictions,
        opt_res.predictions,
        top_n=5,
    )


def run_gm_hints(
    console: Console,
    dataset_path: str | os.PathLike[str],
    checkpoint_path: str | os.PathLike[str],
    limit: int | None,
    num_threads: int,
) -> None:
    dataset_path = _resolve_dataset(dataset_path)
    checkpoint_path = _resolve_artifact(checkpoint_path)
    examples = load_gm_hints_dataset(dataset_path)
    _, valset = split_train_val_gm(examples, train_ratio=0.35, seed=42)
    if limit is not None:
        valset = valset[: max(1, limit)]

    configure_dspy(SETTINGS)

    baseline = GmHintsModule()
    optimized = GmHintsModule()
    load_optimized(optimized, str(checkpoint_path))

    console.print(Rule("GM Hints"))

    base_res = evaluate_program(baseline, valset, compute_gm_hints_score_with_feedback, num_threads)
    opt_res = evaluate_program(optimized, valset, compute_gm_hints_score_with_feedback, num_threads)

    print_comparison_table(console, "GM Hints Scores", base_res, opt_res)
    labels = _build_labels_gm(valset)
    print_examples_table(
        console,
        "gm_hints",
        valset,
        labels,
        base_res.scores,
        opt_res.scores,
        base_res.predictions,
        opt_res.predictions,
        top_n=5,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate baseline vs optimized DSPy modules (skeleton and remaining) on the validation split.\n"
            "Requires GEMINI_API_KEY env var."
        )
    )
    parser.add_argument(
        "--task",
        choices=["skeleton", "remaining", "gm_hints", "both", "all"],
        default="both",
        help="Which task to validate",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="Number of evaluation threads",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of validation examples (for a quick run)",
    )
    parser.add_argument(
        "--skeleton-checkpoint",
        type=str,
        default=ARTIFACT_SKELETON,
        help="Path to optimized skeleton checkpoint (.json)",
    )
    parser.add_argument(
        "--remaining-checkpoint",
        type=str,
        default=ARTIFACT_REMAINING,
        help="Path to optimized remaining checkpoint (.json)",
    )
    parser.add_argument(
        "--gm-hints-checkpoint",
        type=str,
        default=ARTIFACT_GM_HINTS,
        help="Path to optimized GM Hints checkpoint (.json)",
    )
    parser.add_argument(
        "--skeleton-dataset",
        type=str,
        default=DATASET_SKELETON,
        help="Path to skeleton dataset JSON",
    )
    parser.add_argument(
        "--remaining-dataset",
        type=str,
        default=DATASET_REMAINING,
        help="Path to remaining dataset JSON",
    )
    parser.add_argument(
        "--gm-hints-dataset",
        type=str,
        default=DATASET_GM_HINTS,
        help="Path to GM Hints dataset JSON",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()
    configure_dspy(SETTINGS)
    console = Console()

    # Header Panel
    console.print(
        Panel.fit(
            "Baseline vs Optimized Validation\n[DSPy GEPA checkpoints]",
            title="Fate Generator",
            border_style="cyan",
        )
    )

    if args.task in ("skeleton", "both", "all"):
        run_skeleton(
            console,
            dataset_path=args.skeleton_dataset,
            checkpoint_path=args.skeleton_checkpoint,
            limit=args.limit,
            num_threads=args.threads,
        )

    if args.task in ("remaining", "both", "all"):
        run_remaining(
            console,
            dataset_path=args.remaining_dataset,
            checkpoint_path=args.remaining_checkpoint,
            limit=args.limit,
            num_threads=args.threads,
        )

    if args.task in ("gm_hints", "all"):
        run_gm_hints(
            console,
            dataset_path=args.gm_hints_dataset,
            checkpoint_path=args.gm_hints_checkpoint,
            limit=args.limit,
            num_threads=args.threads,
        )


if __name__ == "__main__":
    main()
