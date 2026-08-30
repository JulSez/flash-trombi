from __future__ import annotations

import random
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from pdf_import import extract_cards

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "flash_trombi.sqlite3"

STATUS_NON_COMMENCE = "non_commence"
STATUS_VU = "vu"
STATUS_MEMORISE = "memorise"
STATUS_ACQUIS = "acquis"

STATUS_LABELS = {
    STATUS_NON_COMMENCE: "Non commencé",
    STATUS_VU: "Vu",
    STATUS_MEMORISE: "Mémorisé",
    STATUS_ACQUIS: "Acquis",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today(value: Optional[date] = None) -> str:
    return (value or date.today()).isoformat()


def _slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9À-ÖØ-öø-ÿ_-]+", "-", value.strip())
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:60] or "classe"


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                folder_path TEXT NOT NULL DEFAULT '',
                pdf_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                external_key TEXT NOT NULL,
                position INTEGER NOT NULL,
                page INTEGER NOT NULL,
                first_name TEXT NOT NULL DEFAULT '',
                last_name TEXT NOT NULL DEFAULT '',
                photo_path TEXT NOT NULL,
                label_path TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'non_commence',
                cycle_no INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                UNIQUE(class_id, external_key)
            );

            CREATE TABLE IF NOT EXISTS memory_days (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                cycle_no INTEGER NOT NULL,
                memory_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(student_id, cycle_no, memory_date)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                session_date TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                maintenance_mode INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS session_students (
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                initial_status TEXT NOT NULL,
                correct_count INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(session_id, student_id)
            );

            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                asked_at TEXT NOT NULL,
                correct INTEGER NOT NULL
            );
            """
        )


def create_class(name: str, pdf_bytes: bytes) -> int:
    init_db()
    name = name.strip()
    if not name:
        raise ValueError("Le nom de la classe est obligatoire.")

    cards = extract_cards(pdf_bytes)
    if not cards:
        raise ValueError("Aucun portrait n'a été détecté dans ce PDF.")

    class_id = None
    folder = None
    try:
        with connect() as conn:
            cursor = conn.execute(
                "INSERT INTO classes(name, created_at) VALUES (?, ?)",
                (name, _now()),
            )
            class_id = cursor.lastrowid
            folder = DATA_DIR / "classes" / f"{class_id:04d}-{_slugify(name)}"
            portraits_dir = folder / "portraits"
            labels_dir = folder / "labels"
            portraits_dir.mkdir(parents=True, exist_ok=False)
            labels_dir.mkdir(parents=True, exist_ok=False)

            pdf_path = folder / "source.pdf"
            pdf_path.write_bytes(pdf_bytes)
            conn.execute(
                "UPDATE classes SET folder_path=?, pdf_path=? WHERE id=?",
                (str(folder), str(pdf_path), class_id),
            )

            for card in cards:
                ext = card["photo_ext"].lower().replace("jpeg", "jpg")
                photo_path = portraits_dir / f"student_{card['position']:03d}.{ext}"
                label_path = labels_dir / f"student_{card['position']:03d}.png"
                photo_path.write_bytes(card["photo_bytes"])
                label_path.write_bytes(card["label_bytes"])
                conn.execute(
                    """
                    INSERT INTO students(
                        class_id, external_key, position, page, photo_path, label_path, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        class_id,
                        card["external_key"],
                        card["position"],
                        card["page"],
                        str(photo_path),
                        str(label_path),
                        _now(),
                    ),
                )
        return int(class_id)
    except sqlite3.IntegrityError as exc:
        if folder and folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        raise ValueError("Une classe portant ce nom existe déjà.") from exc
    except Exception:
        if folder and folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        raise


