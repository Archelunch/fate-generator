from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING


def _is_single_sentence(text: str) -> bool:
    if "\n" in text or "\r" in text:
        return False
    # naive: ends with punctuation or no period but short
    stripped = text.strip()
    if not stripped:
        return False
    # Avoid multiple sentence enders
    if stripped.count(".") > 1 or stripped.count("?") > 1 or stripped.count("!") > 1:
        return False
    return True


def _has_mechanical_tokens(text: str) -> bool:
    lowered = text.lower()
    forbidden = [
        "+2",
        "+1",
        "-1",
        "-2",
        "++",
        "--",
        "+",
        "-",
        "d4",
        "d6",
        "d8",
        "d10",
        "d12",
        "d20",
        "d100",
    ]
    return any(tok in lowered for tok in forbidden)


def _only_simple_chars(text: str) -> bool:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ '-")
    return all(ch in allowed for ch in text)


def validate_structure_gate(
    *,
    idea: str,
    setting: str | None,
    skill_list: list[str],
    high_concept: str | None,
    trouble: str | None,
    ranked_skills: list[str] | None,
) -> tuple[bool, list[str]]:
    """Return (ok, messages). If not ok, messages contain targeted reasons.

    Hard-gate: any failure returns ok=False.
    """
    problems: list[str] = []

    # Text fields
    for name, value in ("high_concept", high_concept), ("trouble", trouble):
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{name} must be a non-empty string.")
            continue
        if len(value.strip()) > 120:
            problems.append(f"{name} should be concise (<=120 chars).")
        if not _is_single_sentence(value):
            problems.append(f"{name} must be a single sentence.")
        if _has_mechanical_tokens(value):
            problems.append(f"{name} should not contain mechanical tokens like +2 or dice.")
        if value.strip().lower().startswith("high concept:") or value.strip().lower().startswith("trouble:"):
            problems.append(f"{name} should not include leading labels (e.g., 'High Concept:').")

    if isinstance(high_concept, str) and isinstance(trouble, str):
        if high_concept.strip().lower() == trouble.strip().lower():
            problems.append("high_concept and trouble must be distinct.")

    # Skills list
    if not isinstance(ranked_skills, list) or not ranked_skills:
        problems.append("ranked_skills must be a non-empty list.")
    else:
        if len(ranked_skills) != len(skill_list):
            problems.append("ranked_skills must include all and only the allowed skills.")
        seen: set[str] = set()
        allowed = {s.strip() for s in skill_list}
        for s in ranked_skills:
            if not isinstance(s, str) or not s.strip():
                problems.append("Each ranked skill must be a non-empty string.")
                break
            if s in seen:
                problems.append("ranked_skills must not contain duplicates.")
                break
            seen.add(s)
            # only simple chars in skills to avoid annotations
            if not _only_simple_chars(s):
                problems.append(f"Skill '{s}' contains invalid characters.")
                break
            if s.strip() not in allowed:
                problems.append(f"Skill '{s}' not in allowed list.")
                break

    return (len(problems) == 0, problems)


def validate_remaining_gate(
    *,
    mode: str,
    pred_aspect_name: str | None,
    pred_aspect_description: str | None,
    pred_stunt_name: str | None,
    pred_stunt_description: str | None,
) -> tuple[bool, list[str]]:
    """Hard gate for remaining suggestions.

    - For aspects: require non-empty name and a concise description (<= 140 chars), single sentence.
    - For stunts: require non-empty name and description; forbid dice/mechanical tokens like +2 only if misformatted.
      Stunts may include mechanics language, but keep it a single sentence and <= 200 chars.
    """
    problems: list[str] = []
    m = (mode or "").strip().lower()

    def check_sentence(name: str, text: str, max_len: int) -> None:
        if not text or not text.strip():
            problems.append(f"{name} must be non-empty.")
            return
        if len(text.strip()) > max_len:
            problems.append(f"{name} should be concise (<= {max_len} chars).")
        if not _is_single_sentence(text):
            problems.append(f"{name} must be a single sentence.")

    if m == "aspects" or m in {"high_concept", "trouble"}:
        if not pred_aspect_name or not pred_aspect_name.strip():
            problems.append("aspect.name must be non-empty.")
        if pred_aspect_description is None:
            problems.append("aspect.description must be provided.")
        else:
            check_sentence("aspect.description", pred_aspect_description, 140)
    elif m == "stunts" or m == "single_stunt":
        if not pred_stunt_name or not pred_stunt_name.strip():
            problems.append("stunt.name must be non-empty.")
        if pred_stunt_description is None:
            problems.append("stunt.description must be provided.")
        else:
            check_sentence("stunt.description", pred_stunt_description, 200)
    else:
        problems.append("mode must be one of aspects|stunts|high_concept|trouble|single_stunt")

    return (len(problems) == 0, problems)


