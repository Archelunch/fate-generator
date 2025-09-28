import dspy
from pydantic import BaseModel

from app.models import AspectSuggestion, CharacterStateInput, StuntSuggestion


class GenerateCharacterSkeleton(dspy.Signature):  # type: ignore[misc]
    """Generate a Fate Core TTRPG character skeleton from an idea and setting. Make sense for the character concept.
    The best aspects are double-edged, say more than one thing, and keep the phrasing simple.
    character aspect might describe: personality traits, backgrounds, relationships, problems, possessions, items and so forth. The best aspects overlap across a few of those categories, because that means you have more ways to bring them into play.
    """

    idea: str = dspy.InputField()
    setting: str | None = dspy.InputField(desc="Campaign setting or context")
    skill_list: list[str] = dspy.InputField(desc="Allowed skills. Choose ONLY from this list.")

    high_concept: str = dspy.OutputField(desc="Compelling High Concept aspect, one sentence")
    trouble: str = dspy.OutputField(
        desc="Trouble aspect: Problems, goals, or issues the character is dealing with, one sentence"
    )
    ranked_skills: list[str] = dspy.OutputField(
        desc=("Return ONLY a list of skills sorted by suitability to the character concept")
    )


class GenerateRemainingSuggestions(dspy.Signature):  # type: ignore[misc]
    """Suggest additions/updates for a Fate character sheet given state and constraints.
    Be creative, make distinct suggestions and avoid repetitions. Make sense for the character concept.
    The best aspects are double-edged, say more than one thing, and keep the phrasing simple.
    character aspect might describe: personality traits, backgrounds, relationships, problems, possessions, items and so forth. The best aspects overlap across a few of those categories, because that means you have more ways to bring them into play.

    Possible stunts (not limited to these):
    Upgrade a boost to an aspect (with free invoke) replacing a boost, optionally, when you succeed with style for a specific action (Attack, Create an Advantage)
    Add a +2 opposition to a specific thing (ex. block moving; writing in code) when doing a specific action (ex. Overcome, Create an Advantage, Attack, Defend)
    Switch one specific skill with another specific skill when attempting something that's your speciality (ex. expert on Languages)
    Create an Advantage (no free invoke) that takes a Fair +2 roll to remove once per scene
    Ignore a simple rule (ex. can't use a skill twice in a challenge) once per scene
    Add a +3 opposition to a specific thing (ex. block moving; writing in code) when attempting something that's your speciality (ex. expert on Languages), once per scene
    Grant +2 to a specific action using a specific skill in a specific circumstance (ex. when you're On Fire; when you're Surrounded)

    Rules:
    - Respect constraints: items with locked=True are immutable. If allow_overwrite is False, userEdited=True items are also immutable.
    - Only populate outputs relevant to the requested `mode`.
      * mode=aspects: generate new aspects beyond High Concept and Trouble.
      * mode=high_concept: propose a replacement sentence for the High Concept aspect only.
      * mode=trouble: propose a replacement sentence for the Trouble aspect only.
        If `action_type` is provided (overcome, create_advantage, attack, defend), orient the mechanics accordingly.
    - Omit non-relevant outputs by returning null for those fields.
    """

    state: CharacterStateInput = dspy.InputField(desc="Current character state with optional locked/userEdited flags.")
    constraints: list[str] = dspy.InputField(desc="Immutable constraints derived from locked/userEdited flags.")
    allow_overwrite: bool = dspy.InputField(desc="If false, userEdited fields must be treated as immutable.")
    default_skills: list[str] = dspy.InputField(desc="Use skills only from this list.")
    feedback: str | None = dspy.InputField(desc="Optional short feedback from previous validation errors.")
    # Targeting/options
    mode: str = dspy.InputField(desc="aspect or stunt")
    target_skill_name: str | None = dspy.InputField(desc="Specific skill for stunt generation, or empty for auto.")
    action_type: str | None = dspy.InputField(
        desc="Stunt action type: overcome, create_advantage, attack, defend, or empty."
    )
    user_note: str | None = dspy.InputField(desc="Optional user note to guide style/mechanics for generation.")
    avoid_stunts: list[str] = dspy.InputField(desc="Existing stunt descriptions to avoid duplicating or paraphrasing.")

    aspects: AspectSuggestion | None = dspy.OutputField(desc="New aspect suggestions.")
    stunts: StuntSuggestion | None = dspy.OutputField(desc="New stunt suggestions.")
    notes: str = dspy.OutputField(desc="Brief rationale or high-level choices.")


class GMHintItem(BaseModel):
    type: str
    title: str
    narrative: str
    mechanics: str


class GenerateGmHints(dspy.Signature):  # type: ignore[misc]
    """Generate practical Fate Core usage hints for a specific Aspect or Stunt.

    Input:
    - Full character state (idea, setting, aspects, skills, stunts)
    - Target item: type ('aspect'|'stunt') and its id
    - Optional world setting via state.meta.setting

    Output:
    - A merged list of concise, actionable hints with a type tag and both narrative and mechanics.

    Rules:
    - For a non-Trouble aspect: produce exactly 2 hints (any relevant mix of invoke/compel/create_advantage).
    - For a Trouble aspect (name == 'Trouble' or id == 'aspect-trouble'): produce exactly 3 hints
      with types: two GM-facing (use like 'compel') and one player-facing ('player_invoke').
    - For a stunt: produce exactly 3 hints with types: 'trigger', 'edge_case', 'synergy'.
    - Each hint must include: short title, 2–3 sentence narrative grounded in the setting, and mechanics line aligned with Fate Core.
    - Avoid duplications; be specific to the target text and the top skills.
    """

    state: CharacterStateInput = dspy.InputField(desc="Full character sheet for context.")
    target_type: str = dspy.InputField(desc="'aspect' or 'stunt'.")
    target_id: str = dspy.InputField(desc="ID of the target aspect or stunt.")
    setting_hint: str | None = dspy.InputField(desc="Optional setting/world hint.")

    hints: list[GMHintItem] = dspy.OutputField(desc="List of {type,title,narrative,mechanics} items.")
    notes: str = dspy.OutputField(desc="Optional rationale or guidance.")
