"""Compute faithfulness metrics for a generator/judge combination.

Reads the eval set, generator outputs and judge judgments already on disk
(never calls the API) and writes a Markdown report.

Usage:
    python -m metrics.run --gen v1 --judge v2
"""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

EVAL_SET_PATH = Path("data/processed/eval_set.jsonl")
OUT_DIR = Path("results")
INVALID_CASES_PATH = Path("data/processed/invalid_cases.txt")

CASE_TYPES = ["standard", "sparse_profile", "fallback", "low_confidence", "conflicting_signals", "missing_fields"]
BAIT_TYPES = ["health_tags", "cuisine_not_reason", "contradicted_like", "contradicted_history", "none"]


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion."""
    if n == 0:
        return (0.0, 0.0)
    p_hat = successes / n
    denom = 1 + z**2 / n
    center = p_hat + z**2 / (2 * n)
    adjustment = z * math.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2))
    return ((center - adjustment) / denom, (center + adjustment) / denom)


def _judgments_path(gen: str, judge: str) -> Path:
    suffix = "" if judge == "v1" else f"_judge_{judge}"
    return OUT_DIR / f"{gen}{suffix}_judgments.jsonl"


def _load_jsonl(path: Path) -> dict[str, dict]:
    rows = {}
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            rows[row["case_id"]] = row
    return rows


def _case_bait(eval_row: dict) -> list[str]:
    bait = eval_row.get("bait") or []
    return bait if bait else ["none"]


def load_invalid_case_ids(path: Path = INVALID_CASES_PATH) -> set[str]:
    """case_ids with a known-invalid ground-truth payload (see the file's own header)."""
    if not path.exists():
        return set()
    ids = set()
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ids.add(line.split(",")[0])
    return ids


def load_cases(gen: str, judge: str, exclude_ids: set[str] | None = None) -> list[dict]:
    """One merged record per case_id: eval payload + generator output + judgment."""
    eval_rows = _load_jsonl(EVAL_SET_PATH)
    outputs = _load_jsonl(OUT_DIR / f"{gen}_outputs.jsonl")
    judgments = _load_jsonl(_judgments_path(gen, judge))
    exclude_ids = exclude_ids or set()

    cases = []
    for case_id, eval_row in eval_rows.items():
        if case_id not in outputs or case_id not in judgments or case_id in exclude_ids:
            continue
        cases.append({
            "case_id": case_id,
            "payload": eval_row["payload"],
            "bait": _case_bait(eval_row),
            "explanation": outputs[case_id]["explanation"],
            "judgment": judgments[case_id],
        })
    return cases


def _rate_row(label: str, successes: int, n: int) -> str:
    lo, hi = wilson_ci(successes, n)
    rate = successes / n if n else 0.0
    return f"| {label} | {successes}/{n} | {rate:.1%} | [{lo:.1%}, {hi:.1%}] |"


def _pass_rate_line(cat: str, in_group: list[dict]) -> str:
    n = len(in_group)
    passes = sum(1 for c in in_group if c["judgment"]["verdict"] == "pass")
    rate = passes / n if n else 0.0
    return f"| {cat} | {n} | {passes} | {rate:.1%} |"


def _pass_rates_by_case_type(cases: list[dict]) -> list[str]:
    return [_pass_rate_line(ct, [c for c in cases if c["payload"]["case_type"] == ct]) for ct in CASE_TYPES]


def _pass_rates_by_bait(cases: list[dict]) -> list[str]:
    return [_pass_rate_line(bt, [c for c in cases if bt in c["bait"]]) for bt in BAIT_TYPES]


def build_report(gen: str, judge: str, cases: list[dict]) -> str:
    n = len(cases)
    judge_errors = [c for c in cases if c["judgment"]["verdict"] == "judge_error"]
    scored = [c for c in cases if c["judgment"]["verdict"] != "judge_error"]
    n_scored = len(scored)

    passes = sum(1 for c in scored if c["judgment"]["verdict"] == "pass")
    hallucinated = sum(
        1 for c in scored if any(cl.get("supported") is False for cl in c["judgment"].get("claims", []))
    )
    primary_stated = sum(1 for c in scored if c["judgment"].get("primary_reason_stated"))
    length_ok = sum(
        1 for c in scored if c["judgment"].get("rule_check_results", {}).get("word_count", 0) <= 40
    )

    failure_type_counts = Counter()
    for c in scored:
        for ft in c["judgment"].get("failure_types", []):
            failure_type_counts[ft] += 1

    lines = []
    lines.append(f"# {gen} metrics — generator {gen}, judge {judge}\n")
    lines.append(
        f"Computed from {n} eval cases already on disk (`data/processed/eval_set.jsonl`, "
        f"`results/{gen}_outputs.jsonl`, `{_judgments_path(gen, judge)}`). No API calls made by this script.\n"
    )
    if judge_errors:
        lines.append(f"**{len(judge_errors)} judge_error case(s) excluded from all rates below: "
                      f"{', '.join(c['case_id'] for c in judge_errors)}.**\n")

    lines.append("## Headline metrics\n")
    lines.append("| metric | count | rate | 95% CI (Wilson) |")
    lines.append("|---|---|---|---|")
    lines.append(_rate_row("Faithfulness rate (verdict = pass)", passes, n_scored))
    lines.append(_rate_row("Hallucination rate (≥ 1 claim supported=false)", hallucinated, n_scored))
    lines.append(_rate_row("Primary-reason coverage", primary_stated, n_scored))
    lines.append(_rate_row("Length compliance (≤ 40 words)", length_ok, n_scored))
    lines.append("")
    if hallucinated == n_scored - passes:
        lines.append(
            "Hallucination rate exactly matches the fail rate (1 − faithfulness rate) — consistent with "
            "the judge's `supported=false ⇒ verdict=fail` check (`judge/run.py`); no case fails without "
            "an unsupported claim, and none has an unsupported claim without failing.\n"
        )

    lines.append("## Failure counts by type\n")
    lines.append("(a case can carry more than one failure type, so counts don't sum to the fail count)\n")
    lines.append("| failure type | n |")
    lines.append("|---|---|")
    for ft, count in failure_type_counts.most_common():
        lines.append(f"| {ft} | {count} |")
    lines.append("")

    lines.append("## Pass rate by case_type\n")
    lines.append("| case_type | n | pass | rate |")
    lines.append("|---|---|---|---|")
    lines.extend(_pass_rates_by_case_type(scored))
    lines.append("")

    lines.append("## Pass rate by bait type\n")
    lines.append("(a case can carry more than one bait tag; `none` = no bait)\n")
    lines.append("| bait type | n | pass | rate |")
    lines.append("|---|---|---|---|")
    lines.extend(_pass_rates_by_bait(scored))
    lines.append("")

    lines.append("## Example failures\n")
    failing = [c for c in scored if c["judgment"]["verdict"] == "fail"]
    top_types = [ft for ft, _ in failure_type_counts.most_common(2)]
    examples = []
    seen_ids = set()
    for ft in top_types:
        match = next(
            (c for c in failing if ft in c["judgment"].get("failure_types", []) and c["case_id"] not in seen_ids),
            None,
        )
        if match:
            examples.append((f"most common: {ft}", match))
            seen_ids.add(match["case_id"])
    stress_match = next(
        (c for c in failing if c["payload"]["case_type"] != "standard" and c["case_id"] not in seen_ids), None
    )
    if stress_match:
        examples.append((f"stress case ({stress_match['payload']['case_type']})", stress_match))

    for label, c in examples:
        reasons_str = "; ".join(f"{r['code']}={r['value']} ({r['weight']})" for r in c["payload"]["reasons"])
        lines.append(f"**{c['case_id']}** ({label})\n")
        lines.append(f"- Reasons: {reasons_str or '(none)'}")
        lines.append(f"- Explanation: \"{c['explanation']}\"")
        lines.append(f"- Failure types: {', '.join(c['judgment'].get('failure_types', []))}")
        lines.append(f"- Judge rationale: {c['judgment'].get('rationale', '(none)')}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gen", required=True, help="generator version")
    parser.add_argument("--judge", required=True, help="judge version")
    args = parser.parse_args()

    cases = load_cases(args.gen, args.judge)
    report = build_report(args.gen, args.judge, cases)

    out_path = OUT_DIR / f"{args.gen}_metrics.md"
    out_path.write_text(report)
    print(f"Wrote {out_path} from {len(cases)} cases.")


if __name__ == "__main__":
    main()
