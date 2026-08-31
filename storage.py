from __future__ import annotations

import io
import random
import re
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from paths import CLASSES_DIR, DATA_DIR, DB_PATH, ensure_data_dirs
from pdf_import import extract_cards

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


def _stored_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(DATA_DIR.resolve()))
    except ValueError:
        return str(path)


def resolve_data_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    parts = path.parts
    if parts and parts[0].lower() == "data":
        path = Path(*parts[1:])
    return DATA_DIR / path


def _normalize_class_ids(class_ids: int | Sequence[int]) -> List[int]:
    if isinstance(class_ids, int):
        values = [class_ids]
    else:
        values = [int(value) for value in class_ids]
    return list(dict.fromkeys(values))


def _scope_key(class_ids: int | Sequence[int]) -> str:
    return ",".join(str(value) for value in sorted(_normalize_class_ids(class_ids)))


def _parse_scope(session: sqlite3.Row | Dict) -> List[int]:
    scope = str(session["class_scope"] or "").strip() if "class_scope" in session.keys() else ""
    if scope:
        return [int(part) for part in scope.split(",") if part.strip()]
    return [int(session["class_id"])]


@contextmanager
def connect():
    ensure_data_dirs()
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


def _ensure_column(conn: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if name not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db() -> None:
    ensure_data_dirs()
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
        _ensure_column(conn, "students", "name_source", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "sessions", "class_scope", "TEXT NOT NULL DEFAULT ''")


def class_name_exists(name: str) -> bool:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM classes WHERE name=? COLLATE NOCASE", (name.strip(),)).fetchone()
        return bool(row)


def analyze_pdf(pdf_bytes: bytes) -> List[Dict]:
    return extract_cards(pdf_bytes)


def create_class(name: str, pdf_bytes: bytes) -> int:
    return create_class_from_cards(name, pdf_bytes, analyze_pdf(pdf_bytes))


def create_class_from_cards(name: str, pdf_bytes: bytes, cards: Sequence[Dict]) -> int:
    init_db()
    name = name.strip()
    if not name:
        raise ValueError("Donne un nom à la classe.")
    if not cards:
        raise ValueError("Aucun portrait sélectionné.")

    class_id: Optional[int] = None
    folder: Optional[Path] = None
    try:
        with connect() as conn:
            cursor = conn.execute("INSERT INTO classes(name, created_at) VALUES (?, ?)", (name, _now()))
            class_id = int(cursor.lastrowid)
            folder = CLASSES_DIR / f"{class_id:04d}-{_slugify(name)}"
            portraits_dir = folder / "portraits"
            labels_dir = folder / "labels"
            portraits_dir.mkdir(parents=True, exist_ok=False)
            labels_dir.mkdir(parents=True, exist_ok=False)

            pdf_path = folder / "trombinoscope.pdf"
            pdf_path.write_bytes(pdf_bytes)
            conn.execute(
                "UPDATE classes SET folder_path=?, pdf_path=? WHERE id=?",
                (_stored_path(folder), _stored_path(pdf_path), class_id),
            )

            for new_position, card in enumerate(cards, start=1):
                ext = str(card.get("photo_ext", "jpg")).lower().replace("jpeg", "jpg")
                if ext not in {"jpg", "png", "webp"}:
                    ext = "jpg"
                photo_path = portraits_dir / f"student_{new_position:03d}.{ext}"
                label_path = labels_dir / f"student_{new_position:03d}.png"
                photo_path.write_bytes(card["photo_bytes"])
                label_path.write_bytes(card["label_bytes"])
                conn.execute(
                    """
                    INSERT INTO students(
                        class_id, external_key, position, page,
                        first_name, last_name, name_source,
                        photo_path, label_path, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        class_id,
                        card.get("external_key") or f"n{new_position:03d}",
                        new_position,
                        int(card.get("page", 1)),
                        str(card.get("first_name", "")).strip(),
                        str(card.get("last_name", "")).strip(),
                        str(card.get("name_source", "")).strip(),
                        _stored_path(photo_path),
                        _stored_path(label_path),
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
            ORDER BY c.name COLLATE NOCASE
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_class(class_id: int) -> Optional[Dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM classes WHERE id=?", (class_id,)).fetchone()
        return dict(row) if row else None


def delete_class(class_id: int) -> None:
    with connect() as conn:
        row = conn.execute("SELECT folder_path FROM classes WHERE id=?", (class_id,)).fetchone()
        if not row:
            return
        folder = resolve_data_path(row["folder_path"])
        conn.execute("DELETE FROM classes WHERE id=?", (class_id,))
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)


def memory_dates(conn: sqlite3.Connection, student_id: int, cycle_no: int) -> List[str]:
    rows = conn.execute(
        """
        SELECT memory_date FROM memory_days
        WHERE student_id=? AND cycle_no=?
        ORDER BY memory_date
        """,
        (student_id, cycle_no),
    ).fetchall()
    return [str(row["memory_date"]) for row in rows]


def _student_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict:
    item = dict(row)
    item["photo_path"] = str(resolve_data_path(item["photo_path"]))
    if item.get("label_path"):
        item["label_path"] = str(resolve_data_path(item["label_path"]))
    item["memory_dates"] = memory_dates(conn, int(item["id"]), int(item["cycle_no"]))
    if "class_name" not in item:
        class_row = conn.execute("SELECT name FROM classes WHERE id=?", (item["class_id"],)).fetchone()
        item["class_name"] = class_row["name"] if class_row else ""
    return item


def get_students(class_id: int) -> List[Dict]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT s.*, c.name AS class_name FROM students s JOIN classes c ON c.id=s.class_id WHERE s.class_id=? ORDER BY s.position",
            (class_id,),
        ).fetchall()
        return [_student_dict(conn, row) for row in rows]


def get_students_for_classes(class_ids: Sequence[int]) -> List[Dict]:
    ids = _normalize_class_ids(class_ids)
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT s.*, c.name AS class_name
            FROM students s JOIN classes c ON c.id=s.class_id
            WHERE s.class_id IN ({placeholders})
            ORDER BY c.name COLLATE NOCASE, s.last_name COLLATE NOCASE,
                     s.first_name COLLATE NOCASE, s.position
            """,
            ids,
        ).fetchall()
        return [_student_dict(conn, row) for row in rows]


def random_student(class_ids: Sequence[int], exclude_ids: Sequence[int] = ()) -> Optional[Dict]:
    ids = _normalize_class_ids(class_ids)
    if not ids:
        return None
    students = get_students_for_classes(ids)
    if not students:
        return None
    blocked = {int(value) for value in exclude_ids}
    candidates = [student for student in students if int(student["id"]) not in blocked]
    if not candidates:
        candidates = students
    return random.choice(candidates)


def update_student_name(student_id: int, first_name: str, last_name: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE students SET first_name=?, last_name=?, name_source='manuel' WHERE id=?",
            (first_name.strip(), last_name.strip(), student_id),
        )


def class_stats(class_id: int) -> Dict[str, int]:
    return multi_class_stats([class_id])


def multi_class_stats(class_ids: Sequence[int]) -> Dict[str, int]:
    ids = _normalize_class_ids(class_ids)
    stats = {status: 0 for status in STATUS_LABELS}
    if not ids:
        stats["total"] = 0
        return stats
    placeholders = ",".join("?" for _ in ids)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT status, COUNT(*) AS n FROM students WHERE class_id IN ({placeholders}) GROUP BY status",
            ids,
        ).fetchall()
    stats.update({str(row["status"]): int(row["n"]) for row in rows})
    stats["total"] = sum(stats.values())
    return stats


