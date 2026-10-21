import random
import time

import streamlit as st

from .. import db, nav, ui
from .. import questions as qs

MAX_MINUTES = 60
MAX_QUESTIONS = 60
WARN_SECONDS = 5 * 60
DANGER_SECONDS = 60
DEFAULT_COUNTS = {"mcq": 12, "tf": 4, "short": 6}
PART_TITLES = {"mcq": "Phần I. Trắc nghiệm nhiều lựa chọn", "tf": "Phần II. Trắc nghiệm đúng sai",
               "short": "Phần III. Trắc nghiệm trả lời ngắn"}


# ------------------------------------------------------------------ answer widgets <-> storage
def _key(item_id: int, j: int | None = None) -> str:
    return f"pa_{item_id}" if j is None else f"pa_{item_id}_{j}"


def _widget_response(item: dict):
    if item["qtype"] == "tf":
        vals = [st.session_state.get(_key(item["id"], j)) for j in range(4)]
        return [None if v is None else v == "Đúng" for v in vals]
    value = st.session_state.get(_key(item["id"]))
    if item["qtype"] == "short":
        return (value or "").strip() or None
    return value


def _restore(item: dict) -> None:
    """Seed widget state from saved answers (after refresh / re-login)."""
    resp = item["response"]
    if item["qtype"] == "tf":
        resp = resp if isinstance(resp, list) else [None] * 4
        for j in range(4):
            k = _key(item["id"], j)
            if k not in st.session_state:
                st.session_state[k] = None if resp[j] is None else ("Đúng" if resp[j] else "Sai")
    else:
        k = _key(item["id"])
        if k not in st.session_state:
            st.session_state[k] = resp if item["qtype"] == "mcq" else (resp or "")


def _on_change(session_id: int, item: dict) -> None:
    if not db.save_response(session_id, item["id"], _widget_response(item)):
        st.session_state["practice_locked_notice"] = True


def _save_all(session_id: int, items: list[dict]) -> None:
    for item in items:
        db.save_response(session_id, item["id"], _widget_response(item))


# ------------------------------------------------------------------ dialogs
@st.dialog("Nộp bài")
def _submit_dialog(session_id: int, items: list[dict], answered: int) -> None:
    total = len(items)
    if answered < total:
        st.warning(f"Em mới trả lời **{answered}/{total}** câu. Câu chưa trả lời được tính là sai.", icon="⚠️")
    else:
        st.success(f"Em đã trả lời đủ {total} câu.", icon="✅")
    st.write("Nộp bài ngay bây giờ? Sau khi nộp em không thể sửa câu trả lời.")
    c1, c2 = st.columns(2)
    if c1.button("Làm tiếp", width="stretch"):
        st.rerun()
    if c2.button("Nộp bài", type="primary", width="stretch"):
        _save_all(session_id, items)
        db.finalize_session(session_id, auto=False)
        _go_result(session_id, "Đã nộp bài! 🎉")


def _go_result(session_id: int, message: str) -> None:
    st.session_state["history_session_id"] = session_id
    ui.flash(message, "📨")
    st.switch_page(nav.page("history"))


# ------------------------------------------------------------------ page
def render() -> None:
    user = ui.require_role("student")
    if st.session_state.pop("goto_history", False):
        st.switch_page(nav.page("history"))
    db.expire_overdue_sessions()
    session = db.active_session(user["id"])
    if session:
        _take(session)
    else:
        _create(user)


def _create(user: dict) -> None:
    ui.hero(f"📝 Chào {user['full_name']}", f"Tạo bài ôn tập Vật lí {qs.GRADE} từ kho đề của thầy/cô.")
    teacher_id = db.teacher_of_student(user["id"])
    bank = db.list_bank(teacher_id) if teacher_id else []
    if not bank:
        st.info("Thầy/cô chưa đưa câu hỏi nào vào kho đề. Em quay lại sau nhé!", icon="📭")
        return

    st.markdown("#### 1 · Chọn kho đề và số câu")
    topics = sorted({q["topic"] for q in bank if q["topic"]})
    with st.expander("Lọc theo chủ đề / mức độ (không bắt buộc)"):
        f_topics = st.multiselect("Chủ đề", topics, placeholder="Tất cả chủ đề")
        f_levels = st.multiselect("Mức độ tư duy", list(qs.LEVELS), format_func=qs.level_label,
                                  placeholder="Tất cả mức độ")
    pool = [q for q in bank if (not f_topics or q["topic"] in f_topics) and (not f_levels or q["level"] in f_levels)]

    counts: dict[str, int] = {}
    for qtype, label in qs.QTYPES.items():
        available = sum(1 for q in pool if q["qtype"] == qtype)
        with st.container(border=True):
            c1, c2 = st.columns([2, 1], vertical_alignment="center")
            use = c1.checkbox(f"{qs.QTYPE_ICONS[qtype]} **{label}**  \n{available} câu có sẵn",
                              key=f"pc_use_{qtype}", disabled=available == 0)
            if use and available:
                counts[qtype] = c2.number_input("Số câu", 1, available, min(DEFAULT_COUNTS[qtype], available),
                                                key=f"pc_n_{qtype}")
    total = sum(counts.values())

    st.markdown("#### 2 · Thời gian làm bài")
    minutes = st.slider("Thời gian (phút)", 5, MAX_MINUTES, 45, step=5, label_visibility="collapsed",
                        format="%d phút")

    if total > MAX_QUESTIONS:
        st.warning(f"Mỗi bài ôn tập tối đa {MAX_QUESTIONS} câu.")
    if st.button(f"Bắt đầu ôn tập ({total} câu · {minutes} phút)", type="primary", icon="▶️", width="stretch",
                 disabled=total == 0 or total > MAX_QUESTIONS):
        picked = []
        for qtype in qs.QTYPES:  # Phần I -> II -> III, random order inside each part
            if counts.get(qtype):
                picked += random.sample([q for q in pool if q["qtype"] == qtype], counts[qtype])
        try:
            db.create_session(user["id"], teacher_id, picked, minutes)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.rerun()


