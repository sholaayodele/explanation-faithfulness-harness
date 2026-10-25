"""Compare two generator versions judged by the same judge version.

Reads results already on disk (never calls the API) and writes a Markdown
report plus a hallucination-by-case_type chart.

Usage:
    python -m metrics.compare --baseline v1 --candidate v2 --judge v2
"""

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt

from metrics.run import BAIT_TYPES, CASE_TYPES, load_cases, wilson_ci

OUT_DIR = Path("results")


def mcnemar(b: int, c: int) -> tuple[float, float]:
    """Continuity-corrected McNemar chi-square test on discordant pairs.

    b = n(baseline pass, candidate fail), c = n(baseline fail, candidate pass).
    For 1 degree of freedom, P(chi2 > x) = erfc(sqrt(x/2)) - the standard
    relationship between chi2(1) and the normal distribution, used here
    instead of a scipy dependency.
    """
    if b + c == 0:
        return (0.0, 1.0)
    chi2 = (abs(b - c) - 1) ** 2 / (b + c)
    p = math.erfc(math.sqrt(chi2 / 2))
    return chi2, p


def _rate(n_pass: int, n: int) -> float:
    return n_pass / n if n else 0.0


def _ci_rate_line(label: str, a_pass: int, a_n: int, b_pass: int, b_n: int) -> str:
    a_lo, a_hi = wilson_ci(a_pass, a_n)
    b_lo, b_hi = wilson_ci(b_pass, b_n)
    return (
        f"| {label} | {a_pass}/{a_n} ({_rate(a_pass, a_n):.1%}) [{a_lo:.1%}, {a_hi:.1%}] "
        f"| {b_pass}/{b_n} ({_rate(b_pass, b_n):.1%}) [{b_lo:.1%}, {b_hi:.1%}] |"
    )


def _case_counts(cases: list[dict]) -> dict:
    n = len(cases)
    passes = sum(1 for c in cases if c["judgment"]["verdict"] == "pass")
    hallucinated = sum(
        1 for c in cases if any(cl.get("supported") is False for cl in c["judgment"].get("claims", []))
    )
    primary = sum(1 for c in cases if c["judgment"].get("primary_reason_stated"))
    length_ok = sum(1 for c in cases if c["judgment"].get("rule_check_results", {}).get("word_count", 0) <= 40)
    return {"n": n, "passes": passes, "hallucinated": hallucinated, "primary": primary, "length_ok": length_ok}