def _student_sort_key(row: sqlite3.Row) -> tuple:
    has_name = bool(str(row["last_name"] or "").strip() or str(row["first_name"] or "").strip())
    return (
        0 if has_name else 1,
        str(row["last_name"] or "").casefold(),
        str(row["first_name"] or "").casefold(),
        int(row["position"]),
    )


def _session_class_ids(session: sqlite3.Row) -> List[int]:
    return _parse_scope(session)


def get_today_open_session_for_classes(
    class_ids: int | Sequence[int], on_date: Optional[date] = None
) -> Optional[Dict]:
    ids = _normalize_class_ids(class_ids)
    if not ids:
        return None
    today = _today(on_date)
    scope = _scope_key(ids)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM sessions
            WHERE session_date=? AND completed_at IS NULL
              AND (
                    class_scope=?
                    OR (class_scope='' AND ?=1 AND class_id=?)
                  )
            ORDER BY id DESC LIMIT 1
            """,
            (today, scope, len(ids), ids[0]),
        ).fetchone()
        return dict(row) if row else None


def get_today_open_session(class_id: int, on_date: Optional[date] = None) -> Optional[Dict]:
    return get_today_open_session_for_classes([class_id], on_date)


def _already_in_session(conn: sqlite3.Connection, session_id: int) -> set[int]:
    return {
        int(row["student_id"])
        for row in conn.execute(
            "SELECT student_id FROM session_students WHERE session_id=?", (session_id,)
        ).fetchall()
    }


def _active_count(conn: sqlite3.Connection, session_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM session_students WHERE session_id=? AND completed=0",
        (session_id,),
    ).fetchone()
    return int(row["n"] or 0)


def _eligible_rows(
    conn: sqlite3.Connection,
    class_ids: Sequence[int],
    excluded: set[int],
    today: str,
) -> tuple[List[sqlite3.Row], List[sqlite3.Row], List[sqlite3.Row], List[sqlite3.Row]]:
    if not class_ids:
        return [], [], [], []
    placeholders = ",".join("?" for _ in class_ids)
    rows = conn.execute(
        f"""
        SELECT s.*, c.name AS class_name
        FROM students s JOIN classes c ON c.id=s.class_id
        WHERE s.class_id IN ({placeholders})
        """,
        class_ids,
    ).fetchall()

    memorised_due: List[sqlite3.Row] = []
    seen: List[sqlite3.Row] = []
    not_started: List[sqlite3.Row] = []
    acquired: List[sqlite3.Row] = []

    for student in rows:
        sid = int(student["id"])
        if sid in excluded:
            continue
        status = student["status"]
        if status == STATUS_MEMORISE:
            dates = memory_dates(conn, sid, int(student["cycle_no"]))
            if not dates or dates[-1] < today:
                memorised_due.append(student)
        elif status == STATUS_VU:
            seen.append(student)
        elif status == STATUS_NON_COMMENCE:
            not_started.append(student)
        elif status == STATUS_ACQUIS:
            acquired.append(student)

    random.shuffle(memorised_due)
    random.shuffle(seen)
    random.shuffle(acquired)
    not_started.sort(
        key=lambda row: (str(row["class_name"]).casefold(),) + _student_sort_key(row)
    )
    return memorised_due, seen, not_started, acquired


def _add_student_to_session(
    conn: sqlite3.Connection, session_id: int, student: sqlite3.Row
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO session_students(session_id, student_id, initial_status)
        VALUES (?, ?, ?)
        """,
        (session_id, int(student["id"]), str(student["status"])),
    )
    if student["status"] == STATUS_NON_COMMENCE:
        conn.execute(
            "UPDATE students SET status=? WHERE id=?",
            (STATUS_VU, int(student["id"])),
        )


