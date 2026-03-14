"""Generate Quarto website source files from data products."""

import csv
import json
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
        f"## Current release: v{version}",
        "",
    ]

    # Archives
    if zip_file.exists() and tar_file.exists():
        lines.append("### Complete archives")
        lines.append("")
        lines.append("Download all data files and codebook in a single archive:")
        lines.append("")
        lines.append(f"- [{zip_file.name}]({base}/{zip_file.name})")
        lines.append(f"- [{tar_file.name}]({base}/{tar_file.name})")
        lines.append("")

    # Codebook
    lines.append("### Codebook")
    lines.append("")
    if codebook_pdf.exists():
        lines.append(f"- [{codebook_pdf.name}]({base}/{codebook_pdf.name}) (PDF)")
    if codebook_md.exists():
        lines.append(f"- [{codebook_md.name}]({base}/{codebook_md.name}) (Markdown)")
    lines.append("")

    # Data files by type
    lines.append("### Range datasets")
    lines.append("")
    lines.append("One row per country--date range with constant diplomatic status.")
    lines.append("")
    for f in range_files:
        label = _system_label(f.name)
        lines.append(f"- [{f.name}]({base}/{f.name}) ({label})")
    lines.append("")

    lines.append("### Monthly datasets")
    lines.append("")
    lines.append("One row per country--month with min/max/median/mode aggregation.")
    lines.append("")
    for f in monthly_files:
        label = _system_label(f.name)
        lines.append(f"- [{f.name}]({base}/{f.name}) ({label})")
    lines.append("")

    lines.append("### Yearly datasets")
    lines.append("")
    lines.append("One row per country--year with min/max/median/mode aggregation.")
    lines.append("")
    for f in yearly_files:
        label = _system_label(f.name)
        lines.append(f"- [{f.name}]({base}/{f.name}) ({label})")
    lines.append("")

    # Archive section placeholder
    lines.append("## Previous releases")
    lines.append("")
    lines.append("No previous releases.")
    lines.append("")

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


def _generate_explorer_data(data_dir: Path, version: str) -> None:
    """Generate web/explorer/data.json from range CSVs."""
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

    explorer_dir = WEB_DIR / "explorer"
    explorer_dir.mkdir(parents=True, exist_ok=True)
    (explorer_dir / "data.json").write_text(json.dumps(result, separators=(",", ":")))


def generate_web_sources(data_dir: Path, version: str) -> None:
    """Generate all web source files from data products."""
    _generate_download_page(data_dir, version)
    _generate_explorer_data(data_dir, version)
