import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Meta(BaseModel):
    idea: str
    setting: str | None = None
    ladderType: str = Field(default="1-4")


class Aspect(BaseModel):
    id: str = Field(default_factory=generate_uuid)
    name: str
    description: str | None = None


class Skill(BaseModel):
    id: str = Field(default_factory=generate_uuid)
    name: str
    rank: int = 0


class Stunt(BaseModel):
    id: str = Field(default_factory=generate_uuid)
    name: str
    description: str | None = None


class CharacterSheet(BaseModel):
    id: str = Field(default_factory=generate_uuid)
    meta: Meta
    aspects: list[Aspect] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    stunts: list[Stunt] = Field(default_factory=list)


# Request model for the /api/generate_skeleton endpoint (Phase A)
class GenerateSkeletonRequest(BaseModel):
    idea: str = Field(min_length=1, max_length=1000, description="The idea for the character")
    setting: str | None = None
    skillList: list[str] | None = None


# Response models for the /api/generate_skeleton endpoint (Phase A)
class RankedSkill(BaseModel):
    id: str
    name: str
    rank: int


class CharacterSkeleton(BaseModel):
    highConcept: str
    trouble: str
    skills: list[RankedSkill]


# Request/response models for the /api/generate_remaining endpoint (Phase B)


class ValidationFieldError(BaseModel):
    path: str
    message: str


class ConflictField(BaseModel):
    field: str
    currentValue: Any | None = None
    proposedValue: Any | None = None
    reason: str


class GenerationErrorResponse(BaseModel):
    code: str
    message: str
    validationErrors: list[ValidationFieldError] | None = None
    conflicts: list[ConflictField] | None = None


# === Client-side annotated schema (inputs to DSPy signature) ===


class UIAspect(BaseModel):
    id: str
    name: str
    description: str | None = None
    locked: bool | None = None
    userEdited: bool | None = None


class UISkill(BaseModel):
    id: str
    name: str
    rank: int = 0
    locked: bool | None = None
    userEdited: bool | None = None


class UIStunt(BaseModel):
    id: str
    name: str
    description: str | None = None
    locked: bool | None = None
    userEdited: bool | None = None


class CharacterStateInput(BaseModel):
    meta: Meta
    aspects: list[UIAspect] = Field(default_factory=list)
    skills: list[UISkill] = Field(default_factory=list)
    stunts: list[UIStunt] = Field(default_factory=list)


class GenerateRemainingRequest(BaseModel):
    # Structured frontend state for constraints (includes optional locked/userEdited)
    character: CharacterStateInput
    allowOverwriteUserEdits: bool = False

    # Optional generation scoping/options
    class GenerationOptions(BaseModel):
        mode: Literal[
            "aspects",
            "stunts",
            "single_stunt",
            "skills",
            "high_concept",
            "trouble",
        ]
        count: int | None = None
        targetSkillId: str | None = None
        actionType: Literal["overcome", "create_advantage", "attack", "defend"] | None = None
        note: str | None = None
        skillBank: list[str] | None = None

    options: GenerationOptions | None = None


# === DSPy signature output schema (model suggestions/deltas) ===


class AspectSuggestion(BaseModel):
    id: str | None = None  # present for updates; omitted/None for new
    name: str | None = None
    description: str | None = None


class SkillSuggestion(BaseModel):
    id: str | None = None
    name: str | None = None
    rank: int | None = None


class StuntSuggestion(BaseModel):
    id: str | None = None
    name: str | None = None
    description: str | None = None


class GenerateRemainingResult(BaseModel):
    aspects: list[AspectSuggestion] | None = None
    skills: list[SkillSuggestion] | None = None
    stunts: list[StuntSuggestion] | None = None
    notes: str | None = None


# === GM Assistant (Hints) ===


class GMHint(BaseModel):
    id: str = Field(default_factory=generate_uuid)
    type: Literal[
        "invoke",
        "compel",
        "create_advantage",
        "player_invoke",
        "trigger",
        "edge_case",
        "synergy",
    ]
    title: str
    narrative: str
    mechanics: str


class GMHintsRequest(BaseModel):
    character: CharacterStateInput

    class Target(BaseModel):
        type: Literal["aspect", "stunt"]
        id: str

    class Options(BaseModel):
        num: int | None = None
        tone: Literal["neutral", "cinematic"] | None = None

    target: Target
    options: Options | None = None


class GMHintsResponse(BaseModel):
    hints: list[GMHint]
    notes: str | None = None
