import os
import hashlib
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from google import genai
from pinecone import Pinecone

# .env is optional now: keys can also be typed in the app sidebar
load_dotenv(Path(__file__).resolve().parent / ".env")

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]

COLUMN_ALIASES = {
    "date": "day", "day": "day",
    "month": "month", "year": "year",
    "resolution number": "resolution_no", "resolution no": "resolution_no",
    "resolution_number": "resolution_no", "resolution_no": "resolution_no",
    "resolution": "resolution_no", "resolution no.": "resolution_no",
    "particulars": "particulars",
}
REQUIRED = ["day", "month", "year", "resolution_no", "particulars"]
BATCH = 96  # max documents per upsert when Pinecone embeds the text


def _norm(c):
    return str(c).strip().lower().rstrip(".").replace("\n", " ")


def _to_month(v):
    s = str(v).strip().lower()
    short = [m[:3] for m in MONTHS]
    if s in MONTHS:
        return MONTHS.index(s) + 1
    if s[:3] in short and not s.replace(".", "").isdigit():
        return short.index(s[:3]) + 1
    try:
        n = int(float(s))
        return n if 1 <= n <= 12 else None
    except ValueError:
        return None


def _find_header(raw):
    """Return (row_index, {column_position: standard_name}) for the first row that looks like the header."""
    for i in range(min(len(raw), 40)):
        mapping = {}
        for j, v in enumerate(raw.iloc[i].tolist()):
            if pd.isna(v):
                continue
            name = COLUMN_ALIASES.get(_norm(v))
            if name and name not in mapping.values():
                mapping[j] = name
        if {"month", "year", "particulars"} <= set(mapping.values()):
            return i, mapping
    return None, None


def load_excel(file):
    sheets = pd.read_excel(file, sheet_name=None, header=None, dtype=str)
    frames, seen = [], []
    for name, raw in sheets.items():
        seen.append(name)
        h, mapping = _find_header(raw)
        if h is None:
            continue
        body = raw.iloc[h + 1:, list(mapping.keys())].copy()
        body.columns = list(mapping.values())
        for col in REQUIRED:
            if col not in body.columns:
                body[col] = None
        frames.append(body[REQUIRED])
    if not frames:
        raise ValueError(
            "Could not find a header row with Date / Month / Year / Resolution No / Particulars "
            f"in any sheet. Sheets checked: {seen}"
        )
    df = pd.concat(frames, ignore_index=True)
    total = len(df)

    df["particulars"] = df["particulars"].astype(str).str.strip()
    df.loc[df["particulars"].isin(["", "nan", "None"]), "particulars"] = None
    df["day"] = pd.to_numeric(df["day"], errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["month"] = df["month"].apply(lambda v: _to_month(v) if pd.notna(v) else None)
    df = df.dropna(subset=["particulars", "day", "month", "year"]).copy()
    df["day"], df["month"], df["year"] = df["day"].astype(int), df["month"].astype(int), df["year"].astype(int)

    df["resolution_no"] = (
        df["resolution_no"].fillna("NA").astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    )
    df.loc[df["resolution_no"].isin(["", "nan", "None"]), "resolution_no"] = "NA"
    df["date_int"] = df["year"] * 10000 + df["month"] * 100 + df["day"]
    df["date_str"] = df.apply(lambda r: f"{r.day} {MONTHS[r.month - 1].title()} {r.year}", axis=1)
    df = df.reset_index(drop=True)  # row position == id suffix "row-<position>"
    df.attrs["skipped"] = total - len(df)
    return df


def namespace_for(file_bytes):
    return "xl-" + hashlib.sha1(file_bytes).hexdigest()[:16]


def get_clients(gemini_key, pinecone_key, index_name):
    return genai.Client(api_key=gemini_key), Pinecone(api_key=pinecone_key).index(index_name)


def is_ingested(index, ns):
    try:
        r = index.documents.search(
            namespace=ns, top_k=1,
            score_by=[{"type": "embed", "fields": ["chunk_text"], "query": "resolution"}],
            include_fields=["*"],
        )
        return len(r.matches) > 0
    except Exception:
        return False


def ingest_df(index, df, ns, progress=None):
    docs = []
    for i, r in df.iterrows():
        docs.append({
            "_id": f"row-{i}",
            "title": f"Resolution {r.resolution_no}",
            "chunk_text": f"Resolution {r.resolution_no} dated {r.date_str}: {r.particulars}",
            "resolution_no": r.resolution_no,
            "day": int(r.day), "month": int(r.month), "year": int(r.year),
            "date_int": int(r.date_int), "date_str": r.date_str,
        })
    for i in range(0, len(docs), BATCH):
        index.documents.upsert(namespace=ns, documents=docs[i:i + BATCH])
        if progress:
            progress(min(i + BATCH, len(docs)) / len(docs))
