import streamlit as st

from .. import db, ui
from ..auth import verify_password


def render() -> None:
    session_user = ui.current_user()
    user = db.get_user(session_user["id"])
    role = "Giáo viên" if user["role"] == "teacher" else "Học sinh"
    ui.hero("👤 Tài khoản", f"{user['full_name']} · {role}")

    with st.container(border=True):
        st.markdown(f"**Tên đăng nhập:** `{user['username']}`")
        if user["role"] == "student":
            cls = db.get_class(user["class_id"])
            st.markdown(f"**Lớp:** {cls['class_number'] + ' - ' + cls['name'] if cls else '—'}")
            if user.get("student_code"):
                st.markdown(f"**Mã học sinh:** {user['student_code']}")

    st.subheader("Đổi mật khẩu")
    with st.form("change_pw", clear_on_submit=True):
        current = st.text_input("Mật khẩu hiện tại", type="password", autocomplete="current-password")
        new = st.text_input("Mật khẩu mới", type="password", autocomplete="new-password")
        confirm = st.text_input("Nhập lại mật khẩu mới", type="password", autocomplete="new-password")
        if st.form_submit_button("Cập nhật mật khẩu", type="primary", width="stretch"):
            if not verify_password(current, user["password_hash"]):
                st.error("Mật khẩu hiện tại không đúng.")
            elif len(new) < 6:
                st.error("Mật khẩu mới phải có ít nhất 6 ký tự.")
            elif new != confirm:
                st.error("Hai mật khẩu mới không khớp.")
            else:
                db.update_password(user["id"], new)
                ui.flash("Đã cập nhật mật khẩu.", "🔒")
                st.rerun()
