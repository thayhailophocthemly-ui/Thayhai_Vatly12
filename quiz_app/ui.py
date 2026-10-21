"""Shared UI helpers: styling, formatting and session access."""

from __future__ import annotations

from datetime import datetime

import streamlit as st


CSS = """
<style>
:root { --pq-primary: #2563eb; --pq-ok: #16a34a; --pq-bad: #dc2626; --pq-warn: #d97706; }

/* Comfortable reading width + touch-friendly controls */
.block-container { padding-top: 2.2rem; padding-bottom: 4rem; max-width: 960px; }
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
    min-height: 2.75rem; border-radius: 0.6rem; font-weight: 600;
}
div[role="radiogroup"] label { padding: 0.35rem 0.25rem; }
div[role="radiogroup"] { gap: 0.15rem; }

.pq-hero { padding: 1.1rem 1.25rem; border-radius: 1rem; margin-bottom: 1rem;
    background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 55%, #0ea5e9 100%); color: #fff; }
.pq-hero h1, .pq-hero h2 { color: #fff; margin: 0; padding: 0; font-size: 1.55rem; }
.pq-hero p { margin: 0.25rem 0 0; opacity: 0.9; }

.pq-badge { display: inline-block; padding: 0.1rem 0.6rem; border-radius: 999px; font-size: 0.78rem;
    font-weight: 600; border: 1px solid currentColor; white-space: nowrap; }
.pq-badge.draft { color: #64748b; } .pq-badge.published { color: var(--pq-ok); }
.pq-badge.closed { color: var(--pq-bad); } .pq-badge.progress { color: var(--pq-warn); }
.pq-badge.done { color: var(--pq-primary); }

.pq-timer { position: fixed; top: 3.6rem; right: 1rem; z-index: 999990;
    padding: 0.45rem 0.9rem; border-radius: 0.75rem; font-weight: 700; font-size: 1.15rem;
    font-variant-numeric: tabular-nums; color: #fff; background: #1e3a8a;
    box-shadow: 0 6px 18px rgba(0,0,0,0.18); }
.pq-timer.warn { background: var(--pq-warn); }
.pq-timer.danger { background: var(--pq-bad); animation: pq-pulse 1s infinite; }
@keyframes pq-pulse { 50% { opacity: 0.75; } }

@media (max-width: 640px) {
    .block-container { padding-left: 0.9rem; padding-right: 0.9rem; padding-top: 1.6rem; }
    .pq-hero h1, .pq-hero h2 { font-size: 1.25rem; }
    .pq-timer { top: auto; bottom: 1rem; right: 50%; transform: translateX(50%); font-size: 1.3rem; }
    [data-testid="stMetricValue"] { font-size: 1.4rem; }
}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str = "") -> None:
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(f'<div class="pq-hero"><h2>{title}</h2>{sub}</div>', unsafe_allow_html=True)


def badge(text: str, kind: str) -> str:
    return f'<span class="pq-badge {kind}">{text}</span>'


STATUS_BADGES = {
    "in_progress": ("Đang làm", "progress"),
    "submitted": ("Đã nộp", "done"),
    "auto_submitted": ("Tự động nộp", "done"),
}
NOT_STARTED = "Chưa làm"


def status_label(status: str | None) -> str:
    return STATUS_BADGES.get(status or "", (NOT_STARTED,))[0]


def status_badge(status: str | None) -> str:
    text, kind = STATUS_BADGES.get(status or "", (NOT_STARTED, "draft"))
    return badge(text, kind)


def fmt_time(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M") if ts else "-"


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_points(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:g}" if float(value) == round(float(value), 2) else f"{value:.2f}"


def current_user() -> dict | None:
    return st.session_state.get("user")


def require_role(role: str) -> dict:
    user = current_user()
    if not user or user["role"] != role:
        st.error("Bạn không có quyền truy cập trang này.")
        st.stop()
    return user


def flash(message: str, icon: str = "✅") -> None:
    """Queue a toast that survives the next st.rerun()."""
    st.session_state.setdefault("_flash", []).append((message, icon))


def show_flash() -> None:
    for message, icon in st.session_state.pop("_flash", []):
        st.toast(message, icon=icon)
