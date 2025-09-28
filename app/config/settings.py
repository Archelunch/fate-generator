import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field


def _env_or_default(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default) if default is not None else os.environ.get(key)


def _env_chain(*keys: str) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return None


class Settings(BaseModel):
    app_name: str = Field(default_factory=lambda: _env_or_default("APP_NAME", "Fate Generator") or "Fate Generator")
    environment: str = Field(default_factory=lambda: _env_or_default("ENV", "dev") or "dev")
    static_dir: str | None = None
    templates_dir: str | None = None
    log_level: str = Field(default_factory=lambda: _env_or_default("LOG_LEVEL", "INFO") or "INFO")
    # Artifacts
    artifact_skeleton_path: str | None = None
    artifact_remaining_path: str | None = None
    artifact_gm_hints_path: str | None = None
    # DSPy / LLM configuration
    dspy_model: str = Field(
        default_factory=lambda: _env_or_default("DSPY_MODEL", "gemini/gemini-2.5-flash-lite")
        or "gemini/gemini-2.5-flash-lite"
    )
    dspy_reflection_model: str = Field(
        default_factory=lambda: _env_or_default("DSPY_REFLECTION_MODEL", "gemini/gemini-2.5-pro")
        or "gemini/gemini-2.5-pro"
    )
    dspy_api_key: str | None = Field(
        default_factory=lambda: _env_chain("DSPY_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
    )
    dspy_temperature: float = Field(
        default_factory=lambda: float(os.environ.get("DSPY_TEMPERATURE", "0.7")), ge=0.0, le=2.0
    )
    dspy_max_tokens: int = Field(default_factory=lambda: int(os.environ.get("DSPY_MAX_TOKENS", "20000")), gt=0)
    dspy_cache: bool = os.environ.get("DSPY_CACHE", "true").lower() in ("1", "true", "yes", "on")

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def artifacts_dir(self) -> Path:
        return self.project_root / "artifacts"

    @property
    def datasets_dir(self) -> Path:
        return self.project_root / "datasets"

    def resolve_path(self, value: str | os.PathLike[str] | None, *, fallback: Path | None = None) -> Path | None:
        if value is None:
            return fallback
        path = Path(value)
        if not path.is_absolute():
            path = self.project_root / path
        return path

    def resolve_paths(self, values: Iterable[str | os.PathLike[str]] | None) -> list[Path]:
        if not values:
            return []
        return [self.resolve_path(v) for v in values if v is not None]

    def dataset_path(self, filename: str) -> Path:
        return self.datasets_dir / filename

    @property
    def resolved_static_dir(self) -> Path | None:
        return self.resolve_path(self.static_dir)

    @property
    def resolved_templates_dir(self) -> Path | None:
        return self.resolve_path(self.templates_dir)

    @property
    def resolved_artifact_skeleton_path(self) -> Path | None:
        fallback = self.artifacts_dir / "gepa_character_skeleton.json"
        return self.resolve_path(self.artifact_skeleton_path, fallback=fallback)

    @property
    def resolved_artifact_remaining_path(self) -> Path | None:
        fallback = self.artifacts_dir / "gepa_remaining.json"
        return self.resolve_path(self.artifact_remaining_path, fallback=fallback)

    @property
    def resolved_artifact_gm_hints_path(self) -> Path | None:
        fallback = self.artifacts_dir / "gepa_gm_hints.json"
        return self.resolve_path(self.artifact_gm_hints_path, fallback=fallback)


def _load_yaml_config() -> dict[str, Any]:
    # Config discovery: env CONFIG_PATH > ./config/app.yaml > ./app/config/app.yaml
    candidates: list[Path] = []
    env_path = os.environ.get("CONFIG_PATH")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path("config/app.yaml").absolute())
    candidates.append(Path(__file__).resolve().parent / "app.yaml")

    for path in candidates:
        try:
            # Lazy import yaml to avoid optional dependency issues in type checking
            if path.exists():
                try:
                    import yaml as _yaml  # type: ignore
                except Exception:  # pragma: no cover
                    continue
                with path.open("r", encoding="utf-8") as f:
                    data = _yaml.safe_load(f) or {}
                    if isinstance(data, dict):
                        return data
        except Exception:
            continue
    return {}


@lru_cache
def get_settings() -> Settings:
    cfg = _load_yaml_config()
    # Environment variables remain the ultimate override via default factories above
    return Settings(**cfg)
