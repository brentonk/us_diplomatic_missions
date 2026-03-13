"""Load and validate pipeline configuration from extraction_config.yaml."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ModelsConfig:
    extraction: str = "claude-sonnet-4-6"
    reconciliation: str = "claude-opus-4-6"


@dataclass
class ApiConfig:
    temperature: float = 0
    max_tokens_extraction: int = 4096
    max_tokens_reconciliation: int = 8192
    concurrency_extraction: int = 5
    concurrency_reconciliation: int = 3
    skip_existing: bool = True


@dataclass
class VerificationConfig:
    quote_match_threshold: float = 0.85


@dataclass
class PathsConfig:
    rdcr_articles: Path = field(default_factory=lambda: Path("./rdcr/articles"))
    pocom_missions: Path = field(default_factory=lambda: Path("./pocom/missions-countries"))
    pocom_roles: Path = field(default_factory=lambda: Path("./pocom/roles-country-chiefs"))
    transitions_csv: Path = field(default_factory=lambda: Path("./input/2024-01-16_transitions.csv"))
    country_aliases: Path = field(default_factory=lambda: Path("./input/country_aliases.yaml"))
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    log_dir: Path = field(default_factory=lambda: Path("./logs"))
    prompt_extract: Path = field(default_factory=lambda: Path("./input/prompt_extract.txt"))
    prompt_reconcile: Path = field(default_factory=lambda: Path("./input/prompt_reconcile.txt"))


@dataclass
class PipelineConfig:
    models: ModelsConfig = field(default_factory=ModelsConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    verification: VerificationConfig = field(default_factory=VerificationConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    repo_root: Path = field(default_factory=lambda: Path("."))


def load_config(config_path: str | Path, repo_root: str | Path | None = None) -> PipelineConfig:
    """Load pipeline configuration from a YAML file.

    Relative paths in the config are resolved against repo_root.
    """
    config_path = Path(config_path)
    if repo_root is None:
        repo_root = config_path.parent.parent
    repo_root = Path(repo_root).resolve()

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    models = ModelsConfig(**raw.get("models", {}))
    api = ApiConfig(**raw.get("api", {}))
    verification = VerificationConfig(**raw.get("verification", {}))

    paths_raw = raw.get("paths", {})
    paths_resolved = {}
    for key, val in paths_raw.items():
        p = Path(val)
        if not p.is_absolute():
            p = repo_root / p
        paths_resolved[key] = p.resolve()
    paths = PathsConfig(**paths_resolved)

    return PipelineConfig(
        models=models,
        api=api,
        verification=verification,
        paths=paths,
        repo_root=repo_root,
    )
