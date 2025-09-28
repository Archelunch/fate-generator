from app.models import (
    Aspect,
    CharacterSheet,
    CharacterStateInput,
    GenerateRemainingResult,
    Skill,
    Stunt,
)


def merge_suggestions_into_sheet(
    state: CharacterStateInput,
    suggestions: GenerateRemainingResult,
) -> CharacterSheet:
    """Merge model suggestions with existing state, preserving IDs for existing items."""
    # Start from existing items
    aspects_by_id: dict[str, Aspect] = {
        a.id: Aspect(id=a.id, name=a.name, description=a.description) for a in state.aspects
    }
    skills_by_id: dict[str, Skill] = {s.id: Skill(id=s.id, name=s.name, rank=s.rank) for s in state.skills}
    stunts_by_id: dict[str, Stunt] = {
        s.id: Stunt(id=s.id, name=s.name, description=s.description) for s in state.stunts
    }

    # Apply aspect suggestions
    for aspect_sug in suggestions.aspects or []:
        if aspect_sug.id and aspect_sug.id in aspects_by_id:
            existing_aspect = aspects_by_id[aspect_sug.id]
            if aspect_sug.name is not None:
                existing_aspect.name = aspect_sug.name
            if aspect_sug.description is not None:
                existing_aspect.description = aspect_sug.description
        else:
            # New aspect
            new_aspect = Aspect(name=(aspect_sug.name or ""), description=aspect_sug.description)
            aspects_by_id[new_aspect.id] = new_aspect

    # Apply skill suggestions
    for skill_sug in suggestions.skills or []:
        if skill_sug.id and skill_sug.id in skills_by_id:
            existing_skill = skills_by_id[skill_sug.id]
            if skill_sug.name is not None:
                existing_skill.name = skill_sug.name
            if skill_sug.rank is not None:
                existing_skill.rank = int(skill_sug.rank)
        else:
            new_skill = Skill(name=(skill_sug.name or ""), rank=int(skill_sug.rank or 0))
            skills_by_id[new_skill.id] = new_skill

    # Apply stunt suggestions
    for stunt_sug in suggestions.stunts or []:
        if stunt_sug.id and stunt_sug.id in stunts_by_id:
            existing_stunt = stunts_by_id[stunt_sug.id]
            if stunt_sug.name is not None:
                existing_stunt.name = stunt_sug.name
            if stunt_sug.description is not None:
                existing_stunt.description = stunt_sug.description
        else:
            new_stunt = Stunt(name=(stunt_sug.name or ""), description=stunt_sug.description)
            stunts_by_id[new_stunt.id] = new_stunt

    return CharacterSheet(
        meta=state.meta,
        aspects=list(aspects_by_id.values()),
        skills=list(skills_by_id.values()),
        stunts=list(stunts_by_id.values()),
    )
