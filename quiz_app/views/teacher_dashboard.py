import streamlit as st

from .. import db, nav, practice_view, ui
from .. import questions as qs


def render() -> None:
    user = ui.require_role("teacher")
    db.expire_overdue_sessions()
    ui.hero(f"Chào mừng trở lại, {user['full_name']} 👋", f"Ôn tập Vật lí {qs.GRADE} — tổng quan lớp học và kho đề.")

    stats = db.teacher_stats(user["id"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Lớp học", stats["classes"])
    c2.metric("Học sinh", stats["students"])
    c3.metric("HS ôn tập (7 ngày)", stats["active_week"])

    st.subheader("Kho đề")
    cols = st.columns(3)
    for col, (t, n) in zip(cols, stats["banks"].items()):
        col.metric(f"{qs.QTYPE_ICONS[t]} {qs.qtype_label(t)}", f"{n} câu")

    st.subheader("Thao tác nhanh")
    a1, a2, a3 = st.columns(3)
    with a1:
        if st.button("✨ Tạo câu hỏi bằng AI", width="stretch", type="primary"):
            st.switch_page(nav.page("generate"))
    with a2:
        if st.button("🗂️ Kho đề", width="stretch"):
            st.switch_page(nav.page("bank"))
    with a3:
        if st.button("📈 Lịch sử ôn tập", width="stretch"):
            st.switch_page(nav.page("progress"))

    st.subheader("Lượt ôn tập gần đây")
    sessions = db.list_sessions(teacher_id=user["id"])[:8]
    if not sessions:
        st.info("Chưa có học sinh nào làm bài ôn tập.", icon="📭")
        return
    names = {s["id"]: s["full_name"] for s in db.list_students(user["id"])}
    st.dataframe(practice_view.sessions_table(sessions, names), hide_index=True,
                 column_config=practice_view.SESSION_COLUMNS)
