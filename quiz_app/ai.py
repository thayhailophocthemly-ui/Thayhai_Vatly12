"""Google Gemini integration: exam-matrix analysis, question generation, feedback and tutoring chat.

All AI output is in Vietnamese and targets Vật lý lớp 12 (Chương trình GDPT 2018).
"""

from __future__ import annotations

import io
import json
import math
import os
import re

import streamlit as st

from . import questions as qs

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_PER_CALL = 12  # questions per generation request (keeps responses well-formed)
MAX_MATRIX_CHARS = 60_000


class AIError(RuntimeError):
    pass


# ------------------------------------------------------------------ config
def secret(key: str) -> str | None:
    try:
        value = st.secrets.get(key)
    except Exception:
        value = None
    return value or os.environ.get(key)


def get_api_key() -> str | None:
    return st.session_state.get("gemini_api_key_override") or secret("GEMINI_API_KEY")


def get_model() -> str:
    return st.session_state.get("gemini_model_override") or secret("GEMINI_MODEL") or DEFAULT_MODEL


_CLIENTS: dict = {}  # one client per API key; it must stay referenced or its HTTP session is closed


def _client():
    api_key = get_api_key()
    if not api_key:
        raise AIError("Chưa cấu hình khóa API Gemini. Hãy thêm GEMINI_API_KEY vào .streamlit/secrets.toml "
                      "hoặc nhập khóa trong mục Cài đặt.")
    try:
        from google import genai
    except ImportError as exc:
        raise AIError("Chưa cài thư viện 'google-genai'. Hãy chạy: python -m pip install google-genai") from exc
    if api_key not in _CLIENTS:
        _CLIENTS[api_key] = genai.Client(api_key=api_key)
    return _CLIENTS[api_key]


def _generate(contents, *, schema: dict | None = None, system: str | None = None, temperature: float = 0.7):
    from google.genai import types

    kwargs: dict = {"temperature": temperature}
    if system:
        kwargs["system_instruction"] = system
    if schema is not None:
        kwargs.update(response_mime_type="application/json", response_schema=schema)
    config = types.GenerateContentConfig(**kwargs)
    try:
        response = _client().models.generate_content(model=get_model(), contents=contents, config=config)
    except AIError:
        raise
    except Exception as exc:
        raise AIError(f"Gọi Gemini thất bại: {exc}") from exc
    text = response.text or ""
    if schema is None:
        return text.strip()
    try:
        return json.loads(text or "null")
    except json.JSONDecodeError as exc:
        raise AIError("Gemini trả về dữ liệu không hợp lệ. Vui lòng thử lại.") from exc


# ------------------------------------------------------------------ exam matrix
def _docx_text(data: bytes) -> str:
    """Paragraphs and tables of a .docx in document order (tables as 'a | b | c' rows)."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    lines: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = Paragraph(child, doc).text.strip()
            if text:
                lines.append(text)
        elif tag == "tbl":
            lines.append("[BẢNG]")
            for row in Table(child, doc).rows:
                # Merged cells are repeated in every grid column they span, which keeps each
                # number aligned under its "Phần ... / mức độ" header.
                lines.append(" | ".join(" ".join(cell.text.split()) for cell in row.cells))
            lines.append("[HẾT BẢNG]")
    return "\n".join(lines)


def matrix_parts(filename: str, data: bytes) -> list:
    """Turn an uploaded PDF/Word file into Gemini content parts."""
    from google.genai import types

    name = filename.lower()
    if name.endswith(".pdf"):
        return [types.Part.from_bytes(data=data, mime_type="application/pdf")]
    if name.endswith(".docx"):
        try:
            text = _docx_text(data)
        except Exception as exc:
            raise AIError(f"Không đọc được file Word: {exc}") from exc
        if not text.strip():
            raise AIError("File Word không có nội dung.")
        return [f"NỘI DUNG FILE MA TRẬN ĐỀ ({filename}):\n{text[:MAX_MATRIX_CHARS]}"]
    if name.endswith(".doc"):
        raise AIError("Định dạng .doc cũ không được hỗ trợ. Hãy mở file trong Word và lưu lại dưới dạng .docx hoặc PDF.")
    raise AIError("Chỉ hỗ trợ file PDF (.pdf) hoặc Word (.docx).")


_PART_QTYPE = {"I": "mcq", "II": "tf", "III": "short"}
_CELL_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "part": {"type": "STRING", "enum": list(_PART_QTYPE)},
            "topic": {"type": "STRING"},
            "requirement": {"type": "STRING"},
            "level": {"type": "STRING", "enum": list(qs.LEVELS)},
            "number": {"type": "NUMBER"},
            "unit": {"type": "STRING", "enum": ["cau", "y", "diem"]},
        },
        "required": ["part", "topic", "requirement", "level", "number", "unit"],
    },
}

_PLAN_PROMPT = """Bạn là chuyên gia khảo thí môn Vật lí THPT ở Việt Nam. Tài liệu kèm theo là MA TRẬN ĐỀ KIỂM TRA
(có thể kèm bản đặc tả) môn Vật lí lớp 12, định dạng đề từ năm 2025 gồm:
- Phần I: Trắc nghiệm nhiều lựa chọn.  - Phần II: Trắc nghiệm đúng sai (mỗi câu 4 ý).  - Phần III: Trắc nghiệm trả lời ngắn.
Mức độ tư duy: "biet" (Biết / Nhận biết), "hieu" (Hiểu / Thông hiểu), "vandung" (Vận dụng / Vận dụng cao).

