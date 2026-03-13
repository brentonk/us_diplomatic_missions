"""Pydantic models for pipeline work units, events, and metadata."""

from pydantic import BaseModel, field_validator


class CsvEvent(BaseModel):
    """A single row from the transitions CSV."""
    state_dept_name: str
    status_change: str
    year: int | None = None
    month: int | None = None
    day: int | None = None
    last_verified: str = ""
    notes: str = ""
    row_index: int  # 1-indexed position within this country's events

    def date_str(self) -> str:
        """Return ISO 8601 date or partial date."""
        if self.year is None:
            return ""
        parts = [f"{self.year:04d}"]
        if self.month is not None:
            parts.append(f"{self.month:02d}")
            if self.day is not None:
                parts.append(f"{self.day:02d}")
        return "-".join(parts)


class CountryMapping(BaseModel):
    """Mapping from a CSV country name to source file paths."""
    csv_name: str
    rdcr_path: str | None = None
    pocom_path: str | None = None

    def to_mapping_dict(self) -> dict:
        """Serialize for the country_mapping.json output format."""
        return {"rdcr": self.rdcr_path, "pocom": self.pocom_path}


class NumberedText(BaseModel):
    """Source text with line numbers prepended."""
    text: str
    lines: list[str]
    line_to_byte_offset: dict[int, int]
    source_file: str
    repo_commit: str

    @field_validator("line_to_byte_offset", mode="before")
    @classmethod
    def _coerce_offset_keys(cls, v: dict) -> dict[int, int]:
        """JSON round-trips dict keys as strings; coerce back to int."""
        return {int(k): v for k, v in v.items()}


class WorkUnit(BaseModel):
    """All data needed to process one country."""
    country: str
    csv_events: list[CsvEvent]
    rdcr_text: NumberedText | None = None
    pocom_text: NumberedText | None = None
    token_estimates: dict[str, int] = {}
    flagged_large: bool = False


class ExtractedEvent(BaseModel):
    """A single event extracted by the LLM in Stage 2."""
    date: str
    new_status: str
    event_description: str
    confidence: str
    evidence: list[dict] = []


class ApiMetadata(BaseModel):
    """Metadata from an Anthropic API response."""
    message_id: str
    model: str
    usage: dict
    stop_reason: str


# Valid status values for the new_status field
VALID_STATUSES = [
    "Embassy",
    "Ambassador Nonresident",
    "Legation",
    "Envoy Nonresident",
    "Consulate",
    "Consul Nonresident",
    "Liaison",
    "Interests",
    "None",
]
