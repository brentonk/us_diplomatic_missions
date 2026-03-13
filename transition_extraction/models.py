"""Dataclasses for pipeline work units, events, and metadata."""

from dataclasses import dataclass, field


@dataclass
class CsvEvent:
    """A single row from the transitions CSV."""
    state_dept_name: str
    status_change: str
    year: int | None
    month: int | None
    day: int | None
    last_verified: str
    notes: str
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

    def to_dict(self) -> dict:
        return {
            "state_dept_name": self.state_dept_name,
            "status_change": self.status_change,
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "last_verified": self.last_verified,
            "notes": self.notes,
            "row_index": self.row_index,
            "date": self.date_str(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CsvEvent":
        return cls(
            state_dept_name=d["state_dept_name"],
            status_change=d["status_change"],
            year=d.get("year"),
            month=d.get("month"),
            day=d.get("day"),
            last_verified=d.get("last_verified", ""),
            notes=d.get("notes", ""),
            row_index=d["row_index"],
        )


@dataclass
class CountryMapping:
    """Mapping from a CSV country name to source file paths."""
    csv_name: str
    rdcr_path: str | None = None
    pocom_path: str | None = None

    def to_dict(self) -> dict:
        result = {}
        if self.rdcr_path is not None:
            result["rdcr"] = self.rdcr_path
        else:
            result["rdcr"] = None
        if self.pocom_path is not None:
            result["pocom"] = self.pocom_path
        else:
            result["pocom"] = None
        return result

    @classmethod
    def from_dict(cls, csv_name: str, d: dict) -> "CountryMapping":
        return cls(
            csv_name=csv_name,
            rdcr_path=d.get("rdcr"),
            pocom_path=d.get("pocom"),
        )


@dataclass
class NumberedText:
    """Source text with line numbers prepended."""
    text: str  # the full numbered text
    lines: list[str]  # original lines (without numbers)
    line_to_byte_offset: dict[int, int]  # line number -> byte offset in original file
    source_file: str  # relative path from repo root
    repo_commit: str  # git commit hash of the submodule

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "lines": self.lines,
            "line_to_byte_offset": {str(k): v for k, v in self.line_to_byte_offset.items()},
            "source_file": self.source_file,
            "repo_commit": self.repo_commit,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NumberedText":
        return cls(
            text=d["text"],
            lines=d["lines"],
            line_to_byte_offset={int(k): v for k, v in d["line_to_byte_offset"].items()},
            source_file=d["source_file"],
            repo_commit=d["repo_commit"],
        )


@dataclass
class WorkUnit:
    """All data needed to process one country."""
    country: str
    csv_events: list[CsvEvent]
    rdcr_text: NumberedText | None = None
    pocom_text: NumberedText | None = None
    token_estimates: dict[str, int] = field(default_factory=dict)
    flagged_large: bool = False

    def to_dict(self) -> dict:
        return {
            "country": self.country,
            "csv_events": [e.to_dict() for e in self.csv_events],
            "rdcr_text": self.rdcr_text.to_dict() if self.rdcr_text else None,
            "pocom_text": self.pocom_text.to_dict() if self.pocom_text else None,
            "token_estimates": self.token_estimates,
            "flagged_large": self.flagged_large,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorkUnit":
        return cls(
            country=d["country"],
            csv_events=[CsvEvent.from_dict(e) for e in d["csv_events"]],
            rdcr_text=NumberedText.from_dict(d["rdcr_text"]) if d.get("rdcr_text") else None,
            pocom_text=NumberedText.from_dict(d["pocom_text"]) if d.get("pocom_text") else None,
            token_estimates=d.get("token_estimates", {}),
            flagged_large=d.get("flagged_large", False),
        )


@dataclass
class ExtractedEvent:
    """A single event extracted by the LLM in Stage 2."""
    date: str
    new_status: str
    event_description: str
    confidence: str
    evidence: list[dict]  # list of {line_start, line_end, quote}

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "new_status": self.new_status,
            "event_description": self.event_description,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExtractedEvent":
        return cls(
            date=d["date"],
            new_status=d["new_status"],
            event_description=d["event_description"],
            confidence=d["confidence"],
            evidence=d.get("evidence", []),
        )


@dataclass
class ApiMetadata:
    """Metadata from an Anthropic API response."""
    message_id: str
    model: str
    usage: dict  # {input_tokens, output_tokens}
    stop_reason: str

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "model": self.model,
            "usage": self.usage,
            "stop_reason": self.stop_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ApiMetadata":
        return cls(
            message_id=d["message_id"],
            model=d["model"],
            usage=d["usage"],
            stop_reason=d["stop_reason"],
        )


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
