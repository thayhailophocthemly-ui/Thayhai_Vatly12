"""Data-access layer. All business queries live here, on top of the TableStore."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import streamlit as st

from . import questions as qs
from .auth import hash_password
from .store import GoogleSheetsBackend, LocalJsonBackend, TableStore

log = logging.getLogger(__name__)

LOCAL_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "quiz_data.json"
ANSWER_GRACE_SECONDS = 2


def _secret(key: str, default=None):
    try:
        return st.secrets.get(key, os.environ.get(key, default))
    except Exception:  # no secrets.toml at all
        return os.environ.get(key, default)


@st.cache_resource(show_spinner="Đang kết nối nơi lưu trữ...")
def get_store() -> TableStore:
    # QUIZ_LOCAL_DATA=<path> forces local file storage (tests / sandbox), even when Sheets is configured.
    forced_local = os.environ.get("QUIZ_LOCAL_DATA")
    if forced_local:
        backend = LocalJsonBackend(Path(forced_local))
    else:
        sheets_cfg = _secret("google_sheets") or {}
        creds = _secret("gcp_service_account")
        spreadsheet = sheets_cfg.get("spreadsheet") if sheets_cfg else os.environ.get("QUIZ_SPREADSHEET")
        if creds and spreadsheet:
            backend = GoogleSheetsBackend(dict(creds), spreadsheet)
        else:
            log.warning("Google Sheets not configured - using local JSON storage at %s", LOCAL_DATA_PATH)
            backend = LocalJsonBackend(LOCAL_DATA_PATH)
    store = TableStore(backend)
    _seed(store)
    _migrate(store)
    store.flush()
    return store


def _seed(store: TableStore) -> None:
    if not store.where("users", role="teacher"):
        store.insert("users", {
            "username": _secret("QUIZ_ADMIN_USER", "teacher"),
            "password_hash": hash_password(_secret("QUIZ_ADMIN_PASSWORD", "teacher123")),
            "full_name": "Giáo viên", "role": "teacher", "created_at": time.time(),
        })


_LEGACY_LEVEL = {"Easy": "biet", "Medium": "hieu", "Hard": "vandung"}


def _migrate(store: TableStore) -> None:
    """v1 stored multiple-choice questions only (correct_index + difficulty)."""
    with store.lock:
        for q in store.where("question_bank", lambda r: not r["qtype"]):
            store.update("question_bank", q["id"], qtype="mcq", answer=q["correct_index"],
                         level=_LEGACY_LEVEL.get(q["difficulty"] or "", "hieu"), updated_at=time.time())


def _s() -> TableStore:
    return get_store()


def _norm(text: str | None) -> str:
    return (text or "").strip()


# ---------------------------------------------------------------- users
def get_user_by_username(username: str) -> dict | None:
    key = _norm(username).lower()
    rows = _s().where("users", lambda r: (r["username"] or "").lower() == key)
    return rows[0] if rows else None


def get_user(user_id: int) -> dict | None:
    return _s().get("users", user_id)


def username_exists(username: str, exclude_id: int | None = None) -> bool:
    user = get_user_by_username(username)
    return user is not None and user["id"] != exclude_id


def update_password(user_id: int, new_password: str) -> None:
    _s().update("users", user_id, password_hash=hash_password(new_password))


def list_teachers() -> list[dict]:
    return sorted(_s().where("users", role="teacher"), key=lambda r: r["full_name"].lower())


def create_teacher(username: str, password: str, full_name: str, created_by: int) -> int:
    return _s().insert("users", {
        "username": _norm(username), "password_hash": hash_password(password), "full_name": _norm(full_name),
        "role": "teacher", "created_by": created_by, "created_at": time.time(),
    })


def teacher_of_student(student_id: int) -> int | None:
    """The teacher whose question banks a student practises from: class teacher, else account creator."""
    store = _s()
    student = store.get("users", student_id)
    if not student:
        return None
    cls = store.get("classes", student["class_id"])
    return cls["teacher_id"] if cls else student["created_by"]


# ---------------------------------------------------------------- classes
def list_classes(teacher_id: int) -> list[dict]:
    store = _s()
    classes = store.where("classes", teacher_id=teacher_id)
    students = store.where("users", role="student")
    for c in classes:
        c["student_count"] = sum(1 for s in students if s["class_id"] == c["id"])
    return sorted(classes, key=lambda c: (c["class_number"], c["name"]))


def get_class(class_id: int | None) -> dict | None:
    return _s().get("classes", class_id)


def create_class(teacher_id: int, name: str, class_number: str) -> int:
    return _s().insert("classes", {"name": _norm(name), "class_number": _norm(class_number),
                                   "teacher_id": teacher_id, "created_at": time.time()})


def update_class(class_id: int, name: str, class_number: str) -> None:
    _s().update("classes", class_id, name=_norm(name), class_number=_norm(class_number))


def delete_class(class_id: int) -> None:
    store = _s()
    with store.lock:
        for s in store.where("users", class_id=class_id):
            store.update("users", s["id"], class_id=None)
        store.delete("classes", lambda r: r["id"] == class_id)


def class_number_exists(teacher_id: int, class_number: str, exclude_id: int | None = None) -> bool:
    key = _norm(class_number).lower()
    return any((c["class_number"] or "").lower() == key and c["id"] != exclude_id
               for c in _s().where("classes", teacher_id=teacher_id))


# ---------------------------------------------------------------- students
def list_students(teacher_id: int, class_id: int | None = None, unassigned_only: bool = False) -> list[dict]:
    """Students created by this teacher or enrolled in one of this teacher's classes."""
    store = _s()
    classes = {c["id"]: c for c in store.where("classes", teacher_id=teacher_id)}
    out = []
    for u in store.where("users", role="student"):
        if u["created_by"] != teacher_id and u["class_id"] not in classes:
            continue
        if class_id is not None and u["class_id"] != class_id:
            continue
        if unassigned_only and u["class_id"] is not None:
            continue
        c = classes.get(u["class_id"]) or store.get("classes", u["class_id"])
        u.pop("password_hash", None)
        u["class_name"] = c["name"] if c else None
        u["class_number"] = c["class_number"] if c else None
        out.append(u)
    return sorted(out, key=lambda u: u["full_name"].lower())


