from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config.settings import Settings
from app.dspy_modules import CharacterSkeletonModule, GmHintsModule, RemainingSuggestionsModule


@dataclass
class ServiceRegistry:
    skeleton: CharacterSkeletonModule
    remaining: RemainingSuggestionsModule
    gm_hints: GmHintsModule

    def close(self) -> None:
        # Placeholder for future resource cleanup
        return


def build_service_registry(settings: Settings) -> ServiceRegistry:
    skel = CharacterSkeletonModule()
    rem = RemainingSuggestionsModule()
    gm = GmHintsModule()

    # Load trained artifacts if paths provided in settings
    try:
        if settings.artifact_skeleton_path:
            skel.load(settings.artifact_skeleton_path)
    except Exception:
        pass
    try:
        if settings.artifact_remaining_path:
            rem.load(settings.artifact_remaining_path)
    except Exception:
        pass
    try:
        if settings.artifact_gm_hints_path:
            gm.load(settings.artifact_gm_hints_path)
    except Exception:
        pass

    return ServiceRegistry(skeleton=skel, remaining=rem, gm_hints=gm)



