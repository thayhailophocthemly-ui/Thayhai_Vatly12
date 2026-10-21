"""Question types, cognitive levels, validation and grading."""

from __future__ import annotations

QTYPES = {
    "mcq": "Trắc nghiệm nhiều lựa chọn",
    "tf": "Trắc nghiệm đúng sai",
    "short": "Trắc nghiệm trả lời ngắn",
}
QTYPE_ICONS = {"mcq": "🔘", "tf": "✅", "short": "✍️"}
LEVELS = {"biet": "Biết", "hieu": "Hiểu", "vandung": "Vận dụng"}
LETTERS = "ABCD"
TF_LETTERS = "abcd"
GRADE = "Lớp 12"
# Chủ đề Vật lý 12 - Chương trình GDPT 2018
TOPICS_12 = ["Vật lí nhiệt", "Khí lí tưởng", "Từ trường", "Vật lí hạt nhân và phóng xạ"]


def qtype_label(qtype: str | None) -> str:
    return QTYPES.get(qtype or "", qtype or "")


def level_label(level: str | None) -> str:
    return LEVELS.get(level or "", level or "")


def empty_question(qtype: str) -> dict:
    return {
        "qtype": qtype, "topic": "", "level": "biet", "question": "",
        "options": ["", "", "", ""] if qtype in ("mcq", "tf") else [],
        "answer": 0 if qtype == "mcq" else [True, True, True, True] if qtype == "tf" else "",
        "explanation": "",
    }


def validate(q: dict) -> str | None:
    """Return an error message (Vietnamese) or None when the question is well-formed."""
    if q.get("qtype") not in QTYPES:
        return "Loại câu hỏi không hợp lệ."
    if q.get("level") not in LEVELS:
        return "Mức độ tư duy không hợp lệ."
    if not str(q.get("question") or "").strip():
        return "Vui lòng nhập nội dung câu hỏi."
    if q["qtype"] in ("mcq", "tf"):
        opts = q.get("options") or []
        if len(opts) != 4 or any(not str(o).strip() for o in opts):
            return "Cần nhập đủ 4 phương án." if q["qtype"] == "mcq" else "Cần nhập đủ 4 ý a, b, c, d."
    if q["qtype"] == "mcq" and not (isinstance(q.get("answer"), int) and 0 <= q["answer"] < 4):
        return "Chọn đáp án đúng."
    if q["qtype"] == "tf" and not (isinstance(q.get("answer"), list) and len(q["answer"]) == 4
                                   and all(isinstance(x, bool) for x in q["answer"])):
        return "Chọn Đúng/Sai cho cả 4 ý."
    if q["qtype"] == "short" and not str(q.get("answer") or "").strip():
        return "Vui lòng nhập đáp án."
    return None


def _to_number(text: str) -> float | None:
    cleaned = str(text).strip().replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def short_matches(expected: str, given: str | None) -> bool:
    if given is None or not str(given).strip():
        return False
    a, b = _to_number(expected), _to_number(given)
    if a is not None and b is not None:
        return abs(a - b) <= 1e-9 * max(1.0, abs(a))
    return str(expected).strip().lower() == str(given).strip().lower()


def grade(qtype: str, answer, response) -> tuple[bool, int]:
    """Return (is_correct, partial). partial = number of correct statements for tf, else 0/1."""
    if qtype == "mcq":
        ok = response is not None and response == answer
        return ok, int(ok)
    if qtype == "tf":
        resp = response if isinstance(response, list) else [None] * 4
        hits = sum(1 for r, a in zip(resp, answer) if r is not None and r == a)
        return hits == 4, hits
    ok = short_matches(str(answer), response)
    return ok, int(ok)


def is_answered(qtype: str, response) -> bool:
    if qtype == "tf":
        return isinstance(response, list) and any(r is not None for r in response)
    if qtype == "short":
        return bool(str(response or "").strip())
    return response is not None


def answer_text(q: dict) -> str:
    """Human-readable correct answer."""
    if q["qtype"] == "mcq":
        return LETTERS[q["answer"]]
    if q["qtype"] == "tf":
        return ", ".join(f"{TF_LETTERS[i]}) {'Đúng' if v else 'Sai'}" for i, v in enumerate(q["answer"]))
    return str(q["answer"])


def response_text(q: dict, response) -> str:
    if not is_answered(q["qtype"], response):
        return "(chưa trả lời)"
    if q["qtype"] == "mcq":
        return LETTERS[response]
    if q["qtype"] == "tf":
        return ", ".join(f"{TF_LETTERS[i]}) {'—' if v is None else 'Đúng' if v else 'Sai'}"
                         for i, v in enumerate(response))
    return str(response)


def as_text(q: dict) -> str:
    """Plain-text rendering of a question (used in AI prompts)."""
    lines = [f"[{qtype_label(q['qtype'])} · {level_label(q.get('level'))} · {q.get('topic') or ''}]", q["question"]]
    if q["qtype"] == "mcq":
        lines += [f"{LETTERS[i]}. {o}" for i, o in enumerate(q["options"])]
    elif q["qtype"] == "tf":
        lines += [f"{TF_LETTERS[i]}) {o}" for i, o in enumerate(q["options"])]
    lines.append(f"Đáp án: {answer_text(q)}")
    return "\n".join(lines)
