"""Assemble and render the codebook from source fragments."""

from __future__ import annotations

import csv
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state_codes import StateCodeResolver

CODEBOOK_DIR = Path(__file__).parent / "codebook"


def _generate_mapping_gaps_section(
    resolver: StateCodeResolver, transitions_csv: Path,
) -> str:
    """Generate a codebook section documenting state system ↔ USDOS mapping gaps."""
    # Gather USDOS names from transitions CSV
    with open(transitions_csv, newline="") as f:
        usdos_names = {row["state_dept_name"].strip() for row in csv.DictReader(f)}

    lines: list[str] = ["# Mapping gaps", ""]

    # --- Direction 1: state system codes with no USDOS mapping ---
    lines.append(
        "The following state system member codes have no corresponding entry in "
        "the USDOS diplomatic history. In the data, these entities have an empty "
        "`country_name_usdos` value and `us_mission_status` is set to \"None\" "
        "for all dates."
    )
    lines.append("")

    for label, mapping, raw in [
        ("COW", resolver._cow_mapping, resolver._cow),
        ("GW", resolver._gw_mapping, resolver._gw_base),
        ("GWM", resolver._gw_mapping, resolver._gw_full),
    ]:
        unmapped = [
            (code, iv)
            for code in raw
            if code != "USA" and code not in mapping
            for iv in raw[code]
        ]
        unmapped.sort(key=lambda x: (x[1].number, x[1].start))
        if not unmapped:
            continue
        lines.append(f"## {label}")
        lines.append("")
        lines.append("| Code | Number | Name | Membership |")
        lines.append("|------|-------:|------|------------|")
        for code, iv in unmapped:
            lines.append(
                f"| {code} | {iv.number} | {iv.name} "
                f"| {iv.start.year}--{iv.end.year} |"
            )
        lines.append("")

    # --- Direction 2: USDOS names with no state system code ---
    lines.append(
        "The following entities appear in the USDOS diplomatic records but do "
        "not correspond to any code in the given state system. They are included "
        "in the hand-coded transitions data but excluded from the corresponding "
        "panel datasets."
    )
    lines.append("")

    for label, name_index in [
        ("COW", resolver._cow_name_index),
        ("GW / GWM", resolver._gw_name_index),
    ]:
        unmatched = sorted(n for n in usdos_names if n not in name_index)
        if unmatched:
            lines.append(f"**{label}**: {', '.join(unmatched)}.")
            lines.append("")

    return "\n".join(lines)


def build_codebook(
    version: str,
    output_dir: Path,
    release_date: str | None = None,
    resolver: StateCodeResolver | None = None,
    transitions_csv: Path | None = None,
) -> tuple[Path, Path]:
    """Assemble codebook Markdown from fragments and render to PDF.

    Returns (md_path, pdf_path).
    """
    # Collect fragments: _header.md first, then numbered files in order
    fragments = []
    header = CODEBOOK_DIR / "_header.md"
    if header.exists():
        fragments.append(header)
    for p in sorted(CODEBOOK_DIR.glob("[0-9]*.md")):
        fragments.append(p)

    # Assemble and substitute version/date
    codebook_date = release_date if release_date is not None else date.today().isoformat()
    parts = []
    for frag in fragments:
        text = frag.read_text()
        text = text.replace("{{VERSION}}", version)
        text = text.replace("{{DATE}}", codebook_date)
        parts.append(text)

    # Insert procedurally generated mapping gaps section before acknowledgments
    if resolver is not None and transitions_csv is not None:
        gaps_md = _generate_mapping_gaps_section(resolver, transitions_csv)
        # Insert before the last part (acknowledgments)
        parts.insert(-1, gaps_md)

    assembled = "\n\n".join(parts)

    # Write assembled Markdown
    md_name = f"CODEBOOK_us_mission_status_v{version}.md"
    pdf_name = f"CODEBOOK_us_mission_status_v{version}.pdf"
    md_path = output_dir / md_name
    pdf_path = output_dir / pdf_name

    output_dir.mkdir(parents=True, exist_ok=True)
    md_path.write_text(assembled)

    # Render PDF via pandoc
    if shutil.which("pandoc") is None:
        raise RuntimeError(
            "pandoc is required to render the codebook PDF but was not found on PATH. "
            "Install it from https://pandoc.org/installing.html and ensure a LaTeX "
            "distribution with XeLaTeX is also installed (e.g., TeX Live)."
        )
    subprocess.run(
        ["pandoc", str(md_path), "-o", str(pdf_path), "--pdf-engine=xelatex", "--number-sections", "--toc"],
        check=True,
    )

    return md_path, pdf_path
