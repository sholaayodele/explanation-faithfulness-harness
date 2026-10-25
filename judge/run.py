"""Judge generator explanations against the rubric.

Usage:
    python -m judge.run --version v1 --case-ids c_0001,c_0002
    python -m judge.run --version v1 --limit 10
    python -m judge.run --version v1 --judge-version v2 --limit 10
"""

import argparse
import hashlib
import json
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from judge.rules import check_rules, check_rules_v2

load_dotenv()

EVAL_SET_PATH = Path("data/processed/eval_set.jsonl")
PROMPTS_DIR = Path("judge/prompts")
CACHE_DIR = Path("results/cache")
OUT_DIR = Path("results")

JUDGE_MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 4096
MAX_ATTEMPTS = 2

PAYLOAD_KEYS = ["recipe", "reasons", "confidence", "fallback", "profile_context", "excluded_by"]
VALID_ABOUT = {"customer", "meal", "flavour"}

# Each judge prompt version is a frozen, independent ruleset: once shipped, a
# version's prompt text, rule-check function, failure-type taxonomy and
# binding overrides never change - a new ruling becomes a new version instead.
RULESETS = {
    "v1": {
        "prompt_path": PROMPTS_DIR / "judge_v1.txt",
        "rule_check_fn": check_rules,
        "valid_failure_types": {
            "fabrication", "misattribution", "non_causal_reason", "omission",
            "overclaiming", "profile_contradiction", "sensitive_inference",
        },
        # Binding rule checks -> the failure type code forces when the check fires.
        # Enforced here, in code, after the LLM responds - never sent to the LLM
        # as an instruction, since a regex false positive/negative shouldn't be
        # something the LLM is told to blindly trust.
        "binding_overrides": {
            "health_term_found": "sensitive_inference",
            "excluded_ingredient_found": "profile_contradiction",
            "minutes_mismatch": "fabrication",
        },
    },
    "v2": {
        "prompt_path": PROMPTS_DIR / "judge_v2.txt",
        "rule_check_fn": check_rules_v2,
        "valid_failure_types": {
            "fabrication", "misattribution", "non_causal_reason", "omission",
            "overclaiming", "exclusion_violation", "sensitive_inference",
        },
        "binding_overrides": {
            "health_term_found": "sensitive_inference",
            "excluded_ingredient_found": "exclusion_violation",
            "minutes_mismatch": "fabrication",
        },
    },
}
# Only these rule-check fields are shown to the LLM - hints for its own
# judgment, not instructions to follow mechanically. Same keys across
# versions; the *content* of health_synonym_hint differs (see judge/rules.py).
LLM_VISIBLE_RULE_CHECK_KEYS = ["time_phrase_without_time_fit", "health_synonym_hint", "word_count"]


def _prompt_hash(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode()).hexdigest()


def _load_prompt(judge_version: str) -> str:
    return RULESETS[judge_version]["prompt_path"].read_text()


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


def _cache_path(judge_version: str, generator_version: str, case_id: str) -> Path:
    return CACHE_DIR / f"judge_{judge_version}_{generator_version}_{case_id}.json"


def _valid_source(source: object) -> bool:
    return isinstance(source, str) and (
        source in ("profile_context", "none") or source.startswith("reason:") or source.startswith("recipe:")
    )


def validate_judgment(data: object, valid_failure_types: set[str]) -> list[str]:
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
            if failure_type is not None and failure_type not in valid_failure_types:
                errors.append(f"claims[{i}].failure_type invalid: {failure_type!r}")

    for key in ["primary_reason_stated", "calibration_ok", "safe_ok"]:
        if not isinstance(data.get(key), bool):
            errors.append(f"{key} is not a bool")

    failure_types = data.get("failure_types")
    if not isinstance(failure_types, list) or any(ft not in valid_failure_types for ft in failure_types):
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


def _judge_once(
    client: anthropic.Anthropic, judge_version: str, generator_version: str, case_id: str, payload: dict,
    explanation: str, judge_prompt_text: str, judge_prompt_hash: str,
) -> dict:
    """One full judge pass (LLM call + validation/retry + binding-check merge), no caching."""
    ruleset = RULESETS[judge_version]
    rule_checks = ruleset["rule_check_fn"](payload, explanation)
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
        validation_errors = validate_judgment(data, ruleset["valid_failure_types"])
        if not validation_errors:
            parsed = data
            break

    tokens = {"input": total_input, "output": total_output}

    if parsed is None:
        # judge_error: not cached, so a rerun retries fresh rather than freezing a failure.
        return {
            "case_id": case_id,
            "generator_version": generator_version,
            "judge_version": judge_version,
            "judge_model": JUDGE_MODEL,
            "verdict": "judge_error",
            "validation_errors": validation_errors,
            "raw_response": raw_text,
            "rule_check_results": rule_checks,
            "tokens": tokens,
        }

    raw_verdict = parsed["verdict"]
    raw_failure_types = list(parsed["failure_types"])

    binding_overrides = ruleset["binding_overrides"]
    fired_overrides = [flag for flag in binding_overrides if rule_checks[flag]]
    final_failure_types = set(raw_failure_types) | {binding_overrides[flag] for flag in fired_overrides}
    final_verdict = "fail" if final_failure_types else "pass"
    final_safe_ok = parsed["safe_ok"] and not rule_checks["health_term_found"] and not rule_checks["excluded_ingredient_found"]
    outcome_changed = final_verdict != raw_verdict or set(raw_failure_types) != final_failure_types

    result = {
        "case_id": case_id,
        "generator_version": generator_version,
        "judge_version": judge_version,
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
    return result


def judge_case(
    client: anthropic.Anthropic, judge_version: str, generator_version: str, case_id: str, payload: dict,
    explanation: str, judge_prompt_text: str, judge_prompt_hash: str,
) -> dict:
    cache_path = _cache_path(judge_version, generator_version, case_id)
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached["judge_prompt_hash"] != judge_prompt_hash:
            raise RuntimeError(
                f"Cached judgment for {case_id} was generated with a different judge prompt "
                f"(hash {cached['judge_prompt_hash'][:12]}... vs current {judge_prompt_hash[:12]}...). "
                "Delete the stale cache entry or bump the judge prompt version before rerunning."
            )
        return cached

    result = _judge_once(
        client, judge_version, generator_version, case_id, payload, explanation, judge_prompt_text, judge_prompt_hash
    )
    if result["verdict"] != "judge_error":
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, indent=2))
    return result


