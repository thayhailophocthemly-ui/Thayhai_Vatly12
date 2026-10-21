"""Rendering and editing of the three question types (shared by teacher and student pages)."""

from __future__ import annotations

import streamlit as st

from . import questions as qs


def meta_line(q: dict) -> str:
    parts = [f"{qs.QTYPE_ICONS.get(q['qtype'], '')} {qs.qtype_label(q['qtype'])}", qs.level_label(q.get("level"))]
    if q.get("topic"):
        parts.append(q["topic"])
    return " · ".join(p for p in parts if p)


def render_question(q: dict, show_answer: bool = True) -> None:
    """Question with its options/statements and (optionally) the correct answer highlighted."""
    st.markdown(q["question"])
    if q["qtype"] == "mcq":
        for j, opt in enumerate(q["options"]):
            text = f"**{qs.LETTERS[j]}.** {opt}"
            if show_answer and j == q["answer"]:
                st.success(text, icon="✔️")
            else:
                st.markdown(text)
    elif q["qtype"] == "tf":
        for j, stmt in enumerate(q["options"]):
            text = f"**{qs.TF_LETTERS[j]})** {stmt}"
            if show_answer:
                text += f" — **{'Đúng' if q['answer'][j] else 'Sai'}**"
            st.markdown(text)
    elif show_answer:
        st.success(f"Đáp án: **{q['answer']}**", icon="✔️")
    if show_answer and q.get("explanation"):
        with st.expander("Lời giải"):
            st.markdown(q["explanation"])


def question_editor(key: str, q: dict, submit_label: str = "Lưu") -> dict | None:
    """A form to edit any question type. Returns the edited question when submitted and valid."""
    qtype = q["qtype"]
    with st.form(key, clear_on_submit=False):
        c1, c2 = st.columns([2, 1])
        topics = list(dict.fromkeys([*( [q["topic"]] if q.get("topic") else []), *qs.TOPICS_12]))
        topic = c1.selectbox("Chủ đề", topics, index=0 if q.get("topic") else None, accept_new_options=True,
                             placeholder="Chọn hoặc gõ chủ đề", key=f"{key}_topic")
        levels = list(qs.LEVELS)
        level = c2.selectbox("Mức độ", levels, index=levels.index(q.get("level") or "biet"),
                             format_func=qs.level_label, key=f"{key}_level")
        label = "Phần dẫn / nội dung câu hỏi *" if qtype == "tf" else "Câu hỏi *"
        text = st.text_area(label, value=q["question"], help="Dùng $...$ để viết công thức, VD: $pV = nRT$",
                            key=f"{key}_q")
        options, answer = [], None
        if qtype == "mcq":
            options = [st.text_input(f"Phương án {qs.LETTERS[j]} *", value=q["options"][j], key=f"{key}_o{j}")
                       for j in range(4)]
            answer = st.radio("Đáp án đúng", range(4), index=q["answer"] if isinstance(q["answer"], int) else 0,
                              horizontal=True, format_func=lambda j: qs.LETTERS[j], key=f"{key}_a")
        elif qtype == "tf":
            answer = []
            for j in range(4):
                c1, c2 = st.columns([4, 1.3], vertical_alignment="bottom")
                options.append(c1.text_input(f"Ý {qs.TF_LETTERS[j]}) *", value=q["options"][j], key=f"{key}_o{j}"))
                truth = c2.radio(f"Ý {qs.TF_LETTERS[j]}", ["Đúng", "Sai"],
                                 index=0 if q["answer"][j] else 1, horizontal=True,
                                 label_visibility="collapsed", key=f"{key}_a{j}")
                answer.append(truth == "Đúng")
        else:
            answer = st.text_input("Đáp án *", value=str(q["answer"] or ""), key=f"{key}_a",
                                   help="Một số, tối đa 4 kí tự, dùng dấu phẩy thập phân. VD: 0,25")
        explanation = st.text_area("Lời giải", value=q.get("explanation") or "", key=f"{key}_e")
        if not st.form_submit_button(submit_label, type="primary", width="stretch"):
            return None
    edited = {**q, "topic": (topic or "").strip(), "level": level, "question": text.strip(),
              "options": [o.strip() for o in options], "answer": answer, "explanation": explanation.strip()}
    error = qs.validate(edited)
    if error:
        st.error(error)
        return None
    return edited


def render_result_item(item: dict, number: int) -> None:
    """One answered practice item: the student's answer next to the correct one."""
    resp = item["response"]
    answered = qs.is_answered(item["qtype"], resp)
    icon = "✅" if item["is_correct"] else ("⏭️" if not answered else "❌")
    head = f"**Câu {number}** {icon} &nbsp;·&nbsp; {meta_line(item)}"
    if item["qtype"] == "tf":
        head += f" &nbsp;·&nbsp; **{item['partial'] or 0}/4 ý đúng**"
    st.markdown(head)
    st.markdown(item["question"])
    if item["qtype"] == "mcq":
        for j, opt in enumerate(item["options"]):
            is_key = j == item["answer"]
            marks = (["em chọn"] if j == resp else []) + (["đáp án đúng"] if is_key else [])
            text = f"**{qs.LETTERS[j]}.** {opt}" + (f"  — *{', '.join(marks)}*" if marks else "")
            if j == resp and not is_key:
                st.error(text, icon="✖️")
            elif is_key:
                st.success(text, icon="✔️")
            else:
                st.markdown(text)
    elif item["qtype"] == "tf":
        given = resp if isinstance(resp, list) else [None] * 4
        for j, stmt in enumerate(item["options"]):
            truth = item["answer"][j]
            chosen = given[j]
            chosen_txt = "chưa chọn" if chosen is None else ("Đúng" if chosen else "Sai")
            text = (f"**{qs.TF_LETTERS[j]})** {stmt}  \nEm chọn: *{chosen_txt}* · Đáp án: **{'Đúng' if truth else 'Sai'}**")
            if chosen is not None and chosen == truth:
                st.success(text, icon="✔️")
            elif chosen is None:
                st.warning(text, icon="➖")
            else:
                st.error(text, icon="✖️")
    else:
        text = f"Em trả lời: *{resp if answered else 'chưa trả lời'}* · Đáp án: **{item['answer']}**"
        if item["is_correct"]:
            st.success(text, icon="✔️")
        elif answered:
            st.error(text, icon="✖️")
        else:
            st.warning(text, icon="➖")
    if not answered:
        st.caption("Em chưa trả lời câu này.")
    if item.get("explanation"):
        with st.expander("Lời giải"):
            st.markdown(item["explanation"])
