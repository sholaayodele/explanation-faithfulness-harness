"""Judge generator explanations against the rubric.

Usage:
    python -m judge.run --version v1 --case-ids c_0001,c_0002
    python -m judge.run --version v1 --limit 10
"""

import argparse
import hashlib
import json
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from judge.rules import check_rules

load_dotenv()

EVAL_SET_PATH = Path("data/processed/eval_set.jsonl")
JUDGE_PROMPT_PATH = Path("judge/prompts/judge_v1.txt")
JUDGE_VERSION = "v1"
CACHE_DIR = Path("results/cache")
OUT_DIR = Path("results")

JUDGE_MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 4096
MAX_ATTEMPTS = 2

PAYLOAD_KEYS = ["recipe", "reasons", "confidence", "fallback", "profile_context", "excluded_by"]

VALID_ABOUT = {"customer", "meal", "flavour"}
VALID_FAILURE_TYPES = {
    "fabrication", "misattribution", "non_causal_reason", "omission",
    "overclaiming", "profile_contradiction", "sensitive_inference",
}

# Binding rule checks -> the failure type code forces when the check fires.
# Enforced here, in code, after the LLM responds - never sent to the LLM as
# an instruction, since a regex false positive (or negative) shouldn't be
# something the LLM is told to blindly trust.
BINDING_OVERRIDES = {
    "health_term_found": "sensitive_inference",
    "excluded_ingredient_found": "profile_contradiction",
    "minutes_mismatch": "fabrication",
}
# Only these rule-check fields are shown to the LLM - hints for its own
# judgment, not instructions to follow mechanically.
LLM_VISIBLE_RULE_CHECK_KEYS = ["time_phrase_without_time_fit", "health_synonym_hint", "word_count"]


def _prompt_hash(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode()).hexdigest()


def _load_prompt() -> str:
    return JUDGE_PROMPT_PATH.read_text()


def _load_eval_set() -> dict[str, dict]:
    rows = {}
    with EVAL_SET_PATH.open() as f:
        for line in f:
            row = json.loads(line)
            rows[row["case_id"]] = row
    return rows


def _load_generator_outputs(generator_version: str) -> dict[str, dict]:
    path = OUT_DIR / f"{generator_version}_outputs.jsonl"
    rows = {}
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            rows[row["case_id"]] = row
    return rows


def _filtered_payload(payload: dict) -> dict:
    return {k: payload[k] for k in PAYLOAD_KEYS}


def _cache_path(generator_version: str, case_id: str) -> Path:
    return CACHE_DIR / f"judge_{JUDGE_VERSION}_{generator_version}_{case_id}.json"


def _valid_source(source: object) -> bool:
    return isinstance(source, str) and (
        source in ("profile_context", "none") or source.startswith("reason:") or source.startswith("recipe:")
    )


def validate_judgment(data: object) -> list[str]:
    """Check shape, enums, and the verdict<->failure_types consistency rule."""
    if not isinstance(data, dict):
        return ["response is not a JSON object"]

    errors = []
    required = ["claims", "primary_reason_stated", "calibration_ok", "safe_ok", "failure_types", "verdict", "rationale"]
    for key in required:
        if key not in data:
            errors.append(f"missing key: {key}")
    if errors:
        return errors

    if not isinstance(data["claims"], list):
        errors.append("claims is not a list")
    else:
        for i, claim in enumerate(data["claims"]):
            if not isinstance(claim, dict):
                errors.append(f"claims[{i}] is not an object")
                continue
            for key in ["text", "about", "source", "supported", "failure_type"]:
                if key not in claim:
                    errors.append(f"claims[{i}] missing key: {key}")
                    continue
            if claim.get("about") not in VALID_ABOUT:
                errors.append(f"claims[{i}].about invalid: {claim.get('about')!r}")
            if not _valid_source(claim.get("source")):
                errors.append(f"claims[{i}].source invalid: {claim.get('source')!r}")
            if not isinstance(claim.get("supported"), bool):
                errors.append(f"claims[{i}].supported is not a bool")
            failure_type = claim.get("failure_type")
            if failure_type is not None and failure_type not in VALID_FAILURE_TYPES:
                errors.append(f"claims[{i}].failure_type invalid: {failure_type!r}")

    for key in ["primary_reason_stated", "calibration_ok", "safe_ok"]:
        if not isinstance(data.get(key), bool):
            errors.append(f"{key} is not a bool")

    failure_types = data.get("failure_types")
    if not isinstance(failure_types, list) or any(ft not in VALID_FAILURE_TYPES for ft in failure_types):
        errors.append(f"failure_types invalid: {failure_types!r}")

    if data.get("verdict") not in ("pass", "fail"):
        errors.append(f"verdict invalid: {data.get('verdict')!r}")

    if not errors:
        is_fail = data["verdict"] == "fail"
        has_failures = bool(failure_types)
        if is_fail != has_failures:
            errors.append(
                f"verdict/failure_types inconsistent: verdict={data['verdict']!r}, failure_types={failure_types!r}"
            )

    if not isinstance(data.get("rationale"), str):
        errors.append("rationale is not a string")

    return errors


def _call_judge(client: anthropic.Anthropic, prompt_text: str) -> tuple[str, int, int]:
    response = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt_text}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "").strip()
    return text, response.usage.input_tokens, response.usage.output_tokens


