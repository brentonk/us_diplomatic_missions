"""Stage 0: Country Name Resolution.

Maps CSV country names to source repo filenames (rdcr and pocom)
using normalization, alias lookup, and pattern matching.
"""

import json
import re
from pathlib import Path

import pandas as pd
import yaml

from .config import PipelineConfig
from .models import CountryMapping
from .text_utils import normalize_country_name


def _list_xml_stems(directory: Path) -> dict[str, str]:
    """List XML files in a directory and return {normalized_stem: original_stem}."""
    stems = {}
    if not directory.exists():
        return stems
    for f in directory.glob("*.xml"):
        stem = f.stem
        normalized = normalize_country_name(stem.replace("-", " "))
        stems[normalized] = stem
    return stems


def _load_aliases(aliases_path: Path) -> dict[str, str | dict]:
    """Load country_aliases.yaml. Values can be strings or dicts with rdcr/pocom keys."""
    if not aliases_path.exists():
        return {}
    with open(aliases_path) as f:
        data = yaml.safe_load(f) or {}
    return data


def _try_match(csv_name: str, stems: dict[str, str], aliases: dict[str, str | dict], repo_key: str) -> str | None:
    """Try to match a CSV country name to a repo stem.

    Returns the original stem (not normalized) if matched, else None.
    """
    # 1. Check aliases first
    if csv_name in aliases:
        alias_val = aliases[csv_name]
        if isinstance(alias_val, dict):
            target = alias_val.get(repo_key)
        else:
            target = alias_val
        if target is not None:
            # Verify the aliased stem actually exists
            norm_target = normalize_country_name(target.replace("-", " "))
            if norm_target in stems:
                return stems[norm_target]
            # Try exact match on the target as-is
            if target in [s for s in stems.values()]:
                return target

    # 2. Normalize CSV name and try exact match
    norm_csv = normalize_country_name(csv_name)
    if norm_csv in stems:
        return stems[norm_csv]

    # 3. Handle "X, The" pattern: strip trailing ", The"
    if ", the" in norm_csv.lower() or norm_csv.endswith(", the"):
        stripped = re.sub(r",\s*the$", "", norm_csv, flags=re.IGNORECASE).strip()
        if stripped in stems:
            return stems[stripped]

    # 4. Handle parenthetical suffixes: try name-before-parenthesis
    if "(" in csv_name:
        before_paren = csv_name[:csv_name.index("(")].strip()
        norm_before = normalize_country_name(before_paren)
        if norm_before in stems:
            return stems[norm_before]

    # 5. Replace spaces with hyphens for slug matching
    slug = re.sub(r"\s+", "-", norm_csv)
    slug_normalized = normalize_country_name(slug.replace("-", " "))
    if slug_normalized in stems:
        return stems[slug_normalized]

    return None


def resolve_countries(config: PipelineConfig) -> dict[str, CountryMapping]:
    """Resolve CSV country names to source file paths.

    Returns a dict mapping CSV country names to CountryMapping objects.
    """
    # Read unique country names from CSV
    df = pd.read_csv(config.paths.transitions_csv)
    csv_names = sorted(df["state_dept_name"].unique())

    # List available XML stems
    rdcr_stems = _list_xml_stems(config.paths.rdcr_articles)
    pocom_stems = _list_xml_stems(config.paths.pocom_missions)

    # Load aliases
    aliases = _load_aliases(config.paths.country_aliases)

    mappings: dict[str, CountryMapping] = {}
    unresolved: list[str] = []

    for name in csv_names:
        rdcr_match = _try_match(name, rdcr_stems, aliases, "rdcr")
        pocom_match = _try_match(name, pocom_stems, aliases, "pocom")

        rdcr_path = f"rdcr/articles/{rdcr_match}.xml" if rdcr_match else None
        pocom_path = f"pocom/missions-countries/{pocom_match}.xml" if pocom_match else None

        if rdcr_path is None and pocom_path is None:
            unresolved.append(name)

        mappings[name] = CountryMapping(
            csv_name=name,
            rdcr_path=rdcr_path,
            pocom_path=pocom_path,
        )

    return mappings


def run_stage0(config: PipelineConfig) -> None:
    """Run Stage 0 and write output files."""
    mappings = resolve_countries(config)

    # Build output JSON
    output = {}
    for name, mapping in sorted(mappings.items()):
        output[name] = mapping.to_dict()

    # Write mapping file
    output_dir = config.paths.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "country_mapping.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    # Print resolution report
    resolved_both = []
    rdcr_only = []
    pocom_only = []
    unresolved = []

    for name, mapping in sorted(mappings.items()):
        if mapping.rdcr_path and mapping.pocom_path:
            resolved_both.append(name)
        elif mapping.rdcr_path:
            rdcr_only.append(name)
        elif mapping.pocom_path:
            pocom_only.append(name)
        else:
            unresolved.append(name)

    total = len(mappings)
    print(f"Stage 0: Country Name Resolution")
    print(f"  Total CSV countries: {total}")
    print(f"  Resolved (both repos): {len(resolved_both)}")
    print(f"  RDCR only: {len(rdcr_only)}")
    print(f"  POCOM only: {len(pocom_only)}")
    print(f"  Unresolved: {len(unresolved)}")

    if rdcr_only:
        print(f"\n  RDCR only:")
        for name in rdcr_only:
            print(f"    - {name}")

    if pocom_only:
        print(f"\n  POCOM only:")
        for name in pocom_only:
            print(f"    - {name}")

    if unresolved:
        print(f"\n  UNRESOLVED (add to country_aliases.yaml):")
        for name in unresolved:
            print(f"    - {name}")

    print(f"\n  Output: {output_path}")