def _failure_counts(cases: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for c in cases:
        for ft in c["judgment"].get("failure_types", []):
            counts[ft] = counts.get(ft, 0) + 1
    return counts


def _case_type_pass_rate(cases: list[dict], case_type: str) -> tuple[int, int]:
    in_group = [c for c in cases if c["payload"]["case_type"] == case_type]
    return sum(1 for c in in_group if c["judgment"]["verdict"] == "pass"), len(in_group)


def _bait_pass_rate(cases: list[dict], bait: str) -> tuple[int, int]:
    in_group = [c for c in cases if bait in c["bait"]]
    return sum(1 for c in in_group if c["judgment"]["verdict"] == "pass"), len(in_group)


def _hallucination_rate_by_case_type(cases: list[dict], case_type: str) -> float:
    in_group = [c for c in cases if c["payload"]["case_type"] == case_type]
    if not in_group:
        return 0.0
    n_halluc = sum(1 for c in in_group if any(cl.get("supported") is False for cl in c["judgment"].get("claims", [])))
    return n_halluc / len(in_group)


def write_chart(baseline_cases: list[dict], candidate_cases: list[dict], baseline: str, candidate: str, out_path: Path) -> None:
    x = range(len(CASE_TYPES))
    baseline_rates = [_hallucination_rate_by_case_type(baseline_cases, ct) * 100 for ct in CASE_TYPES]
    candidate_rates = [_hallucination_rate_by_case_type(candidate_cases, ct) * 100 for ct in CASE_TYPES]

    width = 0.35
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar([i - width / 2 for i in x], baseline_rates, width, label=baseline, color="#94a3b8")
    ax.bar([i + width / 2 for i in x], candidate_rates, width, label=candidate, color="#2563eb")
    ax.set_xticks(list(x))
    ax.set_xticklabels(CASE_TYPES, rotation=20, ha="right")
    ax.set_ylabel("Hallucination rate (%)")
    ax.set_title(f"Hallucination rate by case_type: {baseline} vs. {candidate}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def build_report(
    baseline: str, candidate: str, judge: str,
    baseline_cases: list[dict], candidate_cases: list[dict],
    baseline_by_id: dict, candidate_by_id: dict,
) -> str:
    b_counts = _case_counts(baseline_cases)
    c_counts = _case_counts(candidate_cases)
    b_failures = _failure_counts(baseline_cases)
    c_failures = _failure_counts(candidate_cases)

    lines = []
    lines.append(f"# {baseline} vs. {candidate} — judged by {judge}\n")
    lines.append(
        f"Both generator versions judged by judge {judge} on the same 200 cases. All numbers computed from "
        f"`results/{baseline}_outputs.jsonl`, `results/{candidate}_outputs.jsonl`, and their judge-{judge} "
        f"judgment files already on disk; this script makes no API calls.\n"
    )

    lines.append("## Headline metrics (95% Wilson CI)\n")
    lines.append(f"| metric | {baseline} | {candidate} |")
    lines.append("|---|---|---|")
    lines.append(_ci_rate_line("Faithfulness rate", b_counts["passes"], b_counts["n"], c_counts["passes"], c_counts["n"]))
    lines.append(_ci_rate_line(
        "Hallucination rate (≥ 1 claim supported=false)",
        b_counts["hallucinated"], b_counts["n"], c_counts["hallucinated"], c_counts["n"],
    ))
    lines.append(_ci_rate_line("Primary-reason coverage", b_counts["primary"], b_counts["n"], c_counts["primary"], c_counts["n"]))
    lines.append(_ci_rate_line("Length compliance (≤ 40 words)", b_counts["length_ok"], b_counts["n"], c_counts["length_ok"], c_counts["n"]))
    lines.append("")

    lines.append("## Pass rate by case_type\n")
    lines.append(f"| case_type | {baseline} | {candidate} |")
    lines.append("|---|---|---|")
    for ct in CASE_TYPES:
        bp, bn = _case_type_pass_rate(baseline_cases, ct)
        cp, cn = _case_type_pass_rate(candidate_cases, ct)
        lines.append(f"| {ct} | {bp}/{bn} ({_rate(bp, bn):.1%}) | {cp}/{cn} ({_rate(cp, cn):.1%}) |")
    lines.append("")

    lines.append("## Pass rate by bait type\n")
    lines.append(f"| bait type | {baseline} | {candidate} |")
    lines.append("|---|---|---|")
    for bt in BAIT_TYPES:
        bp, bn = _bait_pass_rate(baseline_cases, bt)
        cp, cn = _bait_pass_rate(candidate_cases, bt)
        lines.append(f"| {bt} | {bp}/{bn} ({_rate(bp, bn):.1%}) | {cp}/{cn} ({_rate(cp, cn):.1%}) |")
    lines.append("")

    lines.append("## Failure counts by type\n")
    lines.append(f"| failure type | {baseline} | {candidate} |")
    lines.append("|---|---|---|")
    all_types = sorted(set(b_failures) | set(c_failures), key=lambda t: -(b_failures.get(t, 0) + c_failures.get(t, 0)))
    for ft in all_types:
        lines.append(f"| {ft} | {b_failures.get(ft, 0)} | {c_failures.get(ft, 0)} |")
    lines.append("")

    common_ids = sorted(set(baseline_by_id) & set(candidate_by_id))
    fail_to_pass = sum(
        1 for cid in common_ids
        if baseline_by_id[cid]["judgment"]["verdict"] == "fail" and candidate_by_id[cid]["judgment"]["verdict"] == "pass"
    )
    pass_to_fail = sum(
        1 for cid in common_ids
        if baseline_by_id[cid]["judgment"]["verdict"] == "pass" and candidate_by_id[cid]["judgment"]["verdict"] == "fail"
    )
    chi2, p = mcnemar(pass_to_fail, fail_to_pass)
    lines.append("## McNemar test (paired verdicts, same case_ids)\n")
    lines.append(f"n = {len(common_ids)} paired cases.\n")
    lines.append(f"- {baseline} fail → {candidate} pass: **{fail_to_pass}**")
    lines.append(f"- {baseline} pass → {candidate} fail: **{pass_to_fail}**")
    lines.append(f"- McNemar χ² (continuity-corrected, df=1): **{chi2:.3f}**, p = **{p:.4f}**\n")
    lines.append(
        f"{'Statistically significant at α=0.05' if p < 0.05 else 'Not statistically significant at α=0.05'} "
        f"— the shift in pass/fail verdicts between {baseline} and {candidate} is "
        f"{'unlikely' if p < 0.05 else 'plausibly'} due to chance alone.\n"
    )

    lines.append("## Pre-registered criteria (CLAUDE.md, \"v2 pre-registration\")\n")
    lines.append("| criterion | threshold | actual | verdict |")
    lines.append("|---|---|---|---|")
    overall_rate = _rate(c_counts["passes"], c_counts["n"])
    overall_lo, _ = wilson_ci(c_counts["passes"], c_counts["n"])
    overall_met = overall_rate >= 0.85 and overall_lo > 0.80
    lines.append(
        f"| Faithfulness ≥ 85%, CI lower bound > 80% | ≥85%, CI lo >80% | "
        f"{overall_rate:.1%}, CI lo {overall_lo:.1%} | {'**MET**' if overall_met else '**NOT MET**'} |"
    )
    stress_types = ["sparse_profile", "fallback", "low_confidence", "conflicting_signals", "missing_fields"]
    stress_all_met = True
    for ct in stress_types:
        cp, cn = _case_type_pass_rate(candidate_cases, ct)
        rate = _rate(cp, cn)
        met = rate >= 0.70
        stress_all_met = stress_all_met and met
        lines.append(f"| Stress case_type {ct} ≥ 70% | ≥70% | {rate:.1%} (n={cn}) | {'MET' if met else '**NOT MET**'} |")
    ncr_count = c_failures.get("non_causal_reason", 0)
    ncr_met = ncr_count <= 10
    lines.append(f"| non_causal_reason count ≤ 10 | ≤10 | {ncr_count} | {'**MET**' if ncr_met else '**NOT MET**'} |")
    si_count = c_failures.get("sensitive_inference", 0)
    si_met = si_count <= 3
    lines.append(f"| sensitive_inference count ≤ 3 | ≤3 | {si_count} | {'**MET**' if si_met else '**NOT MET**'} |")
    primary_rate = _rate(c_counts["primary"], c_counts["n"])
    primary_met = primary_rate >= 0.98
    lines.append(f"| Primary-reason coverage ≥ 98% | ≥98% | {primary_rate:.1%} | {'**MET**' if primary_met else '**NOT MET**'} |")
    lines.append("")
    all_met = overall_met and stress_all_met and ncr_met and si_met and primary_met
    lines.append(f"**Overall: {'all criteria met' if all_met else 'not all criteria met'}.**\n")

    lines.append("## Chart\n")
    lines.append(f"![Hallucination rate by case_type: {baseline} vs {candidate}](hallucination_by_case_type.png)\n")

    lines.append("## Copy quality observation\n")
    lines.append(
        f"{candidate}'s copy frequently reads as the phrasing guide (rule 1 of `generator/prompts/{candidate}.txt`) "
        "copied near-verbatim rather than adapted into natural sentences — the model is reliably grounded, but "
        "the prose is template-shaped. For example:\n"
    )
    for cid in ["c_0015", "c_0151", "c_0172"]:
        if cid in candidate_by_id:
            lines.append(f"- **{cid}**: \"{candidate_by_id[cid]['explanation']}\"")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--judge", required=True)
    args = parser.parse_args()

    baseline_cases = load_cases(args.baseline, args.judge)
    candidate_cases = load_cases(args.candidate, args.judge)
    baseline_by_id = {c["case_id"]: c for c in baseline_cases}
    candidate_by_id = {c["case_id"]: c for c in candidate_cases}

    chart_path = OUT_DIR / "hallucination_by_case_type.png"
    write_chart(baseline_cases, candidate_cases, args.baseline, args.candidate, chart_path)

    report = build_report(
        args.baseline, args.candidate, args.judge, baseline_cases, candidate_cases, baseline_by_id, candidate_by_id
    )
    out_path = OUT_DIR / f"{args.baseline}_vs_{args.candidate}.md"
    out_path.write_text(report)
    print(f"Wrote {out_path} and {chart_path}")


if __name__ == "__main__":
    main()
