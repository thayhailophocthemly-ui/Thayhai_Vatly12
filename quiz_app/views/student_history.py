import streamlit as st

from .. import db, nav, practice_view, ui


def render() -> None:
    user = ui.require_role("student")
    db.expire_overdue_sessions()
    ui.hero("🏆 Kết quả & lịch sử ôn tập", "Xem đáp án, nhận xét của AI và sự tiến bộ của em.")

    sessions = db.list_sessions(student_id=user["id"])
    if not sessions:
        st.info("Em chưa có bài ôn tập nào.", icon="📭")
        if st.button("Tạo bài ôn tập", type="primary", icon="📝"):
            st.switch_page(nav.page("home"))
        return

    opts = {s["id"]: s for s in sessions}
    keys = list(opts)
    wanted = st.session_state.get("history_session_id")
    session_id = st.selectbox(
        "Bài ôn tập", keys, index=keys.index(wanted) if wanted in opts else 0,
        format_func=lambda i: f"{ui.fmt_time(opts[i]['started_at'])} — {opts[i]['correct'] or 0}/{opts[i]['total']} câu đúng")
    st.session_state["history_session_id"] = session_id

    tab_result, tab_progress = st.tabs(["📄 Kết quả bài làm", "📈 Sự tiến bộ"])
    with tab_result:
        practice_view.render_result(opts[session_id], allow_chat=True, auto_feedback=True)
    with tab_progress:
        practice_view.progress_chart(sessions)
        st.dataframe(practice_view.sessions_table(sessions), hide_index=True,
                     column_config=practice_view.SESSION_COLUMNS)