def judge_case(
    client: anthropic.Anthropic, generator_version: str, case_id: str, payload: dict, explanation: str,
    judge_prompt_text: str, judge_prompt_hash: str,
) -> dict:
    cache_path = _cache_path(generator_version, case_id)
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached["judge_prompt_hash"] != judge_prompt_hash:
            raise RuntimeError(
                f"Cached judgment for {case_id} was generated with a different judge prompt "
                f"(hash {cached['judge_prompt_hash'][:12]}... vs current {judge_prompt_hash[:12]}...). "
                "Delete the stale cache entry or bump the judge prompt version before rerunning."
            )
        return cached

    rule_checks = check_rules(payload, explanation)
    llm_visible_rule_checks = {k: rule_checks[k] for k in LLM_VISIBLE_RULE_CHECK_KEYS}
    filled_prompt = (
        judge_prompt_text
        .replace("{payload_json}", json.dumps(_filtered_payload(payload), indent=2))
        .replace("{explanation}", explanation)
        .replace("{rule_check_json}", json.dumps(llm_visible_rule_checks, indent=2))
    )

    total_input = 0
    total_output = 0
    parsed = None
    raw_text = None
    validation_errors = []
    for _ in range(MAX_ATTEMPTS):
        raw_text, input_tokens, output_tokens = _call_judge(client, filled_prompt)
        total_input += input_tokens
        total_output += output_tokens
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            validation_errors = [f"malformed JSON: {e}"]
            continue
        validation_errors = validate_judgment(data)
        if not validation_errors:
            parsed = data
            break

    tokens = {"input": total_input, "output": total_output}

    if parsed is None:
        # judge_error: not cached, so a rerun retries fresh rather than freezing a failure.
        return {
            "case_id": case_id,
            "generator_version": generator_version,
            "judge_model": JUDGE_MODEL,
            "verdict": "judge_error",
            "validation_errors": validation_errors,
            "raw_response": raw_text,
            "rule_check_results": rule_checks,
            "tokens": tokens,
        }

    raw_verdict = parsed["verdict"]
    raw_failure_types = list(parsed["failure_types"])

    fired_overrides = [flag for flag in BINDING_OVERRIDES if rule_checks[flag]]
    final_failure_types = set(raw_failure_types) | {BINDING_OVERRIDES[flag] for flag in fired_overrides}
    final_verdict = "fail" if final_failure_types else "pass"
    final_safe_ok = parsed["safe_ok"] and not rule_checks["health_term_found"] and not rule_checks["excluded_ingredient_found"]
    outcome_changed = final_verdict != raw_verdict or set(raw_failure_types) != final_failure_types

    result = {
        "case_id": case_id,
        "generator_version": generator_version,
        "judge_model": JUDGE_MODEL,
        "raw_verdict": raw_verdict,
        "raw_failure_types": raw_failure_types,
        "verdict": final_verdict,
        "failure_types": sorted(final_failure_types),
        "code_overrides": fired_overrides,
        "override_changed_outcome": outcome_changed,
        "claims": parsed["claims"],
        "primary_reason_stated": parsed["primary_reason_stated"],
        "calibration_ok": parsed["calibration_ok"],
        "safe_ok": final_safe_ok,
        "rationale": parsed["rationale"],
        "rule_check_results": rule_checks,
        "tokens": tokens,
        "judge_prompt_hash": judge_prompt_hash,
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result, indent=2))
    return result


def _write_judgments(generator_version: str, results: list[dict]) -> Path:
    out_path = OUT_DIR / f"{generator_version}_judgments.jsonl"
    existing = {}
    if out_path.exists():
        with out_path.open() as f:
            for line in f:
                row = json.loads(line)
                existing[row["case_id"]] = row
    for result in results:
        existing[result["case_id"]] = {k: v for k, v in result.items() if k != "judge_prompt_hash"}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for case_id in sorted(existing.keys()):
            f.write(json.dumps(existing[case_id]) + "\n")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, help="generator version to judge")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--case-ids", default=None)
    args = parser.parse_args()

    judge_prompt_text = _load_prompt()
    judge_prompt_hash = _prompt_hash(judge_prompt_text)
    eval_rows = _load_eval_set()
    outputs = _load_generator_outputs(args.version)

    if args.case_ids:
        case_ids = args.case_ids.split(",")
    else:
        case_ids = sorted(outputs.keys())
        if args.limit is not None:
            case_ids = case_ids[: args.limit]

    client = anthropic.Anthropic()

    results = []
    errors = 0
    for case_id in case_ids:
        payload = eval_rows[case_id]["payload"]
        explanation = outputs[case_id]["explanation"]
        result = judge_case(client, args.version, case_id, payload, explanation, judge_prompt_text, judge_prompt_hash)
        results.append(result)
        if result["verdict"] == "judge_error":
            errors += 1
            print(f"{case_id}: JUDGE_ERROR - {result['validation_errors']}")
        else:
            override_note = f" [OVERRIDE: {result['code_overrides']}]" if result["override_changed_outcome"] else ""
            print(f"{case_id}: {result['verdict']} {result['failure_types']}{override_note}")

    out_path = _write_judgments(args.version, results)

    total_input = sum(r["tokens"]["input"] for r in results)
    total_output = sum(r["tokens"]["output"] for r in results)
    overrides = sum(1 for r in results if r.get("override_changed_outcome"))

    print(f"\nJudged {len(results)} cases ({errors} judge_error, not counted; {overrides} code overrides changed the outcome). Wrote {out_path}")
    print(f"Total input tokens: {total_input}, output tokens: {total_output}")


if __name__ == "__main__":
    main()
