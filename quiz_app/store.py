"""Table store persisted to Google Sheets (one worksheet per table) or a local JSON file.

All reads are served from an in-memory copy that is loaded once at startup.
Writes update memory immediately; a background thread flushes changes every few
seconds in a single batched request. Only changed rows are written (a whole
worksheet is rewritten only after deletes or a schema change), which keeps the
app fast and well inside the Google Sheets API quota (~60 requests/minute) even
when a whole class is practising at the same time.

NOTE: the app owns the spreadsheet while it is running - manual edits made in
Google Sheets will be overwritten. Use "Tải lại dữ liệu" (Cài đặt) after editing
the sheet by hand. Worksheets that are not listed in SCHEMA are never touched.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

log = logging.getLogger(__name__)

# column -> type. Types: int, float, str, json, bool. Empty cell == None.
SCHEMA: dict[str, dict[str, str]] = {
    "users": {
        "id": "int", "username": "str", "password_hash": "str", "full_name": "str", "role": "str",
        "student_code": "str", "email": "str", "class_id": "int", "created_by": "int", "created_at": "float",
    },
    "classes": {
        "id": "int", "name": "str", "class_number": "str", "teacher_id": "int", "created_at": "float",
    },
    # qtype: mcq | tf | short. level: biet | hieu | vandung.
    # options: mcq -> 4 choices, tf -> 4 statements, short -> [].
    # answer:  mcq -> int index, tf -> [bool x4], short -> str.
    "question_bank": {
        "id": "int", "teacher_id": "int", "qtype": "str", "topic": "str", "level": "str", "question": "str",
        "options": "json", "answer": "json", "explanation": "str", "created_at": "float", "updated_at": "float",
        # legacy columns from v1 (multiple-choice only); migrated on startup, kept for reference
        "correct_index": "int", "difficulty": "str",
    },
    "practice_sessions": {
        "id": "int", "student_id": "int", "teacher_id": "int", "qtypes": "json", "duration_minutes": "int",
        "started_at": "float", "deadline": "float", "submitted_at": "float", "status": "str",
        "total": "int", "correct": "int", "ai_feedback": "str",
    },
    # One row per question in a practice session; the question is snapshotted so history
    # stays intact when the teacher edits or deletes the bank question later.
    "practice_items": {
        "id": "int", "session_id": "int", "position": "int", "bank_id": "int", "qtype": "str", "topic": "str",
        "level": "str", "question": "str", "options": "json", "answer": "json", "explanation": "str",
        "response": "json", "is_correct": "bool", "partial": "int",
    },
}

FLUSH_INTERVAL_SECONDS = 3.0


def _encode(value: Any, typ: str) -> str:
    if value is None:
        return ""
    if typ == "json":
        return json.dumps(value, ensure_ascii=False)
    if typ == "bool":
        return "TRUE" if value else "FALSE"
    if typ == "float":
        return repr(float(value))
    return str(value)


def _decode(raw: Any, typ: str) -> Any:
    if raw is None or raw == "":
        return None
    try:
        if typ == "int":
            return int(float(raw))
        if typ == "float":
            return float(raw)
        if typ == "bool":
            return str(raw).strip().upper() in ("TRUE", "1", "YES")
        if typ == "json":
            return json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError):
        log.warning("Could not decode %r as %s", raw, typ)
        return None
    return str(raw)


# ------------------------------------------------------------------ backends
class LocalJsonBackend:
    """Fallback for local development when no Google credentials are configured."""

    label = "Local JSON file"
    granular = False  # always receives whole tables

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> dict[str, list[list[str]]]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, full: dict[str, list[list[str]]], rows: dict[str, list[tuple[int, list[str]]]]) -> None:
        current = self.load_all()
        current.update(full)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)


class GoogleSheetsBackend:
    """Stores each table in its own worksheet; row 1 is the header."""

    label = "Google Sheets"
    granular = True
    _GROW_ROWS = 500

    def __init__(self, service_account_info: dict, spreadsheet: str):
        import gspread

        client = gspread.service_account_from_dict(service_account_info)
        if spreadsheet.startswith("http"):
            self.sh = client.open_by_url(spreadsheet)
        else:
            self.sh = client.open_by_key(spreadsheet)
        self.url = self.sh.url
        self._worksheets = {ws.title: ws for ws in self.sh.worksheets()}
        self._written_rows: dict[str, int] = {}

    def _worksheet(self, table: str, n_cols: int):
        ws = self._worksheets.get(table)
        if ws is None:
            ws = self.sh.add_worksheet(title=table, rows=self._GROW_ROWS, cols=max(n_cols, 1))
            self._worksheets[table] = ws
        return ws

    def _ensure_grid(self, ws, n_rows: int, n_cols: int) -> None:
        if n_rows > ws.row_count or n_cols > ws.col_count:
            ws.resize(rows=max(ws.row_count, n_rows + self._GROW_ROWS), cols=max(ws.col_count, n_cols))

    def load_all(self) -> dict[str, list[list[str]]]:
        titles = [t for t in SCHEMA if t in self._worksheets]
        if not titles:
            return {}
        # One request for every table.
        resp = self.sh.values_batch_get([f"'{t}'" for t in titles],
                                        params={"valueRenderOption": "UNFORMATTED_VALUE"})
        out = {}
        for title, vr in zip(titles, resp.get("valueRanges", [])):
            values = [[("" if c is None else str(c)) for c in row] for row in vr.get("values", [])]
            out[title] = values
            self._written_rows[title] = len(values)
        return out

    def save(self, full: dict[str, list[list[str]]], rows: dict[str, list[tuple[int, list[str]]]]) -> None:
        data = []
        for table, values in full.items():
            n_cols = len(values[0])
            ws = self._worksheet(table, n_cols)
            # Pad with blank rows so rows deleted since the last write are cleared.
            previous = self._written_rows.get(table, 0)
            padded = values + [[""] * n_cols for _ in range(max(0, previous - len(values)))]
            self._ensure_grid(ws, len(padded), n_cols)
            data.append({"range": f"'{table}'!A1", "values": padded})
        for table, changed in rows.items():
            if not changed:
                continue
            n_cols = len(changed[0][1])
            ws = self._worksheet(table, n_cols)
            self._ensure_grid(ws, max(r for r, _ in changed), n_cols)
            data += [{"range": f"'{table}'!A{r}", "values": [vals]} for r, vals in changed]
        if data:
            self.sh.values_batch_update({"valueInputOption": "RAW", "data": data})
        for table, values in full.items():
            self._written_rows[table] = len(values)
        for table, changed in rows.items():
            if changed:
                self._written_rows[table] = max(self._written_rows.get(table, 0), max(r for r, _ in changed))


# ------------------------------------------------------------------ store
class TableStore:
    def __init__(self, backend):
        self.backend = backend
        self._lock = threading.RLock()
        self._flush_lock = threading.Lock()  # one flush at a time, so snapshots are written in order
        self._tables: dict[str, list[dict]] = {}
        self._full_dirty: set[str] = set()
        self._row_dirty: dict[str, set[int]] = {}
        self.last_flush_error: str | None = None
        self.last_flush_at: float | None = None
        self.reload()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._flush_loop, name="store-flusher", daemon=True)
        self._thread.start()
        atexit.register(self.flush)

    # ---- loading / flushing
    def reload(self) -> None:
        raw = self.backend.load_all()
        with self._lock:
            self._tables = {}
            self._full_dirty = set()
            self._row_dirty = {}
            for table, columns in SCHEMA.items():
                values = raw.get(table) or []
                rows: list[dict] = []
                if values:
                    header = values[0]
                    for line in values[1:]:
                        if not any(str(c).strip() for c in line):
                            continue
                        cells = dict(zip(header, line))
                        rows.append({col: _decode(cells.get(col), typ) for col, typ in columns.items()})
                    if header != list(columns):  # new/reordered columns -> rewrite with current header
                        self._full_dirty.add(table)
                else:  # missing worksheet / empty table -> write the header
                    self._full_dirty.add(table)
                self._tables[table] = [r for r in rows if r.get("id") is not None]
        self.flush()

    def _serialize_row(self, table: str, row: dict) -> list[str]:
        return [_encode(row.get(col), typ) for col, typ in SCHEMA[table].items()]

    def _serialize(self, table: str) -> list[list[str]]:
        return [list(SCHEMA[table])] + [self._serialize_row(table, r) for r in self._tables[table]]

    def flush(self) -> None:
        with self._flush_lock:
            self._flush()

    def _flush(self) -> None:
        with self._lock:
            if not self._full_dirty and not any(self._row_dirty.values()):
                return
            full_tables = set(self._full_dirty)
            row_dirty = {t: set(ids) for t, ids in self._row_dirty.items() if ids}
            if not self.backend.granular:
                full_tables |= set(row_dirty)
                row_dirty = {}
            full = {t: self._serialize(t) for t in full_tables}
            rows: dict[str, list[tuple[int, list[str]]]] = {}
            for t, ids in row_dirty.items():
                if t in full_tables:
                    continue
                # Sheet row number = position in the table + 2 (1-based, header in row 1).
                rows[t] = [(i + 2, self._serialize_row(t, r)) for i, r in enumerate(self._tables[t]) if r["id"] in ids]
            self._full_dirty.clear()
            self._row_dirty.clear()
        try:
            self.backend.save(full, rows)
            self.last_flush_error = None
            self.last_flush_at = time.time()
        except Exception as exc:  # keep data in memory and retry on next tick
            log.exception("Flush failed")
            self.last_flush_error = str(exc)
            with self._lock:
                self._full_dirty |= full_tables
                for t, ids in row_dirty.items():
                    self._row_dirty.setdefault(t, set()).update(ids)

    def _flush_loop(self) -> None:
        while not self._stop.wait(FLUSH_INTERVAL_SECONDS):
            self.flush()

    @property
    def pending_tables(self) -> set[str]:
        with self._lock:
            return set(self._full_dirty) | {t for t, ids in self._row_dirty.items() if ids}

    def _mark(self, table: str, row_id: int) -> None:
        self._row_dirty.setdefault(table, set()).add(row_id)

    # ---- CRUD
    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def all(self, table: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._tables[table]]

    def where(self, table: str, pred: Callable[[dict], bool] | None = None, **eq) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._tables[table]
                    if all(r.get(k) == v for k, v in eq.items()) and (pred is None or pred(r))]

    def get(self, table: str, row_id: int | None) -> dict | None:
        if row_id is None:
            return None
        with self._lock:
            for r in self._tables[table]:
                if r["id"] == row_id:
                    return dict(r)
        return None

    def insert(self, table: str, row: dict) -> int:
        with self._lock:
            rows = self._tables[table]
            new_id = max((r["id"] for r in rows), default=0) + 1
            clean = {col: row.get(col) for col in SCHEMA[table]}
            clean["id"] = new_id
            rows.append(clean)
            self._mark(table, new_id)
            return new_id

    def insert_many(self, table: str, rows: Iterable[dict]) -> list[int]:
        with self._lock:
            return [self.insert(table, r) for r in rows]

    def update(self, table: str, row_id: int, **fields) -> bool:
        with self._lock:
            for r in self._tables[table]:
                if r["id"] == row_id:
                    r.update({k: v for k, v in fields.items() if k in SCHEMA[table] and k != "id"})
                    self._mark(table, row_id)
                    return True
        return False

    def delete(self, table: str, pred: Callable[[dict], bool]) -> int:
        with self._lock:
            before = len(self._tables[table])
            self._tables[table] = [r for r in self._tables[table] if not pred(r)]
            removed = before - len(self._tables[table])
            if removed:
                self._full_dirty.add(table)  # rows shifted -> rewrite the worksheet
            return removed
