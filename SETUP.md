# Setup Guide

From zero to a working install. Written for Windows (where it's tested); macOS/Linux notes are
inline. Total time ≈ 30–45 min, most of it waiting on downloads. After this, see
[USAGE.md](USAGE.md).

## What you need

- **Python 3.11+**
- **Docker Desktop** (simplest way to get PostgreSQL + pgvector) — or a native Postgres with the
  `pgvector` extension
- **Tesseract OCR** + **poppler** (only needed for scanned or broken-encoding PDFs; you can skip
  them if all your PDFs have a clean text layer)
- **An API key for any OpenAI-compatible LLM** (DeepSeek, OpenAI, OpenRouter, Groq, …) — or a
  local model via Ollama / LM Studio (no key, no cost)

---

## 1. Get the code and Python environment

```bash
git clone https://github.com/Bobksl/Equity-Filings-RAG.git
cd Equity-Filings-RAG

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

> Tip: put the virtualenv outside any cloud-synced folder (OneDrive/Dropbox/iCloud) — syncing
> thousands of package files is slow and can corrupt them.

The first run downloads the embedding model **BAAI/bge-m3 (~2.3 GB)** into your Hugging Face
cache. One-time; do it on decent Wi-Fi.

## 2. PostgreSQL + pgvector (Docker — recommended)

```bash
docker run --name filings-db -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=filings \
  -p 5432:5432 -d pgvector/pgvector:pg18
```

Load the schema (7 tables + the HNSW vector index):

```bash
# macOS/Linux/Git Bash:
docker exec -i filings-db psql -U postgres -d filings < schema.sql
# Windows PowerShell (no '<' redirection):
Get-Content schema.sql | docker exec -i filings-db psql -U postgres -d filings
```

*Native Postgres instead of Docker:* install PostgreSQL 16+, install the `pgvector` extension,
`createdb filings`, then run `schema.sql` (it begins with `CREATE EXTENSION IF NOT EXISTS vector`).

## 3. OCR tools (optional — for scanned / broken-font PDFs)

**Tesseract**
- Windows: install the [UB Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki). On the
  "Choose components" screen, expand **Additional language data** and tick every language your
  filings use (e.g. Chinese Traditional `chi_tra`). macOS: `brew install tesseract tesseract-lang`.
  Linux: `sudo apt install tesseract-ocr tesseract-ocr-chi-tra`.
- The default OCR language is `chi_tra+eng` (see `OCR_LANG` in `src/config.py`); change it to match
  your documents (e.g. `eng`, or `chi_sim+eng`).
- If a needed `.traineddata` file isn't in Tesseract's install dir (Windows `Program Files` needs
  admin to write), drop it in any folder and point `TESSDATA_DIR` at it in `.env`.

**poppler** (renders PDF pages to images for OCR)
- Windows: download a [poppler-windows release](https://github.com/oschwartz10612/poppler-windows/releases),
  unzip, and set `POPPLER_PATH` in `.env` to its `Library\bin` folder (or add it to PATH).
  macOS: `brew install poppler`. Linux: `sudo apt install poppler-utils`.

## 4. Configure `.env`

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Edit `.env`:
- **LLM:** set `LLM_API_KEY`, and `LLM_BASE_URL` + `LLM_MODEL` for your provider. The file has a
  ready-to-copy table for DeepSeek / OpenAI / OpenRouter / Groq / Together / Mistral / Ollama /
  LM Studio.
- **Postgres:** set `PGPASSWORD=devpass` (matches the Docker command above). Keep `PGHOST=127.0.0.1`
  on Windows (see Troubleshooting).
- **Embeddings:** the defaults (`BAAI/bge-m3`, `EMBEDDING_DIM=1024`) match `schema.sql`. If you
  change the embedding model, update `EMBEDDING_DIM` **and** the `vector(1024)` column in
  `schema.sql` to its output dimension.

## 5. Verify

```bash
python scripts/test_llm.py       # should print your provider/model then "LLM_OK ... OK"
python -m src.db                 # should print the PostgreSQL version string
```

Both green? You're ready — head to [USAGE.md](USAGE.md) to index your first PDF.

---

## Daily startup

1. Start Docker Desktop, then `docker start filings-db`.
2. Activate the virtualenv.
3. Run modules from the project root: `python -m src.<module>` (Windows: add `-X utf8`).

## Troubleshooting

- **DB calls hang forever (Windows):** use `PGHOST=127.0.0.1`, not `localhost`. Windows resolves
  `localhost` to IPv6 `::1` first, and Docker's IPv6 port mapping can hang silently. `config.py`
  also sets a 10 s connect timeout so failures are loud.
- **"could not connect" / VS Code can't reach the DB:** the container isn't running — `docker start
  filings-db`. Connection details: host `127.0.0.1`, port `5432`, user `postgres`, password
  `devpass`, database `filings`.
- **Empty LLM replies:** some reasoning models spend the whole output budget on hidden thinking.
  Raise `LLM_MAX_TOKENS` in `.env`.
- **Summarizer errors on huge sections:** your model's context is smaller than a section — lower
  `LLM_SECTION_TEXT_CAP` in `.env` (e.g. `60000`).
- **Tesseract "Failed loading language":** the `.traineddata` isn't found — point `TESSDATA_DIR` at
  the folder that contains it. (The code sets `TESSDATA_PREFIX` internally; don't pass
  `--tessdata-dir` through pytesseract, it mishandles quoted paths.)
- **Unicode errors in the console (Windows):** run Python with `-X utf8`.
- **Embedding is slow:** ~25 min per ~200-page filing on CPU is normal (one-time per document).
  For a lighter model, set `EMBEDDING_MODEL=intfloat/multilingual-e5-base` + `EMBEDDING_DIM=768`
  in `.env` and change `vector(1024)` → `vector(768)` in `schema.sql` before loading it.