def create_student(teacher_id: int, username: str, password: str, full_name: str,
                   student_code: str = "", email: str = "", class_id: int | None = None) -> int:
    return _s().insert("users", {
        "username": _norm(username), "password_hash": hash_password(password), "full_name": _norm(full_name),
        "role": "student", "student_code": _norm(student_code), "email": _norm(email),
        "class_id": class_id, "created_by": teacher_id, "created_at": time.time(),
    })


def update_student(student_id: int, username: str, full_name: str, student_code: str,
                   email: str, class_id: int | None, new_password: str | None = None) -> None:
    fields = dict(username=_norm(username), full_name=_norm(full_name), student_code=_norm(student_code),
                  email=_norm(email), class_id=class_id)
    if new_password:
        fields["password_hash"] = hash_password(new_password)
    _s().update("users", student_id, **fields)


def set_student_class(student_ids: list[int], class_id: int | None) -> None:
    store = _s()
    with store.lock:
        for sid in student_ids:
            store.update("users", sid, class_id=class_id)


def delete_student(student_id: int) -> None:
    store = _s()
    with store.lock:
        session_ids = {s["id"] for s in store.where("practice_sessions", student_id=student_id)}
        if session_ids:
            store.delete("practice_items", lambda r: r["session_id"] in session_ids)
            store.delete("practice_sessions", lambda r: r["id"] in session_ids)
        store.delete("users", lambda r: r["id"] == student_id and r["role"] == "student")


# ---------------------------------------------------------------- question banks
def _clean_question(q: dict) -> dict:
    qtype = q["qtype"]
    answer = q["answer"]
    if qtype == "mcq":
        answer = int(answer)
    elif qtype == "tf":
        answer = [bool(x) for x in answer]
    else:
        answer = _norm(str(answer))
    return {
        "qtype": qtype, "topic": _norm(q.get("topic")), "level": q.get("level") or "biet",
        "question": _norm(q["question"]),
        "options": [_norm(str(o)) for o in (q.get("options") or [])] if qtype in ("mcq", "tf") else [],
        "answer": answer, "explanation": _norm(q.get("explanation")),
    }


def list_bank(teacher_id: int, qtype: str | None = None) -> list[dict]:
    rows = _s().where("question_bank", lambda r: qtype is None or r["qtype"] == qtype, teacher_id=teacher_id)
    return sorted(rows, key=lambda r: -(r["created_at"] or 0))


def get_bank_question(bank_id: int) -> dict | None:
    return _s().get("question_bank", bank_id)


def bank_counts(teacher_id: int | None) -> dict[str, int]:
    counts = {t: 0 for t in qs.QTYPES}
    if teacher_id is None:
        return counts
    for q in _s().where("question_bank", teacher_id=teacher_id):
        if q["qtype"] in counts:
            counts[q["qtype"]] += 1
    return counts


def add_to_bank(teacher_id: int, q: dict) -> int:
    """Insert a question into the bank of its type, skipping exact duplicates. Returns the bank id."""
    store = _s()
    clean = _clean_question(q)
    with store.lock:
        existing = store.where("question_bank", lambda r: r["question"] == clean["question"],
                               teacher_id=teacher_id, qtype=clean["qtype"])
        if existing:
            return existing[0]["id"]
        now = time.time()
        return store.insert("question_bank", {**clean, "teacher_id": teacher_id, "created_at": now, "updated_at": now})


def update_bank_question(bank_id: int, q: dict) -> None:
    _s().update("question_bank", bank_id, **_clean_question(q), updated_at=time.time())