NHIỆM VỤ: CHÉP LẠI CHÍNH XÁC từng ô số liệu khác 0 trong ma trận, KHÔNG tính toán, KHÔNG gộp, KHÔNG suy diễn.
Cách làm:
1. Xác định mỗi cột số liệu thuộc Phần nào (I, II hay III) và mức độ tư duy nào.
2. Duyệt LẦN LƯỢT từng dòng chủ đề/nội dung, từng cột; với MỖI ô có giá trị > 0, trả về một phần tử:
   - part: "I", "II" hoặc "III"
   - topic: tên chủ đề/nội dung của dòng đó (ngắn gọn, đúng như ma trận)
   - requirement: yêu cầu cần đạt / đơn vị kiến thức nếu có ghi (từ ma trận hoặc bản đặc tả), nếu không có thì ""
   - level: mức độ tư duy của cột
   - number: con số trong ô
   - unit: "cau" nếu ô ghi số câu; "y" nếu ô ghi số ý/lệnh hỏi (thường gặp ở Phần II); "diem" nếu ô ghi số điểm
3. Bỏ qua các dòng/cột tổng cộng, tỉ lệ %, và ô trống hoặc bằng 0. Không bỏ sót ô nào của cả ba phần.
"""


def _plan_from_cells(cells: list[dict]) -> list[dict]:
    """Deterministic conversion of transcribed matrix cells into question counts per plan row."""
    rows: dict[tuple, dict] = {}

    def add(qtype: str, topic: str, requirement: str, level: str, count: int) -> None:
        if count <= 0:
            return
        row = rows.setdefault((qtype, topic, level), {"qtype": qtype, "topic": topic, "requirement": "",
                                                      "level": level, "count": 0})
        row["count"] += count
        if requirement and requirement not in row["requirement"]:
            row["requirement"] = "; ".join(x for x in (row["requirement"], requirement) if x)

    tf_statements: dict[str, dict] = {}  # topic -> {"levels": {level: n}, "req": str}
    for c in cells:
        try:
            part, level, unit, number = c["part"], c["level"], c["unit"], float(c["number"])
            topic, req = str(c["topic"]).strip(), str(c.get("requirement") or "").strip()
        except (KeyError, TypeError, ValueError):
            continue
        if part not in _PART_QTYPE or level not in qs.LEVELS or number <= 0 or not topic:
            continue
        qtype = _PART_QTYPE[part]
        if qtype == "tf" and unit == "y":
            entry = tf_statements.setdefault(topic, {"levels": {}, "req": ""})
            entry["levels"][level] = entry["levels"].get(level, 0) + number
            entry["req"] = "; ".join(x for x in (entry["req"], req) if x)
            continue
        if unit == "diem":  # 2025 format: Phần I 0,25đ/câu, Phần II 1đ/câu, Phần III 0,25đ/câu
            count = round(number / (1.0 if qtype == "tf" else 0.25))
        else:
            count = round(number)
        add(qtype, topic, req, level, count)

    order = list(qs.LEVELS)
    for topic, entry in tf_statements.items():
        total = sum(entry["levels"].values())
        # Level holding most statements; ties go to the higher cognitive level.
        level = max(entry["levels"], key=lambda lv: (entry["levels"][lv], order.index(lv)))
        add("tf", topic, entry["req"], level, math.ceil(total / 4))

    qorder = list(qs.QTYPES)
    return sorted(rows.values(), key=lambda r: (qorder.index(r["qtype"]), r["topic"], order.index(r["level"])))


def analyze_matrix(filename: str, data: bytes, notes: str = "") -> list[dict]:
    contents = matrix_parts(filename, data) + [_PLAN_PROMPT + (f"\nGhi chú của giáo viên: {notes}" if notes.strip() else "")]
    raw = _generate(contents, schema=_CELL_SCHEMA, temperature=0.0)
    plan = _plan_from_cells(raw if isinstance(raw, list) else [])
    if not plan:
        raise AIError("Không phân tích được ma trận đề. Hãy kiểm tra file hoặc nhập kế hoạch thủ công.")
    return plan


# ------------------------------------------------------------------ question generation
_Q_SCHEMAS = {
    "mcq": {
        "question": {"type": "STRING"},
        "options": {"type": "ARRAY", "items": {"type": "STRING"}},
        "correct_index": {"type": "INTEGER"},
    },
    "tf": {
        "question": {"type": "STRING"},
        "statements": {"type": "ARRAY", "items": {"type": "STRING"}},
        "truths": {"type": "ARRAY", "items": {"type": "BOOLEAN"}},
    },
    "short": {
        "question": {"type": "STRING"},
        "answer": {"type": "STRING"},
    },
}

_TYPE_RULES = {
    "mcq": """Dạng: TRẮC NGHIỆM NHIỀU LỰA CHỌN.
