import uuid

import pandas as pd
import streamlit as st

from .. import ai, db, nav, qview, ui
from .. import questions as qs

SKIP = "skip"
DEST_LABELS = {SKIP: "— Không lưu —", **{k: f"Kho {v.lower()}" for k, v in qs.QTYPES.items()}}
MAX_TOTAL = 60


def _reset() -> None:
    for key in ("gen_plan", "gen_draft", "gen_matrix_name", "gen_plan_editor"):
        st.session_state.pop(key, None)


def render() -> None:
    user = ui.require_role("teacher")
    ui.hero("✨ Tạo câu hỏi bằng AI", f"Vật lí {qs.GRADE} · Gemini soạn câu hỏi theo ma trận đề kiểm tra của thầy/cô.")

    if not ai.get_api_key():
        st.warning("Chưa cấu hình khóa API Gemini. Hãy thêm `GEMINI_API_KEY` vào `.streamlit/secrets.toml` "
                   "hoặc nhập khóa trong mục **Cài đặt**.", icon="🔑")

    if st.session_state.get("gen_draft"):
        _review(user)
    elif st.session_state.get("gen_plan") is not None:
        _plan_step()
    else:
        _upload_step()


# ------------------------------------------------------------------ step 1: matrix
def _upload_step() -> None:
    st.markdown("#### Bước 1 · Tải lên ma trận đề kiểm tra")
    st.caption("File PDF hoặc Word (.docx) chứa ma trận (và bản đặc tả nếu có). AI sẽ đọc số câu hỏi theo từng "
               "chủ đề, dạng câu hỏi và mức độ tư duy (Biết, Hiểu, Vận dụng).")
    file = st.file_uploader("Ma trận đề", type=["pdf", "docx"], label_visibility="collapsed")
    notes = st.text_area("Ghi chú cho AI (không bắt buộc)",
                         placeholder="VD: Chỉ lấy phần Khí lí tưởng; bỏ qua phần chuyên đề")
    c1, c2 = st.columns(2)
    if c1.button("Phân tích ma trận", type="primary", icon="🔍", width="stretch", disabled=file is None):
        with st.spinner("Gemini đang đọc ma trận đề..."):
            try:
                plan = ai.analyze_matrix(file.name, file.getvalue(), notes)
            except ai.AIError as exc:
                st.error(str(exc), icon="🚫")
                return
        st.session_state["gen_plan"] = plan
        st.session_state["gen_matrix_name"] = file.name
        st.rerun()
    if c2.button("Tự nhập kế hoạch", icon="✍️", width="stretch",
                 help="Bỏ qua ma trận và tự nhập số câu theo chủ đề, dạng và mức độ"):
        st.session_state["gen_plan"] = [{"qtype": "mcq", "topic": qs.TOPICS_12[0], "requirement": "",
                                         "level": "biet", "count": 4}]
        st.rerun()


