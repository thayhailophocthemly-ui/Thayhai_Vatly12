import streamlit as st

from .. import db, ui


@st.dialog("Xóa lớp học")
def _confirm_delete(cls: dict) -> None:
    st.write(f"Xóa lớp **{cls['class_number']} - {cls['name']}**?")
    st.caption(f"{cls['student_count']} học sinh của lớp sẽ được giữ lại nhưng không còn thuộc lớp này.")
    c1, c2 = st.columns(2)
    if c1.button("Hủy", width="stretch"):
        st.rerun()
    if c2.button("Xóa", type="primary", width="stretch"):
        db.delete_class(cls["id"])
        ui.flash(f"Đã xóa lớp {cls['class_number']}.", "🗑️")
        st.rerun()


def _validate(teacher_id: int, name: str, number: str, exclude_id: int | None = None) -> str | None:
    if not name.strip() or not number.strip():
        return "Vui lòng nhập tên lớp và mã lớp."
    if db.class_number_exists(teacher_id, number, exclude_id):
        return f"Mã lớp '{number.strip()}' đã tồn tại."
    return None


def render() -> None:
    user = ui.require_role("teacher")
    ui.hero("🏫 Lớp học", "Tạo lớp học và quản lý học sinh trong lớp.")

    with st.expander("➕ Tạo lớp mới", expanded=not db.list_classes(user["id"])):
        with st.form("new_class", clear_on_submit=True):
            c1, c2 = st.columns([1, 2])
            number = c1.text_input("Mã lớp *", placeholder="VD: 10A1")
            name = c2.text_input("Tên lớp *", placeholder="VD: Vật lý 10 - Buổi sáng")
            if st.form_submit_button("Tạo lớp", type="primary", width="stretch"):
                error = _validate(user["id"], name, number)
                if error:
                    st.error(error)
                else:
                    db.create_class(user["id"], name, number)
                    ui.flash(f"Đã tạo lớp {number.strip()}.")
                    st.rerun()

    classes = db.list_classes(user["id"])
    if not classes:
        st.info("Bạn chưa có lớp nào. Hãy tạo lớp ở trên.", icon="🏫")
        return

    query = st.text_input("Tìm lớp", placeholder="Lọc theo tên hoặc mã lớp", label_visibility="collapsed")
    q = query.strip().lower()
    for cls in classes:
        if q and q not in cls["name"].lower() and q not in cls["class_number"].lower():
            continue
        with st.expander(f"**{cls['class_number']}** · {cls['name']} · {cls['student_count']} học sinh"):
            _class_panel(user, cls)


def _class_panel(user: dict, cls: dict) -> None:
    tab_students, tab_add, tab_edit = st.tabs(["Học sinh", "Thêm học sinh", "Sửa lớp"])

    with tab_students:
        members = db.list_students(user["id"], class_id=cls["id"])
        if not members:
            st.caption("Lớp chưa có học sinh.")
        for s in members:
            c1, c2 = st.columns([4, 1.3], vertical_alignment="center")
            code = f" · #{s['student_code']}" if s["student_code"] else ""
            c1.markdown(f"**{s['full_name']}**  \n`{s['username']}`{code}")
            if c2.button("Xóa khỏi lớp", key=f"rm_{cls['id']}_{s['id']}", width="stretch",
                         help="Xóa khỏi lớp này (tài khoản học sinh vẫn được giữ lại)"):
                db.set_student_class([s["id"]], None)
                ui.flash(f"Đã xóa {s['full_name']} khỏi lớp {cls['class_number']}.", "➖")
                st.rerun()

    with tab_add:
        candidates = [s for s in db.list_students(user["id"]) if s["class_id"] != cls["id"]]
        if not candidates:
            st.caption("Không còn học sinh nào khác. Hãy tạo học sinh ở trang **Học sinh**.")
        else:
            labels = {s["id"]: f"{s['full_name']} ({s['username']})"
                      + (f" — đang ở lớp {s['class_number']}" if s["class_number"] else " — chưa có lớp")
                      for s in candidates}
            chosen = st.multiselect("Chọn học sinh", options=list(labels), format_func=labels.get,
                                    key=f"add_{cls['id']}", placeholder="Chọn một hoặc nhiều học sinh")
            if st.button("Thêm vào lớp", key=f"addbtn_{cls['id']}", type="primary", disabled=not chosen,
                         width="stretch"):
                db.set_student_class(chosen, cls["id"])
                ui.flash(f"Đã thêm {len(chosen)} học sinh vào lớp {cls['class_number']}.")
                st.rerun()

    with tab_edit:
        with st.form(f"edit_class_{cls['id']}"):
            number = st.text_input("Mã lớp", value=cls["class_number"])
            name = st.text_input("Tên lớp", value=cls["name"])
            if st.form_submit_button("Lưu thay đổi", width="stretch"):
                error = _validate(user["id"], name, number, exclude_id=cls["id"])
                if error:
                    st.error(error)
                else:
                    db.update_class(cls["id"], name, number)
                    ui.flash("Đã cập nhật lớp.")
                    st.rerun()
        if st.button("Xóa lớp", key=f"del_{cls['id']}", icon="🗑️", width="stretch"):
            _confirm_delete(cls)
