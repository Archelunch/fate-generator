from __future__ import annotations

from typing import Any, Literal, cast

from app.models import CharacterStateInput, GMHint, GMHintsResponse


def normalize_gm_hints(
    state: CharacterStateInput,
    *,
    target_type: str,
    target_id: str,
    raw_prediction: Any,
) -> GMHintsResponse:
    # Determine which aspect is targeted and classify it
    is_trouble = False
    if target_type == "aspect":
        target_aspect = None
        for a in state.aspects:
            if a.id == target_id:
                target_aspect = a
                break
        if target_aspect is not None:
            name_norm = (target_aspect.name or "").strip().lower()
            is_trouble = name_norm == "trouble" or target_aspect.id == "aspect-trouble"

    raw_hints: list[Any] = list(getattr(raw_prediction, "hints", []) or [])

    def to_hint(obj: Any) -> GMHint | None:
        def _field(name: str) -> Any:
            if isinstance(obj, dict):
                return obj.get(name)
            return getattr(obj, name, None)

        t = (_field("type") or "").strip().lower()
        title = (_field("title") or "").strip() or "Hint"
        narrative = (_field("narrative") or "").strip()
        mechanics = (_field("mechanics") or "").strip()
        if not narrative or not mechanics:
            return None
        valid_types = {
            "invoke",
            "compel",
            "create_advantage",
            "player_invoke",
            "trigger",
            "edge_case",
            "synergy",
        }
        if t not in valid_types:
            aliases = {"ca": "create_advantage", "player": "player_invoke", "gm": "compel"}
            t = aliases.get(t, t)
            if t not in valid_types:
                t = "invoke" if target_type == "aspect" else "trigger"
        return GMHint(
            type=cast(
                Literal[
                    "invoke",
                    "compel",
                    "create_advantage",
                    "player_invoke",
                    "trigger",
                    "edge_case",
                    "synergy",
                ],
                t,
            ),
            title=title,
            narrative=narrative,
            mechanics=mechanics,
        )

    normalized = [h for h in (to_hint(h) for h in raw_hints) if h is not None]

    # Deduplicate by (type + narrative)
    uniq: list[GMHint] = []
    seen: set[str] = set()
    for h in normalized:
        key = f"{h.type}|{h.narrative.strip().lower()}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)

    # Enforce counts by target category
    final: list[GMHint] = []
    if target_type == "stunt":
        wants = ["trigger", "edge_case", "synergy"]
        for w in wants:
            cand = next((h for h in uniq if h.type == w), None)
            if cand is None:
                final.append(
                    GMHint(
                        type=cast(
                            Literal[
                                "invoke",
                                "compel",
                                "create_advantage",
                                "player_invoke",
                                "trigger",
                                "edge_case",
                                "synergy",
                            ],
                            w,
                        ),
                        title=w.replace("_", " ").title(),
                        narrative="Usage example.",
                        mechanics="Add a concrete Fate mechanic line.",
                    )
                )
            else:
                final.append(cand)
    else:
        # Aspect targets
        if is_trouble:
            # Trouble: only Compel and Player Invoke
            compel_cand = next((h for h in uniq if h.type == "compel"), None)
            if compel_cand is None:
                final.append(
                    GMHint(
                        type="compel",
                        title="Compel",
                        narrative="GM uses the Trouble against the PC.",
                        mechanics="Offer a fate point to introduce a complication tied to the Trouble.",
                    )
                )
            else:
                final.append(compel_cand)

            player_cand = next((h for h in uniq if h.type in ("player_invoke", "invoke")), None)
            if player_cand is None:
                final.append(
                    GMHint(
                        type="player_invoke",
                        title="Player Invoke",
                        narrative="Player leverages their Trouble in a clutch moment.",
                        mechanics="Spend a fate point to gain +2 or reroll.",
                    )
                )
            else:
                final.append(
                    GMHint(
                        type="player_invoke",
                        title=player_cand.title,
                        narrative=player_cand.narrative,
                        mechanics=player_cand.mechanics,
                    )
                )
        else:
            # High Concept and other aspects: only Player Invoke
            player_cand = next((h for h in uniq if h.type in ("player_invoke", "invoke")), None)
            if player_cand is None:
                final.append(
                    GMHint(
                        type="player_invoke",
                        title="Player Invoke",
                        narrative="Leverage this aspect to turn the situation to your favor.",
                        mechanics="Spend a fate point to gain +2 or reroll.",
                    )
                )
            else:
                final.append(
                    GMHint(
                        type="player_invoke",
                        title=player_cand.title,
                        narrative=player_cand.narrative,
                        mechanics=player_cand.mechanics,
                    )
                )

    return GMHintsResponse(hints=final, notes=getattr(raw_prediction, "notes", None) or None)