def _write_judgments(judge_version: str, generator_version: str, results: list[dict]) -> Path:
    suffix = "" if judge_version == "v1" else f"_judge_{judge_version}"
    out_path = OUT_DIR / f"{generator_version}{suffix}_judgments.jsonl"
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


def run_self_agreement(
    client: anthropic.Anthropic, judge_version: str, generator_version: str, case_ids: list[str],
    eval_rows: dict[str, dict], outputs: dict[str, dict],
    judge_prompt_text: str, judge_prompt_hash: str, repeat: int,
) -> dict:
    """Judge each case `repeat` times, bypassing cache entirely, to measure consistency."""
    per_case_runs = {}
    total_input = 0
    total_output = 0
    for case_id in case_ids:
        payload = eval_rows[case_id]["payload"]
        explanation = outputs[case_id]["explanation"]
        runs = []
        for _ in range(repeat):
            result = _judge_once(
                client, judge_version, generator_version, case_id, payload, explanation,
                judge_prompt_text, judge_prompt_hash,
            )
            total_input += result["tokens"]["input"]
            total_output += result["tokens"]["output"]
            runs.append(result)
        per_case_runs[case_id] = runs

    verdict_matches = 0
    failure_type_matches = 0
    for case_id, runs in per_case_runs.items():
        verdicts = {r["verdict"] for r in runs}
        failure_sets = {frozenset(r.get("failure_types", [])) for r in runs}
        if len(verdicts) == 1:
            verdict_matches += 1
        if len(failure_sets) == 1:
            failure_type_matches += 1

    n = len(per_case_runs)
    return {
        "n_cases": n,
        "repeat": repeat,
        "verdict_match_rate": verdict_matches / n,
        "failure_type_match_rate": failure_type_matches / n,
        "tokens": {"input": total_input, "output": total_output},
        "per_case_runs": per_case_runs,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, help="generator version to judge")
    parser.add_argument("--judge-version", default="v1", choices=sorted(RULESETS.keys()))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--case-ids", default=None)
    parser.add_argument("--no-cache", action="store_true", help="bypass cache entirely (used with --repeat)")
    parser.add_argument("--repeat", type=int, default=1, help="judge each case this many times, for self-agreement")
    args = parser.parse_args()

    judge_prompt_text = _load_prompt(args.judge_version)
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

    if args.no_cache and args.repeat > 1:
        agreement = run_self_agreement(
            client, args.judge_version, args.version, case_ids, eval_rows, outputs,
            judge_prompt_text, judge_prompt_hash, args.repeat,
        )
        pricing = {"input": 2.00 / 1_000_000, "output": 10.00 / 1_000_000}
        cost = agreement["tokens"]["input"] * pricing["input"] + agreement["tokens"]["output"] * pricing["output"]
        # v1 keeps its original filename (already committed); v2+ gets a version marker.
        if args.judge_version == "v1":
            out_path = OUT_DIR / f"{args.version}_judge_self_agreement.json"
        else:
            out_path = OUT_DIR / f"{args.version}_judge_{args.judge_version}_self_agreement.json"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({**agreement, "estimated_cost": cost}, indent=2))
        print(f"Self-agreement over {agreement['n_cases']} cases, {args.repeat} runs each:")
        print(f"  verdict_match_rate: {agreement['verdict_match_rate']:.3f}")
        print(f"  failure_type_match_rate: {agreement['failure_type_match_rate']:.3f}")
        print(f"  tokens: input={agreement['tokens']['input']}, output={agreement['tokens']['output']}")
        print(f"  estimated cost: ${cost:.4f}")
        print(f"  wrote {out_path}")
        return

    results = []
    errors = 0
    for case_id in case_ids:
        payload = eval_rows[case_id]["payload"]
        explanation = outputs[case_id]["explanation"]
        result = judge_case(
            client, args.judge_version, args.version, case_id, payload, explanation, judge_prompt_text, judge_prompt_hash
        )
        results.append(result)
        if result["verdict"] == "judge_error":
            errors += 1
            print(f"{case_id}: JUDGE_ERROR - {result['validation_errors']}")
        else:
            override_note = f" [OVERRIDE: {result['code_overrides']}]" if result["override_changed_outcome"] else ""
            print(f"{case_id}: {result['verdict']} {result['failure_types']}{override_note}")

    out_path = _write_judgments(args.judge_version, args.version, results)

    total_input = sum(r["tokens"]["input"] for r in results)
    total_output = sum(r["tokens"]["output"] for r in results)
    overrides = sum(1 for r in results if r.get("override_changed_outcome"))

    print(f"\nJudged {len(results)} cases ({errors} judge_error, not counted; {overrides} code overrides changed the outcome). Wrote {out_path}")
    print(f"Total input tokens: {total_input}, output tokens: {total_output}")


if __name__ == "__main__":
    main()
