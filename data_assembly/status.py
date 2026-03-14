"""Diplomatic status ordering and aggregation utilities."""

from collections import Counter

STATUS_ORDER = [
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

STATUS_RANK = {s: i for i, s in enumerate(STATUS_ORDER)}


def status_to_rank(s: str) -> int:
    return STATUS_RANK[s]


def rank_to_status(r: int) -> str:
    return STATUS_ORDER[r]


def status_max(statuses: list[str]) -> str:
    """Greatest diplomatic status (lowest rank number)."""
    return rank_to_status(min(status_to_rank(s) for s in statuses))


def status_min(statuses: list[str]) -> str:
    """Least diplomatic status (highest rank number)."""
    return rank_to_status(max(status_to_rank(s) for s in statuses))


def status_median(statuses: list[str]) -> str:
    """Median diplomatic status. Ties break toward greater status."""
    ranks = sorted(status_to_rank(s) for s in statuses)
    n = len(ranks)
    mid = (n - 1) / 2
    # For even-length, mid is X.5 — take the lower index (smaller rank = greater status)
    return rank_to_status(ranks[int(mid)])


def status_mode(statuses: list[str]) -> str:
    """Modal diplomatic status. Ties break toward greater status."""
    counts = Counter(status_to_rank(s) for s in statuses)
    max_count = max(counts.values())
    # Among ranks tied for most frequent, pick lowest rank (greatest status)
    best_rank = min(r for r, c in counts.items() if c == max_count)
    return rank_to_status(best_rank)
