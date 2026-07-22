"""Central configuration — everything comes from .env (see .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# DeepSeek (OpenAI-compatible)
DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

# Postgres — 127.0.0.1 (not 'localhost'): Windows resolves localhost to ::1 first and Docker's
# IPv6 mapping can hang; connect_timeout makes any such failure loud instead of a silent hang.
PG = dict(
    host=os.getenv("PGHOST", "127.0.0.1"),
    port=int(os.getenv("PGPORT", "5432")),
    dbname=os.getenv("PGDATABASE", "filings"),
    user=os.getenv("PGUSER", "postgres"),
    password=os.getenv("PGPASSWORD", ""),
    connect_timeout=10,
)

# Embeddings
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

# Chunking
CHUNK_TOKENS = 700          # target size (600–800 band)
CHUNK_OVERLAP_TOKENS = 100  # ~15% overlap
OCR_MIN_CHARS = 100         # per-page: fewer extracted chars than this ⇒ treat page as scanned

# OCR / PDF tooling (Windows binary locations; overridable via .env)
TESSERACT_CMD = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
TESSDATA_DIR = os.getenv("TESSDATA_DIR", r"C:\tools\tessdata")  # holds chi_tra (Program Files needs admin)
POPPLER_PATH = os.getenv("POPPLER_PATH", r"C:\tools\poppler\Library\bin")
OCR_LANG = "chi_tra+eng"