# ------------------------------------------------------------------ step 2: plan
def _plan_step() -> None:
    name = st.session_state.get("gen_matrix_name")
    st.markdown("#### Bước 2 · Kiểm tra kế hoạch ra câu hỏi")
    st.caption((f"Kế hoạch đọc từ **{name}**. " if name else "")
               + "Thầy/cô có thể sửa, thêm hoặc xóa dòng trước khi tạo câu hỏi.")

    type_names = {v: k for k, v in qs.QTYPES.items()}
    level_names = {v: k for k, v in qs.LEVELS.items()}
    df = pd.DataFrame([{
        "Dạng câu hỏi": qs.qtype_label(r["qtype"]), "Chủ đề": r["topic"], "Yêu cầu cần đạt": r.get("requirement", ""),
        "Mức độ": qs.level_label(r["level"]), "Số câu": int(r["count"]),
    } for r in st.session_state["gen_plan"]])
    edited = st.data_editor(
        df, num_rows="dynamic", hide_index=True, key="gen_plan_editor",
        column_config={
            "Dạng câu hỏi": st.column_config.SelectboxColumn(options=list(qs.QTYPES.values()), required=True),
            "Chủ đề": st.column_config.TextColumn(required=True),
            "Yêu cầu cần đạt": st.column_config.TextColumn(width="large"),
            "Mức độ": st.column_config.SelectboxColumn(options=list(qs.LEVELS.values()), required=True),
            "Số câu": st.column_config.NumberColumn(min_value=0, max_value=30, step=1, required=True),
        },
    )
    plan = []
    for _, row in edited.iterrows():
        if pd.isna(row["Số câu"]) or not row["Dạng câu hỏi"] or not row["Mức độ"] or not str(row["Chủ đề"] or "").strip():
            continue
        if int(row["Số câu"]) > 0:
            plan.append({"qtype": type_names[row["Dạng câu hỏi"]], "topic": str(row["Chủ đề"]).strip(),
                         "requirement": "" if pd.isna(row["Yêu cầu cần đạt"]) else str(row["Yêu cầu cần đạt"]),
                         "level": level_names[row["Mức độ"]], "count": int(row["Số câu"])})

    totals = {t: sum(r["count"] for r in plan if r["qtype"] == t) for t in qs.QTYPES}
    cols = st.columns(3)
    for col, (t, n) in zip(cols, totals.items()):
        col.metric(qs.qtype_label(t), n)
    grand = sum(totals.values())
    if grand > MAX_TOTAL:
        st.warning(f"Mỗi lần tạo tối đa {MAX_TOTAL} câu (hiện {grand}). Hãy giảm số câu hoặc tạo làm nhiều lần.")
    notes = st.text_area("Yêu cầu thêm cho AI (không bắt buộc)", placeholder="VD: Lấy $g = 9{,}8$ m/s²; ưu tiên tình huống thực tế")

    c1, c2 = st.columns(2)
    if c1.button("Làm lại", icon="↩️", width="stretch"):
        _reset()
        st.rerun()
    if c2.button(f"Tạo {grand} câu hỏi", type="primary", icon="✨", width="stretch",
                 disabled=grand == 0 or grand > MAX_TOTAL):
        bar = st.progress(0.0, text="Gemini đang soạn câu hỏi...")

        def progress(done: int, total: int) -> None:
            bar.progress(done / total, text=f"Gemini đang soạn câu hỏi... ({done}/{total})")

        try:
            questions = ai.generate_from_plan(plan, notes, progress)
        except ai.AIError as exc:
            bar.empty()
            st.error(str(exc), icon="🚫")
            return
        for q in questions:
            q["_key"] = uuid.uuid4().hex[:10]
        st.session_state["gen_plan"] = plan
        st.session_state.pop("gen_plan_editor", None)  # edits are now baked into gen_plan
        st.session_state["gen_draft"] = questions
        if len(questions) < grand:
            ui.flash(f"Gemini chỉ tạo được {len(questions)}/{grand} câu hỏi.", "⚠️")
        st.rerun()


# ------------------------------------------------------------------ step 3: review
def _dest_key(q: dict) -> str:
    return f"gen_dest_{q['_key']}"


