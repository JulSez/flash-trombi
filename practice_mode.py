from __future__ import annotations

import random
from typing import Dict, List, Sequence


def only_memorised_remain(students: Sequence[dict]) -> bool:
    """True when every non-acquired student is currently memorised."""
    remaining = [student for student in students if student.get("status") != "acquis"]
    return bool(remaining) and all(student.get("status") == "memorise" for student in remaining)


def create_practice_session(
    class_ids: Sequence[int],
    students: Sequence[dict],
    limit: int = 10,
    rng: random.Random | None = None,
) -> Dict:
    """Create a short first pass from memorised students.

    The first pass contains at most ``limit`` different students. Students missed
    during that pass are queued again afterwards. A missed retry is appended to
    the end again, so the series finishes only once every missed student has
    eventually been recognised.
    """
    rng = rng or random.Random()
    candidates = [dict(student) for student in students if student.get("status") == "memorise"]
    if not candidates:
        raise ValueError("Aucun élève mémorisé à réviser.")

    sample_size = min(max(1, int(limit)), len(candidates))
    chosen = rng.sample(candidates, sample_size)
    student_map = {int(student["id"]): student for student in chosen}
    queue = [int(student["id"]) for student in chosen]

    return {
        "class_ids": sorted({int(value) for value in class_ids}),
        "students": student_map,
        "queue": queue,
        "retry_queue": [],
        "phase": "first",
        "first_total": sample_size,
        "first_done": 0,
        "attempts": 0,
        "completed": False,
    }


def current_practice_student(state: Dict) -> dict | None:
    queue: List[int] = state.get("queue", [])
    if not queue:
        return None
    return state.get("students", {}).get(int(queue[0]))


def answer_practice(state: Dict, correct: bool) -> Dict:
    """Apply one answer and advance the queue in-place."""
    queue: List[int] = state.get("queue", [])
    if not queue:
        state["completed"] = True
        return {"message": "Série terminée.", "completed": True, "phase": state.get("phase", "first")}

    student_id = int(queue.pop(0))
    phase = str(state.get("phase", "first"))
    state["attempts"] = int(state.get("attempts", 0)) + 1

    if phase == "first":
        state["first_done"] = int(state.get("first_done", 0)) + 1

    if correct:
        message = "Bien vu ✅"
    else:
        state.setdefault("retry_queue", []).append(student_id)
        message = "On le reverra à la fin."

    if not queue:
        retry_queue: List[int] = state.get("retry_queue", [])
        if retry_queue:
            state["queue"] = retry_queue[:]
            state["retry_queue"] = []
            state["phase"] = "retry"
        else:
            state["completed"] = True

    return {
        "message": message,
        "completed": bool(state.get("completed")),
        "phase": str(state.get("phase", phase)),
    }