- `options`: đúng 4 phương án, KHÔNG ghi chữ "A.", "B." ở đầu. `correct_index`: chỉ số (0-3) của phương án đúng duy nhất.
- Phương án nhiễu hợp lí (sai lầm thường gặp: nhầm đơn vị, nhầm công thức, sai dấu...). Thay đổi vị trí đáp án đúng giữa các câu.""",
    "tf": """Dạng: TRẮC NGHIỆM ĐÚNG SAI (định dạng đề thi 2025).
- `question`: phần dẫn (tình huống, thí nghiệm, đồ thị mô tả bằng lời, số liệu...).
- `statements`: đúng 4 ý a, b, c, d (KHÔNG ghi "a)" ở đầu), mỗi ý là một khẳng định có thể Đúng hoặc Sai, độ khó tăng dần từ a đến d.
- `truths`: 4 giá trị true/false tương ứng. Nên có cả ý đúng và ý sai.""",
    "short": """Dạng: TRẮC NGHIỆM TRẢ LỜI NGẮN (định dạng đề thi 2025).
- Đáp án là MỘT SỐ, tối đa 4 kí tự kể cả dấu "-" và dấu phẩy (ví dụ: 12, 0,25, -1,5, 2500).
- Đề bài phải nói rõ đơn vị và cách làm tròn (ví dụ "làm tròn đến hàng phần mười").
- `answer`: chỉ ghi con số, dùng dấu phẩy thập phân, không ghi đơn vị.""",
}

_COMMON_RULES = """Yêu cầu chung:
1. Đối tượng: học sinh lớp 12, Chương trình Vật lí GDPT 2018. Toàn bộ nội dung bằng tiếng Việt, dùng thuật ngữ như trong SGK
   (ví dụ "nội năng", "nhiệt dung riêng", "áp suất", "cảm ứng từ", "độ phóng xạ", "chu kì bán rã").
2. Bám sát chủ đề, yêu cầu cần đạt và MỨC ĐỘ TƯ DUY của từng dòng kế hoạch:
   - Biết: nhận biết, nhắc lại khái niệm, định luật, công thức, đơn vị.
   - Hiểu: giải thích, so sánh, vận dụng trực tiếp một công thức.
   - Vận dụng: giải quyết tình huống thực tế, bài toán nhiều bước.
3. Viết công thức bằng LaTeX đặt giữa dấu $...$, ví dụ $pV = nRT$, $\\Delta U = A + Q$. Dùng dấu phẩy thập phân, trong LaTeX viết {,}
   (ví dụ $1{,}5\\,\\text{atm}$). Không dùng ký tự $ cho mục đích khác.
   Trong chuỗi JSON, MỖI dấu \\ của LaTeX phải viết thành \\\\ (ví dụ "\\\\frac", "\\\\text", "\\\\times").
