"""Generate Quarto website source files from data products."""

import csv
import json
import re
from pathlib import Path

REPO_URL = "https://raw.githubusercontent.com/brentonk/us_diplomatic_missions/main"
WEB_DIR = Path(__file__).resolve().parents[1] / "web"


def _generate_download_page(data_dir: Path, version: str) -> None:
    """Generate web/download.qmd with versioned download links."""
    base = f"{REPO_URL}/data/v{version}"

    range_files = sorted(data_dir.glob(f"mission_status_range_*_v{version}.csv"))
    monthly_files = sorted(data_dir.glob(f"mission_status_monthly_*_v{version}.csv"))
    yearly_files = sorted(data_dir.glob(f"mission_status_yearly_*_v{version}.csv"))
    codebook_md = data_dir / f"CODEBOOK_us_mission_status_v{version}.md"
    codebook_pdf = data_dir / f"CODEBOOK_us_mission_status_v{version}.pdf"
    zip_file = data_dir / f"us_mission_status_v{version}.zip"
    tar_file = data_dir / f"us_mission_status_v{version}.tar.gz"

    lines = [
        "---",
        'title: "Download"',
        "---",
        "",
        f"Current release: **v{version}**",
        "",
    ]

    # Archives
    if zip_file.exists() and tar_file.exists():
        lines.extend([
            "::: {.download-section}",
            "### Complete Archives",
            "",
            "Download all data files and codebook in a single archive.",
            "",
            f"- [`{zip_file.name}`]({base}/{zip_file.name}) (ZIP)",
            f"- [`{tar_file.name}`]({base}/{tar_file.name}) (TAR.GZ)",
            "",
            ":::",
            "",
        ])

    # Codebook
    lines.extend([
        "::: {.download-section}",
        "### Codebook",
        "",
    ])
    if codebook_pdf.exists():
        lines.append(f"- [`{codebook_pdf.name}`]({base}/{codebook_pdf.name}) (PDF)")
    if codebook_md.exists():
        lines.append(f"- [`{codebook_md.name}`]({base}/{codebook_md.name}) (Markdown)")
    lines.extend(["", ":::", ""])

    # Range datasets
    lines.extend([
        "::: {.download-section}",
        "### Range Datasets",
        "",
        "One row per country--date range with constant diplomatic status.",
        "",
    ])
    for f in range_files:
        label = _system_label(f.name)
        lines.append(f"- [`{f.name}`]({base}/{f.name}) ({label})")
    lines.extend(["", ":::", ""])

    # Monthly datasets
    lines.extend([
        "::: {.download-section}",
        "### Monthly Datasets",
        "",
        "One row per country--month with min/max/median/mode aggregation.",
        "",
    ])
    for f in monthly_files:
        label = _system_label(f.name)
        lines.append(f"- [`{f.name}`]({base}/{f.name}) ({label})")
    lines.extend(["", ":::", ""])

    # Yearly datasets
    lines.extend([
        "::: {.download-section}",
        "### Yearly Datasets",
        "",
        "One row per country--year with min/max/median/mode aggregation.",
        "",
    ])
    for f in yearly_files:
        label = _system_label(f.name)
        lines.append(f"- [`{f.name}`]({base}/{f.name}) ({label})")
    lines.extend(["", ":::", ""])

    # Previous releases
    lines.extend([
        "## Previous Releases",
        "",
        "No previous releases.",
        "",
    ])

    (WEB_DIR / "download.qmd").write_text("\n".join(lines))


def _system_label(filename: str) -> str:
    """Extract human-readable system label from filename."""
    if "_gwm_" in filename:
        return "GW + microstates"
    if "_gw_" in filename:
        return "Gleditsch-Ward"
    if "_cow_" in filename:
        return "Correlates of War"
    return ""


def _build_explorer_data(data_dir: Path, version: str) -> str:
    """Build explorer JSON string from range CSVs."""
    result: dict[str, dict] = {}

    for system in ("cow", "gw"):
        suffix = "_cow" if system == "cow" else "_gw"
        # Use gwm for the gw explorer view so microstates are included
        filename = f"mission_status_range_{'gwm' if system == 'gw' else system}_v{version}.csv"
        csv_path = data_dir / filename
        if not csv_path.exists():
            continue

        countries: dict[str, dict] = {}
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                abbrev = row[f"country_abbrev{suffix}"]
                if abbrev not in countries:
                    countries[abbrev] = {
                        "code": int(row[f"country_code{suffix}"]),
                        "name": row[f"country_name{suffix}"],
                        "ranges": [],
                    }
                countries[abbrev]["ranges"].append({
                    "start": row["date_start"],
                    "end": row["date_end"],
                    "status": row["us_mission_status"],
                    "usdos": row["country_name_usdos"],
                })

        result[system] = countries

    return json.dumps(result, separators=(",", ":"))


def _generate_explorer_page(data_dir: Path, version: str) -> None:
    """Generate web/explorer/index.qmd with inlined data."""
    explorer_json = _build_explorer_data(data_dir, version)

    template_path = WEB_DIR / "explorer" / "_template.qmd"
    template = template_path.read_text()
    output = template.replace("/* __EXPLORER_DATA__ */null", explorer_json)

    (WEB_DIR / "explorer" / "index.qmd").write_text(output)


def _generate_codebook_page(data_dir: Path, version: str) -> None:
    """Generate web/codebook.qmd from the codebook Markdown source."""
    codebook_md = data_dir / f"CODEBOOK_us_mission_status_v{version}.md"
    if not codebook_md.exists():
        return

    content = codebook_md.read_text()

    # Strip the pandoc YAML frontmatter and replace with Quarto frontmatter
    content = re.sub(
        r"\A---\n.*?\n---\n*",
        "",
        content,
        count=1,
        flags=re.DOTALL,
    )

    lines = [
        "---",
        f'title: "Codebook (v{version})"',
        "number-sections: true",
        "---",
        "",
        content,
    ]

    (WEB_DIR / "codebook.qmd").write_text("\n".join(lines))


def generate_web_sources(data_dir: Path, version: str) -> None:
    """Generate all web source files from data products."""
    _generate_download_page(data_dir, version)
    _generate_explorer_page(data_dir, version)
    _generate_codebook_page(data_dir, version)
