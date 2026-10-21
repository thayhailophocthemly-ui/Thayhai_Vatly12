# ⚛️ Ôn tập Vật lí 12

A mobile-friendly Streamlit app for **Vật lí lớp 12** (Chương trình GDPT 2018, 2025 exam format).
Teachers build three question banks with Google Gemini, guided by their exam matrix. Students build their own
timed practice sets from those banks, get AI feedback, and can ask the AI about any question.
All data is stored in **Google Sheets**. The interface is in Vietnamese.

## Features

**Teachers**
- **Three question banks:** *Trắc nghiệm nhiều lựa chọn* (4 options), *Trắc nghiệm đúng sai* (a stem with 4
  statements a–d), and *Trắc nghiệm trả lời ngắn* (numeric answer).
- **AI generation from the exam matrix** (*ma trận đề*):
  1. Upload a PDF or Word (.docx) file.
  2. Gemini transcribes every non-zero cell (Phần I/II/III × chủ đề × Biết/Hiểu/Vận dụng). The app converts the
     cells into question counts: true/false statements become questions at 4 statements per question, and points
     convert using the 2025 scale.
  3. Review and edit the plan, then generate.
- **Answer self-check:** Gemini solves every generated question again with the answer hidden. Any disagreement
  is flagged ⚠️ for the teacher.
- **Review before saving:** for each question, edit the content and answer, drop it, and choose which bank it
  goes into. If you pick a bank of a different type, the AI rewrites the question in that format first, for you
  to review.
- **Bank management:** list, filter, add, edit, and delete questions in each bank.
- **Practice history:** a per-student overview, a progress chart, accuracy by topic and level, each session's
  answers and AI feedback, and a CSV export.
- Manage classes and students (create, edit, delete, assign to or remove from a class, CSV import).

**Students**
- Build a practice set: pick one or more banks, how many questions from each, optional topic/level filters,
  and a time limit of up to 60 minutes.
- Timed practice with autosave. It submits automatically when the time runs out, even if the browser was
  closed, and resumes after a refresh.
- Results show the number correct out of the total (true/false also shows how many statements were right),
  all answers and explanations, and **AI feedback** on strengths, weaknesses and progress compared with
  earlier sessions.
- **Ask the AI** about any question in a per-question chat.

## Quick start

```bash
python -m pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then edit it
python -m streamlit run app.py
```

Sign in with `teacher` / `teacher123` (or the `QUIZ_ADMIN_USER` / `QUIZ_ADMIN_PASSWORD` values from your
secrets), then **change the password** under *Tài khoản*.

> Without the `[google_sheets]` / `[gcp_service_account]` sections, the app stores data in a local file
> (`data/quiz_data.json`).
>
> To try things without touching the real spreadsheet, set `QUIZ_LOCAL_DATA` to a file path. The app then
> uses that local file even if Google Sheets is configured. In PowerShell:
> `$env:QUIZ_LOCAL_DATA="sandbox.json"; python -m streamlit run app.py`

## Google Sheets setup

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and **enable the Google Sheets API**.
2. Go to *IAM & Admin → Service accounts*, create a service account, then *Keys → Add key → JSON*.
3. Create an empty Google Spreadsheet and **share it with the service account's `client_email` as Editor**.
4. Copy the spreadsheet URL into `[google_sheets] spreadsheet`. Copy the fields of the JSON key into
   `[gcp_service_account]` in `.streamlit/secrets.toml`.

The app uses these worksheets: `users`, `classes`, `question_bank`, `practice_sessions` and `practice_items`.
Practice items keep a copy of each question, so a student's history stays intact even if the teacher later
edits or deletes the question in the bank.

**Upgrading from the exam version:**
- On first start, existing trusted questions move into the multiple-choice bank.
- The old `exams`, `exam_questions` and `attempts` worksheets are left untouched. Delete them by hand if you
  no longer need them.

**How saving works.** The app keeps the data in memory and saves only the changed rows in one batched request
every ~3 seconds. A whole worksheet is rewritten only after a delete. This keeps the app within the Sheets API
quota (about 60 requests per minute per service account) while a whole class practises. Because of this:
- Run **one** app instance per spreadsheet.
- Editing the sheet by hand while the app is running will be overwritten. If you edit it, click
  **Cài đặt → Tải lại dữ liệu** right afterwards.

## Gemini setup

Get an API key at <https://aistudio.google.com/apikey> and set `GEMINI_API_KEY` in your secrets.
`GEMINI_MODEL` selects the model (default `gemini-2.5-flash`). A larger model reads complex matrices and
writes harder calculation questions more reliably. Teachers can also enter a key for their current session
under **Cài đặt**.

AI-generated questions can still contain mistakes. The self-check flags most of them, but teachers should
review questions before saving them to a bank.

## Project layout

```
app.py                       entry point: login + role-based navigation
quiz_app/store.py            table store: Google Sheets / local JSON backends, batched row-level writes
quiz_app/db.py               data access: users, classes, banks, practice sessions, migration
quiz_app/questions.py        question types, cognitive levels, validation, grading
quiz_app/ai.py               Gemini: matrix reading, generation, answer self-check, feedback, chat
quiz_app/qview.py            rendering/editing of the three question types
quiz_app/practice_view.py    result view, AI feedback, per-question chat, progress chart
quiz_app/views/              one module per page (teacher_*, student_*, login, account)
```
