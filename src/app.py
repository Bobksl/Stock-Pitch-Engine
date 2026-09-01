"""Module 6 — Streamlit UI: cited chat + alerts feed + corpus overview.

Run from the project root:  streamlit run src/app.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src.config import EMBEDDING_MODEL, LLM_MODEL
from src.db import get_conn
from src.retrieval.chat import answer

st.set_page_config(page_title="Equity Filings RAG", page_icon="📑", layout="wide")


# ---------- cached lookups ----------
@st.cache_data(ttl=60)
def corpus_overview():
    with get_conn() as conn:
        docs = conn.execute("""
            SELECT d.doc_id, d.ticker, co.company_name, d.fiscal_year, d.doc_type,
                   d.page_count, d.is_scanned, count(c.chunk_id) AS chunks
            FROM documents d
            JOIN companies co USING (ticker)
            LEFT JOIN chunks c USING (doc_id)
            GROUP BY d.doc_id, co.company_name
            ORDER BY d.ticker, d.fiscal_year""").fetchall()
    return docs


@st.cache_data(ttl=60)
def filter_options():
    with get_conn() as conn:
        tickers = [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM documents ORDER BY 1")]
        years = [r[0] for r in conn.execute("SELECT DISTINCT fiscal_year FROM documents ORDER BY 1 DESC")]
    return tickers, years


@st.cache_data(ttl=30)
def load_alerts():
    with get_conn() as conn:
        return conn.execute("""
            SELECT a.alert_id, a.alert_type, a.alert_text, a.page_ref, a.created_at,
                   d.ticker, d.fiscal_year, s.section_type, s.start_page, s.end_page
            FROM alerts a
            JOIN documents d USING (doc_id)
            LEFT JOIN sections s USING (section_id)
            ORDER BY a.alert_type DESC, d.ticker, a.alert_id""").fetchall()


# ---------- sidebar ----------
tickers, years = filter_options()
with st.sidebar:
    st.title("📑 Equity Filings RAG")
    st.caption(f"{LLM_MODEL} · {EMBEDDING_MODEL} · PostgreSQL + pgvector · no frameworks")
    f_ticker = st.selectbox("Ticker filter", ["All"] + tickers)
    f_year = st.selectbox("Fiscal year filter", ["All"] + [str(y) for y in years])
    k = st.slider("Chunks to retrieve (top-k)", 4, 16, 8)
    st.divider()
    st.caption("Every answer and alert links back to document, section, and page. "
               "Answers come ONLY from the indexed filings.")

tab_chat, tab_alerts, tab_corpus = st.tabs(["💬 Chat", "🔔 Alerts", "📄 Corpus"])


# ---------- chat ----------
with tab_chat:
    if "history" not in st.session_state:
        st.session_state.history = []

    col_chat, col_src = st.columns([3, 2], gap="large")

    with col_chat:
        for turn in st.session_state.history:
            with st.chat_message("user"):
                st.write(turn["q"])
            with st.chat_message("assistant"):
                st.markdown(turn["a"])

    q = st.chat_input("Ask about the indexed filings, e.g. 'What drove Tencent's margin expansion in 2025?'")
    if q:
        with col_chat:
            with st.chat_message("user"):
                st.write(q)
            with st.chat_message("assistant"), st.spinner("Retrieving + generating…"):
                res = answer(
                    q,
                    ticker=None if f_ticker == "All" else f_ticker,
                    year=None if f_year == "All" else int(f_year),
                    k=k,
                )
                st.markdown(res["answer"])
        st.session_state.history.append({"q": q, "a": res["answer"], "cites": res["citations"]})

    with col_src:
        st.subheader("Sources (latest answer)")
        if st.session_state.history:
            for c in st.session_state.history[-1]["cites"]:
                pages = f"p.{c['page']}" if c["end_page"] == c["page"] else f"p.{c['page']}-{c['end_page']}"
                with st.expander(f"{c['ticker']} {c['fiscal_year']} | {c['section']} | {pages} "
                                 f"(dist {c['distance']:.3f})"):
                    st.caption("Cosine distance — lower is more similar. "
                               "Open the source PDF at the cited page to verify.")
                    if "content" in c:
                        st.text(c["content"][:1200])
        else:
            st.caption("Ask a question to see its supporting chunks here.")


# ---------- alerts ----------
with tab_alerts:
    st.subheader("Alerts feed")
    st.caption("`change_detected` = material YoY changes between two annual reports of the same "
               "issuer (LLM diff of per-section summaries). `new_filing` = ingestion events. "
               "Every alert carries its source document, section, and page.")
    rows = load_alerts()
    changes = [r for r in rows if r[1] == "change_detected"]
    news = [r for r in rows if r[1] == "new_filing"]

    st.markdown(f"#### 🔺 Material changes ({len(changes)})")
    for (_id, _t, text, page_ref, created, ticker, year, stype, sp, ep) in changes:
        head = f"{ticker} FY{year} | {stype or 'n/a'} | source: p.{page_ref}"
        with st.expander(head):
            st.markdown(text)
            st.caption(f"Source section spans p.{sp}-{ep} of the FY{year} report · generated {created:%Y-%m-%d %H:%M}")

    st.markdown(f"#### 📥 New filings ({len(news)})")
    for (_id, _t, text, page_ref, created, ticker, year, stype, sp, ep) in news:
        st.markdown(f"- {text} *({created:%Y-%m-%d %H:%M})*")


# ---------- corpus ----------
with tab_corpus:
    st.subheader("Indexed corpus")
    docs = corpus_overview()
    st.dataframe(
        [{"Ticker": t, "Company": co, "FY": y, "Type": dt, "Pages": pc,
          "OCR'd": "yes" if sc else "no", "Chunks": ch}
         for (_id, t, co, y, dt, pc, sc, ch) in docs],
        use_container_width=True, hide_index=True,
    )
    st.caption("OCR'd = majority of pages required Tesseract (chi_tra+eng) because the PDF text "
               "layer was missing or had a broken font encoding.")
