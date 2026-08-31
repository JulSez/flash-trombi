from __future__ import annotations

from datetime import date
from typing import Iterable

STAGE_NEW = "new"
STAGE_SEEN = "seen"
STAGE_MEMORISED = "memorised"
STAGE_REVIEW = "review"
STAGE_ACQUIRED = "acquired"

STAGE_LABELS = {
    STAGE_NEW: "Nouveau",
    STAGE_SEEN: "Vu",
    STAGE_MEMORISED: "Mémorisé",
    STAGE_REVIEW: "À réviser",
    STAGE_ACQUIRED: "Acquis",
}

STAGE_ORDER = [
    STAGE_NEW,
    STAGE_SEEN,
    STAGE_MEMORISED,
    STAGE_REVIEW,
    STAGE_ACQUIRED,
]


def display_stage(student: dict, on_date: date | None = None) -> str:
    status = str(student.get("status", "non_commence"))
    if status == "acquis":
        return STAGE_ACQUIRED
    if status == "memorise":
        dates = list(student.get("memory_dates") or [])
        if dates and dates[-1] < (on_date or date.today()).isoformat():
            return STAGE_REVIEW
        return STAGE_MEMORISED
    if status == "vu":
        return STAGE_SEEN
    return STAGE_NEW


def mastery_points(student: dict) -> int:
    """Internal score used only to draw the class progress bar."""
    status = str(student.get("status", "non_commence"))
    if status == "acquis":
        return 6
    if status == "memorise":
        dates = list(student.get("memory_dates") or [])
        return 4 if len(dates) >= 2 else 2
    if status == "vu":
        return 1
    return 0


def stage_counts(students: Iterable[dict], on_date: date | None = None) -> dict[str, int]:
    counts = {stage: 0 for stage in STAGE_ORDER}
    for student in students:
        counts[display_stage(student, on_date)] += 1
    counts["total"] = sum(counts.values())
    return counts


def mastery_ratio(students: Iterable[dict]) -> float:
    items = list(students)
    if not items:
        return 0.0
    return sum(mastery_points(student) for student in items) / (len(items) * 6)
