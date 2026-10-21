"""Ôn tập Vật lí 12 - Streamlit entry point.

Run with:  python -m streamlit run app.py
"""

import streamlit as st

st.set_page_config(page_title="Ôn tập Vật lí cùng Thầy Hải AI", page_icon="⚛️", layout="centered",
                   initial_sidebar_state="auto")

from quiz_app import db, nav, ui  # noqa: E402
from quiz_app.views import (  # noqa: E402
    account, login, student_history, student_practice, teacher_bank, teacher_classes, teacher_dashboard,
    teacher_generate, teacher_progress, teacher_settings, teacher_students,
)

ui.inject_css()

try:
    db.get_store()
except Exception as exc:  # misconfigured Google Sheets credentials, no network, ...
    st.error("Không kết nối được với nơi lưu trữ dữ liệu. Hãy kiểm tra cấu hình Google Sheets trong "
             "`.streamlit/secrets.toml`.")
    st.exception(exc)
    st.stop()

ui.show_flash()
user = ui.current_user()

if user is None:
    pg = st.navigation([st.Page(login.render, title="Đăng nhập", icon="🔐")], position="hidden")
else:
    account_page = st.Page(account.render, title="Tài khoản", icon="👤", url_path="account")
    if user["role"] == "teacher":
        pages = {
            "Tổng quan": [st.Page(teacher_dashboard.render, title="Trang chủ", icon="🏠", url_path="home", default=True)],
            "Kho đề": [
                st.Page(teacher_generate.render, title="Tạo câu hỏi bằng AI", icon="✨", url_path="generate"),
                st.Page(teacher_bank.render, title="Kho đề", icon="🗂️", url_path="bank"),
            ],
            "Học sinh": [
                st.Page(teacher_progress.render, title="Lịch sử ôn tập", icon="📈", url_path="progress"),
                st.Page(teacher_classes.render, title="Lớp học", icon="🏫", url_path="classes"),
                st.Page(teacher_students.render, title="Học sinh", icon="🎓", url_path="students"),
            ],
            "Tài khoản": [st.Page(teacher_settings.render, title="Cài đặt", icon="⚙️", url_path="settings"),
                          account_page],
        }
    else:
        pages = {
            "Học sinh": [
                st.Page(student_practice.render, title="Ôn tập", icon="📝", url_path="home", default=True),
                st.Page(student_history.render, title="Kết quả & lịch sử", icon="🏆", url_path="history"),
                account_page,
            ],
        }
    nav.register(pages)
    pg = st.navigation(pages)

    role = "Giáo viên" if user["role"] == "teacher" else "Học sinh"
    with st.sidebar:
        st.markdown(f"**{user['full_name']}**  \n{role} · `{user['username']}`")
        if st.button("Đăng xuất", icon="🚪", width="stretch"):
            st.session_state.clear()
            st.rerun()

pg.run()
