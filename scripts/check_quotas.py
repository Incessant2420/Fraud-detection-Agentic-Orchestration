"""Hit Groq's rate-limit headers for each configured model and write
current RPM/RPD/TPM/TPD into config/quotas.yaml.

Groq does not expose a dedicated quota endpoint; the canonical way to read
live limits is to make one minimal chat completion per model and read the
`x-ratelimit-*` response headers Groq attaches to every call.
"""
import os
import sys
import yaml
import requests
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

API_KEY = os.environ.get("GROQ_API_KEY")
if not API_KEY:
    print("GROQ_API_KEY not set", file=sys.stderr)
    sys.exit(1)

MODELS_CFG = yaml.safe_load(open(ROOT / "config" / "models.yaml"))
MODEL_IDS = sorted({
    MODELS_CFG["executor"]["model"],
    MODELS_CFG["synthesizer"]["model"],
    MODELS_CFG["critic"]["model"],
    MODELS_CFG["judge"]["model"],
    MODELS_CFG["fallback_mid_tier"]["model"],
})

HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
RATELIMIT_KEYS = [
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
]


def probe(model: str) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=HEADERS,
        json=body,
        timeout=30,
    )
    out = {"model": model, "http_status": resp.status_code}
    for k in RATELIMIT_KEYS:
        out[k.replace("x-ratelimit-", "")] = resp.headers.get(k)
    if resp.status_code >= 400:
        out["error"] = resp.text[:300]
    return out


def main():
    results = {}
    for model in MODEL_IDS:
        print(f"probing {model} ...")
        r = probe(model)
        results[model] = r
        print(f"  status={r['http_status']} "
              f"req_remaining={r.get('remaining-requests')}/{r.get('limit-requests')} "
              f"tok_remaining={r.get('remaining-tokens')}/{r.get('limit-tokens')}")

    out_path = ROOT / "config" / "quotas.yaml"
    with open(out_path, "w") as f:
        yaml.safe_dump({"probed_at_note": "live probe via chat-completions ratelimit headers",
                         "models": results}, f, sort_keys=False)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
