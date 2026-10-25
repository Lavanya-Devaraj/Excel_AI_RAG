import io
import os
import json
from pathlib import Path
from datetime import datetime
import streamlit as st
from google.genai import types
from common import *

st.set_page_config(page_title="Resolution Assistant", page_icon="📄", layout="wide")

SAVE_DIR = Path(__file__).resolve().parent / "saved_files"  # uploaded files are kept here
SAVE_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------- styling
st.markdown("""
<style>
.stApp { background: #f6f8fc; }
#MainMenu, footer, .stAppDeployButton { visibility: hidden; display: none; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1.2rem; max-width: 1100px; }

section[data-testid="stSidebar"] { background: #eef2f9; border-right: 1px solid #e1e7f2; }
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
    background: #f9fbff; border: 1.5px dashed #b9c7e6; border-radius: 14px; padding: 1.4rem 1rem;
}
.side-title { font-size: 1.25rem; font-weight: 700; color: #16233f; margin-bottom: .2rem; }
.side-sub { color: #5c6b8a; font-size: .92rem; margin-bottom: 1rem; }
.ok-msg { color: #1a9b5a; font-size: .9rem; margin-top: .4rem; font-weight: 500; }

.hdr { display: flex; align-items: center; gap: 14px; }
.hdr .logo { width: 46px; height: 46px; border-radius: 12px; background: #2f6bff; color: #fff;
             display: flex; align-items: center; justify-content: center; font-size: 1.5rem; }
.hdr .t { font-size: 1.45rem; font-weight: 700; color: #16233f; line-height: 1.2; }
.hdr .s { color: #5c6b8a; font-size: .95rem; }

/* chat bubbles */
div[data-testid="stChatMessage"] { background: transparent; padding: .4rem 0; gap: .8rem; }
div[data-testid="stChatMessage"] > div:last-child {
    background: #ffffff; border: 1px solid #e3e8f2; border-radius: 16px; padding: 1rem 1.2rem;
    box-shadow: 0 1px 2px rgba(20,40,90,.04);
}
div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { flex-direction: row-reverse; }
div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) > div:last-child {
    background: #dce8ff; border-color: #cfdcf7; max-width: 75%;
}
[data-testid="stChatMessageAvatarAssistant"] { background: #2f6bff !important; color: #fff !important; border-radius: 50%; }
[data-testid="stChatMessageAvatarUser"] { background: #e6eefc !important; color: #2f6bff !important; border-radius: 50%; }
.ts { color: #6b7a99; font-size: .78rem; margin-top: .3rem; text-align: right; }

div[data-testid="stChatInput"] { border-radius: 16px; border: 1px solid #cfd9ee; background: #fff; }
div[data-testid="stChatInput"] button { background: #2f6bff; color: #fff; border-radius: 10px; }
.empty-card { background: #fff; border: 1px dashed #c6d3ee; border-radius: 16px; padding: 2.2rem;
              text-align: center; color: #5c6b8a; margin-top: 2rem; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- header
h1, h2 = st.columns([6, 1.2])
with h1:
    st.markdown(
        '<div class="hdr"><div class="logo">🔍</div><div>'
        '<div class="t">Resolution Assistant</div>'
        '<div class="s">Ask questions about your board resolutions</div></div></div>',
        unsafe_allow_html=True,
    )
with h2:
    if st.button("🗑  Clear chat", use_container_width=True):
        st.session_state["msgs"] = []
        st.rerun()

# ---------------------------------------------------------------- sidebar: upload + settings
with st.sidebar:
    st.markdown('<div class="side-title">📄 Upload Document</div>'
                '<div class="side-sub">Upload your Excel file containing board resolutions to start asking questions.</div>',
                unsafe_allow_html=True)
    uploaded = st.file_uploader("Upload Excel", type=["xls", "xlsx"], label_visibility="collapsed")
    if uploaded is not None:  # save every new upload to disk so it survives closing the app
        up_bytes = uploaded.getvalue()
        up_name = f"{namespace_for(up_bytes)}__{uploaded.name}"
        if st.session_state.get("last_up") != up_name:
            (SAVE_DIR / up_name).write_bytes(up_bytes)
            st.session_state["last_up"] = up_name
            st.session_state["picked"] = up_name

    saved = sorted(SAVE_DIR.glob("*__*"), key=lambda p: p.stat().st_mtime, reverse=True)
    saved_names = [p.name for p in saved]
    picked = None
    if saved_names:
        if st.session_state.get("picked") not in saved_names:
            st.session_state["picked"] = saved_names[0]  # newest saved file loads automatically
        picked = st.selectbox("Saved files", saved_names, key="picked",
                              format_func=lambda n: n.split("__", 1)[1])
        if st.button("Remove this saved file", use_container_width=True):
            (SAVE_DIR / picked).unlink()
            st.session_state.pop("ns", None)
            st.rerun()
    status = st.empty()
    st.write("")
    with st.expander("⚙️ Settings"):
        gemini_key = st.text_input("Gemini API key", value=os.getenv("GEMINI_API_KEY", ""), type="password")
        pinecone_key = st.text_input("Pinecone API key", value=os.getenv("PINECONE_API_KEY", ""), type="password")
        index_name = st.text_input("Pinecone index name", value=os.getenv("PINECONE_INDEX", "dcmsriram-docs"))
        gen_model = st.text_input("Gemini model", value=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"))
    st.caption("Columns needed: date, month, year, resolution number, particulars")

if "msgs" not in st.session_state:
    st.session_state["msgs"] = []


def empty_state(text):
    st.markdown(f'<div class="empty-card">{text}</div>', unsafe_allow_html=True)
    st.chat_input("Ask a question about the uploaded resolutions...", disabled=True)
    st.stop()


if not (gemini_key and pinecone_key and index_name):
    empty_state("Open <b>⚙️ Settings</b> in the left panel and enter your API keys and index name.")
if picked is None:
    empty_state("⬆️ Upload your Excel file in the left panel to start asking questions.")


@st.cache_resource(show_spinner="Connecting to Pinecone (creating the index if needed)...")
def connect(g, p, n):
    return get_clients(g, p, n)


try:
    client, index = connect(gemini_key, pinecone_key, index_name)
except Exception as e:
    st.error(f"Could not connect to Pinecone: {e}")
    st.stop()

# ---------------------------------------------------------------- load + index the file
file_bytes = (SAVE_DIR / picked).read_bytes()
file_label = picked.split("__", 1)[1]
ns = namespace_for(file_bytes)

if st.session_state.get("ns") != ns:
    try:
        df_new = load_excel(io.BytesIO(file_bytes))
    except Exception as e:
        st.error(f"Could not read the file: {e}")
        st.stop()
    if not is_ingested(index, ns):
        bar = st.progress(0.0, text=f"Indexing {len(df_new)} resolutions...")
        try:
            ingest_df(index, df_new, ns, progress=lambda f: bar.progress(f, text=f"Indexing... {int(f * 100)}%"))
        except Exception as e:
            if "not served by the documents API" in str(e):
                st.error(
                    f"The index '{index_name}' was created as an older Pinecone index type. "
                    "Use a NEW index name in ⚙️ Settings (for example dcmsriram-docs)."
                )
            else:
                st.error(f"Indexing failed: {e}")
            st.stop()
        bar.empty()
    st.session_state.update(ns=ns, df=df_new, msgs=[], skipped=df_new.attrs.get("skipped", 0))

df = st.session_state["df"]
status.markdown(f'<div class="ok-msg">✅ {file_label} · {len(df)} resolutions ready</div>',
                unsafe_allow_html=True)
if st.session_state.get("skipped"):
    st.sidebar.caption(f"{st.session_state['skipped']} rows skipped (blank or missing date/particulars).")

# ---------------------------------------------------------------- query logic
PARSE_PROMPT = """You convert a user's question about a register of resolutions into JSON.
Dates in the data are dd mm yyyy. Return ONLY JSON with these keys:
- "intent": "search" (find/explain what was decided), or "count" (how many), or "list" (list all matching, no topic)
- "search_text": the topic words to search (empty string if none)
- "resolution_no": string or null
- "year": integer or null
- "month": integer 1-12 or null
- "day": integer or null
- "date_from": integer yyyymmdd or null
- "date_to": integer yyyymmdd or null
Use "count" or "list" only when the question is purely about date/number filters with no topic.
Question: """

ANSWER_PROMPT = """Answer the question using ONLY the resolutions below.
Always cite the resolution number and date for each fact (format: Res <number> (<date>)). Use bullet points
when listing several resolutions, oldest first. If the answer is not in them, say so clearly.

Resolutions:
{ctx}

Question: {q}"""


def gen(prompt, as_json=False):
    cfg = types.GenerateContentConfig(response_mime_type="application/json") if as_json else None
    return client.models.generate_content(model=gen_model, contents=prompt, config=cfg).text


def pinecone_filter(p):
    f = {}
    if p.get("resolution_no"): f["resolution_no"] = {"$eq": str(p["resolution_no"])}
    if p.get("year"): f["year"] = {"$eq": int(p["year"])}
    if p.get("month"): f["month"] = {"$eq": int(p["month"])}
    if p.get("day"): f["day"] = {"$eq": int(p["day"])}
    rng = {}
    if p.get("date_from"): rng["$gte"] = int(p["date_from"])
    if p.get("date_to"): rng["$lte"] = int(p["date_to"])
    if rng: f["date_int"] = rng
    return f or None


def pandas_filter(p):
    d = df
    if p.get("resolution_no"): d = d[d.resolution_no == str(p["resolution_no"])]
    if p.get("year"): d = d[d.year == int(p["year"])]
    if p.get("month"): d = d[d.month == int(p["month"])]
    if p.get("day"): d = d[d.day == int(p["day"])]
    if p.get("date_from"): d = d[d.date_int >= int(p["date_from"])]
    if p.get("date_to"): d = d[d.date_int <= int(p["date_to"])]
    return d


def rrf(rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, _id in enumerate(ranking, start=1):
            scores[_id] = scores.get(_id, 0.0) + 1.0 / (k + rank)
    return scores


def hybrid_search(query, flt, top_k=10, fetch_k=30):
    """Semantic (embed) + keyword (BM25) search, fused with reciprocal rank fusion."""
    rankings = []
    for clause in (
        {"type": "embed", "fields": ["chunk_text"], "query": query},
        {"type": "text", "fields": ["chunk_text"], "query": query},
    ):
        try:
            kw = dict(namespace=ns, top_k=fetch_k, score_by=[clause], include_fields=["*"])
            if flt:
                kw["filter"] = flt
            rankings.append([m._id for m in index.documents.search(**kw).matches])
        except Exception as e:
            st.warning(f"{clause['type']} search failed: {e}")
    fused = rrf(rankings)
    ids = sorted(fused, key=fused.get, reverse=True)[:top_k]
    return df.loc[[int(i.split("-")[1]) for i in ids]]


def to_ctx(d):
    return "\n".join(f"Res {r.resolution_no} ({r.date_str}): {r.particulars}" for r in d.itertuples())


def answer(q):
    p = json.loads(gen(PARSE_PROMPT + q, as_json=True))
    intent = p.get("intent", "search")
    no_topic = not p.get("search_text")

    if intent == "count" and no_topic:
        d = pandas_filter(p)
        return f"There are **{len(d)}** matching resolutions.", d
    if (intent == "list" or p.get("resolution_no")) and no_topic:
        d = pandas_filter(p).head(100)
        if d.empty:
            return "No matching resolutions found.", None
        return gen(ANSWER_PROMPT.format(ctx=to_ctx(d), q=q)), d

    d = hybrid_search(p.get("search_text") or q, pinecone_filter(p))
    if d.empty:
        return "No matching resolutions found.", None
    return gen(ANSWER_PROMPT.format(ctx=to_ctx(d), q=q)), d


# ---------------------------------------------------------------- chat UI
def render(m):
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m["role"] == "user":
            st.markdown(f'<div class="ts">{m["time"]}</div>', unsafe_allow_html=True)
        elif m.get("src") is not None and len(m["src"]):
            with st.expander(f"Source rows ({len(m['src'])})"):
                st.dataframe(m["src"], use_container_width=True, hide_index=True)


for m in st.session_state["msgs"]:
    render(m)

if q := st.chat_input("Ask a question about the uploaded resolutions..."):
    um = {"role": "user", "content": q, "time": datetime.now().strftime("%I:%M %p")}
    st.session_state["msgs"].append(um)
    render(um)
    with st.chat_message("assistant"):
        with st.spinner("Searching the resolutions..."):
            try:
                text, src = answer(q)
            except Exception as e:
                text, src = f"Something went wrong: `{e}`", None
    src_view = None
    if src is not None and len(src):
        src_view = src[["resolution_no", "date_str", "particulars"]].rename(
            columns={"resolution_no": "Res No", "date_str": "Date", "particulars": "Particulars"})
    am = {"role": "assistant", "content": text, "src": src_view}
    st.session_state["msgs"].append(am)
    st.rerun()
