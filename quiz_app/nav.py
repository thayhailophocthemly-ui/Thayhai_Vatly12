"""Per-session registry of navigation pages (filled by app.py) so views can link to each other."""

import streamlit as st


def register(pages: dict) -> None:
    # The default page is served at the root and may report an empty url_path -> key it as "home".
    st.session_state["_pages"] = {(p.url_path or "home"): p for group in pages.values() for p in group}


def page(url_path: str):
    return st.session_state["_pages"][url_path]
