"""Practice-session result view, AI feedback, per-question tutoring chat and progress chart.

Shared by the student pages (with chat) and the teacher progress page (read-only).
"""

from __future__ import annotations

from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from . import ai, db, qview, ui
from . import questions as qs


def percent(session: dict) -> float:
    return (session["correct"] or 0) / session["total"] * 100 if session["total"] else 0.0


def qtypes_text(session: dict) -> str:
    return ", ".join(qs.qtype_label(t) for t in session["qtypes"] or [])


def sessions_table(sessions: list[dict], with_student: dict[int, str] | None = None) -> pd.DataFrame:
    rows = []
    for s in sessions:
        row = {}
        if with_student is not None:
            row["Học sinh"] = with_student.get(s["student_id"], "?")
        mins = ((s["submitted_at"] or s["started_at"]) - s["started_at"]) / 60
        row.update({
            "Ngày làm": ui.fmt_time(s["started_at"]), "Kho đề": qtypes_text(s),
            "Đúng/Tổng": f"{s['correct'] or 0}/{s['total']}", "Tỉ lệ đúng": percent(s),
            "Thời gian": f"{mins:.0f}/{s['duration_minutes']} phút",
            "Nộp bài": "Tự động (hết giờ)" if s["status"] == "auto_submitted" else "Học sinh nộp",
        })
        rows.append(row)
    return pd.DataFrame(rows)


SESSION_COLUMNS = {"Tỉ lệ đúng": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)}


def progress_chart(sessions: list[dict], title: str = "Tỉ lệ câu đúng qua các lần ôn tập") -> None:
    """Single-series line of % correct per session (oldest -> newest)."""
    ordered = sorted(sessions, key=lambda s: s["started_at"])
    if len(ordered) < 2:
        return
    df = pd.DataFrame([{
        "Lần": i + 1, "Ngày": datetime.fromtimestamp(s["started_at"]).strftime("%d/%m %H:%M"),
        "Tỉ lệ đúng (%)": round(percent(s), 1), "Kết quả": f"{s['correct'] or 0}/{s['total']}",
    } for i, s in enumerate(ordered)])
    base = alt.Chart(df).encode(
        x=alt.X("Lần:O", title="Lần ôn tập", axis=alt.Axis(labelAngle=0, grid=False)),
        y=alt.Y("Tỉ lệ đúng (%):Q", scale=alt.Scale(domain=[0, 100]), title="% câu đúng",
                axis=alt.Axis(tickCount=5, gridOpacity=0.35)),
        tooltip=["Lần", "Ngày", "Kết quả", "Tỉ lệ đúng (%)"],
    )
    chart = (base.mark_line(strokeWidth=2) + base.mark_point(size=80, filled=True, strokeWidth=2,
                                                             stroke="white")).properties(title=title, height=260)
    st.altair_chart(chart, use_container_width=True)


def topic_table(items: list[dict]) -> pd.DataFrame:
    groups: dict[tuple, list[bool]] = {}
    for it in items:
        groups.setdefault((it["topic"] or "Khác", it["level"]), []).append(bool(it["is_correct"]))
    rows = [{"Chủ đề": t, "Mức độ": qs.level_label(lv), "Đúng/Tổng": f"{sum(v)}/{len(v)}",
             "Tỉ lệ đúng": sum(v) / len(v) * 100}
            for (t, lv), v in sorted(groups.items(), key=lambda kv: (kv[0][0], list(qs.LEVELS).index(kv[0][1])
                                                                       if kv[0][1] in qs.LEVELS else 9))]
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ AI feedback
def _history_for(session: dict) -> list[dict]:
    older = [s for s in db.list_sessions(student_id=session["student_id"])
             if s["id"] != session["id"] and s["started_at"] < session["started_at"]][:10]
    items = db.items_for_sessions({s["id"] for s in older})
    return [{"date": ui.fmt_time(s["started_at"]), "correct": s["correct"] or 0, "total": s["total"],
             "items": [it for it in items if it["session_id"] == s["id"]]} for s in older]


def _make_feedback(session: dict, items: list[dict]) -> str | None:
    student = db.get_user(session["student_id"])
    try:
        with st.spinner("AI đang nhận xét bài làm..."):
            text = ai.feedback(student["full_name"] if student else "học sinh", items, _history_for(session))
    except ai.AIError as exc:
        st.warning(f"Chưa tạo được nhận xét AI: {exc}", icon="🤖")
        return None
    db.set_feedback(session["id"], text)
    return text