def _replenish_session(
    conn: sqlite3.Connection,
    session_id: int,
    today: str,
    prefer_non_started: bool = False,
) -> int:
    session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not session:
        return 0
    class_ids = _session_class_ids(session)
    added = 0

    while _active_count(conn, session_id) < 10:
        excluded = _already_in_session(conn, session_id)
        memorised_due, seen, not_started, acquired = _eligible_rows(conn, class_ids, excluded, today)
        chosen: Optional[sqlite3.Row] = None

        if int(session["maintenance_mode"]):
            chosen = acquired[0] if acquired else None
        elif prefer_non_started and not_started:
            chosen = not_started[0]
            prefer_non_started = False
        elif memorised_due:
            chosen = memorised_due[0]
        elif seen:
            chosen = seen[0]
        elif not_started:
            chosen = not_started[0]
        else:
            chosen = None

        if chosen is None:
            break
        _add_student_to_session(conn, session_id, chosen)
        added += 1

    return added


def start_or_resume_session(
    class_ids: int | Sequence[int], on_date: Optional[date] = None
) -> Dict:
    init_db()
    ids = _normalize_class_ids(class_ids)
    if not ids:
        raise ValueError("Coche au moins une classe.")
    existing = get_today_open_session_for_classes(ids, on_date)
    if existing:
        return existing

    today = _today(on_date)
    with connect() as conn:
        placeholders = ",".join("?" for _ in ids)
        total = int(
            conn.execute(
                f"SELECT COUNT(*) AS n FROM students WHERE class_id IN ({placeholders})", ids
            ).fetchone()["n"]
        )
        if total == 0:
            raise ValueError("Les classes cochées ne contiennent aucun élève.")

        acquired = int(
            conn.execute(
                f"SELECT COUNT(*) AS n FROM students WHERE class_id IN ({placeholders}) AND status=?",
                [*ids, STATUS_ACQUIS],
            ).fetchone()["n"]
        )
        maintenance = int(acquired == total)

        cursor = conn.execute(
            """
            INSERT INTO sessions(class_id, class_scope, session_date, started_at, maintenance_mode)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ids[0], _scope_key(ids), today, _now(), maintenance),
        )
        session_id = int(cursor.lastrowid)
        _replenish_session(conn, session_id, today)

        if _active_count(conn, session_id) == 0:
            conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            raise ValueError(
                "Rien à travailler aujourd'hui : les élèves à réviser ont déjà été faits."
            )
        return dict(conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())


def get_session(session_id: int) -> Optional[Dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["class_ids"] = _session_class_ids(row)
        return item


def get_session_students(session_id: int) -> List[Dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.*, c.name AS class_name,
                   ss.correct_count, ss.completed, ss.initial_status
            FROM session_students ss
            JOIN students s ON s.id=ss.student_id
            JOIN classes c ON c.id=s.class_id
            WHERE ss.session_id=?
            ORDER BY ss.completed, c.name COLLATE NOCASE,
                     s.last_name COLLATE NOCASE, s.first_name COLLATE NOCASE, s.position
            """,
            (session_id,),
        ).fetchall()
        return [_student_dict(conn, row) for row in rows]


