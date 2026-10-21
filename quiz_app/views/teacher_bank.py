import streamlit as st

from .. import db, qview, ui
from .. import questions as qs

PAGE_SIZE = 15


@st.dialog("Xóa câu hỏi")
def _confirm_delete(q: dict) -> None:
    st.write("Xóa câu hỏi này khỏi kho đề?")
    st.caption(q["question"][:200])
    st.caption("Các bài ôn tập học sinh đã làm vẫn giữ nguyên nội dung câu hỏi.")
    c1, c2 = st.columns(2)
    if c1.button("Hủy", width="stretch"):
        st.rerun()
    if c2.button("Xóa", type="primary", width="stretch"):
        db.delete_bank_question(q["id"])
        ui.flash("Đã xóa câu hỏi.", "🗑️")
        st.rerun()


def render() -> None:
    user = ui.require_role("teacher")
    ui.hero("🗂️ Kho đề", f"Vật lí {qs.GRADE} · Xem, thêm, sửa, xóa câu hỏi trong từng kho.")
    counts = db.bank_counts(user["id"])
    tabs = st.tabs([f"{qs.QTYPE_ICONS[t]} {label} ({counts[t]})" for t, label in qs.QTYPES.items()])
    for tab, qtype in zip(tabs, qs.QTYPES):
        with tab:
            _bank_tab(user, qtype)


def _bank_tab(user: dict, qtype: str) -> None:
    ver_key = f"bank_new_ver_{qtype}"
    with st.expander(f"➕ Thêm câu hỏi vào kho {qs.qtype_label(qtype).lower()}"):
        new = qview.question_editor(f"bank_new_{qtype}_{st.session_state.get(ver_key, 0)}",
                                    qs.empty_question(qtype), "Thêm vào kho")
        if new:
            db.add_to_bank(user["id"], new)
            st.session_state[ver_key] = st.session_state.get(ver_key, 0) + 1  # fresh, empty form
            ui.flash("Đã thêm câu hỏi.", "➕")
            st.rerun()

    bank = db.list_bank(user["id"], qtype)
    if not bank:
        st.info("Kho này chưa có câu hỏi. Hãy tạo câu hỏi bằng AI hoặc thêm thủ công.", icon="📭")
        return

    topics = sorted({q["topic"] for q in bank if q["topic"]})
    c1, c2 = st.columns(2)
    f_topics = c1.multiselect("Chủ đề", topics, placeholder="Tất cả chủ đề", key=f"bf_t_{qtype}")
    f_levels = c2.multiselect("Mức độ", list(qs.LEVELS), format_func=qs.level_label,
                              placeholder="Tất cả mức độ", key=f"bf_l_{qtype}")
    search = st.text_input("Tìm kiếm", placeholder="Tìm theo nội dung câu hỏi", key=f"bf_s_{qtype}")
    items = [q for q in bank
             if (not f_topics or q["topic"] in f_topics)
             and (not f_levels or q["level"] in f_levels)
             and (not search.strip() or search.strip().lower() in q["question"].lower())]

    by_level = " · ".join(f"{qs.level_label(lv)}: {sum(1 for q in items if q['level'] == lv)}" for lv in qs.LEVELS)
    st.caption(f"{len(items)}/{len(bank)} câu hỏi · {by_level}")

    pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = st.number_input("Trang", 1, pages, 1, key=f"bf_p_{qtype}") if pages > 1 else 1
    start = (page - 1) * PAGE_SIZE
    for n, q in enumerate(items[start:start + PAGE_SIZE], start=start + 1):
        title = " ".join(q["question"].split())
        title = title[:80] + ("…" if len(title) > 80 else "")
        with st.expander(f"**{n}.** {title}  ·  {qs.level_label(q['level'])}"
                         + (f" · {q['topic']}" if q["topic"] else "")):
            qview.render_question(q)
            st.caption(f"Cập nhật: {ui.fmt_time(q['updated_at'] or q['created_at'])}")
            edit_key = f"bank_edit_{q['id']}"
            c1, c2 = st.columns(2)
            if c1.button("Sửa", key=f"be_{q['id']}", icon="✏️", width="stretch"):
                st.session_state[edit_key] = not st.session_state.get(edit_key, False)
                st.rerun()
            if c2.button("Xóa", key=f"bd_{q['id']}", icon="🗑️", width="stretch"):
                _confirm_delete(q)
            if st.session_state.get(edit_key):
                updated = qview.question_editor(f"bank_form_{q['id']}", q, "Lưu thay đổi")
                if updated:
                    db.update_bank_question(q["id"], updated)
                    st.session_state[edit_key] = False
                    ui.flash("Đã cập nhật câu hỏi.")
                    st.rerun()