4. `explanation`: lời giải ngắn gọn (2-5 câu) bằng tiếng Việt, nêu rõ vì sao đáp án đúng.
5. Kiểm tra kĩ mọi phép tính; đáp án phải chính xác. Không trùng lặp câu hỏi.
6. Ghi `topic` và `level` đúng như dòng kế hoạch mà câu hỏi thuộc về."""


def _q_schema(qtype: str) -> dict:
    props = dict(_Q_SCHEMAS[qtype])
    props["explanation"] = {"type": "STRING"}
    props["topic"] = {"type": "STRING"}
    props["level"] = {"type": "STRING", "enum": list(qs.LEVELS)}
    return {"type": "ARRAY", "items": {"type": "OBJECT", "properties": props, "required": list(props)}}


# A LaTeX command written with a single backslash inside JSON ("\text", "\frac", "\times", "\beta", "\rho")
# decodes to a control character + letters. Restore the backslash.
_CONTROL_LATEX = re.compile(r"[\t\f\b\r](?=[A-Za-z])")
_CONTROL_NAMES = {"\t": "\\t", "\f": "\\f", "\b": "\\b", "\r": "\\r"}
_NEWLINE_LATEX = re.compile(r"\n(?=(?:nu|neq|ne|nabla|not|neg|ni|newline)\b)")


def _fix_latex(text: str) -> str:
    text = _CONTROL_LATEX.sub(lambda m: _CONTROL_NAMES[m.group(0)], text)
    return _NEWLINE_LATEX.sub(lambda m: "\\n", text) if "$" in text else text


def _to_question(qtype: str, item: dict) -> dict | None:
    try:
        q = {"qtype": qtype, "topic": str(item.get("topic") or "").strip(), "level": item.get("level"),
             "question": str(item["question"]).strip(), "explanation": str(item.get("explanation") or "").strip()}
        if qtype == "mcq":
            q["options"] = [str(o).strip() for o in item["options"]][:4]
            q["answer"] = int(item["correct_index"])
        elif qtype == "tf":
            q["options"] = [str(o).strip() for o in item["statements"]][:4]
            q["answer"] = [bool(x) for x in item["truths"]][:4]
        else:
            q["options"] = []
            q["answer"] = str(item["answer"]).strip()
    except (KeyError, TypeError, ValueError):
        return None
    q["question"], q["explanation"] = _fix_latex(q["question"]), _fix_latex(q["explanation"])
    q["options"] = [_fix_latex(o) for o in q["options"]]
    return q if qs.validate(q) is None else None


def _chunks(rows: list[dict]) -> list[list[dict]]:
    """Split plan rows into requests of at most MAX_PER_CALL questions."""
    out, current, size = [], [], 0
    for row in rows:
        remaining = row["count"]
        while remaining > 0:
            take = min(remaining, MAX_PER_CALL - size)
            current.append({**row, "count": take})
            size += take
            remaining -= take
            if size >= MAX_PER_CALL:
                out.append(current)
                current, size = [], 0
    if current:
        out.append(current)
    return out


def _plan_text(rows: list[dict]) -> str:
    return "\n".join(
        f"- {r['count']} câu · chủ đề: {r['topic']} · mức độ: {qs.level_label(r['level'])} (level=\"{r['level']}\")"
        + (f" · yêu cầu cần đạt: {r['requirement']}" if r.get("requirement") else "")
        for r in rows)


_SOLVE_FIELDS = {
    "mcq": ("correct_index: chỉ số 0-3 của phương án đúng.", {"correct_index": {"type": "INTEGER"}}),
    "tf": ("truths: 4 giá trị true/false cho các ý a, b, c, d.",
           {"truths": {"type": "ARRAY", "items": {"type": "BOOLEAN"}}}),
    "short": ("answer: chỉ ghi con số, dấu phẩy thập phân, đúng cách làm tròn đề yêu cầu.",
              {"answer": {"type": "STRING"}}),
}


def _disagreement(q: dict, solved: dict) -> str | None:
    """Describe the independently solved answer when it differs from the question's answer key."""
    if q["qtype"] == "mcq":
        idx = int(solved["correct_index"])
        return None if idx == q["answer"] else f"phương án {qs.LETTERS[idx]}"
    if q["qtype"] == "tf":
        truths = [bool(x) for x in solved["truths"]][:4]
        if len(truths) != 4 or truths == q["answer"]:
            return None
        return ", ".join(f"{qs.TF_LETTERS[j]}) {'Đúng' if v else 'Sai'}" for j, v in enumerate(truths))
    return None if qs.short_matches(q["answer"], str(solved["answer"])) else str(solved["answer"])


