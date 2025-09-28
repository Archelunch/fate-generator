from __future__ import annotations

from typing import Any

from app.models import SkillSuggestion, UISkill


def _get_ranks_for_ladder(ladder_type: str) -> list[int]:
    return [5, 4, 3, 2, 1] if (ladder_type or "").strip() == "1-5" else [4, 3, 2, 1]


def _rebalance_skills_pyramid(
    skills: list[SkillSuggestion] | list[Any],
    locked_ids: set[str],
    ladder_type: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        {"id": getattr(s, "id", None), "name": getattr(s, "name", None), "rank": int(getattr(s, "rank", 0))}
        for s in skills
        if getattr(s, "name", None) is not None
    ]
    ranks = _get_ranks_for_ladder(ladder_type)
    next_lower = {ranks[i]: (ranks[i + 1] if i + 1 < len(ranks) else ranks[-1]) for i in range(len(ranks))}
    count = {r: 0 for r in ranks}

    locked = [s for s in items if s.get("id") in locked_ids]
    others = [s for s in items if s.get("id") not in locked_ids]

    placed: list[dict[str, Any]] = []

    for s in locked:
        r = int(s.get("rank") or 1)
        if r not in ranks:
            r = ranks[0] if r > ranks[0] else ranks[-1]
        s["rank"] = r
        placed.append(s)
        count[r] += 1

    for s in sorted(others, key=lambda x: int(x.get("rank") or 0), reverse=True):
        r = int(s.get("rank") or 1)
        if r not in ranks:
            r = ranks[0] if r > ranks[0] else ranks[-1]
        while True:
            idx_ok = ranks.index(r)
            if idx_ok == len(ranks) - 1:
                break
            lower = next_lower[r]
            if (count[r] + 1) <= count[lower]:
                break
            r = lower
        s["rank"] = r
        placed.append(s)
        count[r] += 1

    for i in range(len(ranks) - 1):
        high = ranks[i]
        low = ranks[i + 1]
        while count[high] > count[low]:
            cand = next((p for p in placed if p["rank"] == high and p.get("id") not in locked_ids), None)
            if cand is None:
                lower_cand = next((p for p in placed if p["rank"] not in (high, low) and p.get("id") not in locked_ids), None)
                if lower_cand is None:
                    break
                old_r = lower_cand["rank"]
                count[old_r] -= 1
                lower_cand["rank"] = low
                count[low] += 1
                continue
            cand["rank"] = low
            count[high] -= 1
            count[low] += 1

    return placed


def _slugify(name: str) -> str:
    return (name or "").lower().strip().replace(" ", "-").replace("/", "-").replace("_", "-")


def _ensure_skill_ids(
    items: list[SkillSuggestion],
    existing: list[UISkill],
) -> list[SkillSuggestion]:
    name_to_existing: dict[str, str] = {
        (getattr(s, "name", "") or "").strip().lower(): s.id for s in existing if getattr(s, "id", None)
    }
    used_ids: set[str] = set([getattr(s, "id", "") for s in items if getattr(s, "id", None)])
    result: list[SkillSuggestion] = []
    for s in items:
        sid = getattr(s, "id", None)
        nm = (getattr(s, "name", "") or "").strip()
        if not sid:
            existing_id = name_to_existing.get(nm.lower())
            if existing_id and existing_id not in used_ids:
                sid = existing_id
            else:
                base = f"skill-{_slugify(nm)}"
                candidate = base if base not in used_ids else f"{base}-2"
                n = 2
                while candidate in used_ids:
                    n += 1
                    candidate = f"{base}-{n}"
                sid = candidate
        used_ids.add(sid)
        result.append(SkillSuggestion(id=sid, name=getattr(s, "name", None), rank=getattr(s, "rank", None)))
    return result


def _canonicalize_skill_name(name: str, bank: list[str]) -> str | None:
    bank_map = {b.strip().lower(): b for b in bank}
    key = (name or "").strip().lower()
    if key in bank_map:
        return bank_map[key]
    synonyms = {
        "willpower": "Will",
        "cunning": "Deceive",
        "knowledge": "Lore",
        "awareness": "Notice",
        "charisma": "Rapport",
        "strength": "Physique",
        "agility": "Athletics",
        "marksmanship": "Shoot",
    }
    if key in synonyms and synonyms[key].strip().lower() in bank_map:
        return bank_map[synonyms[key].strip().lower()]
    return None


def _get_minimum_quota(ladder_type: str) -> dict[int, int]:
    if (ladder_type or "").strip() == "1-5":
        return {5: 0, 4: 1, 3: 2, 2: 3}
    return {4: 1, 3: 2, 2: 3}


def _pad_pyramid_to_minimum(
    items: list[dict[str, Any]],
    locked_ids: set[str],
    ladder_type: str,
    skill_bank: list[str],
    total_max: int = 10,
) -> list[dict[str, Any]]:
    ranks = _get_ranks_for_ladder(ladder_type)
    base_quota = _get_minimum_quota(ladder_type)
    required_sum = sum(base_quota.values())
    lowest = ranks[-1]
    quota: dict[int, int] = dict(base_quota)
    quota[lowest] = max(0, total_max - required_sum)

    used_names: set[str] = {str(it.get("name") or "").strip().lower() for it in items}
    counts: dict[int, int] = {r: 0 for r in ranks}
    for it in items:
        r = int(it.get("rank", lowest))
        if r in counts:
            counts[r] += 1

    def _next_bank_name() -> str | None:
        for nm in skill_bank:
            key = str(nm or "").strip().lower()
            if key and key not in used_names:
                used_names.add(key)
                return nm
        return None

    padded = list(items)
    for r in ranks:
        need = max(0, quota.get(r, 0) - (counts.get(r, 0)))
        for _ in range(need):
            nm = _next_bank_name()
            if not nm:
                break
            padded.append({"id": None, "name": nm, "rank": r})
            counts[r] = counts.get(r, 0) + 1

    rebalanced = _rebalance_skills_pyramid(padded, locked_ids, ladder_type)
    return rebalanced



