from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any

import dspy
from dotenv import load_dotenv

from app.config.runtime import configure_dspy
from app.config.settings import get_settings
from app.core.skeleton import validate_gm_hints_gate
from app.dspy_modules import GmHintsModule
from app.judges import GmHintsJudge
from app.models import CharacterStateInput

load_dotenv()
SETTINGS = get_settings()
DATASET_PATH = SETTINGS.dataset_path("dataset_gm_hints.json")
ARTIFACTS_DIR = SETTINGS.artifacts_dir
SAVE_PATH = SETTINGS.resolved_artifact_gm_hints_path or (ARTIFACTS_DIR / "gepa_gm_hints.json")


def load_gm_hints_dataset(path: os.PathLike[str] | str) -> list[dspy.Example]:
    with Path(path).open(encoding="utf-8") as f:
        raw: list[dict[str, Any]] = json.load(f)
    examples: list[dspy.Example] = []
    for item in raw:
        inp = item.get("input", {})
        out = item.get("output", {})
        state = CharacterStateInput.model_validate(inp.get("state"))
        ex = dspy.Example(
            {
                "state": state,
                "target_type": inp.get("target_type"),
                "target_id": inp.get("target_id"),
                # gold
                "gold_hints": out.get("hints") or [],
                "gold_notes": out.get("notes"),
            }
        ).with_inputs("state", "target_type", "target_id")
        examples.append(ex)
    return examples


def split_train_val(
    examples: list[dspy.Example], train_ratio: float = 0.35, seed: int = 42
) -> tuple[list[dspy.Example], list[dspy.Example]]:
    rng = random.Random(seed)
    shuffled = list(examples)
    rng.shuffle(shuffled)
    n_train = max(1, int(len(shuffled) * train_ratio))
    trainset = shuffled[:n_train]
    valset = shuffled[n_train:]
    return trainset, valset


judge = GmHintsJudge()


def _safe_float(v: Any) -> float:
    try:
        f = float(v)
        return 0.0 if f < 0 else 1.0 if f > 1 else f
    except Exception:
        return 0.0


def compute_gm_hints_score_with_feedback(
    example: dspy.Example,
    prediction: dspy.Prediction,
    trace: Any | None = None,
    pred_name: str | None = None,
    pred_trace: Any | None = None,
) -> dspy.Prediction:
    state: CharacterStateInput | None = getattr(example, "state", None)
    target_type: str = getattr(example, "target_type", "")
    target_id: str = getattr(example, "target_id", "")

    raw_hints = list(getattr(prediction, "hints", []) or [])
    # Normalize to list[dict[str,str]] from possible Pydantic objects
    pred_hints: list[dict[str, str]] = []
    for h in raw_hints:
        if isinstance(h, dict):
            pred_hints.append(
                {
                    "type": str(h.get("type", "")),
                    "title": str(h.get("title", "")),
                    "narrative": str(h.get("narrative", "")),
                    "mechanics": str(h.get("mechanics", "")),
                }
            )
        else:
            pred_hints.append(
                {
                    "type": str(getattr(h, "type", "")),
                    "title": str(getattr(h, "title", "")),
                    "narrative": str(getattr(h, "narrative", "")),
                    "mechanics": str(getattr(h, "mechanics", "")),
                }
            )
    gold_hints: list[dict[str, str]] = list(getattr(example, "gold_hints", []) or [])

    ok, problems = validate_gm_hints_gate(target_type=target_type, pred_hints=pred_hints)
    if not ok:
        return dspy.Prediction(score=0.0, feedback="Structure gate failed: " + "; ".join(problems[:5]))

    model_name = SETTINGS.dspy_model
    api_key = SETTINGS.dspy_api_key
    with dspy.context(lm=dspy.LM(model_name, api_key=api_key, temperature=0.5, max_tokens=20000)):
        judged = judge(
            state=state.model_dump() if state else {},
            target_type=target_type,
            target_id=target_id,
            gold_hints=gold_hints,
            pred_hints=pred_hints,
        )

    grounding = _safe_float(getattr(judged, "grounding", 0.0))
    mechanics = _safe_float(getattr(judged, "mechanics", 0.0))
    clarity = _safe_float(getattr(judged, "clarity", 0.0))
    variety = _safe_float(getattr(judged, "variety", 0.0))
    notes = (getattr(judged, "notes", "") or "").strip()

    # Balanced weighting emphasizing mechanics and grounding
    score = 0.35 * grounding + 0.40 * mechanics + 0.15 * clarity + 0.10 * variety
    parts = [
        f"grounding={grounding:.2f}",
        f"mechanics={mechanics:.2f}",
        f"clarity={clarity:.2f}",
        f"variety={variety:.2f}",
    ]
    if notes:
        parts.append(notes)
    return dspy.Prediction(score=float(score), feedback="; ".join(parts))


def main() -> None:
    load_dotenv()
    configure_dspy(SETTINGS)
    # ... rest of main function ...

    examples = load_gm_hints_dataset(DATASET_PATH)
    trainset, valset = split_train_val(examples, train_ratio=0.35, seed=42)
    print(f"Loaded {len(trainset)} train and {len(valset)} val examples")

    student = GmHintsModule()
    gepa = dspy.GEPA(
        metric=compute_gm_hints_score_with_feedback,
        auto="light",
        num_threads=4,
        track_stats=True,
        track_best_outputs=True,
        reflection_lm=dspy.LM(
            SETTINGS.dspy_reflection_model,
            temperature=SETTINGS.dspy_temperature,
            api_key=SETTINGS.dspy_api_key,
            max_tokens=SETTINGS.dspy_max_tokens,
        ),
    )

    optimized = gepa.compile(student=student, trainset=trainset, valset=valset)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    optimized.save(str(SAVE_PATH))
    print(f"Saved optimized program to: {SAVE_PATH}")


if __name__ == "__main__":
    main()
