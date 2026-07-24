"""Smoke test: verify the configured LLM (any OpenAI-compatible provider) works.

Reads LLM_API_KEY / LLM_BASE_URL / LLM_MODEL from .env (see .env.example).
Run:  python scripts/test_llm.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import llm
from src.config import LLM_BASE_URL, LLM_MODEL


def main() -> None:
    print(f"Provider: {LLM_BASE_URL}  |  Model: {LLM_MODEL}")
    reply = llm.chat(
        [
            {"role": "system", "content": "You are a terse assistant."},
            {"role": "user", "content": "Reply with exactly: LLM_OK"},
        ],
        temperature=0,
    )
    print("reply:", reply)
    print("OK" if "LLM_OK" in reply else "Unexpected reply — check model/endpoint, but the call succeeded.")


if __name__ == "__main__":
    main()
