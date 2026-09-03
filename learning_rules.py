from __future__ import annotations

from datetime import date
from typing import Dict, Optional, Sequence

import storage

TARGET_ACTIVE_STUDENTS = 10
_INSTALLED = False


def _fill_with_acquired(
    session_id: int,
    on_date: Optional[date] = None,
    target: int = TARGET_ACTIVE_STUDENTS,
) -> int:
    """Use acquired pupils only as fillers when a session has fewer than target active pupils."""
    today = storage._today(on_date)
    with storage.connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session or session["completed_at"]:
            return 0

        active = storage._active_count(conn, session_id)
        if active >= target:
            return 0

        class_ids = storage._session_class_ids(session)
        excluded = storage._already_in_session(conn, session_id)
        _, _, _, acquired = storage._eligible_rows(conn, class_ids, excluded, today)

        added = 0
        for student in acquired:
            if active >= target:
                break
            storage._add_student_to_session(conn, session_id, student)
            active += 1
            added += 1
        return added


def _reset_learning_streak_on_miss(session_id: int, student_id: int, correct: bool) -> None:
    """A learning streak is consecutive: one miss always sends the counter back to zero."""
    if correct:
        return

    with storage.connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not session or not student or session["completed_at"]:
            return
        if int(session["maintenance_mode"]) or int(session["memorised_review_mode"]):
            return
        if str(student["status"]) not in {storage.STATUS_NON_COMMENCE, storage.STATUS_VU}:
            return

        conn.execute(
            "UPDATE session_students SET correct_count=0 WHERE session_id=? AND student_id=?",
            (session_id, student_id),
        )


def _record_acquired_answer(
    session_id: int,
    student_id: int,
    correct: bool,
    on_date: Optional[date] = None,
) -> Dict:
    """Handle an acquired pupil used as a filler in an otherwise normal/review session."""
    with storage.connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session or session["completed_at"]:
            raise ValueError("Cette session est déjà terminée.")

        ss = conn.execute(
            "SELECT * FROM session_students WHERE session_id=? AND student_id=?",
            (session_id, student_id),
        ).fetchone()
        if not ss or int(ss["completed"]):
            raise ValueError("Cet élève n'est plus dans la série.")

        student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not student or str(student["status"]) != storage.STATUS_ACQUIS:
            raise ValueError("Élève acquis introuvable dans cette série.")

        conn.execute(
            "INSERT INTO attempts(session_id, student_id, asked_at, correct) VALUES (?, ?, ?, ?)",
            (session_id, student_id, storage._now(), int(bool(correct))),
        )

        if correct:
            status = storage.STATUS_ACQUIS
            message = "Toujours acquis 👍"
        else:
            new_cycle = int(student["cycle_no"]) + 1
            conn.execute(
                "UPDATE students SET status=?, cycle_no=? WHERE id=?",
                (storage.STATUS_VU, new_cycle, student_id),
            )
            status = storage.STATUS_VU
            message = "À retravailler : retour à Vu."

        conn.execute(
            """
            UPDATE session_students
            SET completed=1, correct_count=0, review_first_done=1, review_failed=0
            WHERE session_id=? AND student_id=?
            """,
            (session_id, student_id),
        )

    _fill_with_acquired(session_id, on_date)

    with storage.connect() as conn:
        active = storage._active_count(conn, session_id)
        finished = active == 0
        if finished:
            conn.execute(
                "UPDATE sessions SET completed_at=COALESCE(completed_at, ?) WHERE id=?",
                (storage._now(), session_id),
            )
        refreshed = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        dates = storage.memory_dates(conn, student_id, int(refreshed["cycle_no"]))

    return {
        "status": status,
        "correct_count": 0,
        "memory_dates": dates,
        "message": message,
        "session_finished": finished,
        "active_count": active,
    }


def install_runtime_behavior() -> None:
    """Install v0.6.4 learning rules after the shortlist compatibility layer."""
    global _INSTALLED
    if _INSTALLED:
        return

    base_start = storage.start_or_resume_session
    base_record = storage.record_answer

    def start_with_minimum_group(
        class_ids: int | Sequence[int], on_date: Optional[date] = None
    ) -> Dict:
        session = base_start(class_ids, on_date)
        _fill_with_acquired(int(session["id"]), on_date)
        return session

    def record_with_consecutive_streak(
        session_id: int,
        student_id: int,
        correct: bool,
        on_date: Optional[date] = None,
    ) -> Dict:
        _reset_learning_streak_on_miss(session_id, student_id, correct)

        with storage.connect() as conn:
            student = conn.execute("SELECT status FROM students WHERE id=?", (student_id,)).fetchone()
        if student and str(student["status"]) == storage.STATUS_ACQUIS:
            return _record_acquired_answer(session_id, student_id, correct, on_date)

        result = base_record(session_id, student_id, correct, on_date)
        if not result.get("session_finished"):
            _fill_with_acquired(session_id, on_date)
            with storage.connect() as conn:
                result["active_count"] = storage._active_count(conn, session_id)
        return result

    storage.start_or_resume_session = start_with_minimum_group
    storage.record_answer = record_with_consecutive_streak
    _INSTALLED = True
