"""Parsers for rdcr TEI XML and pocom mission XML files."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI_PREFIX = f"{{{TEI_NS}}}"

# Cache for resolved role titles
_role_cache: dict[str, str] = {}


def _tei(tag: str) -> str:
    """Return a TEI-namespaced tag name."""
    return f"{TEI_PREFIX}{tag}"


def _extract_text(elem: ET.Element) -> str:
    """Recursively extract all text from an element, collapsing inline elements."""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        tag = child.tag.replace(TEI_PREFIX, "") if isinstance(child.tag, str) else ""
        # Skip figures, graphics, bibliography
        if tag in ("figure", "graphic", "listBibl"):
            if child.tail:
                parts.append(child.tail)
            continue
        # Inline elements: just grab their text content
        parts.append(_extract_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def parse_rdcr_tei(filepath: str | Path) -> str:
    """Parse a TEI XML file from rdcr/articles/ and return plain text prose.

    Strips XML tags, collapses inline elements to text, preserves paragraph breaks.
    Skips <figure>, <graphic>, <listBibl> elements. Renders <head> as section headers.
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    body = root.find(f".//{_tei('body')}")
    if body is None:
        return ""

    output_parts: list[str] = []

    def _process_div(div: ET.Element) -> None:
        div_type = div.get("type", "")
        # Skip appendix/resources sections
        if div_type == "appendix":
            return

        for child in div:
            tag = child.tag.replace(TEI_PREFIX, "") if isinstance(child.tag, str) else ""

            if tag == "head":
                head_text = _extract_text(child).strip()
                if head_text:
                    output_parts.append(f"## {head_text}")
                    output_parts.append("")

            elif tag == "p":
                para_text = _extract_text(child).strip()
                # Collapse internal whitespace (from XML formatting)
                para_text = re.sub(r"\s+", " ", para_text)
                if para_text:
                    output_parts.append(para_text)
                    output_parts.append("")

            elif tag == "div":
                _process_div(child)

            elif tag in ("figure", "graphic", "listBibl"):
                continue

    for child in body:
        tag = child.tag.replace(TEI_PREFIX, "") if isinstance(child.tag, str) else ""
        if tag == "div":
            _process_div(child)

    # Clean up trailing blank lines
    text = "\n".join(output_parts).rstrip()
    return text


def _resolve_role_title(role_id: str, roles_dir: str | Path) -> str:
    """Look up a role ID in the roles-country-chiefs directory and return the singular display name."""
    if role_id in _role_cache:
        return _role_cache[role_id]

    role_file = Path(roles_dir) / f"{role_id}.xml"
    if not role_file.exists():
        _role_cache[role_id] = role_id.replace("-", " ").title()
        return _role_cache[role_id]

    tree = ET.parse(role_file)
    root = tree.getroot()
    singular = root.find(".//singular")
    if singular is not None and singular.text:
        title = singular.text.strip()
    else:
        title = role_id.replace("-", " ").title()

    _role_cache[role_id] = title
    return title


def _humanize_person_id(person_id: str) -> str:
    """Convert a person slug like 'hornibrook-william-harrison' to 'William Harrison Hornibrook'."""
    parts = person_id.split("-")
    if len(parts) < 2:
        return person_id.replace("-", " ").title()
    # Last name is the first part, remaining parts are given names
    last_name = parts[0].title()
    given_names = [p.title() for p in parts[1:]]
    return " ".join(given_names) + " " + last_name


def _get_element_text(parent: ET.Element, tag: str) -> str:
    """Get the text of a child element, or empty string if missing/empty."""
    elem = parent.find(tag)
    if elem is not None:
        # Check for a <date> sub-element first
        date_elem = elem.find("date")
        if date_elem is not None and date_elem.text:
            return date_elem.text.strip()
        # Check for a <text> sub-element
        text_elem = elem.find("text")
        if text_elem is not None and text_elem.text:
            return text_elem.text.strip()
        # Fall back to the element's own text
        if elem.text:
            return elem.text.strip()
    return ""


def _get_date_and_note(parent: ET.Element, tag: str) -> tuple[str, str]:
    """Get date text and note text from a date container element (appointed, started, ended, etc.)."""
    elem = parent.find(tag)
    if elem is None:
        return "", ""
    date_elem = elem.find("date")
    note_elem = elem.find("note")
    date_text = date_elem.text.strip() if date_elem is not None and date_elem.text else ""
    note_text = note_elem.text.strip() if note_elem is not None and note_elem.text else ""
    return date_text, note_text


def parse_pocom_missions(filepath: str | Path, roles_dir: str | Path) -> str:
    """Parse a pocom missions-countries XML file and return readable text.

    Each chief-of-mission record becomes a readable block. Mission notes are rendered inline.
    Role IDs are resolved to display names via the roles-country-chiefs directory.
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    chiefs_elem = root.find("chiefs")
    if chiefs_elem is None:
        return ""

    output_parts: list[str] = []
    territory_id = root.find("territory-id")
    if territory_id is not None and territory_id.text:
        output_parts.append(f"## Chiefs of Mission: {territory_id.text.strip().replace('-', ' ').title()}")
        output_parts.append("")

    for child in chiefs_elem:
        if child.tag == "chief":
            person_id = _get_element_text(child, "person-id")
            role_id = _get_element_text(child, "role-title-id")
            role_title = _resolve_role_title(role_id, roles_dir) if role_id else "Unknown Role"
            person_name = _humanize_person_id(person_id) if person_id else "Unknown"

            appointed_date, _ = _get_date_and_note(child, "appointed")
            started_date, _ = _get_date_and_note(child, "started")
            ended_date, ended_note = _get_date_and_note(child, "ended")

            # Build the chief record line
            parts = [f"{person_name}, {role_title}."]
            if appointed_date:
                parts.append(f"Appointed: {appointed_date}.")
            if started_date:
                parts.append(f"Credentials presented: {started_date}.")
            if ended_date:
                if ended_note:
                    parts.append(f"{ended_note} {ended_date}.")
                else:
                    parts.append(f"Left post: {ended_date}.")

            # Include the chief's own <note> if present
            note_elem = child.find("note")
            if note_elem is not None and note_elem.text and note_elem.text.strip():
                note_text = re.sub(r"\s+", " ", note_elem.text.strip())
                parts.append(f"Note: {note_text}")

            output_parts.append(" ".join(parts))
            output_parts.append("")

        elif child.tag == "mission-note":
            text_elem = child.find("text")
            if text_elem is not None and text_elem.text:
                note_text = re.sub(r"\s+", " ", text_elem.text.strip())
                output_parts.append(f"[Mission Note] {note_text}")
                output_parts.append("")

    text = "\n".join(output_parts).rstrip()
    return text