def validate_gm_hints_gate(
    *,
    target_type: str,
    pred_hints: list[dict[str, str]] | None,
) -> tuple[bool, list[str]]:
    """Hard gate for GM hints.

    Requirements:
    - For aspect target: exactly 2 hints unless target is Trouble -> exactly 3 with types
      ['compel','create_advantage','player_invoke'].
      We only gate shape minimally here: 2–3 items; types present; fields non-empty.
    - For stunt target: exactly 3 hints with types ['trigger','edge_case','synergy'].
    """
    problems: list[str] = []
    if not isinstance(pred_hints, list) or not pred_hints:
        return False, ["pred_hints must be a non-empty list."]

    # Helper to extract string fields from either dict or object
    def _get_str(h: object, key: str) -> str:
        if isinstance(h, dict):
            v = h.get(key)
        else:
            v = getattr(h, key, None)
        s = v if v is not None else ""
        return str(s).strip()

    # Basic field checks
    for i, h in enumerate(pred_hints):
        for key in ("type", "title", "narrative", "mechanics"):
            v = _get_str(h, key)
            if not v:
                problems.append(f"hint[{i}].{key} must be non-empty.")

    t = (target_type or "").strip().lower()
    if t == "stunt":
        expected = {"trigger", "edge_case", "synergy"}
        seen = {_get_str(h, "type").lower() for h in pred_hints}
        if len(pred_hints) != 3:
            problems.append("stunt target must yield exactly 3 hints.")
        if not expected.issubset(seen):
            problems.append("stunt target must include trigger, edge_case, and synergy hints.")
    else:
        # For aspects we allow 2 or 3; judge module will refine counts by Trouble in scoring
        if len(pred_hints) not in (2, 3):
            problems.append("aspect target must yield 2 or 3 hints.")

    return (len(problems) == 0, problems)


def spearman_footrule_similarity(reference: Iterable[str], candidate: Iterable[str]) -> float:
    """Compute normalized Spearman footrule similarity in [0,1].

    1.0 means identical ranking; 0.0 means maximally distant permutation.
    """
    ref_list = list(reference)
    cand_list = list(candidate)
    if not ref_list or len(ref_list) != len(cand_list):
        return 0.0
    n = len(ref_list)
    ref_pos = {item: i for i, item in enumerate(ref_list)}
    cand_pos = {item: i for i, item in enumerate(cand_list)}
    # If candidate misses items, treat as worst
    if set(ref_pos.keys()) != set(cand_pos.keys()):
        return 0.0
    footrule = sum(abs(ref_pos[k] - cand_pos[k]) for k in ref_pos)
    # Max footrule distance for permutations of 0..n-1 is n^2/2 for even n, (n^2-1)/2 for odd n
    max_dist = (n * n) // 2 if n % 2 == 0 else (n * n - 1) // 2
    if max_dist == 0:
        return 1.0
    # Similarity
    return max(0.0, 1.0 - (footrule / float(max_dist)))


if TYPE_CHECKING:  # only for type checkers to avoid runtime import cycles
    from app.models import CharacterSheet


def build_sample_character_skeleton() -> CharacterSheet:  # pragma: no cover - deterministic stub
    """Build a sample character with fixed data for demos and testing."""
    from app.models import Aspect, CharacterSheet, Meta, Skill, Stunt  # local import to avoid cycles

    return CharacterSheet(
        id="00000000-0000-0000-0000-000000000001",
        meta=Meta(idea="Wandering swordsman seeking redemption", setting="Low fantasy", ladderType="1-4"),
        aspects=[
            Aspect(id="aspect-1", name="High Concept", description="Haunted Ronin on a Redemption Path"),
            Aspect(id="aspect-2", name="Trouble", description="Past Sins Catch Up at the Worst Time"),
        ],
        skills=[
            Skill(id="skill-1", name="Fight", rank=3),
            Skill(id="skill-2", name="Notice", rank=2),
            Skill(id="skill-3", name="Stealth", rank=1),
        ],
        stunts=[
            Stunt(id="stunt-1", name="Iaijutsu Strike", description="+2 to Fight when acting first in a duel."),
        ],
    )