def feedback_box(session: dict, items: list[dict], auto: bool) -> None:
    with st.container(border=True):
        st.markdown("##### 🤖 Nhận xét của AI")
        text = session["ai_feedback"]
        if not text and auto and not st.session_state.get(f"fb_failed_{session['id']}"):
            text = _make_feedback(session, items)
            if text is None:
                st.session_state[f"fb_failed_{session['id']}"] = True
        if text:
            st.markdown(text)
        if st.button("Tạo lại nhận xét" if text else "Tạo nhận xét AI", key=f"fb_btn_{session['id']}",
                     icon="🔄", type="tertiary"):
            if _make_feedback(session, items):
                st.rerun()


# ------------------------------------------------------------------ tutoring chat
def _chat(item: dict) -> None:
    key = f"chat_{item['id']}"
    history: list[dict] = st.session_state.setdefault(key, [])
    with st.container(border=True):
        st.caption("💬 Hỏi AI về câu này — ví dụ: *Vì sao ý c sai?*, *Giải thích lại công thức giúp em*")
        for m in history:
            with st.chat_message("user" if m["role"] == "user" else "assistant"):
                st.markdown(m["content"])
        message = st.chat_input("Nhập câu hỏi của em...", key=f"chat_in_{item['id']}")
        if message:
            with st.chat_message("user"):
                st.markdown(message)
            with st.chat_message("assistant"), st.spinner("AI đang trả lời..."):
                try:
                    reply = ai.chat_reply(item, item["response"], history, message)
                except ai.AIError as exc:
                    st.error(str(exc))
                    return
            history += [{"role": "user", "content": message}, {"role": "assistant", "content": reply}]
            st.rerun()


# ------------------------------------------------------------------ result page
def render_result(session: dict, *, allow_chat: bool, auto_feedback: bool) -> None:
    items = db.session_items(session["id"])
    pct = percent(session)
    with st.container(border=True):
        m1, m2, m3 = st.columns(3)
        m1.metric("Số câu đúng", f"{session['correct'] or 0}/{session['total']}")
        m2.metric("Tỉ lệ đúng", f"{pct:.0f}%")
        mins = ((session["submitted_at"] or session["started_at"]) - session["started_at"]) / 60
        m3.metric("Thời gian", f"{mins:.0f} phút")
        st.progress(min(1.0, pct / 100))
        st.caption(f"{ui.fmt_time(session['started_at'])} · {qtypes_text(session)}"
                   + (" · ⏰ tự động nộp khi hết giờ" if session["status"] == "auto_submitted" else ""))
        by_type = []
        for t in qs.QTYPES:
            sub = [it for it in items if it["qtype"] == t]
            if sub:
                txt = f"{qs.QTYPE_ICONS[t]} {qs.qtype_label(t)}: **{sum(1 for i in sub if i['is_correct'])}/{len(sub)}** câu"
                if t == "tf":
                    txt += f" ({sum(i['partial'] or 0 for i in sub)}/{len(sub) * 4} ý)"
                by_type.append(txt)
        st.markdown("  \n".join(by_type))

    feedback_box(session, items, auto=auto_feedback)

    with st.expander("📊 Kết quả theo chủ đề và mức độ"):
        st.dataframe(topic_table(items), hide_index=True, column_config=SESSION_COLUMNS)

    st.markdown("#### Đáp án và lời giải")
    show = st.segmented_control("Lọc câu", ["Tất cả", "Câu sai / chưa làm"], default="Tất cả",
                                key=f"res_filter_{session['id']}", label_visibility="collapsed")
    open_chat = st.session_state.get("chat_open")
    for n, item in enumerate(items, start=1):
        if show == "Câu sai / chưa làm" and item["is_correct"]:
            continue
        with st.container(border=True):
            qview.render_result_item(item, n)
            if allow_chat:
                is_open = open_chat == item["id"]
                if st.button("Đóng hỏi đáp" if is_open else "Hỏi AI về câu này", key=f"chat_btn_{item['id']}",
                             icon="✖️" if is_open else "💬", type="secondary"):
                    st.session_state["chat_open"] = None if is_open else item["id"]
                    st.rerun()
                if is_open:
                    _chat(item)