def delete_bank_question(bank_id: int) -> None:
    _s().delete("question_bank", lambda r: r["id"] == bank_id)


# ---------------------------------------------------------------- practice sessions
def active_session(student_id: int) -> dict | None:
    rows = _s().where("practice_sessions", student_id=student_id, status="in_progress")
    return rows[0] if rows else None


def create_session(student_id: int, teacher_id: int, picked: list[dict], duration_minutes: int) -> int:
    """Create a practice session from bank questions (already sampled and ordered)."""
    store = _s()
    now = time.time()
    with store.lock:
        if active_session(student_id):
            raise ValueError("Em đang có một bài ôn tập chưa nộp.")
        session_id = store.insert("practice_sessions", {
            "student_id": student_id, "teacher_id": teacher_id,
            "qtypes": sorted({q["qtype"] for q in picked}, key=list(qs.QTYPES).index),
            "duration_minutes": int(duration_minutes), "started_at": now,
            "deadline": now + int(duration_minutes) * 60, "status": "in_progress", "total": len(picked),
        })
        store.insert_many("practice_items", [{
            "session_id": session_id, "position": i, "bank_id": q["id"], "qtype": q["qtype"],
            "topic": q["topic"], "level": q["level"], "question": q["question"], "options": q["options"],
            "answer": q["answer"], "explanation": q["explanation"],
        } for i, q in enumerate(picked)])
    return session_id


def get_session(session_id: int) -> dict | None:
    return _s().get("practice_sessions", session_id)


def session_items(session_id: int) -> list[dict]:
    return sorted(_s().where("practice_items", session_id=session_id), key=lambda r: r["position"])


def save_response(session_id: int, item_id: int, response) -> bool:
    """Persist one answer while the session is open. Returns False if the session is closed."""
    store = _s()
    with store.lock:
        s = store.get("practice_sessions", session_id)
        if not s or s["status"] != "in_progress" or time.time() > s["deadline"] + ANSWER_GRACE_SECONDS:
            return False
        store.update("practice_items", item_id, response=response)
        return True


def finalize_session(session_id: int, auto: bool) -> None:
    """Grade every item and mark the session submitted. Safe to call twice."""
    store = _s()
    with store.lock:
        s = store.get("practice_sessions", session_id)
        if not s or s["status"] != "in_progress":
            return
        correct = 0
        for item in session_items(session_id):
            ok, partial = qs.grade(item["qtype"], item["answer"], item["response"])
            correct += ok
            store.update("practice_items", item["id"], is_correct=ok, partial=partial)
        submitted_at = min(time.time(), s["deadline"]) if auto else time.time()
        store.update("practice_sessions", session_id, status="auto_submitted" if auto else "submitted",
                     correct=correct, submitted_at=submitted_at)


def expire_overdue_sessions() -> int:
    now = time.time()
    overdue = _s().where("practice_sessions",
                         lambda s: s["status"] == "in_progress" and s["deadline"] + ANSWER_GRACE_SECONDS < now)
    for s in overdue:
        finalize_session(s["id"], auto=True)
    return len(overdue)


def set_feedback(session_id: int, text: str) -> None:
    _s().update("practice_sessions", session_id, ai_feedback=text)


def list_sessions(student_id: int | None = None, teacher_id: int | None = None,
                  include_open: bool = False) -> list[dict]:
    store = _s()

    def keep(s: dict) -> bool:
        return ((student_id is None or s["student_id"] == student_id)
                and (teacher_id is None or s["teacher_id"] == teacher_id)
                and (include_open or s["status"] != "in_progress"))

    return sorted(store.where("practice_sessions", keep), key=lambda s: -(s["started_at"] or 0))


def items_for_sessions(session_ids: set[int]) -> list[dict]:
    return _s().where("practice_items", lambda r: r["session_id"] in session_ids)


def teacher_stats(teacher_id: int) -> dict:
    store = _s()
    sessions = list_sessions(teacher_id=teacher_id)
    week_ago = time.time() - 7 * 86400
    return {
        "classes": len(store.where("classes", teacher_id=teacher_id)),
        "students": len(list_students(teacher_id)),
        "banks": bank_counts(teacher_id),
        "sessions": len(sessions),
        "active_week": len({s["student_id"] for s in sessions if (s["started_at"] or 0) >= week_ago}),
    }


# ---------------------------------------------------------------- storage admin
def storage_info() -> dict:
    store = _s()
    return {
        "backend": store.backend.label,
        "url": getattr(store.backend, "url", None),
        "path": str(getattr(store.backend, "path", "")) or None,
        "pending": sorted(store.pending_tables),
        "last_flush_at": store.last_flush_at,
        "last_error": store.last_flush_error,
    }


def reload_storage() -> None:
    store = _s()
    store.flush()
    store.reload()
    _migrate(store)
