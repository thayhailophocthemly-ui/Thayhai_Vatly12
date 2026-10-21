import time

import streamlit as st

from .. import db, ui
from ..auth import verify_password

MAX_FAILURES = 5
LOCKOUT_SECONDS = 60


def render() -> None:
    ui.hero("⚛️ Trắc nghiệm Vật lý", "Đăng nhập để làm bài hoặc quản lý bài kiểm tra")

    locked_until = st.session_state.get("login_locked_until", 0)
    with st.container(border=True):
        with st.form("login", border=False):
            username = st.text_input("Tên đăng nhập", autocomplete="username")
            password = st.text_input("Mật khẩu", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("Đăng nhập", type="primary", width="stretch")

        if submitted:
            if time.time() < locked_until:
                st.error(f"Bạn đã nhập sai quá nhiều lần. Vui lòng thử lại sau {int(locked_until - time.time())} giây.")
                return
            user = db.get_user_by_username(username) if username.strip() else None
            if user and verify_password(password, user["password_hash"]):
                st.session_state.pop("login_failures", None)
                st.session_state["user"] = {k: user[k] for k in ("id", "username", "full_name", "role")}
                ui.flash(f"Xin chào, {user['full_name']}!", "👋")
                st.rerun()
            failures = st.session_state.get("login_failures", 0) + 1
            st.session_state["login_failures"] = failures
            if failures >= MAX_FAILURES:
                st.session_state["login_locked_until"] = time.time() + LOCKOUT_SECONDS
                st.session_state["login_failures"] = 0
            st.error("Tên đăng nhập hoặc mật khẩu không đúng.")

    default = db.get_user_by_username("teacher")
    if default and default["role"] == "teacher" and verify_password("teacher123", default["password_hash"]):
        st.info("**Lần đầu sử dụng:** đăng nhập giáo viên với tên `teacher` và mật khẩu `teacher123`, "
                "sau đó đổi mật khẩu trong mục **Tài khoản**.", icon="💡")
    st.caption("Học sinh: vui lòng hỏi giáo viên tên đăng nhập và mật khẩu của em.")
