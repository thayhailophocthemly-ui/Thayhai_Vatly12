import pandas as pd
import streamlit as st

from .. import db, practice_view, ui

ALL = 0


def render() -> None:
    user = ui.require_role("teacher")
    db.expire_overdue_sessions()
    ui.hero("📈 Lịch sử ôn tập", "Theo dõi kết quả và sự tiến bộ của từng học sinh.")

    classes = db.list_classes(user["id"])
    students = db.list_students(user["id"])
    sessions = db.list_sessions(teacher_id=user["id"])

    class_opts = {ALL: "Tất cả các lớp", **{c["id"]: f"{c['class_number']} - {c['name']}" for c in classes}}
    class_id = st.selectbox("Lớp", list(class_opts), format_func=class_opts.get)
    if class_id != ALL:
        students = [s for s in students if s["class_id"] == class_id]
    ids = {s["id"] for s in students}
    sessions = [s for s in sessions if s["student_id"] in ids]

    if not sessions:
        st.info("Chưa có học sinh nào làm bài ôn tập.", icon="📭")
        return

    # ---- overview per student
    by_student: dict[int, list[dict]] = {}
    for s in sessions:
        by_student.setdefault(s["student_id"], []).append(s)
    rows = []
    for stu in students:
        own = sorted(by_student.get(stu["id"], []), key=lambda s: s["started_at"])
        pcts = [practice_view.percent(s) for s in own]
        rows.append({
            "Học sinh": stu["full_name"], "Lớp": stu["class_number"] or "—", "Số lần ôn tập": len(own),
            "Lần gần nhất": ui.fmt_time(own[-1]["started_at"]) if own else "—",
            "Tỉ lệ đúng TB": sum(pcts) / len(pcts) if pcts else None,
            "Lần đầu": pcts[0] if pcts else None, "Gần nhất": pcts[-1] if pcts else None,
            "Tiến bộ": (pcts[-1] - pcts[0]) if len(pcts) >= 2 else None,
        })
    m1, m2, m3 = st.columns(3)
    m1.metric("Lượt ôn tập", len(sessions))
    m2.metric("Học sinh đã ôn tập", f"{len(by_student)}/{len(students)}")
    m3.metric("Tỉ lệ đúng TB", f"{sum(practice_view.percent(s) for s in sessions) / len(sessions):.0f}%")

    st.markdown("#### Tổng quan theo học sinh")
    pct = st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)
    st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
        "Tỉ lệ đúng TB": pct, "Lần đầu": st.column_config.NumberColumn(format="%.0f%%"),
        "Gần nhất": st.column_config.NumberColumn(format="%.0f%%"),
        "Tiến bộ": st.column_config.NumberColumn(format="%+.0f%%", help="Tỉ lệ đúng lần gần nhất so với lần đầu (điểm phần trăm)"),
    })
    names = {s["id"]: s["full_name"] for s in students}
    st.download_button("Tải lịch sử (CSV)",
                       practice_view.sessions_table(sessions, names).to_csv(index=False).encode("utf-8-sig"),
                       "lich_su_on_tap.csv", "text/csv", icon="⬇️")

    # ---- one student
    st.markdown("#### Chi tiết học sinh")
    active = [s for s in students if s["id"] in by_student]
    labels = {s["id"]: f"{s['full_name']} ({s['class_number'] or '—'})" for s in active}
    student_id = st.selectbox("Học sinh", list(labels), format_func=labels.get, index=None,
                              placeholder="Chọn học sinh để xem chi tiết")
    if not student_id:
        return
    own = by_student[student_id]
    practice_view.progress_chart(own, f"Tỉ lệ câu đúng của {names[student_id]}")
    st.dataframe(practice_view.sessions_table(own), hide_index=True, column_config=practice_view.SESSION_COLUMNS)
    with st.expander("📊 Tỉ lệ đúng theo chủ đề (tất cả các lần)"):
        items = db.items_for_sessions({s["id"] for s in own})
        st.dataframe(practice_view.topic_table(items), hide_index=True, column_config=practice_view.SESSION_COLUMNS)

    s_opts = {s["id"]: s for s in own}
    session_id = st.selectbox("Xem bài làm", list(s_opts), index=None, placeholder="Chọn một lần ôn tập",
                              format_func=lambda i: f"{ui.fmt_time(s_opts[i]['started_at'])} — "
                                                    f"{s_opts[i]['correct'] or 0}/{s_opts[i]['total']} câu đúng")
    if session_id:
        practice_view.render_result(s_opts[session_id], allow_chat=False, auto_feedback=False)