def _review(user: dict) -> None:
    draft: list[dict] = st.session_state["gen_draft"]
    top = st.columns([3, 1.3], vertical_alignment="center")
    top[0].markdown(f"#### Bước 3 · Duyệt {len(draft)} câu hỏi và chọn kho đề")
    if top[1].button("Quay lại kế hoạch", icon="↩️", width="stretch"):
        st.session_state.pop("gen_draft", None)
        st.rerun()
    st.caption("Mỗi câu hỏi được đưa vào kho đúng với dạng của nó. Chọn kho khác để AI chuyển dạng câu hỏi, "
               "hoặc chọn **Không lưu** để bỏ qua. Thầy/cô có thể sửa nội dung, đáp án trước khi lưu.")
    flagged = sum(1 for q in draft if q.get("ai_check"))
    if flagged:
        st.warning(f"AI đã tự giải lại và thấy **{flagged} câu** có đáp án chưa thống nhất (đánh dấu ⚠️ bên dưới). "
                   "Hãy kiểm tra kĩ các câu này trước khi lưu.", icon="⚠️")

    show = st.segmented_control("Lọc", ["Tất cả", *qs.QTYPES.values()], default="Tất cả",
                                label_visibility="collapsed")
    for i, q in enumerate(draft):
        if show not in (None, "Tất cả") and qs.qtype_label(q["qtype"]) != show:
            continue
        _review_card(draft, i, q)

    dests = {q["_key"]: st.session_state.get(_dest_key(q), q["qtype"]) for q in draft}
    ready = [q for q in draft if dests[q["_key"]] == q["qtype"]]
    pending = [q for q in draft if dests[q["_key"]] not in (SKIP, q["qtype"])]
    st.divider()
    cols = st.columns(3)
    for col, t in zip(cols, qs.QTYPES):
        col.metric(f"Vào {qs.qtype_label(t).lower()}", sum(1 for q in ready if q["qtype"] == t))
    if pending:
        st.warning(f"Có {len(pending)} câu đang chọn kho khác dạng. Hãy bấm **Chuyển dạng bằng AI** ở từng câu "
                   "(hoặc chọn lại kho) trước khi lưu.", icon="⚠️")
    if st.button(f"Lưu {len(ready)} câu vào kho đề", type="primary", icon="💾", width="stretch",
                 disabled=not ready or bool(pending)):
        for q in ready:
            db.add_to_bank(user["id"], q)
        _reset()
        ui.flash(f"Đã lưu {len(ready)} câu hỏi vào kho đề.", "💾")
        st.switch_page(nav.page("bank"))


def _review_card(draft: list[dict], i: int, q: dict) -> None:
    with st.container(border=True):
        st.markdown(f"**Câu {i + 1}** · {qview.meta_line(q)}")
        if q.get("ai_check"):
            st.warning(f"Khi giải lại độc lập, AI ra đáp án **{q['ai_check']}**, khác với đáp án đang ghi "
                       f"(**{qs.answer_text(q)}**). Thầy/cô hãy kiểm tra và sửa nếu cần.", icon="⚠️")
        qview.render_question(q)

        keys = list(DEST_LABELS)
        c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
        dest = c1.selectbox("Đưa vào kho", keys, index=keys.index(q["qtype"]), format_func=DEST_LABELS.get,
                            key=_dest_key(q))
        if c2.button("Bỏ câu này", key=f"gen_del_{q['_key']}", icon="🗑️", width="stretch"):
            draft.pop(i)
            st.rerun()
        if dest not in (SKIP, q["qtype"]):
            st.info(f"Câu hỏi đang ở dạng **{qs.qtype_label(q['qtype']).lower()}**. AI sẽ viết lại câu này thành "
                    f"dạng **{qs.qtype_label(dest).lower()}** để thầy/cô duyệt lại.", icon="🔄")
            if st.button("Chuyển dạng bằng AI", key=f"gen_conv_{q['_key']}", icon="🔄", type="primary"):
                with st.spinner("Gemini đang chuyển dạng câu hỏi..."):
                    try:
                        converted = ai.convert_question(q, dest)
                    except ai.AIError as exc:
                        st.error(str(exc), icon="🚫")
                        return
                converted["_key"] = uuid.uuid4().hex[:10]
                draft[i] = converted
                st.rerun()

        with st.expander("✏️ Sửa câu hỏi và đáp án"):
            edited = qview.question_editor(f"gen_edit_{q['_key']}", q, "Áp dụng")
            if edited:
                edited["ai_check"] = None  # the teacher has reviewed this answer
                draft[i] = edited
                st.rerun()
