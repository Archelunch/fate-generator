from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Literal, TypedDict

import dspy
from dotenv import load_dotenv

from app.core.constants import DEFAULT_FATE_CORE_SKILLS
from app.config.runtime import configure_dspy, configure_logging
from app.config.settings import Settings, get_settings
from app.dspy_modules import CharacterSkeletonModule, GmHintsModule, RemainingSuggestionsModule
from app.models import (
    Aspect,
    CharacterStateInput,
    Meta,
    UIAspect,
    UISkill,
    UIStunt,
    generate_uuid,
)

logger = logging.getLogger(__name__)


def ensure_out_dir(settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    out_dir = cfg.datasets_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def curated_ideas() -> list[dict[str, str | None]]:
    # 10 with empty setting
    empty_setting: list[dict[str, str | None]] = [
        {"idea": "Witty detective with a dark past", "setting": None},
        {"idea": "Exiled noble turned wandering swordmage", "setting": None},
        {"idea": "Cynical medic who can hear ghosts", "setting": None},
        {"idea": "Optimistic archaeologist chasing forbidden myths", "setting": None},
        {"idea": "Retired monster hunter pulled back in", "setting": None},
        {"idea": "Runaway alchemist seeking a cure", "setting": None},
        {"idea": "Clockwork tinkerer with a human heart", "setting": None},
        {"idea": "Gentle giant sworn to nonviolence", "setting": None},
        {"idea": "Silver-tongued thief with a code", "setting": None},
        {"idea": "Haunted bard who remembers future songs", "setting": None},
    ]

    # 10 with world description / campaign idea
    with_setting: list[dict[str, str | None]] = [
        {
            "idea": "Daring skyship pilot chasing living storms",
            "setting": "Shattered archipelago where cities float above an endless storm belt; guilds hoard wind-lore.",
        },
        {
            "idea": "Archivist witch binding stray memories",
            "setting": "A city built inside a petrified god; memories become spirits that must be archived or set free.",
        },
        {
            "idea": "Repentant warlock severing a pact",
            "setting": "Broken kingdoms after a demon winter; fiendish contracts persist like legal curses.",
        },
        {
            "idea": "Time-lost ranger mapping shifting wilds",
            "setting": "Forests rearrange every dawn; cartographers are folk heroes and oracles argue with maps.",
        },
        {
            "idea": "Diplomat from a fallen moon",
            "setting": "Crystalline lunar shards crashed into the sea; refugees barter starlight technology for sanctuary.",
        },
        {
            "idea": "Cyber-monk decoding corrupted prophecies",
            "setting": "Neon monastery in a megacity; scriptures live in glitching data-ghosts.",
        },
        {
            "idea": "Beast-speaker hunting corporate poachers",
            "setting": "Vertical jungle reserve threaded through arcology levels; fauna evolved alongside drones.",
        },
        {
            "idea": "Runesmith courier with explosive secrets",
            "setting": "Steam-and-sigil railways where packages are oath-bound; couriers duel with contracts.",
        },
        {
            "idea": "Exorcist chef feeding restless spirits",
            "setting": "Harbor city where ghost tides roll in nightly; offerings are tickets to the afterlife ferries.",
        },
        {
            "idea": "Golem-rights advocate learning to feel",
            "setting": "Industrial league debates personhood of constructs; artisan unions sponsor sentience trials.",
        },
    ]
    return empty_setting + with_setting


def to_ui_state_from_skeleton(
    idea: str,
    setting: str | None,
    ranked_skills: list[str],
    *,
    empty_skills: bool = False,
    preset_stunt: tuple[str, str] | None = None,
    extra_aspects: list[tuple[str, str]] | None = None,
    high_concept_text: str = "",
    trouble_text: str = "",
) -> CharacterStateInput:
    aspects: list[UIAspect] = [
        UIAspect(
            id=Aspect(name="High Concept", description=high_concept_text).id,
            name="High Concept",
            description=high_concept_text,
            locked=True,
            userEdited=False,
        ),
        UIAspect(
            id=Aspect(name="Trouble", description=trouble_text).id,
            name="Trouble",
            description=trouble_text,
            locked=False,
            userEdited=True,
        ),
    ]
    if extra_aspects:
        for name, desc in extra_aspects:
            a = Aspect(name=name, description=desc)
            aspects.append(UIAspect(id=a.id, name=a.name, description=a.description, locked=False, userEdited=False))

    skills: list[UISkill] = []
    if not empty_skills:
        # Assign simple ranks to top 4 skills (4,3,2,1)
        ranks = [4, 3, 2, 1]
        for idx, sname in enumerate(ranked_skills[:4]):
            skill = UISkill(id=generate_uuid(), name=sname, rank=ranks[idx], locked=False, userEdited=False)
            skills.append(skill)

    stunts: list[UIStunt] = []
    if preset_stunt is not None:
        sname, sdesc = preset_stunt
        st = UIStunt(id=generate_uuid(), name=sname, description=sdesc, locked=False, userEdited=False)
        stunts.append(st)

    meta = Meta(idea=idea, setting=setting)
    return CharacterStateInput(meta=meta, aspects=aspects, skills=skills, stunts=stunts)


# (no merge serialization needed for training datasets)


def progress_bar(current: int, total: int, prefix: str = "") -> None:
    bar_len = 40
    filled = int(bar_len * current / total) if total > 0 else bar_len
    bar = "#" * filled + "-" * (bar_len - filled)
    percent = (current / total * 100) if total else 100.0
    sys.stdout.write(f"\r{prefix} [{bar}] {current}/{total} ({percent:.0f}%)")
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")


def to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    # Pydantic BaseModel has model_dump
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    return value


def load_json_file(path: str | os.PathLike[str]) -> Any:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _augment_state_with_output(state: CharacterStateInput, output_obj: dict[str, Any]) -> None:
    """Ephemerally apply suggested aspects/stunts from output onto the state in place."""
    # Aspects
    aspects_raw = _coerce_list(output_obj.get("aspects"))
    for a in aspects_raw:
        if not isinstance(a, dict):
            continue
        name = (a.get("name") or "").strip()
        desc = a.get("description") or None
        if not name:
            continue
        # skip if duplicate by name+desc
        if any(
            (x.name or "").strip().lower() == name.lower() and (x.description or None) == desc for x in state.aspects
        ):
            continue
        state.aspects.append(
            UIAspect(
                id=a.get("id") or generate_uuid(),
                name=name,
                description=desc,
                locked=False,
                userEdited=False,
            )
        )

    # Stunts
    stunts_raw = _coerce_list(output_obj.get("stunts"))
    for s in stunts_raw:
        if not isinstance(s, dict):
            continue
        name = (s.get("name") or "").strip() or "Stunt"
        desc = s.get("description") or None
        if not desc:
            continue
        # skip if duplicate by description
        if any((x.description or "").strip().lower() == (desc or "").strip().lower() for x in state.stunts):
            continue
        state.stunts.append(
            UIStunt(
                id=s.get("id") or generate_uuid(),
                name=name,
                description=desc,
                locked=False,
                userEdited=False,
            )
        )


def stage_generate_skeletons(input_file: str, out_dir: Path | None = None, *, settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    if out_dir is None:
        out_dir = ensure_out_dir(cfg)

    input_path = Path(input_file)
    if not input_path.is_file():
        raise FileNotFoundError(f"Skeleton stage input not found: {input_path}")

    data = load_json_file(input_file)
    if not isinstance(data, list):
        raise ValueError("Skeleton stage input must be a JSON array of objects {idea, setting?}")

    # Refine for clean ranked_skills using new module wrapper
    skeleton_module = CharacterSkeletonModule()

    def ranked_skills_reward(args: dict[str, Any], pred: dspy.Prediction) -> float | dspy.Prediction:
        skills = getattr(pred, "ranked_skills", None)
        if not isinstance(skills, list) or not skills:
            return 0.0
        expected_skills = args.get("skills", []) or []
        if len(skills) != len(expected_skills):
            return dspy.Prediction(
                score=0.0,
                feedback=f"Expected {len(expected_skills)} skills, got {len(skills)}",
            )
        allowed = {str(s).strip().lower() for s in expected_skills}
        for item in skills:
            if not isinstance(item, str):
                return dspy.Prediction(score=0.0, feedback=f"Expected a list of skill names, got {type(skills)}")
            text = item.strip()
            if text.strip().lower() not in allowed:
                return dspy.Prediction(score=0.0, feedback=f"{text} is not in the allowed list")
            if any(ch in text for ch in [":", "(", ")", "+", "-", ",", ";"]):
                return dspy.Prediction(
                    score=0.0, feedback=f"Only allowed to have letters in the skill name, not {text}"
                )
            if any(ch.isdigit() for ch in text):
                return dspy.Prediction(
                    score=0.0, feedback=f"Only allowed to have letters in the skill name, not {text}"
                )
        return 1.0

    skeleton_refine = dspy.Refine(
        module=skeleton_module,
        N=5,
        reward_fn=ranked_skills_reward,
        threshold=1.0,
    )

    def normalize_ranked_skills(raw: list[Any], allowed: list[str]) -> list[str]:
        allowed_map = {name.lower(): name for name in allowed}
        result: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                continue
            text = item.strip()
            key = text.lower()
            if key in allowed_map and re.fullmatch(r"[A-Za-z ]+", text):
                name = allowed_map[key]
                if name not in result:
                    result.append(name)
                continue
            for name in allowed:
                if re.search(rf"\b{re.escape(name)}\b", text, flags=re.IGNORECASE):
                    if name not in result:
                        result.append(name)
                    break
        return result

    ideas: list[dict[str, str | None]] = []
    for obj in data:
        if isinstance(obj, dict) and obj.get("idea"):
            ideas.append(
                {"idea": str(obj.get("idea")), "setting": (obj.get("setting") if obj.get("setting") else None)}
            )

    skeleton_records: list[dict[str, Any]] = []
    total_skel = len(ideas)
    logger.info("[Stage 1] Generating %d skeletons", total_skel)
    progress_bar(0, total_skel, prefix="Skeletons   ")
    for idx, item in enumerate(ideas, start=1):
        idea = item["idea"] or ""
        setting = item.get("setting") or None
        pred = skeleton_refine(idea=idea, setting=setting, skills=list(DEFAULT_FATE_CORE_SKILLS))
        ranked = list(getattr(pred, "ranked_skills", []) or [])
        ranked = normalize_ranked_skills(ranked, list(DEFAULT_FATE_CORE_SKILLS))
        skeleton_records.append(
            {
                "input": {"idea": idea, "setting": setting, "skill_list": list(DEFAULT_FATE_CORE_SKILLS)},
                "output": {
                    "high_concept": getattr(pred, "high_concept", None),
                    "trouble": getattr(pred, "trouble", None),
                    "ranked_skills": ranked,
                },
            }
        )
        progress_bar(idx, total_skel, prefix="Skeletons   ")

    out_file = out_dir / "dataset_skeleton.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(skeleton_records, f, ensure_ascii=False, indent=2)
    logger.info("[Stage 1] Wrote skeleton dataset: %s", out_file)
    return out_file


def stage_generate_remaining(input_file: str, out_dir: Path | None = None, *, settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    if out_dir is None:
        out_dir = ensure_out_dir(cfg)

    input_path = Path(input_file)
    if not input_path.is_file():
        raise FileNotFoundError(f"Remaining stage input not found: {input_path}")

    skeleton_records = load_json_file(input_file)
    if not isinstance(skeleton_records, list):
        raise ValueError("Remaining stage input must be a JSON array produced by Stage 1")

    def _get_skeleton(idx: int) -> tuple[str, str | None, str, str, list[str]]:
        rec = skeleton_records[idx % len(skeleton_records)]
        inp = rec.get("input", {})
        out = rec.get("output", {})
        return (
            str(inp.get("idea", "")),
            (inp.get("setting") if inp.get("setting") is not None else None),
            str(out.get("high_concept", "")),
            str(out.get("trouble", "")),
            list(out.get("ranked_skills", []) or []),
        )

    remaining_records: list[dict[str, Any]] = []
    # training dataset only captures inputs/outputs; no merged sheets

    class StuntScenario(TypedDict, total=False):
        empty_skills: bool
        preset_stunt: tuple[str, str] | None
        target: Literal["top"] | None
        action: Literal["overcome", "create_advantage", "attack", "defend"]
        note: str | None

    class AspectScenario(TypedDict, total=False):
        extra_aspects: list[tuple[str, str]] | None
        slots: int
        allow_overwrite: bool
        note: str | None

    stunt_scenarios: list[StuntScenario] = [
        {"empty_skills": True, "preset_stunt": None, "target": None, "action": "overcome", "note": None},
        {
            "empty_skills": False,
            "preset_stunt": None,
            "target": "top",
            "action": "create_advantage",
            "note": "Make it cinematic.",
        },
        {
            "empty_skills": False,
            "preset_stunt": ("Acrobat's Flourish", "+2 to Overcome with Athletics when flipping across obstacles."),
            "target": "top",
            "action": "attack",
            "note": None,
        },
        {
            "empty_skills": True,
            "preset_stunt": ("Silver Tongue", "+2 to Create Advantage with Rapport when sowing doubt."),
            "target": None,
            "action": "defend",
            "note": "Once per scene.",
        },
        {
            "empty_skills": False,
            "preset_stunt": None,
            "target": None,
            "action": "overcome",
            "note": "Edge-case utility.",
        },
    ]
    aspect_scenarios: list[AspectScenario] = [
        {"extra_aspects": None, "slots": 2, "allow_overwrite": False, "note": "Double-edged phrasing."},
        {
            "extra_aspects": [("Old Debt", "Owes favors to a shadowy syndicate.")],
            "slots": 1,
            "allow_overwrite": True,
            "note": None,
        },
        {
            "extra_aspects": [
                ("Mentor's Lesson", "Never strike first—set the stage."),
                ("Lucky Charm", "Superstition that sometimes works."),
            ],
            "slots": 1,
            "allow_overwrite": False,
            "note": "Keep them grounded in the setting.",
        },
        {"extra_aspects": None, "slots": 3, "allow_overwrite": True, "note": None},
        {
            "extra_aspects": [("Reputation Precedes", "Doors open—sometimes to traps.")],
            "slots": 1,
            "allow_overwrite": False,
            "note": "Short and punchy.",
        },
    ]

    total_remaining = 30
    rem_done = 0
    logger.info("[Stage 2] Generating %d remaining-suggestions (15 stunts + 15 aspects)", total_remaining)
    progress_bar(0, total_remaining, prefix="Remaining  ")

    rem_mod = RemainingSuggestionsModule()
    for i in range(15):
        idea, setting, high_concept, trouble, ranked = _get_skeleton(i)
        stunt_sc = stunt_scenarios[i % len(stunt_scenarios)]
        target_skill = ranked[0] if (stunt_sc.get("target") == "top" and len(ranked) > 0) else None
        state = to_ui_state_from_skeleton(
            idea=idea,
            setting=setting,
            ranked_skills=ranked,
            empty_skills=bool(stunt_sc.get("empty_skills", False)),
            preset_stunt=stunt_sc.get("preset_stunt"),
            extra_aspects=None,
            high_concept_text=high_concept,
            trouble_text=trouble,
        )

        sugg = rem_mod(
            state=state,
            allow_overwrite=False,
            default_skills=list(DEFAULT_FATE_CORE_SKILLS),
            feedback=None,
            mode="stunts",
            target_skill_name=target_skill,
            action_type=str(stunt_sc["action"]),
            user_note=stunt_sc.get("note"),
        )
        remaining_records.append(
            {
                "input": {
                    "mode": "stunts",
                    "state": state.model_dump(),
                    "allow_overwrite": False,
                    "default_skills": list(DEFAULT_FATE_CORE_SKILLS),
                    "target_skill_name": target_skill,
                    "action_type": stunt_sc["action"],
                    "user_note": stunt_sc.get("note"),
                },
                "output": {
                    "aspects": to_jsonable(getattr(sugg, "aspects", None)),
                    "stunts": to_jsonable(getattr(sugg, "stunts", None)),
                    "notes": getattr(sugg, "notes", None),
                },
            }
        )
        rem_done += 1
        progress_bar(rem_done, total_remaining, prefix="Remaining  ")

    for i in range(15):
        idea, setting, high_concept, trouble, ranked = _get_skeleton(i + 5)
        aspect_sc = aspect_scenarios[i % len(aspect_scenarios)]
        state = to_ui_state_from_skeleton(
            idea=idea,
            setting=setting,
            ranked_skills=ranked,
            empty_skills=False,
            preset_stunt=None,
            extra_aspects=aspect_sc.get("extra_aspects"),
            high_concept_text=high_concept,
            trouble_text=trouble,
        )

        sugg = rem_mod(
            state=state,
            allow_overwrite=bool(aspect_sc.get("allow_overwrite", False)),
            default_skills=list(DEFAULT_FATE_CORE_SKILLS),
            feedback=None,
            mode="aspects",
            aspect_slots_left=int(aspect_sc["slots"]),
            user_note=aspect_sc.get("note"),
        )
        remaining_records.append(
            {
                "input": {
                    "mode": "aspects",
                    "state": state.model_dump(),
                    "allow_overwrite": bool(aspect_sc.get("allow_overwrite", False)),
                    "default_skills": list(DEFAULT_FATE_CORE_SKILLS),
                    "aspect_slots_left": int(aspect_sc["slots"]),
                    "user_note": aspect_sc.get("note"),
                },
                "output": {
                    "aspects": to_jsonable(getattr(sugg, "aspects", None)),
                    "stunts": to_jsonable(getattr(sugg, "stunts", None)),
                    "notes": getattr(sugg, "notes", None),
                },
            }
        )
        rem_done += 1
        progress_bar(rem_done, total_remaining, prefix="Remaining  ")

    out_file = out_dir / "dataset_remaining.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(remaining_records, f, ensure_ascii=False, indent=2)
    logger.info("[Stage 2] Wrote remaining dataset: %s", out_file)
    return out_file


def stage_generate_gm_hints(input_file: str, out_dir: Path | None = None, *, settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    if out_dir is None:
        out_dir = ensure_out_dir(cfg)

    input_path = Path(input_file)
    if not input_path.is_file():
        raise FileNotFoundError(f"GM hints stage input not found: {input_path}")

    remaining_records = load_json_file(input_file)
    if not isinstance(remaining_records, list):
        raise ValueError("GM hints stage input must be a JSON array produced by Stage 2")

    gm_records: list[dict[str, Any]] = []

    trouble_targets: list[tuple[CharacterStateInput, str]] = []
    aspect_targets: list[tuple[CharacterStateInput, str]] = []
    stunt_targets: list[tuple[CharacterStateInput, str]] = []

    for rec in remaining_records:
        inp = rec.get("input", {})
        outp = rec.get("output", {})
        state_obj = inp.get("state")
        if not isinstance(state_obj, dict):
            continue
        state = CharacterStateInput.model_validate(state_obj)
        # Augment with generated suggestions to ensure targets exist
        try:
            _augment_state_with_output(state, outp)
        except Exception as e:
            logger.debug("augment_state failed: %s", e)
        for a in state.aspects:
            if (a.name or "").strip().lower() == "trouble":
                trouble_targets.append((state, a.id))
                break
        non_trouble = next((a for a in state.aspects if (a.name or "").strip().lower() not in {"trouble"}), None)
        if non_trouble is not None:
            aspect_targets.append((state, non_trouble.id))
        # collect all stunts to ensure we can reach 10 total
        for s in state.stunts:
            stunt_targets.append((state, s.id))

    # Deduplicate (state identity + target id) and cap to 10 each
    def _dedupe(pairs: list[tuple[CharacterStateInput, str]]) -> list[tuple[CharacterStateInput, str]]:
        seen: set[str] = set()
        out_list: list[tuple[CharacterStateInput, str]] = []
        for st, tid in pairs:
            key = f"{id(st)}|{tid}"
            if key in seen:
                continue
            seen.add(key)
            out_list.append((st, tid))
        return out_list

    trouble_targets = _dedupe(trouble_targets)[:10]
    aspect_targets = _dedupe(aspect_targets)[:10]
    stunt_targets = _dedupe(stunt_targets)[:10]
    total_gm = len(trouble_targets) + len(aspect_targets) + len(stunt_targets)
    logger.info(
        "[Stage 3] Generating GM hints: trouble=%d, aspects=%d, stunts=%d (total=%d)",
        len(trouble_targets),
        len(aspect_targets),
        len(stunt_targets),
        total_gm,
    )
    progress_bar(0, total_gm, prefix="GM Hints   ")
    gm_done = 0

    gm_mod = GmHintsModule()
    for state, aid in trouble_targets:
        resp = gm_mod(state=state, target_type="aspect", target_id=aid)
        gm_records.append(
            {
                "input": {"target_type": "aspect", "target_id": aid, "state": state.model_dump()},
                "output": {
                    "hints": to_jsonable(getattr(resp, "hints", None)),
                    "notes": getattr(resp, "notes", None),
                },
            }
        )
        gm_done += 1
        progress_bar(gm_done, total_gm, prefix="GM Hints   ")
    for state, aid in aspect_targets:
        resp = gm_mod(state=state, target_type="aspect", target_id=aid)
        gm_records.append(
            {
                "input": {"target_type": "aspect", "target_id": aid, "state": state.model_dump()},
                "output": {
                    "hints": to_jsonable(getattr(resp, "hints", None)),
                    "notes": getattr(resp, "notes", None),
                },
            }
        )
        gm_done += 1
        progress_bar(gm_done, total_gm, prefix="GM Hints   ")
    for state, sid in stunt_targets:
        resp = gm_mod(state=state, target_type="stunt", target_id=sid)
        gm_records.append(
            {
                "input": {"target_type": "stunt", "target_id": sid, "state": state.model_dump()},
                "output": {
                    "hints": to_jsonable(getattr(resp, "hints", None)),
                    "notes": getattr(resp, "notes", None),
                },
            }
        )
        gm_done += 1
        progress_bar(gm_done, total_gm, prefix="GM Hints   ")

    out_file = out_dir / "dataset_gm_hints.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(gm_records, f, ensure_ascii=False, indent=2)
    logger.info("[Stage 3] Wrote GM hints dataset: %s", out_file)
    return out_file


def main() -> None:
    load_dotenv()
    settings = get_settings()
    configure_logging(settings)
    logger.info("Starting dataset generation (multi-stage)")
    configure_dspy(settings)

    if len(sys.argv) < 3:
        print(
            "Usage: python scripts/generate_dataset.py <stage> <input_json>\n"
            "  stage: skeleton | remaining | hints\n"
            "  input_json: path to input JSON for the stage\n",
            file=sys.stderr,
        )
        sys.exit(1)

    stage = sys.argv[1].strip().lower()
    input_json = sys.argv[2]

    if stage == "skeleton":
        stage_generate_skeletons(input_json, settings=settings)
    elif stage == "remaining":
        stage_generate_remaining(input_json, settings=settings)
    elif stage == "hints":
        stage_generate_gm_hints(input_json, settings=settings)
    else:
        raise SystemExit("Unknown stage. Expected one of: skeleton, remaining, hints")


if __name__ == "__main__":
    main()