def verify_answers(questions: list[dict]) -> None:
    """Gemini solves each question again with the answer hidden; disagreements are flagged for the teacher.

    Sets q["ai_check"] to the differing answer (text), or None when both agree. Best-effort: on any
    failure the questions are simply left unflagged.
    """
    by_type: dict[str, list[dict]] = {}
    for q in questions:
        by_type.setdefault(q["qtype"], []).append(q)
    for qtype, group in by_type.items():
        blocks = []
        for i, q in enumerate(group):
            lines = [f"### Câu {i}", q["question"]]
            if qtype == "mcq":
                lines += [f"{qs.LETTERS[j]}. {o}" for j, o in enumerate(q["options"])]
            elif qtype == "tf":
                lines += [f"{qs.TF_LETTERS[j]}) {o}" for j, o in enumerate(q["options"])]
            blocks.append("\n".join(lines))
        hint, fields = _SOLVE_FIELDS[qtype]
        props = {"index": {"type": "INTEGER"}, **fields}
        schema = {"type": "ARRAY", "items": {"type": "OBJECT", "properties": props, "required": list(props)}}
        prompt = (f"Bạn là giáo viên Vật lí giỏi. Hãy tự giải thật cẩn thận từng câu "
                  f"{qs.qtype_label(qtype).lower()} dưới đây (tính từng bước, kiểm tra đơn vị và cách làm tròn), "
                  f"rồi trả về đáp án của bạn.\n{hint}\n`index` là số thứ tự ghi ở tiêu đề mỗi câu.\n\n"
                  + "\n\n".join(blocks))
        try:
            raw = _generate(prompt, schema=schema, temperature=0.0)
        except AIError:
            continue
        solved = {r.get("index"): r for r in raw if isinstance(r, dict)} if isinstance(raw, list) else {}
        for i, q in enumerate(group):
            q["ai_check"] = None
            if i in solved:
                try:
                    q["ai_check"] = _disagreement(q, solved[i])
                except (KeyError, TypeError, ValueError, IndexError):
                    pass


def generate_from_plan(plan: list[dict], notes: str = "", progress=None) -> list[dict]:
    """Generate questions for every plan row. `progress(done, total)` is called after each request."""
    jobs = [(qtype, chunk) for qtype in qs.QTYPES
            for chunk in _chunks([r for r in plan if r["qtype"] == qtype and r["count"] > 0])]
    if not jobs:
        raise AIError("Kế hoạch ra đề chưa có câu hỏi nào.")
    out: list[dict] = []
    for n, (qtype, rows) in enumerate(jobs, start=1):
        need = sum(r["count"] for r in rows)
        prompt = (f"Bạn là giáo viên Vật lí THPT giàu kinh nghiệm ở Việt Nam. Hãy soạn đúng {need} câu hỏi.\n\n"
                  f"{_TYPE_RULES[qtype]}\n\nKế hoạch (số câu theo từng dòng):\n{_plan_text(rows)}\n\n{_COMMON_RULES}"
                  + (f"\n\nYêu cầu thêm của giáo viên: {notes}" if notes.strip() else ""))
        got: list[dict] = []
        for _ in range(2):  # one retry for any shortfall
            missing = need - len(got)
            if missing <= 0:
                break
            extra = "" if not got else (f"\n\nChỉ cần soạn thêm {missing} câu, không trùng các câu sau:\n"
                                        + "\n".join(f"- {q['question'][:150]}" for q in got))
            raw = _generate(prompt + extra, schema=_q_schema(qtype))
            got += [q for q in (_to_question(qtype, it) for it in (raw if isinstance(raw, list) else [])) if q][:missing]
        verify_answers(got)
        out += got
        if progress:
            progress(n, len(jobs))
    if not out:
        raise AIError("Gemini không trả về câu hỏi hợp lệ nào. Vui lòng thử lại.")
    return out


def convert_question(q: dict, target: str) -> dict:
    """Rewrite a question as another type (same topic, level and knowledge)."""
    prompt = (f"Bạn là giáo viên Vật lí THPT. Hãy chuyển câu hỏi dưới đây sang dạng khác, giữ nguyên chủ đề "
              f"\"{q.get('topic') or ''}\", mức độ tư duy level=\"{q.get('level')}\" và kiến thức được kiểm tra.\n\n"
              f"Câu hỏi gốc:\n{qs.as_text(q)}\n\n{_TYPE_RULES[target]}\n\n{_COMMON_RULES}\n\nTrả về đúng 1 câu hỏi.")
    raw = _generate(prompt, schema=_q_schema(target))
    for item in raw if isinstance(raw, list) else []:
        converted = _to_question(target, item)
        if converted:
            converted["topic"] = converted["topic"] or q.get("topic", "")
            verify_answers([converted])
            return converted
    raise AIError("Không chuyển được dạng câu hỏi. Vui lòng thử lại.")