def next_student(session_id: int) -> Optional[Dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.*, c.name AS class_name, ss.correct_count, ss.completed
            FROM session_students ss
            JOIN students s ON s.id=ss.student_id
            JOIN classes c ON c.id=s.class_id
            WHERE ss.session_id=? AND ss.completed=0
            """,
            (session_id,),
        ).fetchall()
        if not rows:
            return None

        recent_rows = conn.execute(
            "SELECT student_id FROM attempts WHERE session_id=? ORDER BY id DESC LIMIT 5",
            (session_id,),
        ).fetchall()
        recent = [int(row["student_id"]) for row in recent_rows]

        candidates = list(rows)
        for blocked_count in range(len(recent), -1, -1):
            blocked = set(recent[:blocked_count])
            pool = [row for row in rows if int(row["id"]) not in blocked]
            if pool:
                candidates = pool
                break
        return _student_dict(conn, random.choice(candidates))


def _finish_session_if_needed(conn: sqlite3.Connection, session_id: int) -> bool:
    if _active_count(conn, session_id) == 0:
        conn.execute("UPDATE sessions SET completed_at=? WHERE id=?", (_now(), session_id))
        return True
    return False


def record_answer(
    session_id: int,
    student_id: int,
    correct: bool,
    on_date: Optional[date] = None,
) -> Dict:
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

        correct_count = int(ss["correct_count"])
        completed = 0
        became_memorised_today = False
        message = ""

        if int(session["maintenance_mode"]):
            if correct:
                completed = 1
                message = "Toujours acquis 👍"
            else:
                new_cycle = int(student["cycle_no"]) + 1
                conn.execute(
                    "UPDATE students SET status=?, cycle_no=? WHERE id=?",
                    (STATUS_VU, new_cycle, student_id),
                )
                conn.execute(
                    "UPDATE session_students SET correct_count=0 WHERE session_id=? AND student_id=?",
                    (session_id, student_id),
                )
                correct_count = 0
                message = "Oublié : retour à Vu, nouveau cycle à zéro."

        elif student["status"] == STATUS_MEMORISE:
            if correct:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO memory_days(student_id, cycle_no, memory_date, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (student_id, int(student["cycle_no"]), today, _now()),
                )
                dates = memory_dates(conn, student_id, int(student["cycle_no"]))
                if len(dates) >= 3:
                    conn.execute(
                        "UPDATE students SET status=? WHERE id=?",
                        (STATUS_ACQUIS, student_id),
                    )
                    message = "Acquis 🎉 — mémorisé sur 3 jours différents."
                else:
                    message = f"Mémorisé sur {len(dates)}/3 jour(s)."
                completed = 1
            else:
                new_cycle = int(student["cycle_no"]) + 1
                conn.execute(
                    "UPDATE students SET status=?, cycle_no=? WHERE id=?",
                    (STATUS_VU, new_cycle, student_id),
                )
                conn.execute(
                    "UPDATE session_students SET correct_count=0 WHERE session_id=? AND student_id=?",
                    (session_id, student_id),
                )
                correct_count = 0
                message = "Raté : retour à Vu, nouveau cycle à zéro."

        else:
            if correct:
                correct_count += 1
                conn.execute(
                    "UPDATE session_students SET correct_count=? WHERE session_id=? AND student_id=?",
                    (correct_count, session_id, student_id),
                )
                if correct_count >= 3:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO memory_days(student_id, cycle_no, memory_date, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (student_id, int(student["cycle_no"]), today, _now()),
                    )
                    conn.execute(
                        "UPDATE students SET status=? WHERE id=?",
                        (STATUS_MEMORISE, student_id),
                    )
                    completed = 1
                    became_memorised_today = True
                    message = "Mémorisé pour aujourd'hui ✅"
                else:
                    message = f"Bonne réponse : {correct_count}/3 dans cette session."
            else:
                message = f"À revoir — {correct_count}/3 bonnes réponses pour l'instant."

        if completed:
            conn.execute(
                "UPDATE session_students SET completed=1 WHERE session_id=? AND student_id=?",
                (session_id, student_id),
            )

        _replenish_session(
            conn,
            session_id,
            today,
            prefer_non_started=became_memorised_today,
        )

        refreshed = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        dates = memory_dates(conn, student_id, int(refreshed["cycle_no"]))
        finished = _finish_session_if_needed(conn, session_id)
        return {
            "status": str(refreshed["status"]),
            "correct_count": correct_count,
            "memory_dates": dates,
            "message": message,
            "session_finished": finished,
            "active_count": _active_count(conn, session_id),
        }


def session_progress(session_id: int) -> Dict[str, int]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS introduced,
                   SUM(CASE WHEN completed=1 THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN completed=0 THEN 1 ELSE 0 END) AS active
            FROM session_students WHERE session_id=?
            """,
            (session_id,),
        ).fetchone()
        attempts = conn.execute(
            "SELECT COUNT(*) AS n FROM attempts WHERE session_id=?", (session_id,)
        ).fetchone()["n"]
        return {
            "total": int(row["introduced"] or 0),
            "introduced": int(row["introduced"] or 0),
            "completed": int(row["completed"] or 0),
            "active": int(row["active"] or 0),
            "attempts": int(attempts or 0),
        }


