import streamlit as st

from .. import ai, db, ui
from .teacher_students import USERNAME_RE


def render() -> None:
    user = ui.require_role("teacher")
    ui.hero("⚙️ Cài đặt", "AI, lưu trữ dữ liệu và tài khoản giáo viên.")

    st.subheader("🤖 Google Gemini")
    if st.session_state.get("gemini_api_key_override"):
        st.success("Đang dùng khóa API đã nhập cho phiên làm việc này.", icon="🔑")
    elif ai.secret("GEMINI_API_KEY"):
        st.success("Đã nạp khóa API từ secrets / biến môi trường.", icon="🔑")
    else:
        st.warning("Chưa cấu hình khóa API.", icon="🔑")
    with st.form("gemini"):
        key = st.text_input("Khóa API cho phiên này (không bắt buộc)", type="password",
                            help="Chỉ lưu trong phiên làm việc hiện tại. Để dùng lâu dài, hãy thêm vào secrets.toml.")
        model = st.text_input("Mô hình", value=ai.get_model())
        st.caption("Lấy khóa API tại https://aistudio.google.com/apikey")
        if st.form_submit_button("Lưu", width="stretch"):
            if key.strip():
                st.session_state["gemini_api_key_override"] = key.strip()
            if model.strip():
                st.session_state["gemini_model_override"] = model.strip()
            ui.flash("Đã lưu cài đặt Gemini cho phiên này.")
            st.rerun()

    st.subheader("🗄️ Lưu trữ")
    info = db.storage_info()
    if info["backend"] == "Google Sheets":
        st.success(f"Đã kết nối Google Sheets — [mở bảng tính]({info['url']})", icon="📗")
    else:
        st.warning(f"Đang lưu vào tệp cục bộ (`{info['path']}`). Hãy cấu hình Google Sheets trong "
                   "`.streamlit/secrets.toml` khi dùng thực tế.", icon="💾")
    if info["last_error"]:
        st.error(f"Lần lưu gần nhất bị lỗi (sẽ tự động thử lại): {info['last_error']}")
    st.caption(f"Lưu lần cuối: {ui.fmt_time(info['last_flush_at'])} · Thay đổi chờ lưu: "
               f"{', '.join(info['pending']) or 'không có'}")
    c1, c2 = st.columns(2)
    if c1.button("Lưu ngay", icon="💾", width="stretch"):
        db.get_store().flush()
        ui.flash("Đã lưu toàn bộ thay đổi.")
        st.rerun()
    if c2.button("Tải lại dữ liệu", icon="🔄", width="stretch",
                 help="Dùng sau khi sửa trực tiếp trên bảng tính. Các thay đổi chưa lưu sẽ được lưu trước."):
        db.reload_storage()
        ui.flash("Đã tải lại dữ liệu.")
        st.rerun()

    st.subheader("👩‍🏫 Tài khoản giáo viên")
    for t in db.list_teachers():
        st.markdown(f"- **{t['full_name']}** · `{t['username']}`" + (" (bạn)" if t["id"] == user["id"] else ""))
    with st.expander("➕ Thêm giáo viên"):
        with st.form("new_teacher", clear_on_submit=True):
            full_name = st.text_input("Họ và tên")
            username = st.text_input("Tên đăng nhập")
            password = st.text_input("Mật khẩu", type="password")
            if st.form_submit_button("Tạo giáo viên", type="primary", width="stretch"):
                if not full_name.strip() or not USERNAME_RE.match(username.strip()):
                    st.error("Nhập họ tên và tên đăng nhập hợp lệ (3-32 ký tự: chữ không dấu, số, . _ -).")
                elif db.username_exists(username):
                    st.error("Tên đăng nhập đã được sử dụng.")
                elif len(password) < 6:
                    st.error("Mật khẩu phải có ít nhất 6 ký tự.")
                else:
                    db.create_teacher(username, password, full_name, user["id"])
                    ui.flash(f"Đã tạo giáo viên {full_name.strip()}.")
                    st.rerun()
