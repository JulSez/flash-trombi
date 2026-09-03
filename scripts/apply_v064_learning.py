from pathlib import Path


storage_path = Path("storage.py")
storage = storage_path.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Missing expected fragment for {label}")
    return text.replace(old, new, 1)


storage = replace_once(
    storage,
    'STATUS_ACQUIS = "acquis"\n',
    'STATUS_ACQUIS = "acquis"\nSESSION_TARGET_SIZE = 10\n',
    "session target constant",
)

helper = '''\n\ndef _fill_session_with_acquired(\n    conn: sqlite3.Connection,\n    session_id: int,\n    today: str,\n    target: int = SESSION_TARGET_SIZE,\n) -> int:\n    """Fill a short session with acquired pupils without displacing pupils who need work."""\n    session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()\n    if not session or session["completed_at"]:\n        return 0\n\n    added = 0\n    while _active_count(conn, session_id) < target:\n        excluded = _already_in_session(conn, session_id)\n        _, _, _, acquired = _eligible_rows(\n            conn, _session_class_ids(session), excluded, today\n        )\n        if not acquired:\n            break\n        _add_student_to_session(conn, session_id, acquired[0])\n        added += 1\n    return added\n'''
storage = replace_once(
    storage,
    "\n\ndef start_or_resume_session(\n",
    helper + "\n\ndef start_or_resume_session(\n",
    "acquired filler helper",
)

storage = replace_once(
    storage,
    '''                for student in memorised[:10]:\n                    _add_student_to_session(conn, session_id, student)\n\n        if _active_count(conn, session_id) == 0:\n''',
    '''                for student in memorised[:10]:\n                    _add_student_to_session(conn, session_id, student)\n\n        _fill_session_with_acquired(conn, session_id, today)\n\n        if _active_count(conn, session_id) == 0:\n''',
    "initial minimum group",
)

storage = replace_once(
    storage,
    '''                correct_count = 0\n                message = "Oublié : retour à Vu, nouveau cycle à zéro."\n\n        elif student["status"] == STATUS_MEMORISE:\n''',
    '''                correct_count = 0\n                completed = 1\n                message = "Oublié : retour à Vu, nouveau cycle à zéro."\n\n        elif student["status"] == STATUS_ACQUIS:\n            if correct:\n                completed = 1\n                message = "Toujours acquis 👍"\n            else:\n                new_cycle = int(student["cycle_no"]) + 1\n                conn.execute(\n                    "UPDATE students SET status=?, cycle_no=? WHERE id=?",\n                    (STATUS_VU, new_cycle, student_id),\n                )\n                conn.execute(\n                    "UPDATE session_students SET correct_count=0 WHERE session_id=? AND student_id=?",\n                    (session_id, student_id),\n                )\n                correct_count = 0\n                completed = 1\n                message = "À retravailler : retour à Vu."\n\n        elif student["status"] == STATUS_MEMORISE:\n''',
    "acquired filler answer",
)

storage = replace_once(
    storage,
    '''            else:\n                message = f"À revoir — {correct_count}/3 bonnes réponses pour l'instant."\n\n        if completed:\n''',
    '''            else:\n                correct_count = 0\n                conn.execute(\n                    "UPDATE session_students SET correct_count=0 WHERE session_id=? AND student_id=?",\n                    (session_id, student_id),\n                )\n                message = "À revoir — la série repart à 0/3."\n\n        if completed:\n''',
    "consecutive success reset",
)

storage = replace_once(
    storage,
    '''        if not int(session["memorised_review_mode"]):\n            _replenish_session(\n                conn,\n                session_id,\n                today,\n                prefer_non_started=became_memorised_today,\n            )\n\n        refreshed = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()\n''',
    '''        if not int(session["memorised_review_mode"]):\n            _replenish_session(\n                conn,\n                session_id,\n                today,\n                prefer_non_started=became_memorised_today,\n            )\n            _fill_session_with_acquired(conn, session_id, today)\n\n        refreshed = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()\n''',
    "rolling acquired fillers",
)

storage_path.write_text(storage, encoding="utf-8")

shortlist_path = Path("shortlist_review.py")
shortlist = shortlist_path.read_text(encoding="utf-8")
shortlist = replace_once(
    shortlist,
    '        if not correct and status == STATUS_MEMORISE:\n',
    '        if not correct and status in {STATUS_MEMORISE, storage.STATUS_ACQUIS}:\n',
    "acquired shortlist miss",
)
shortlist_path.write_text(shortlist, encoding="utf-8")