def _take(session: dict) -> None:
    if time.time() >= session["deadline"]:
        db.finalize_session(session["id"], auto=True)
        _go_result(session["id"], "Hết giờ — bài của em đã được tự động nộp.")
    items = db.session_items(session["id"])

    ui.hero("📝 Bài ôn tập", f"{len(items)} câu · {session['duration_minutes']} phút · {ui.fmt_time(session['started_at'])}")
    st.caption("Câu trả lời được lưu tự động. Khi hết giờ, bài sẽ được tự động nộp.")
    if st.session_state.pop("practice_locked_notice", False):
        st.error("Bài đã hết giờ — thay đổi gần nhất của em không được lưu.")

    _timer(session["id"], session["deadline"], items)

    current = None
    for n, item in enumerate(items, start=1):
        if item["qtype"] != current:
            current = item["qtype"]
            st.subheader(PART_TITLES[current])
        _restore(item)
        with st.container(border=True):
            st.markdown(f"**Câu {n}**")
            st.markdown(item["question"])
            if item["qtype"] == "mcq":
                st.radio(f"Câu {n}", options=list(range(4)),
                         format_func=lambda j, o=item["options"]: f"**{qs.LETTERS[j]}.** {o[j]}",
                         index=None, key=_key(item["id"]), on_change=_on_change, args=(session["id"], item),
                         label_visibility="collapsed")
            elif item["qtype"] == "tf":
                for j, stmt in enumerate(item["options"]):
                    c1, c2 = st.columns([3, 1.4], vertical_alignment="center")
                    c1.markdown(f"**{qs.TF_LETTERS[j]})** {stmt}")
                    c2.radio(f"Câu {n} ý {qs.TF_LETTERS[j]}", ["Đúng", "Sai"], index=None, horizontal=True,
                             key=_key(item["id"], j), on_change=_on_change, args=(session["id"], item),
                             label_visibility="collapsed")
            else:
                st.text_input(f"Câu {n} — đáp án", key=_key(item["id"]), max_chars=8,
                              placeholder="Nhập đáp án (VD: 0,25)", on_change=_on_change, args=(session["id"], item))

    answered = sum(1 for it in items if qs.is_answered(it["qtype"], _widget_response(it)))
    st.progress(answered / max(1, len(items)), text=f"Đã trả lời {answered}/{len(items)} câu")
    if st.button("Nộp bài", type="primary", icon="📨", width="stretch"):
        _submit_dialog(session["id"], items, answered)


@st.fragment(run_every=1)
def _timer(session_id: int, deadline: float, items: list[dict]) -> None:
    remaining = deadline - time.time()
    if remaining <= 0:
        _save_all(session_id, items)
        db.finalize_session(session_id, auto=True)
        st.session_state["history_session_id"] = session_id
        st.session_state["goto_history"] = True  # redirect on the full rerun (not from inside the fragment)
        ui.flash("Hết giờ — bài của em đã được tự động nộp.", "⏰")
        st.rerun(scope="app")
    answered = sum(1 for it in items if qs.is_answered(it["qtype"], _widget_response(it)))
    level = "danger" if remaining <= DANGER_SECONDS else "warn" if remaining <= WARN_SECONDS else ""
    st.markdown(f'<div class="pq-timer {level}">⏱ {ui.fmt_duration(remaining)}'
                f'<span style="font-weight:500;font-size:0.8em;opacity:.85"> · {answered}/{len(items)}</span></div>',
                unsafe_allow_html=True)
    if remaining <= DANGER_SECONDS and not st.session_state.get(f"warned_{session_id}"):
        st.session_state[f"warned_{session_id}"] = True
        st.toast("Còn chưa đến 1 phút!", icon="⏰")