def end_session(session_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE sessions SET completed_at=COALESCE(completed_at, ?) WHERE id=?",
            (_now(), session_id),
        )


def create_backup_bytes() -> bytes:
    init_db()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in DATA_DIR.rglob("*"):
            if path.is_file() and "backups" not in path.relative_to(DATA_DIR).parts:
                archive.write(path, path.relative_to(DATA_DIR).as_posix())
    return buffer.getvalue()


def restore_backup_bytes(zip_bytes: bytes) -> None:
    ensure_data_dirs()
    parent = DATA_DIR.parent
    with tempfile.TemporaryDirectory(prefix="flashtrombi-restore-", dir=parent) as temp_root:
        temp_path = Path(temp_root) / "restored"
        temp_path.mkdir()
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as archive:
            members = archive.infolist()
            for member in members:
                target = (temp_path / member.filename).resolve()
                if temp_path.resolve() not in target.parents and target != temp_path.resolve():
                    raise ValueError("Sauvegarde invalide.")
            archive.extractall(temp_path)

        if not (temp_path / "flash_trombi.sqlite3").exists():
            raise ValueError("Cette archive ne contient pas une sauvegarde Flash Trombi valide.")

        old_path = parent / f"{DATA_DIR.name}.old"
        if old_path.exists():
            shutil.rmtree(old_path, ignore_errors=True)
        if DATA_DIR.exists():
            DATA_DIR.rename(old_path)
        try:
            shutil.copytree(temp_path, DATA_DIR)
        except Exception:
            if DATA_DIR.exists():
                shutil.rmtree(DATA_DIR, ignore_errors=True)
            if old_path.exists():
                old_path.rename(DATA_DIR)
            raise
        finally:
            if old_path.exists():
                shutil.rmtree(old_path, ignore_errors=True)

    init_db()
