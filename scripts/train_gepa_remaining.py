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
from app.core.skeleton import validate_remaining_gate
from app.dspy_modules import RemainingSuggestionsModule
from app.judges import RemainingJudge
from app.models import CharacterStateInput

load_dotenv()
SETTINGS = get_settings()
DATASET_PATH = SETTINGS.dataset_path("dataset_remaining.json")
ARTIFACTS_DIR = SETTINGS.artifacts_dir
SAVE_PATH = SETTINGS.resolved_artifact_remaining_path or (ARTIFACTS_DIR / "gepa_remaining.json")


def load_remaining_dataset(path: os.PathLike[str] | str) -> list[dspy.Example]:
    with Path(path).open(encoding="utf-8") as f:
        raw: list[dict[str, Any]] = json.load(f)
    examples: list[dspy.Example] = []
    for item in raw:
        inp = item.get("input", {})
        out = item.get("output", {})
        state = CharacterStateInput.model_validate(inp.get("state"))

        ex = dspy.Example(
            {
                # inputs
                "mode": inp.get("mode"),
                "state": state,
                "allow_overwrite": bool(inp.get("allow_overwrite", False)),
                "default_skills": list(inp.get("default_skills") or []),
                "target_skill_name": inp.get("target_skill_name"),
                "action_type": inp.get("action_type"),
                "aspect_slots_left": inp.get("aspect_slots_left"),
                "user_note": inp.get("user_note"),
                # gold outputs (one of aspects or stunts)
                "gold_aspect": out.get("aspects"),
                "gold_stunt": out.get("stunts"),
                "gold_notes": out.get("notes"),
            }
        ).with_inputs(
            "mode",
            "state",
            "allow_overwrite",
            "default_skills",
            "target_skill_name",
            "action_type",
            "aspect_slots_left",
            "user_note",
        )
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


remaining_judge = RemainingJudge()


def _extract_gold_pred(example: dspy.Example, pred: dspy.Prediction) -> tuple[dict[str, Any], dict[str, Any]]:
    gold_aspect = getattr(example, "gold_aspect", None) or None
    gold_stunt = getattr(example, "gold_stunt", None) or None

    pred_aspect = getattr(pred, "aspects", None)
    pred_stunt = getattr(pred, "stunts", None)

    return (
        {
            "aspect_name": (gold_aspect or {}).get("name") if isinstance(gold_aspect, dict) else None,
            "aspect_desc": (gold_aspect or {}).get("description") if isinstance(gold_aspect, dict) else None,
            "stunt_name": (gold_stunt or {}).get("name") if isinstance(gold_stunt, dict) else None,
            "stunt_desc": (gold_stunt or {}).get("description") if isinstance(gold_stunt, dict) else None,
        },
        {
            "aspect_name": getattr(pred_aspect, "name", None) if pred_aspect else None,
            "aspect_desc": getattr(pred_aspect, "description", None) if pred_aspect else None,
            "stunt_name": getattr(pred_stunt, "name", None) if pred_stunt else None,
            "stunt_desc": getattr(pred_stunt, "description", None) if pred_stunt else None,
        },
    )


def _safe_float(v: Any) -> float:
    try:
        f = float(v)
        return 0.0 if f < 0 else 1.0 if f > 1 else f
    except Exception:
        return 0.0


def compute_remaining_score_with_feedback(
    example: dspy.Example,
    prediction: dspy.Prediction,
    trace: Any | None = None,
    pred_name: str | None = None,
    pred_trace: Any | None = None,
) -> dspy.Prediction:
    mode: str = getattr(example, "mode", "") or ""
    state: CharacterStateInput | None = getattr(example, "state", None)
    target_skill_name: str | None = getattr(example, "target_skill_name", None)
    action_type: str | None = getattr(example, "action_type", None)

    gold, cand = _extract_gold_pred(example, prediction)

    ok, problems = validate_remaining_gate(
        mode=mode,
        pred_aspect_name=cand["aspect_name"],
        pred_aspect_description=cand["aspect_desc"],
        pred_stunt_name=cand["stunt_name"],
        pred_stunt_description=cand["stunt_desc"],
    )
    if not ok:
        return dspy.Prediction(score=0.0, feedback="Structure gate failed: " + "; ".join(problems[:5]))

    model_name = SETTINGS.dspy_model
    api_key = SETTINGS.dspy_api_key
    with dspy.context(lm=dspy.LM(model_name, api_key=api_key, temperature=0.5, max_tokens=20000)):
        judged = remaining_judge(
            state=state.model_dump() if state else {},
            mode=mode,
            target_skill_name=target_skill_name,
            action_type=action_type,
            gold_aspect_name=gold["aspect_name"],
            gold_aspect_description=gold["aspect_desc"],
            gold_stunt_name=gold["stunt_name"],
            gold_stunt_description=gold["stunt_desc"],
            pred_aspect_name=cand["aspect_name"],
            pred_aspect_description=cand["aspect_desc"],
            pred_stunt_name=cand["stunt_name"],
            pred_stunt_description=cand["stunt_desc"],
        )

    alignment = _safe_float(getattr(judged, "alignment", 0.0))
    mechanics = _safe_float(getattr(judged, "mechanics", 0.0))
    distinctness = _safe_float(getattr(judged, "distinctness", 0.0))
    clarity = _safe_float(getattr(judged, "clarity", 0.0))
    notes = (getattr(judged, "notes", "") or "").strip()

    # Weighting: mechanics is key for stunts; distinctness/clarity for aspects
    if mode in {"stunts", "single_stunt"}:
        score = 0.35 * alignment + 0.40 * mechanics + 0.15 * clarity + 0.10 * distinctness
    else:
        score = 0.40 * alignment + 0.10 * mechanics + 0.25 * clarity + 0.25 * distinctness

    fb = [
        f"alignment={alignment:.2f}",
        f"mechanics={mechanics:.2f}",
        f"clarity={clarity:.2f}",
        f"distinctness={distinctness:.2f}",
    ]
    if notes:
        fb.append(notes)
    return dspy.Prediction(score=float(score), feedback="; ".join(fb))


def main() -> None:
    load_dotenv()
    configure_dspy(SETTINGS)

    examples = load_remaining_dataset(DATASET_PATH)
    trainset, valset = split_train_val(examples, train_ratio=0.35, seed=42)
    print(f"Loaded {len(trainset)} train and {len(valset)} val examples")

    student = RemainingSuggestionsModule()
    gepa = dspy.GEPA(
        metric=compute_remaining_score_with_feedback,
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
