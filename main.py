"""
Connectivity smoke test — verifies the Groq LLM credentials and config are working.

    python main.py

Use this to confirm GROQ_API_KEY / GROQ_MODEL are set correctly (via .env locally or
SSM on EC2) before launching the app or the queue worker.
"""

import os
import sys

from config import load_config

load_config()  # loads SSM (EC2) or .env (local), then validates required vars

from groq import Groq

_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


def main() -> int:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": "Reply with exactly: AnomaGuard LLM OK"}],
        max_tokens=16,
    )
    print(f"Model: {_MODEL}")
    print(f"Response: {resp.choices[0].message.content.strip()}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — smoke test, surface any failure plainly
        print(f"LLM smoke test FAILED: {exc}")
        sys.exit(1)
