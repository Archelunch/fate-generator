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
from app.core.skeleton import (
    spearman_footrule_similarity,
    validate_structure_gate,
)
from app.dspy_modules import CharacterSkeletonModule
from app.judges import SkeletonJudge

load_dotenv()
SETTINGS = get_settings()
DATASET_PATH = SETTINGS.dataset_path("dataset_skeleton.json")
ARTIFACTS_DIR = SETTINGS.artifacts_dir
SAVE_PATH = SETTINGS.resolved_artifact_skeleton_path or (ARTIFACTS_DIR / "gepa_character_skeleton.json")


# --- dataset utils ---
def load_skeleton_dataset(path: os.PathLike[str] | str) -> list[dspy.Example]:
    with Path(path).open(encoding="utf-8") as f:
        raw: list[dict[str, Any]] = json.load(f)
    examples: list[dspy.Example] = []
    for item in raw:
        inp = item.get("input", {})
        out = item.get("output", {})
        ex = dspy.Example(
            {
                "idea": inp.get("idea"),
                "setting": inp.get("setting"),
                "skill_list": inp.get("skill_list") or [],
                # gold outputs
                "high_concept": out.get("high_concept"),
                "trouble": out.get("trouble"),
                "ranked_skills": out.get("ranked_skills") or [],
            }
        ).with_inputs("idea", "setting", "skill_list")
        examples.append(ex)
    return examples


def split_train_val(
    examples: list[dspy.Example], train_ratio: float = 0.3, seed: int = 42
) -> tuple[list[dspy.Example], list[dspy.Example]]:
    rng = random.Random(seed)
    shuffled = list(examples)
    rng.shuffle(shuffled)
    n_train = max(1, int(len(shuffled) * train_ratio))
    trainset = shuffled[:n_train]
    valset = shuffled[n_train:]
    return trainset, valset


# --- judge and metric ---
skeleton_judge = SkeletonJudge()


def _safe_float(value: Any) -> float:
    try:
        f = float(value)
        if f < 0:
            return 0.0
        if f > 1:
            return 1.0
        return f
    except Exception:
        return 0.0


def compute_skeleton_score_with_feedback(
    example: dspy.Example,
    prediction: dspy.Prediction,
    trace: Any | None = None,
    pred_name: str | None = None,
    pred_trace: Any | None = None,
) -> dspy.Prediction:
    idea: str = getattr(example, "idea", "") or ""
    setting: str | None = getattr(example, "setting", None)
    skill_list: list[str] = list(getattr(example, "skill_list", []) or [])

    gold_hc: str = getattr(example, "high_concept", "") or ""
    gold_tr: str = getattr(example, "trouble", "") or ""
    gold_ranked: list[str] = list(getattr(example, "ranked_skills", []) or [])

    pred_hc: str | None = getattr(prediction, "high_concept", None)
    pred_tr: str | None = getattr(prediction, "trouble", None)
    pred_ranked: list[str] | None = getattr(prediction, "ranked_skills", None)

    ok, problems = validate_structure_gate(
        idea=idea,
        setting=setting,
        skill_list=skill_list,
        high_concept=pred_hc,
        trouble=pred_tr,
        ranked_skills=pred_ranked,
    )
    if not ok:
        feedback = "Structure gate failed: " + "; ".join(problems[:5])
        return dspy.Prediction(score=0.0, feedback=feedback)

    # Similarity and validity components
    sim = spearman_footrule_similarity(gold_ranked, pred_ranked or [])
    validity_reward = 1.0  # gate passed => validity guaranteed

    # LLM judge sub-scores
    model_name = SETTINGS.dspy_model
    api_key = SETTINGS.dspy_api_key
    with dspy.context(lm=dspy.LM(model_name, api_key=api_key, temperature=0.5)):
        judged = skeleton_judge(
            idea=idea,
            setting=setting or "",
            skill_list=skill_list,
            gold_high_concept=gold_hc,
            gold_trouble=gold_tr,
            gold_ranked_skills=gold_ranked,
            new_high_concept=pred_hc or "",
            new_trouble=pred_tr or "",
            new_ranked_skills=list(pred_ranked or []),
        )

    hc_alignment = _safe_float(getattr(judged, "hc_alignment", 0.0))
    hc_double = _safe_float(getattr(judged, "hc_double_edged", 0.0))
    tr_alignment = _safe_float(getattr(judged, "tr_alignment", 0.0))
    tr_double = _safe_float(getattr(judged, "tr_double_edged", 0.0))
    skills_rationale = _safe_float(getattr(judged, "skills_rationale", 0.0))
    judge_notes = (getattr(judged, "notes", "") or "").strip()

    hc_score = 0.5 * hc_alignment + 0.5 * hc_double
    tr_score = 0.5 * tr_alignment + 0.5 * tr_double
    skills_score = 0.25 * float(sim) + 0.10 * float(validity_reward) + 0.65 * float(skills_rationale)
    structure_score = 1.0  # gate passed

    overall = 0.30 * hc_score + 0.30 * tr_score + 0.35 * skills_score + 0.05 * structure_score

    fb_parts: list[str] = []
    fb_parts.append(
        f"HC={hc_score:.2f} (align {hc_alignment:.2f}, double {hc_double:.2f}); "
        f"TR={tr_score:.2f} (align {tr_alignment:.2f}, double {tr_double:.2f}); "
        f"Skills={skills_score:.2f} (sim {sim:.2f}, rationale {skills_rationale:.2f}); "
        f"Structure={structure_score:.2f}."
    )
    if sim < 0.6:
        fb_parts.append("Improve ranking coherence with the concept; prioritize top-3 skills more clearly.")
    if hc_alignment < 0.7 or tr_alignment < 0.7:
        fb_parts.append("Tighten alignment with idea/setting; ensure Fate-usable phrasing.")
    if judge_notes:
        fb_parts.append(judge_notes)

    feedback = " \n".join(fb_parts)
    return dspy.Prediction(score=float(overall), feedback=feedback)


def main() -> None:
    # Global LM: student and judge use flash-lite; reflection uses pro
    load_dotenv()
    configure_dspy(SETTINGS)

    # Load and split dataset
    examples = load_skeleton_dataset(DATASET_PATH)
    trainset, valset = split_train_val(examples, train_ratio=0.35, seed=42)
    print(f"Loaded {len(trainset)} train examples and {len(valset)} validation examples")
    # Build student and GEPA
    student = CharacterSkeletonModule()
    gepa = dspy.GEPA(
        metric=compute_skeleton_score_with_feedback,
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
