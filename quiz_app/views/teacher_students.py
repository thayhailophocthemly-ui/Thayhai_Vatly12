import re

import pandas as pd
import streamlit as st

from .. import db, ui

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")
NO_CLASS = -1


def _class_options(classes: list[dict]) -> dict[int, str]:
    opts = {NO_CLASS: "— Chưa có lớp —"}
    opts.update({c["id"]: f"{c['class_number']} - {c['name']}" for c in classes})
    return opts


def _validate(username: str, full_name: str, password: str | None, exclude_id: int | None = None,
              password_required: bool = True) -> str | None:
    if not full_name.strip():
        return "Vui lòng nhập họ và tên."
    if not USERNAME_RE.match(username.strip()):
        return "Tên đăng nhập gồm 3-32 ký tự: chữ không dấu, chữ số, '.', '_' hoặc '-'."
    if db.username_exists(username, exclude_id):
        return f"Tên đăng nhập '{username.strip()}' đã được sử dụng."
    if password_required and len(password or "") < 6:
        return "Mật khẩu phải có ít nhất 6 ký tự."
    if password and len(password) < 6:
        return "Mật khẩu phải có ít nhất 6 ký tự."
    return None


def _reset_selection() -> None:
    st.session_state["stu_ver"] = st.session_state.get("stu_ver", 0) + 1


@st.dialog("Xóa học sinh")
def _confirm_delete(students: list[dict]) -> None:
    st.write(f"Xóa vĩnh viễn **{len(students)}** tài khoản học sinh?")
    st.caption(", ".join(s["full_name"] for s in students))
    st.warning("Toàn bộ bài làm của các học sinh này cũng sẽ bị xóa. Không thể hoàn tác.", icon="⚠️")
    c1, c2 = st.columns(2)
    if c1.button("Hủy", width="stretch"):
        st.rerun()
    if c2.button("Xóa", type="primary", width="stretch"):
        for s in students:
            db.delete_student(s["id"])
        _reset_selection()
        ui.flash(f"Đã xóa {len(students)} học sinh.", "🗑️")
        st.rerun()


def render() -> None:
    user = ui.require_role("teacher")
    ui.hero("🎓 Học sinh", "Tạo tài khoản học sinh, xếp lớp, chỉnh sửa hoặc xóa.")
    classes = db.list_classes(user["id"])
    class_opts = _class_options(classes)

    tab_list, tab_new, tab_import = st.tabs(["Danh sách", "➕ Thêm học sinh", "📥 Nhập từ CSV"])

    with tab_new:
        _new_student_form(user, class_opts)
    with tab_import:
        _import_csv(user, classes)
    with tab_list:
        _student_list(user, class_opts)


def _new_student_form(user: dict, class_opts: dict[int, str]) -> None:
    with st.form("new_student", clear_on_submit=True):
        full_name = st.text_input("Họ và tên *")
        c1, c2 = st.columns(2)
        username = c1.text_input("Tên đăng nhập *", help="Học sinh dùng tên này để đăng nhập")
        password = c2.text_input("Mật khẩu *", type="password", help="Ít nhất 6 ký tự")
        c3, c4 = st.columns(2)
        code = c3.text_input("Mã học sinh")
        email = c4.text_input("Email")
        class_id = st.selectbox("Lớp", options=list(class_opts), format_func=class_opts.get)
        if st.form_submit_button("Tạo học sinh", type="primary", width="stretch"):
            error = _validate(username, full_name, password)
            if error:
                st.error(error)
            else:
                db.create_student(user["id"], username, password, full_name, code, email,
                                  None if class_id == NO_CLASS else class_id)
                _reset_selection()
                ui.flash(f"Đã tạo học sinh {full_name.strip()}.")
                st.rerun()


def _import_csv(user: dict, classes: list[dict]) -> None:
    st.markdown("Tải lên tệp CSV có các cột **full_name** (họ tên), **username** (tên đăng nhập), "
                "**password** (mật khẩu) và có thể thêm **student_code** (mã HS), **email**, "
                "**class_number** (mã lớp).")
    sample = "full_name,username,password,student_code,email,class_number\nNguyễn Văn A,nva,matkhau123,HS001,,10A1\n"
    st.download_button("Tải tệp mẫu", sample.encode("utf-8-sig"), "mau_hoc_sinh.csv", "text/csv", icon="📄")
    file = st.file_uploader("Tệp CSV", type=["csv"])
    if not file:
        return
    try:
        df = pd.read_csv(file, dtype=str, encoding="utf-8-sig").fillna("")
    except Exception as exc:
        st.error(f"Không đọc được tệp CSV: {exc}")
        return
    missing = {"full_name", "username", "password"} - set(df.columns)
    if missing:
        st.error(f"Thiếu cột: {', '.join(sorted(missing))}")
        return
    st.dataframe(df, hide_index=True)
    by_number = {c["class_number"].lower(): c["id"] for c in classes}
    if st.button(f"Nhập {len(df)} học sinh", type="primary", width="stretch"):
        created, errors, seen = 0, [], set()
        for i, row in df.iterrows():
            uname = row["username"].strip()
            error = _validate(uname, row["full_name"], row["password"])
            if not error and uname.lower() in seen:
                error = "tên đăng nhập bị trùng trong tệp"
            number = row.get("class_number", "").strip()
            if not error and number and number.lower() not in by_number:
                error = f"không tìm thấy mã lớp '{number}'"
            if error:
                errors.append(f"Dòng {i + 2} ({uname or '?'}): {error}")
                continue
            seen.add(uname.lower())
            db.create_student(user["id"], uname, row["password"], row["full_name"], row.get("student_code", ""),
                              row.get("email", ""), by_number.get(number.lower()) if number else None)
            created += 1
        if created:
            st.success(f"Đã nhập {created} học sinh.")
        for e in errors:
            st.error(e)


