"""Model access: Nemotron on Nebius Token Factory, or scripted replies for tests and dry runs."""

import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MODELS = {
    "lightning": "nvidia/Nemotron-3_5-Lightning",
    "super": "nvidia/nemotron-3-super-120b-a12b",
    "ultra": "nvidia/Nemotron-3-Ultra-550b-a55b",
}
BASE_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")


def dotenv(path: Path = ROOT / ".env") -> dict[str, str]:
    """KEY=VALUE pairs from the git-ignored .env file."""
    if not path.is_file():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))
    return {k.strip(): v.strip().strip("\"'") for k, v in pairs}


def api_key() -> str | None:
    return os.environ.get("NEBIUS_API_KEY") or dotenv().get("NEBIUS_API_KEY")


class TokenFactory:
    def __init__(self, base_url: str = BASE_URL):
        from openai import OpenAI

        key = api_key()
        if not key:
            raise RuntimeError("Set NEBIUS_API_KEY, or put NEBIUS_API_KEY=... in .env at the repo root.")
        self.client = OpenAI(base_url=base_url, api_key=key)

    def chat(self, model: str, messages: list[dict], **kw) -> tuple[str, dict]:
        t0 = time.time()
        resp = self.client.chat.completions.create(model=MODELS.get(model, model), messages=messages, **kw)
        usage = resp.usage.model_dump() if resp.usage else {}
        return resp.choices[0].message.content or "", {"latency_s": round(time.time() - t0, 2), **usage}


class Scripted:
    """Returns canned replies in order. Lets the pipelines run end to end without tokens."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def chat(self, model: str, messages: list[dict], **kw) -> tuple[str, dict]:
        self.calls.append([dict(m) for m in messages])  # snapshot; the caller keeps appending
        if not self.replies:
            raise RuntimeError("Scripted LLM ran out of replies")
        return self.replies.pop(0), {"latency_s": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
