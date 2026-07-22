"""Smoke test: verify the DeepSeek API key and model work.

Run:  python scripts/test_deepseek.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from src.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL


def main() -> None:
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "You are a terse assistant."},
            {"role": "user", "content": "Reply with exactly: DEEPSEEK_OK"},
        ],
        max_tokens=200,  # v4-flash thinking mode spends reasoning tokens from this budget — keep headroom
        temperature=0,
    )
    print("model:", resp.model)
    print("reply:", resp.choices[0].message.content)
    print("usage:", resp.usage)


if __name__ == "__main__":
    main()