# ------------------------------------------------------------------ feedback & tutoring
def _accuracy_lines(items: list[dict], key: str, label) -> list[str]:
    groups: dict[str, list[bool]] = {}
    for it in items:
        groups.setdefault(it.get(key) or "khác", []).append(bool(it["is_correct"]))
    return [f"  - {label(k)}: {sum(v)}/{len(v)} câu đúng" for k, v in groups.items()]


def feedback(student_name: str, items: list[dict], history: list[dict]) -> str:
    """`items`: graded items of the current session. `history`: older sessions, each with its items."""
    wrong = [it for it in items if not it["is_correct"]]
    current = [f"Kết quả lần này: {sum(1 for i in items if i['is_correct'])}/{len(items)} câu đúng.",
               "Theo dạng câu hỏi:", *_accuracy_lines(items, "qtype", qs.qtype_label),
               "Theo mức độ tư duy:", *_accuracy_lines(items, "level", qs.level_label),
               "Theo chủ đề:", *_accuracy_lines(items, "topic", str)]
    if wrong:
        current.append("Một số câu làm sai / chưa làm:")
        current += [f"  - [{qs.qtype_label(it['qtype'])} · {qs.level_label(it['level'])} · {it['topic']}] "
                    f"{it['question'][:160]}" for it in wrong[:8]]
    past = []
    for h in history[:10]:
        line = f"- {h['date']}: {h['correct']}/{h['total']} câu đúng"
        if h.get("items"):
            line += "; theo chủ đề: " + "; ".join(x.strip(" -") for x in _accuracy_lines(h["items"], "topic", str))
        past.append(line)
    prompt = f"""Bạn là giáo viên Vật lí lớp 12 tận tâm. Hãy nhận xét bài ôn tập của học sinh {student_name}.

{chr(10).join(current)}

Lịch sử các lần ôn tập trước (mới nhất trước):
{chr(10).join(past) if past else "(đây là lần ôn tập đầu tiên)"}

Viết nhận xét bằng tiếng Việt, xưng "thầy/cô" và gọi học sinh là "em", tối đa khoảng 220 từ, dùng Markdown với đúng 4 mục:
**Ưu điểm** — kiến thức/dạng câu/mức độ em làm tốt.
**Hạn chế** — lỗ hổng kiến thức cụ thể (nêu chủ đề, mức độ tư duy).
**Sự tiến bộ** — so sánh với các lần trước (nếu là lần đầu thì nói rõ).
**Gợi ý ôn tập** — 2-3 việc cụ thể nên làm tiếp theo.
Chỉ dựa trên số liệu được cung cấp, không bịa thêm."""
    return _generate(prompt, temperature=0.5)


def chat_reply(item: dict, response, history: list[dict], message: str) -> str:
    """Tutoring chat about one practice question. `history`: [{'role': 'user'|'assistant', 'content': str}]."""
    system = f"""Bạn là gia sư Vật lí lớp 12 thân thiện, kiên nhẫn. Học sinh vừa làm câu hỏi sau và muốn hỏi thêm.

{qs.as_text(item)}
Lời giải tham khảo: {item.get('explanation') or '(không có)'}
Câu trả lời của học sinh: {qs.response_text(item, response)}

Quy tắc: trả lời bằng tiếng Việt, gọi học sinh là "em", ngắn gọn, giải thích từng bước, dùng LaTeX trong $...$ cho công thức.
Chỉ trao đổi về câu hỏi này và kiến thức Vật lí liên quan; nếu em hỏi chuyện khác, nhẹ nhàng hướng em quay lại bài học."""
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
                for m in history[-12:]]
    contents.append({"role": "user", "parts": [{"text": message}]})
    return _generate(contents, system=system, temperature=0.4)


def estimated_requests(plan: list[dict]) -> int:
    return sum(math.ceil(sum(r["count"] for r in plan if r["qtype"] == t) / MAX_PER_CALL) for t in qs.QTYPES)
