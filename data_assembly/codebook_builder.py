"""Assemble and render the codebook from source fragments."""

import subprocess
from datetime import date
from pathlib import Path


CODEBOOK_DIR = Path(__file__).parent / "codebook"


def build_codebook(version: str, output_dir: Path, release_date: str | None = None) -> tuple[Path, Path]:
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
    assembled = "\n\n".join(parts)

    # Write assembled Markdown
    md_name = f"CODEBOOK_us_mission_status_v{version}.md"
    pdf_name = f"CODEBOOK_us_mission_status_v{version}.pdf"
    md_path = output_dir / md_name
    pdf_path = output_dir / pdf_name

    output_dir.mkdir(parents=True, exist_ok=True)
    md_path.write_text(assembled)

    # Render PDF via pandoc
    subprocess.run(
        ["pandoc", str(md_path), "-o", str(pdf_path), "--pdf-engine=xelatex", "--number-sections", "--toc"],
        check=True,
    )

    return md_path, pdf_path
