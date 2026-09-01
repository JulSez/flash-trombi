from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Sequence

import storage
from storage import STATUS_MEMORISE, STATUS_VU, connect


def _scope_key(class_ids: Sequence[int]) -> str:
    return ",".join(str(value) for value in sorted({int(value) for value in class_ids}))


def selection_done_today(students: Sequence[dict], on_date: date | None = None) -> bool:
    """Return True when every selected student is acquired or memorised today."""
    items = list(students)
    if not items:
        return False
    today = (on_date or date.today()).isoformat()
    for student in items:
        status = str(student.get("status", ""))
        if status == "acquis":
            continue
        dates = list(student.get("memory_dates") or [])
        if status != STATUS_MEMORISE or not dates or dates[-1] != today:
            return False
    return True


def memorised_count(students: Sequence[dict]) -> int:
    return sum(str(student.get("status", "")) == STATUS_MEMORISE for student in students)


def start_shortlist_session(class_ids: Sequence[int], on_date: date | None = None) -> Dict:
    """Create a review session containing every memorised student in the selection."""
    ids = sorted({int(value) for value in class_ids})
    if not ids:
        raise ValueError("Choisis au moins une classe.")
    today = (on_date or date.today()).isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    placeholders = ",".join("?" for _ in ids)

    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT s.*
            FROM students s
            WHERE s.class_id IN ({placeholders}) AND s.status=?
            ORDER BY s.class_id, s.position
            """,
            [*ids, STATUS_MEMORISE],
        ).fetchall()
        if not rows:
            raise ValueError("Aucun élève mémorisé à revoir.")

        cursor = conn.execute(
            """
            INSERT INTO sessions(
                class_id, class_scope, session_date, started_at,
                maintenance_mode, memorised_review_mode
            ) VALUES (?, ?, ?, ?, 0, 1)
            """,
            (ids[0], _scope_key(ids), today, now),
        )
        session_id = int(cursor.lastrowid)
        conn.executemany(
            """
            INSERT INTO session_students(session_id, student_id, initial_status)
            VALUES (?, ?, ?)
            """,
            [(session_id, int(row["id"]), STATUS_MEMORISE) for row in rows],
        )
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return dict(session)


def _session_class_ids(session: dict) -> list[int]:
    scope = str(session.get("class_scope") or "").strip()
    if scope:
        return [int(part) for part in scope.split(",") if part.strip()]
    return [int(session["class_id"])]


def _expand_existing_shortlist(session: dict) -> dict:
    """Upgrade legacy 10-person review sessions to the full memorised shortlist."""
    if not int(session.get("memorised_review_mode", 0)) or session.get("completed_at"):
        return session
    ids = _session_class_ids(session)
    placeholders = ",".join("?" for _ in ids)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT id FROM students WHERE class_id IN ({placeholders}) AND status=?",
            [*ids, STATUS_MEMORISE],
        ).fetchall()
        conn.executemany(
            """
            INSERT OR IGNORE INTO session_students(session_id, student_id, initial_status)
            VALUES (?, ?, ?)
            """,
            [(int(session["id"]), int(row["id"]), STATUS_MEMORISE) for row in rows],
        )
        refreshed = conn.execute("SELECT * FROM sessions WHERE id=?", (session["id"],)).fetchone()
        return dict(refreshed)


def record_shortlist_answer(
    session_id: int,
    student_id: int,
    correct: bool,
    on_date: date | None = None,
) -> Dict:
    """Remove one student from the shortlist; one miss immediately sends them back to Vu."""
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session or session["completed_at"] or not int(session["memorised_review_mode"]):
            raise ValueError("Cette short-list n'est plus active.")

        ss = conn.execute(
            "SELECT * FROM session_students WHERE session_id=? AND student_id=?",
            (session_id, student_id),
        ).fetchone()
        if not ss or int(ss["completed"]):
            raise ValueError("Cet élève n'est plus dans la short-list.")

        student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not student:
            raise ValueError("Élève introuvable.")

        conn.execute(
            "INSERT INTO attempts(session_id, student_id, asked_at, correct) VALUES (?, ?, ?, ?)",
            (session_id, student_id, now, int(bool(correct))),
        )

        status = str(student["status"])
        if not correct and status == STATUS_MEMORISE:
            conn.execute(
                "UPDATE students SET status=?, cycle_no=? WHERE id=?",
                (STATUS_VU, int(student["cycle_no"]) + 1, student_id),
            )
            status = STATUS_VU

        conn.execute(
            """
            UPDATE session_students
            SET completed=1, review_first_done=1, review_failed=0
            WHERE session_id=? AND student_id=?
            """,
            (session_id, student_id),
        )
        remaining = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM session_students WHERE session_id=? AND completed=0",
                (session_id,),
            ).fetchone()["n"]
        )
        finished = remaining == 0
        if finished:
            conn.execute("UPDATE sessions SET completed_at=? WHERE id=?", (now, session_id))

        return {
            "status": status,
            "remaining": remaining,
            "session_finished": finished,
            "active_count": remaining,
            "message": "",
            "correct_count": 0,
            "memory_dates": [],
        }


_ORIGINAL_START = storage.start_or_resume_session
_ORIGINAL_RECORD = storage.record_answer
_INSTALLED = False


def _patched_start_or_resume_session(class_ids, on_date=None):
    session = _ORIGINAL_START(class_ids, on_date)
    return _expand_existing_shortlist(dict(session))


def _patched_record_answer(session_id, student_id, correct, on_date=None):
    with connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        is_shortlist = bool(session and int(session["memorised_review_mode"]))
    if is_shortlist:
        return record_shortlist_answer(session_id, student_id, correct, on_date)
    return _ORIGINAL_RECORD(session_id, student_id, correct, on_date)


def install_runtime_behavior() -> None:
    """Install the v0.6.1 review behavior before Streamlit loads app.py."""
    global _INSTALLED
    if _INSTALLED:
        return

    storage.start_or_resume_session = _patched_start_or_resume_session
    storage.record_answer = _patched_record_answer

    import streamlit as st

    original_success = st.success
    original_button = st.button

    def success_with_done_hint(body, *args, **kwargs):
        result = original_success(body, *args, **kwargs)
        if str(body) == "C'est bon pour aujourd'hui 🎉":
            st.caption(
                "Tu peux changer de classe dans la barre de gauche, "
                "ou continuer avec les élèves mémorisés."
            )
        return result

    def button_with_shortlist_label(label, *args, **kwargs):
        on_click = kwargs.get("on_click")
        if str(label) == "▶️ Continuer" and getattr(on_click, "__name__", "") == "start_training":
            label = "▶️ Continuer avec les mémorisés"
        return original_button(label, *args, **kwargs)

    st.success = success_with_done_hint
    st.button = button_with_shortlist_label
    _INSTALLED = True
