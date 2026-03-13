"""Text normalization, line numbering, and fuzzy matching utilities."""

import difflib
import re

from unidecode import unidecode


def normalize_country_name(name: str) -> str:
    """Normalize a country name for matching.

    Lowercase, transliterate diacritics, strip punctuation, collapse whitespace.
    """
    name = unidecode(name)
    name = name.lower()
    name = re.sub(r"[''`]", "", name)
    name = re.sub(r"[^\w\s-]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def name_to_slug(name: str) -> str:
    """Convert a country name to a filename slug (hyphens for spaces)."""
    normalized = normalize_country_name(name)
    return re.sub(r"\s+", "-", normalized)


def number_lines(text: str, source_file: str = "", repo_commit: str = "") -> tuple[str, list[str], dict[int, int]]:
    """Prepend [N] to each line. Return (numbered_text, original_lines, line_to_byte_offset).

    line_to_byte_offset maps 1-indexed line numbers to byte offsets in the original text.
    """
    lines = text.split("\n")
    numbered_parts = []
    line_to_offset = {}
    byte_pos = 0

    for i, line in enumerate(lines):
        line_num = i + 1
        line_to_offset[line_num] = byte_pos
        numbered_parts.append(f"[{line_num}] {line}")
        byte_pos += len(line.encode("utf-8")) + 1  # +1 for newline

    numbered_text = "\n".join(numbered_parts)
    return numbered_text, lines, line_to_offset


def fuzzy_match(claimed_quote: str, actual_text: str) -> float:
    """Compute fuzzy match ratio between a claimed quote and actual source text.

    Uses the best matching substring when the actual text is significantly longer
    than the claimed quote, since LLMs often quote a portion of a long line.

    Returns a float between 0.0 and 1.0.
    """
    claimed = re.sub(r"\s+", " ", claimed_quote.strip())
    actual = re.sub(r"\s+", " ", actual_text.strip())

    # Exact substring match is always a pass
    if claimed in actual:
        return 1.0

    full_ratio = difflib.SequenceMatcher(None, claimed, actual).ratio()

    # If actual text is much longer, find the best matching substring
    if len(actual) > len(claimed) * 1.5 and len(claimed) > 20:
        matcher = difflib.SequenceMatcher(None, claimed, actual)
        blocks = matcher.get_matching_blocks()
        matching_blocks = [b for b in blocks if b.size > 0]
        if matching_blocks:
            best_start = min(b.b for b in matching_blocks)
            best_end = max(b.b + b.size for b in matching_blocks)
            window = len(claimed)
            center = (best_start + best_end) // 2
            sub_start = max(0, center - window // 2)
            sub_end = min(len(actual), sub_start + window + window // 4)
            sub_start = max(0, sub_end - window - window // 4)
            substring = actual[sub_start:sub_end]
            sub_ratio = difflib.SequenceMatcher(None, claimed, substring).ratio()
            return max(full_ratio, sub_ratio)

    return full_ratio


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~1 token per 4 characters."""
    return len(text) // 4


def country_slug(name: str) -> str:
    """Convert a country name to a filesystem-safe slug."""
    slug = name.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug).strip("-")
    return slug
