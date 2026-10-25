# Excel_AI_RAG: Board Resolution Assistant

A chat application that answers questions from a board resolutions Excel file.
Upload the file, ask a question in plain English, and get an answer that cites the
resolution number and date.

**Stack:** Python, Streamlit, Pinecone (vector database), Gemini Flash-Lite (answers), pandas (Excel).

---

## What it does

- Reads an Excel file with these columns: `Date`, `Month`, `Year`, `Resolution No`, `Particulars`.
- Finds the header row automatically (title rows or blank rows above the header are fine).
- Supports `.xls` and `.xlsx`, and reads every sheet that has the headers.
- Answers questions using only the retrieved resolutions, and cites each one.
- Gives exact counts and lists (for example, "how many resolutions in 2021?") by calculating from the Excel file, not from the AI.
- Shows the source rows under every answer.
- Saves uploaded files, so they load again after the app is restarted.

---

## How it works

| Step | What happens | Tool |
|------|--------------|------|
| 1. Read | Excel is read and cleaned (dates, months, resolution numbers) | pandas |
| 2. Chunk | One resolution = one chunk. The resolution number and date are placed inside the text | Python |
| 3. Embed + store | Pinecone creates the embeddings and stores each chunk with filter fields (day, month, year, date range, resolution number) | Pinecone |
| 4. Understand question | The question is turned into filters (for example year 2019) plus topic words | Gemini |
| 5. Search | Meaning search and keyword search both run, and the results are merged (reciprocal rank fusion). Top 10 are kept | Pinecone |
| 6. Answer | The top resolutions are sent to Gemini, which answers only from them and cites them | Gemini |
| 7. Show | Chat page with upload panel, sources, and saved files | Streamlit |

### Why these tools

- **pandas:** reliable Excel reading, and exact counts without AI.
- **Pinecone:** fully managed (no server to run), has built-in embeddings, and supports meaning and keyword search in one index.
- **Gemini Flash-Lite:** fast and low cost, used only to understand the question and write the answer.
- **Streamlit:** a working web app in plain Python.

### Chunking strategy

Each Excel row is one chunk. A resolution is already a complete decision, so splitting it would hurt answer quality.
The text that is embedded looks like this:

```
Resolution 3.6 dated 19 October 2021: <particulars>
```

Day, month, year, a date number (`yyyymmdd`) and the resolution number are stored as separate filter fields,
because exact dates and numbers are handled better by filters than by embeddings.

---

## Setup

### 1. Pinecone index

The app creates the index for you if it does not exist. The schema it uses:

| Field | Type | Settings |
|-------|------|----------|
| `chunk_text` | string | dense embedding (`llama-text-embed-v2`) + full-text search |
| `title` | string | full-text search |

Other fields (`day`, `month`, `year`, `date_int`, `resolution_no`) are added during upload and are filterable automatically.

> Use a **new index name** that does not already exist (for example `dcmsriram-docs`).
> An older index type (one that shows a vector "Dimension" in the console) does not work with this app.

### 2. Install

```bash
pip install -r requirements.txt
```

### 3. Add your keys

Copy `.env.example` to `.env` and fill it in (the file must be named exactly `.env`):

```
GEMINI_API_KEY=your_gemini_key
PINECONE_API_KEY=your_pinecone_key
PINECONE_INDEX=dcmsriram-docs
GEMINI_MODEL=gemini-3.5-flash-lite
```

You can also type the keys into the **Settings** panel in the app.

### 4. Run

```bash
streamlit run app.py
```

Upload the Excel file in the left panel, wait for indexing to finish, then ask a question.

---

## Example questions

- "What is the borrowing limit for rupee term loans?"
- "How many resolutions were passed in 2021?" (exact count)
- "What is resolution 3.6?" (exact lookup)
- "What was approved about Ajbapur sugar in 2021?"

---

## Project files

```
app.py            Streamlit chat page, question handling, search
common.py         Excel reading, Pinecone connection, indexing
requirements.txt  Python packages
.env.example      Template for keys (no real keys)
saved_files/      Uploaded Excel files (not pushed to Git)
```

---

## Security

- `.env`, `saved_files/` and Excel files are listed in `.gitignore`, so keys and company data are not pushed to GitHub.
- Never put real keys in `.env.example`.
- Resolution text is sent to Pinecone (storage and embeddings) and to Google Gemini (answers). Check that this is allowed for your company data.

---

## Known limits

- Accuracy has not been measured yet. Next step: test 20 to 30 real questions with known answers.
- Very long resolutions are not split into smaller chunks. This can be added if testing shows a need.
- A resolution that refers to an earlier one ("in supersession of...") is not linked to it automatically.
- Pinecone's document index type is new, so check the current Pinecone documentation if an API call fails.
- Resolution numbers stored as plain numbers in Excel can lose trailing zeros (`3.10` becomes `3.1`). Format that column as Text in Excel.
