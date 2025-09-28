from app.models import (
    AspectSuggestion,
    CharacterStateInput,
    GenerateRemainingResult,
    Meta,
    SkillSuggestion,
    StuntSuggestion,
    UIAspect,
    UISkill,
    UIStunt,
)
from app.utils import merge_suggestions_into_sheet


def test_merge_preserves_existing_ids_and_updates_fields() -> None:
    state = CharacterStateInput(
        meta=Meta(idea="Test", setting="Nowhere", ladderType="1-4"),
        aspects=[UIAspect(id="aspect-1", name="High Concept", description="Old Desc")],
        skills=[UISkill(id="skill-1", name="Fight", rank=2)],
        stunts=[UIStunt(id="stunt-1", name="Old Stunt", description="Old")],
    )

    suggestions = GenerateRemainingResult(
        aspects=[
            AspectSuggestion(id="aspect-1", description="New Desc"),  # update existing
            AspectSuggestion(name="Brand New Aspect", description="Fresh"),  # new
        ],
        skills=[
            SkillSuggestion(id="skill-1", rank=3),  # update existing
            SkillSuggestion(name="Stealth", rank=1),  # new
        ],
        stunts=[
            StuntSuggestion(id="stunt-1", description="Updated"),  # update existing
            StuntSuggestion(name="New Stunt", description="Fresh"),  # new
        ],
    )

    merged = merge_suggestions_into_sheet(state=state, suggestions=suggestions)

    # Existing IDs preserved
    aspect_ids = {a.id for a in merged.aspects}
    skill_ids = {s.id for s in merged.skills}
    stunt_ids = {s.id for s in merged.stunts}
    assert "aspect-1" in aspect_ids
    assert "skill-1" in skill_ids
    assert "stunt-1" in stunt_ids

    # Fields updated
    updated_aspect = next(a for a in merged.aspects if a.id == "aspect-1")
    assert updated_aspect.description == "New Desc"

    updated_skill = next(s for s in merged.skills if s.id == "skill-1")
    assert updated_skill.rank == 3

    updated_stunt = next(s for s in merged.stunts if s.id == "stunt-1")
    assert updated_stunt.description == "Updated"

    # New items added with generated IDs
    assert len(merged.aspects) == 2
    assert len(merged.skills) == 2
    assert len(merged.stunts) == 2

    new_aspect = next(a for a in merged.aspects if a.id != "aspect-1")
    assert new_aspect.name == "Brand New Aspect"
    assert new_aspect.id != "aspect-1" and new_aspect.id

    new_skill = next(s for s in merged.skills if s.id != "skill-1")
    assert new_skill.name == "Stealth" and new_skill.rank == 1
    assert new_skill.id != "skill-1" and new_skill.id

    new_stunt = next(s for s in merged.stunts if s.id != "stunt-1")
    assert new_stunt.name == "New Stunt" and new_stunt.description == "Fresh"
    assert new_stunt.id != "stunt-1" and new_stunt.id
