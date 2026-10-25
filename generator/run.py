"""Generate explanations for eval_set.jsonl cases with a versioned prompt.

Usage:
    python -m generator.run --version v1 --limit 10
    python -m generator.run --version v1 --case-ids c_0001,c_0002
"""

import argparse
import hashlib
import json
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

EVAL_SET_PATH = Path("data/processed/eval_set.jsonl")
PROMPTS_DIR = Path("generator/prompts")
CACHE_DIR = Path("results/cache")
OUT_DIR = Path("results")

MODEL = "claude-haiku-5-5"
# Haiku 5.5's own default sampling temperature. Not sent on the request: the Claude
# API's 2026-10-21 version rejects temperature/top_p/top_k entirely, even at the
# default value (400) - recorded here only as documentation of the sampling used.
TEMPERATURE = 1.0
MAX_TOKENS = 120

# Source: Anthropic's published Claude API pricing (platform.claude.com/docs/en/about-claude/pricing),
# cross-checked against the bundled claude-api skill's cached pricing table (cached 2026-10-06).
# Haiku 5.5: $0.10/1M input tokens, $0.50/1M output tokens, for prompts under 100K tokens.
PRICING_PER_TOKEN = {
    "claude-haiku-5-5": {"input": 0.10 / 1_000_000, "output": 0.50 / 1_000_000},
}

PAYLOAD_KEYS = ["recipe", "reasons", "confidence", "fallback", "profile_context", "excluded_by"]


def _prompt_hash(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode()).hexdigest()


def _load_prompt(version: str) -> str:
    return (PROMPTS_DIR / f"{version}.txt").read_text()


def _load_eval_set() -> dict[str, dict]:
    rows = {}
    with EVAL_SET_PATH.open() as f:
        for line in f:
            row = json.loads(line)
            rows[row["case_id"]] = row
    return rows


def _filtered_payload(payload: dict) -> dict:
    """Only the fields the generator should see - never bait or case_type."""
    return {k: payload[k] for k in PAYLOAD_KEYS}


def _cache_path(version: str, case_id: str) -> Path:
    return CACHE_DIR / f"{version}_{case_id}.json"


def _call_model(client: anthropic.Anthropic, prompt_text: str) -> tuple[str, int, int]:
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt_text}],
    )
    explanation = next((b.text for b in response.content if b.type == "text"), "").strip()
    return explanation, response.usage.input_tokens, response.usage.output_tokens


def generate_case(
    client: anthropic.Anthropic, version: str, case_id: str, payload: dict, prompt_text: str, prompt_hash: str
) -> dict:
    cache_path = _cache_path(version, case_id)
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached["prompt_hash"] != prompt_hash:
            raise RuntimeError(
                f"Cached entry for {case_id} was generated with a different prompt "
                f"(hash {cached['prompt_hash'][:12]}... vs current {prompt_hash[:12]}...). "
                "Delete the stale cache entry or bump the prompt version before rerunning."
            )
        return cached

    filled_prompt = prompt_text.format(payload_json=json.dumps(_filtered_payload(payload), indent=2))
    explanation, input_tokens, output_tokens = _call_model(client, filled_prompt)

    result = {
        "case_id": case_id,
        "prompt_version": version,
        "model": MODEL,
        "explanation": explanation,
        "tokens": {"input": input_tokens, "output": output_tokens},
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "prompt_hash": prompt_hash,
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result, indent=2))
    return result


def _write_outputs(version: str, results: list[dict]) -> Path:
    out_path = OUT_DIR / f"{version}_outputs.jsonl"
    existing = {}
    if out_path.exists():
        with out_path.open() as f:
            for line in f:
                row = json.loads(line)
                existing[row["case_id"]] = row
    for result in results:
        existing[result["case_id"]] = {k: v for k, v in result.items() if k != "prompt_hash"}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for case_id in sorted(existing.keys()):
            f.write(json.dumps(existing[case_id]) + "\n")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--case-ids", default=None)
    args = parser.parse_args()

    prompt_text = _load_prompt(args.version)
    prompt_hash = _prompt_hash(prompt_text)
    eval_rows = _load_eval_set()

    if args.case_ids:
        case_ids = args.case_ids.split(",")
    else:
        case_ids = sorted(eval_rows.keys())
        if args.limit is not None:
            case_ids = case_ids[: args.limit]

    client = anthropic.Anthropic()

    results = []
    for case_id in case_ids:
        row = eval_rows[case_id]
        result = generate_case(client, args.version, case_id, row["payload"], prompt_text, prompt_hash)
        results.append(result)
        print(f"{case_id}: {result['explanation']}")

    out_path = _write_outputs(args.version, results)

    total_input = sum(r["tokens"]["input"] for r in results)
    total_output = sum(r["tokens"]["output"] for r in results)
    pricing = PRICING_PER_TOKEN[MODEL]
    cost = total_input * pricing["input"] + total_output * pricing["output"]

    print(f"\nRan {len(results)} cases. Wrote {out_path}")
    print(f"Total input tokens: {total_input}, output tokens: {total_output}")
    print(f"Estimated cost: ${cost:.4f}")


if __name__ == "__main__":
    main()
