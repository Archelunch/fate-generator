from __future__ import annotations

import dspy


class JudgeSkeletonQuality(dspy.Signature):
    """Judge the quality of a generated Fate character skeleton against a gold reference.

    Produce normalized float scores in [0,1]. Higher is better.

    Sub-criteria:
    - hc_alignment: How well the High Concept matches idea/setting and is game-usable.
    - hc_double_edged: Is the High Concept double-edged, evocative, concise, Fate-usable phrasing.
    - tr_alignment: How well the Trouble matches idea/setting and is game-usable.
    - tr_double_edged: Is the Trouble double-edged and creates friction/hooks without duplicating HC.
    - skills_rationale: Do the ranked skills make sense for the concept and setting.

    Return strictly numeric floats between 0 and 1 for all scores.
    Also return notes with actionable suggestions for improvement.
    """

    idea: str = dspy.InputField(desc="Original character idea/concept.")
    setting: str | None = dspy.InputField(desc="Optional setting/context.")
    skill_list: list[str] = dspy.InputField(desc="Allowed skills list.")

    gold_high_concept: str = dspy.InputField(desc="Reference high concept")
    gold_trouble: str = dspy.InputField(desc="Reference trouble")
    gold_ranked_skills: list[str] = dspy.InputField(desc="Reference ranked skills")

    new_high_concept: str = dspy.InputField(desc="Predicted high concept")
    new_trouble: str = dspy.InputField(desc="Predicted trouble")
    new_ranked_skills: list[str] = dspy.InputField(desc="Predicted ranked skills")

    hc_alignment: float = dspy.OutputField(desc="[0,1]")
    hc_double_edged: float = dspy.OutputField(desc="[0,1]")
    tr_alignment: float = dspy.OutputField(desc="[0,1]")
    tr_double_edged: float = dspy.OutputField(desc="[0,1]")
    skills_rationale: float = dspy.OutputField(desc="[0,1]")
    notes: str = dspy.OutputField(desc="Useful and actionable feedback.")


class SkeletonJudge(dspy.Module):
    """LLM-backed judge for character skeleton quality.

    Uses a Chain-of-Thought prompt to elicit rationale and numeric sub-scores.
    """

    def __init__(self) -> None:
        super().__init__()
        self._judge = dspy.Predict(JudgeSkeletonQuality)

    def forward(
        self,
        *,
        idea: str,
        setting: str | None,
        skill_list: list[str],
        gold_high_concept: str,
        gold_trouble: str,
        gold_ranked_skills: list[str],
        new_high_concept: str,
        new_trouble: str,
        new_ranked_skills: list[str],
    ) -> dspy.Prediction:
        return self._judge(
            idea=idea,
            setting=setting,
            skill_list=skill_list,
            gold_high_concept=gold_high_concept,
            gold_trouble=gold_trouble,
            gold_ranked_skills=gold_ranked_skills,
            new_high_concept=new_high_concept,
            new_trouble=new_trouble,
            new_ranked_skills=new_ranked_skills,
        )


class JudgeRemainingQuality(dspy.Signature):
    """Judge quality of remaining suggestions (aspects/stunts) vs gold.

    Provide normalized floats in [0,1]. Higher is better.
    Lower score when text is first person, uses "I" or "because"

    For aspects: prioritize alignment, double-edgedness, distinctness, clarity.
    For stunts: prioritize mechanics validity, alignment to concept/skill/action, clarity.
    - alignment: narrative grounded in the setting and target text
    - mechanics: mechanics line is Fate-correct and actionable
    - clarity: concise, readable; titles informative; no fluff;
    - distinctness: non-duplicative hints, complementary coverage
    """

    # Context
    state = dspy.InputField()
    mode: str = dspy.InputField(desc="'aspects'|'stunts'|'high_concept'|'trouble'")
    target_skill_name: str | None = dspy.InputField()
    action_type: str | None = dspy.InputField()

    # Gold
    gold_aspect_name: str | None = dspy.InputField(desc="Reference aspect name")
    gold_aspect_description: str | None = dspy.InputField(desc="Reference aspect description")
    gold_stunt_name: str | None = dspy.InputField(desc="Reference stunt name")
    gold_stunt_description: str | None = dspy.InputField(desc="Reference stunt description")

    # Candidate
    pred_aspect_name: str | None = dspy.InputField(desc="Predicted aspect name")
    pred_aspect_description: str | None = dspy.InputField(desc="Predicted aspect description")
    pred_stunt_name: str | None = dspy.InputField(desc="Predicted stunt name")
    pred_stunt_description: str | None = dspy.InputField(desc="Predicted stunt description")

    # Outputs
    alignment: float = dspy.OutputField(desc="[0,1]")
    mechanics: float = dspy.OutputField(desc="[0,1]")
    distinctness: float = dspy.OutputField(desc="[0,1]")
    clarity: float = dspy.OutputField(desc="[0,1]")
    notes: str = dspy.OutputField(desc="Useful and actionable feedback.")


class RemainingJudge(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self._judge = dspy.Predict(JudgeRemainingQuality)

    def forward(
        self,
        *,
        state: object,
        mode: str,
        target_skill_name: str | None,
        action_type: str | None,
        gold_aspect_name: str | None,
        gold_aspect_description: str | None,
        gold_stunt_name: str | None,
        gold_stunt_description: str | None,
        pred_aspect_name: str | None,
        pred_aspect_description: str | None,
        pred_stunt_name: str | None,
        pred_stunt_description: str | None,
    ) -> dspy.Prediction:
        return self._judge(
            state=state,
            mode=mode,
            target_skill_name=target_skill_name,
            action_type=action_type,
            gold_aspect_name=gold_aspect_name,
            gold_aspect_description=gold_aspect_description,
            gold_stunt_name=gold_stunt_name,
            gold_stunt_description=gold_stunt_description,
            pred_aspect_name=pred_aspect_name,
            pred_aspect_description=pred_aspect_description,
            pred_stunt_name=pred_stunt_name,
            pred_stunt_description=pred_stunt_description,
        )


class JudgeGmHintsQuality(dspy.Signature):
    """Judge GM hints quality for a specific target (aspect or stunt).

    Return normalized floats in [0,1].

    - grounding: narrative grounded in the setting and target text
    - mechanics: mechanics line is Fate-correct and actionable
    - clarity: concise, readable; titles informative; no fluff
    - variety: non-duplicative hints, complementary coverage
    """

    state = dspy.InputField()
    target_type: str = dspy.InputField()
    target_id: str = dspy.InputField()

    gold_hints = dspy.InputField(desc="List of reference hints for comparison")
    pred_hints = dspy.InputField(desc="List of predicted hints to judge")

    grounding: float = dspy.OutputField(desc="[0,1]")
    mechanics: float = dspy.OutputField(desc="[0,1]")
    clarity: float = dspy.OutputField(desc="[0,1]")
    variety: float = dspy.OutputField(desc="[0,1]")
    notes: str = dspy.OutputField(desc="Useful and actionable feedback.")


class GmHintsJudge(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self._judge = dspy.Predict(JudgeGmHintsQuality)

    def forward(
        self,
        *,
        state: object,
        target_type: str,
        target_id: str,
        gold_hints: list[dict[str, str]] | None,
        pred_hints: list[dict[str, str]] | None,
    ) -> dspy.Prediction:
        return self._judge(
            state=state,
            target_type=target_type,
            target_id=target_id,
            gold_hints=gold_hints or [],
            pred_hints=pred_hints or [],
        )