def list_classes() -> List[Dict]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT c.*,
                   COUNT(s.id) AS student_count,
                   SUM(CASE WHEN s.status='acquis' THEN 1 ELSE 0 END) AS acquired_count
            FROM classes c
            LEFT JOIN students s ON s.class_id=c.id
            GROUP BY c.id
            ORDER BY c.name
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_class(class_id: int) -> Optional[Dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM classes WHERE id=?", (class_id,)).fetchone()
        return dict(row) if row else None


def memory_dates(conn: sqlite3.Connection, student_id: int, cycle_no: int) -> List[str]:
    rows = conn.execute(
        """
        SELECT memory_date FROM memory_days
        WHERE student_id=? AND cycle_no=?
        ORDER BY memory_date
        """,
        (student_id, cycle_no),
    ).fetchall()
    return [row["memory_date"] for row in rows]


def get_students(class_id: int) -> List[Dict]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM students WHERE class_id=? ORDER BY position",
            (class_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["memory_dates"] = memory_dates(conn, item["id"], item["cycle_no"])
            result.append(item)
        return result


def update_student_name(student_id: int, first_name: str, last_name: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE students SET first_name=?, last_name=? WHERE id=?",
            (first_name.strip(), last_name.strip(), student_id),
        )


def class_stats(class_id: int) -> Dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM students WHERE class_id=? GROUP BY status",
            (class_id,),
        ).fetchall()
    stats = {status: 0 for status in STATUS_LABELS}
    stats.update({row["status"]: row["n"] for row in rows})
    stats["total"] = sum(stats.values())
    return stats


def _shuffle_take(rows: Iterable[sqlite3.Row], remaining: int) -> List[int]:
    ids = [row["id"] for row in rows]
    random.shuffle(ids)
    return ids[:remaining]


def start_or_resume_session(class_id: int, on_date: Optional[date] = None) -> Dict:
    init_db()
    today = _today(on_date)
    with connect() as conn:
        open_session = conn.execute(
            """
            SELECT * FROM sessions
            WHERE class_id=? AND session_date=? AND completed_at IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (class_id, today),
        ).fetchone()
        if open_session:
            return dict(open_session)

        students = conn.execute(
            "SELECT * FROM students WHERE class_id=? ORDER BY position",
            (class_id,),
        ).fetchall()
        if not students:
            raise ValueError("Cette classe ne contient aucun élève.")

        memorised_due, seen, not_started, acquired = [], [], [], []
        for student in students:
            if student["status"] == STATUS_MEMORISE:
                dates = memory_dates(conn, student["id"], student["cycle_no"])
                if not dates or dates[-1] < today:
                    memorised_due.append(student)
            elif student["status"] == STATUS_VU:
                seen.append(student)
            elif student["status"] == STATUS_NON_COMMENCE:
                not_started.append(student)
            elif student["status"] == STATUS_ACQUIS:
                acquired.append(student)

        all_acquired = len(acquired) == len(students)
        selected: List[int] = []
        maintenance = 0

        if all_acquired:
            maintenance = 1
            selected = _shuffle_take(acquired, min(10, len(acquired)))
        else:
            for bucket in (memorised_due, seen, not_started):
                if len(selected) >= 10:
                    break
                selected.extend(_shuffle_take(bucket, 10 - len(selected)))

        if not selected:
            raise ValueError(
                "Rien à travailler aujourd'hui : les élèves non acquis ont déjà été mémorisés aujourd'hui."
            )

        cursor = conn.execute(
            """
            INSERT INTO sessions(class_id, session_date, started_at, maintenance_mode)
            VALUES (?, ?, ?, ?)
            """,
            (class_id, today, _now(), maintenance),
        )
        session_id = cursor.lastrowid

        for student_id in selected:
            student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
            initial_status = student["status"]
            conn.execute(
                """
                INSERT INTO session_students(session_id, student_id, initial_status)
                VALUES (?, ?, ?)
                """,
                (session_id, student_id, initial_status),
            )
            if initial_status == STATUS_NON_COMMENCE:
                conn.execute(
                    "UPDATE students SET status=? WHERE id=?",
                    (STATUS_VU, student_id),
                )

        return dict(conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())


def get_session(session_id: int) -> Optional[Dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row) if row else None


def get_session_students(session_id: int) -> List[Dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.*, ss.correct_count, ss.completed, ss.initial_status
            FROM session_students ss
            JOIN students s ON s.id=ss.student_id
            WHERE ss.session_id=?
            ORDER BY s.position
            """,
            (session_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["memory_dates"] = memory_dates(conn, item["id"], item["cycle_no"])
            result.append(item)
        return result


def next_student(session_id: int) -> Optional[Dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.*, ss.correct_count, ss.completed
            FROM session_students ss
            JOIN students s ON s.id=ss.student_id
            WHERE ss.session_id=? AND ss.completed=0
            """,
            (session_id,),
        ).fetchall()
        if not rows:
            return None

        recent_rows = conn.execute(
            """
            SELECT student_id FROM attempts
            WHERE session_id=?
            ORDER BY id DESC LIMIT 5
            """,
            (session_id,),
        ).fetchall()
        recent = [row["student_id"] for row in recent_rows]

        chosen_pool = list(rows)
        for blocked_count in range(len(recent), -1, -1):
            blocked = set(recent[:blocked_count])
            candidates = [row for row in rows if row["id"] not in blocked]
            if candidates:
                chosen_pool = candidates
                break

        return dict(random.choice(chosen_pool))


def record_answer(session_id: int, student_id: int, correct: bool, on_date: Optional[date] = None) -> Dict:
    today = _today(on_date)
    with connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session or session["completed_at"]:
            raise ValueError("Cette session est terminée.")

        ss = conn.execute(
            "SELECT * FROM session_students WHERE session_id=? AND student_id=?",
            (session_id, student_id),
        ).fetchone()
        if not ss or ss["completed"]:
            raise ValueError("Cet élève est déjà terminé pour cette session.")

        student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        conn.execute(
            "INSERT INTO attempts(session_id, student_id, asked_at, correct) VALUES (?, ?, ?, ?)",
            (session_id, student_id, _now(), int(bool(correct))),
        )

        message = ""
        correct_count = ss["correct_count"]
        completed = 0

        if session["maintenance_mode"]:
            completed = 1
            message = "Révision d'entretien terminée pour cet élève."

        elif student["status"] == STATUS_MEMORISE:
            if correct:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO memory_days(student_id, cycle_no, memory_date, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (student_id, student["cycle_no"], today, _now()),
                )
                dates = memory_dates(conn, student_id, student["cycle_no"])
                if len(dates) >= 3:
                    conn.execute("UPDATE students SET status=? WHERE id=?", (STATUS_ACQUIS, student_id))
                    message = "Acquis : mémorisé sur 3 jours différents."
                else:
                    message = f"Mémorisé sur {len(dates)}/3 jour(s)."
                completed = 1
            else:
                new_cycle = student["cycle_no"] + 1
                conn.execute(
                    "UPDATE students SET status=?, cycle_no=? WHERE id=?",
                    (STATUS_VU, new_cycle, student_id),
                )
                correct_count = 0
                conn.execute(
                    "UPDATE session_students SET correct_count=0 WHERE session_id=? AND student_id=?",
                    (session_id, student_id),
                )
                message = "Raté : retour à Vu et nouveau cycle de mémorisation."

        else:
            if student["status"] == STATUS_NON_COMMENCE:
                conn.execute("UPDATE students SET status=? WHERE id=?", (STATUS_VU, student_id))

            if correct:
                correct_count += 1
                conn.execute(
                    "UPDATE session_students SET correct_count=? WHERE session_id=? AND student_id=?",
                    (correct_count, session_id, student_id),
                )
                if correct_count >= 3:
                    refreshed = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO memory_days(student_id, cycle_no, memory_date, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (student_id, refreshed["cycle_no"], today, _now()),
                    )
                    conn.execute("UPDATE students SET status=? WHERE id=?", (STATUS_MEMORISE, student_id))
                    completed = 1
                    message = "3 réussites : mémorisé pour aujourd'hui."
                else:
                    message = f"Bonne réponse : {correct_count}/3 aujourd'hui."
            else:
                message = f"Raté. Le compteur reste à {correct_count}/3 réussite(s)."

        if completed:
            conn.execute(
                "UPDATE session_students SET completed=1 WHERE session_id=? AND student_id=?",
                (session_id, student_id),
            )

        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM session_students WHERE session_id=? AND completed=0",
            (session_id,),
        ).fetchone()["n"]
        if remaining == 0:
            conn.execute("UPDATE sessions SET completed_at=? WHERE id=?", (_now(), session_id))

        refreshed = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        dates = memory_dates(conn, student_id, refreshed["cycle_no"])
        return {
            "student_id": student_id,
            "status": refreshed["status"],
            "correct_count": correct_count,
            "completed": bool(completed),
            "memory_dates": dates,
            "message": message,
            "session_finished": remaining == 0,
        }


def session_progress(session_id: int) -> Dict[str, int]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN completed=1 THEN 1 ELSE 0 END) AS completed
            FROM session_students WHERE session_id=?
            """,
            (session_id,),
        ).fetchone()
        attempts = conn.execute(
            "SELECT COUNT(*) AS n FROM attempts WHERE session_id=?",
            (session_id,),
        ).fetchone()["n"]
    return {"total": row["total"] or 0, "completed": row["completed"] or 0, "attempts": attempts}


def end_session(session_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE sessions SET completed_at=COALESCE(completed_at, ?) WHERE id=?",
            (_now(), session_id),
        )