def _student_list(user: dict, class_opts: dict[int, str]) -> None:
    c1, c2 = st.columns([1, 1])
    filter_opts = {0: "Tất cả các lớp", **class_opts}
    class_filter = c1.selectbox("Lớp", options=list(filter_opts), format_func=filter_opts.get,
                                key="stu_class_filter")
    search = c2.text_input("Tìm kiếm", placeholder="Tên, tên đăng nhập hoặc mã HS", key="stu_search")

    students = db.list_students(user["id"])
    if class_filter == NO_CLASS:
        students = [s for s in students if s["class_id"] is None]
    elif class_filter:
        students = [s for s in students if s["class_id"] == class_filter]
    if search.strip():
        q = search.strip().lower()
        students = [s for s in students if q in " ".join(
            str(s[k] or "") for k in ("full_name", "username", "student_code", "email")).lower()]

    if not students:
        st.info("Không tìm thấy học sinh nào.", icon="🎓")
        return

    df = pd.DataFrame([{
        "Họ và tên": s["full_name"], "Tên đăng nhập": s["username"], "Mã HS": s["student_code"] or "",
        "Lớp": f"{s['class_number']}" if s["class_number"] else "—", "Email": s["email"] or "",
    } for s in students])
    st.caption(f"{len(students)} học sinh · đánh dấu các dòng để sửa, chuyển lớp hoặc xóa")
    event = st.dataframe(df, hide_index=True, on_select="rerun", selection_mode="multi-row",
                         key=f"stu_table_{class_filter}_{search}_{st.session_state.get('stu_ver', 0)}")
    selected = [students[i] for i in event.selection.rows if i < len(students)]
    if not selected:
        return

    st.markdown(f"**Đã chọn {len(selected)} học sinh**")
    with st.container(border=True):
        c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
        target = c1.selectbox("Chuyển sang lớp", options=list(class_opts), format_func=class_opts.get,
                              key="bulk_target")
        if c2.button("Áp dụng", width="stretch", type="primary"):
            db.set_student_class([s["id"] for s in selected], None if target == NO_CLASS else target)
            _reset_selection()
            ui.flash(f"Đã cập nhật lớp cho {len(selected)} học sinh.")
            st.rerun()
        c3, c4 = st.columns(2)
        if c3.button("Xóa khỏi lớp", icon="➖", width="stretch"):
            db.set_student_class([s["id"] for s in selected], None)
            _reset_selection()
            ui.flash(f"Đã xóa {len(selected)} học sinh khỏi lớp.", "➖")
            st.rerun()
        if c4.button("Xóa tài khoản", icon="🗑️", width="stretch"):
            _confirm_delete(selected)

    if len(selected) == 1:
        _edit_form(selected[0], class_opts)


def _edit_form(s: dict, class_opts: dict[int, str]) -> None:
    st.markdown(f"#### ✏️ Sửa thông tin {s['full_name']}")
    with st.form(f"edit_student_{s['id']}"):
        full_name = st.text_input("Họ và tên", value=s["full_name"])
        c1, c2 = st.columns(2)
        username = c1.text_input("Tên đăng nhập", value=s["username"])
        password = c2.text_input("Mật khẩu mới", type="password", placeholder="Để trống nếu không đổi")
        c3, c4 = st.columns(2)
        code = c3.text_input("Mã học sinh", value=s["student_code"] or "")
        email = c4.text_input("Email", value=s["email"] or "")
        keys = list(class_opts)
        current = s["class_id"] if s["class_id"] in class_opts else NO_CLASS
        class_id = st.selectbox("Lớp", options=keys, index=keys.index(current), format_func=class_opts.get)
        if st.form_submit_button("Lưu thay đổi", type="primary", width="stretch"):
            error = _validate(username, full_name, password, exclude_id=s["id"], password_required=False)
            if error:
                st.error(error)
            else:
                db.update_student(s["id"], username, full_name, code, email,
                                  None if class_id == NO_CLASS else class_id, password or None)
                _reset_selection()
                ui.flash("Đã cập nhật học sinh.")
                st.rerun()
