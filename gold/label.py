"""Terminal labelling tool: data/gold/to_label.csv -> data/gold/gold_labels.csv.

Shows only facts (reasons, confidence, fallback, excluded_by, recipe, profile
context, explanation) - never the judge's verdict, rationale or rule-check
results, and never suggests an answer. Saves after every case, so quitting
("q") and rerunning resumes where you left off. "b" revisits the previous case.

Usage:
    python -m gold.label                                              # label data/gold/to_label.csv
    python -m gold.label --adjudicate                                 # resolve gold_labels.csv vs. judge v1
    python -m gold.label --adjudicate --cases c_0001,c_0002            # re-prompt just these (e.g. a 2nd pass)
    python -m gold.label --adjudicate --file data/gold/gold_labels_fresh.csv   # resolve a different gold file
                                                                        # vs. its judge v2 output; writes to
                                                                        # gold_labels_fresh_adjudicated.csv,
                                                                        # never edits gold_labels_fresh.csv
"""

import argparse
import csv
import json
from pathlib import Path
from random import Random

SEED = 11
TO_LABEL_PATH = Path("data/gold/to_label.csv")
GOLD_PATH = Path("data/gold/gold_labels.csv")
EVAL_SET_PATH = Path("data/processed/eval_set.jsonl")
OUT_DIR = Path("results")
JUDGMENTS_PATH = Path("results/v1_judgments.jsonl")
ADJUDICATED_PATH = Path("data/gold/gold_labels_adjudicated.csv")

FAILURE_TYPES = {
    "1": "fabrication",
    "2": "misattribution",
    "3": "non_causal_reason",
    "4": "omission",
    "5": "overclaiming",
    "6": "exclusion_violation",
    "7": "sensitive_inference",
}

BUCKETS = {
    "1": "judge_error",
    "2": "rubric_gap",
    "3": "my_slip",
}

COLUMNS = [
    "case_id", "reasons", "confidence", "fallback", "excluded_by",
    "recipe_name", "recipe_minutes", "profile_context", "explanation",
    "my_verdict", "my_failure_types", "my_note",
]
ADJUDICATED_COLUMNS = COLUMNS + ["adjudicated", "bucket", "change_reason"]

RULES_REMINDER = (
    "Rules: 1 Grounded (customer claims must come from reasons; meal facts may come from recipe fields) | "
    "2 Primary reason stated | 3 Calibrated (no overclaiming at low confidence/fallback) | "
    "4 Safe (no excluded ingredients, no health tags, no sensitive inferences)"
)


def _gold_path_for(to_label_path: Path) -> Path:
    """data/gold/to_label.csv -> gold_labels.csv; to_label_fresh.csv -> gold_labels_fresh.csv."""
    name = to_label_path.name.replace("to_label", "gold_labels", 1)
    return to_label_path.with_name(name)


def _load_to_label(to_label_path: Path) -> list[dict]:
    with to_label_path.open(newline="") as f:
        return list(csv.DictReader(f))


def _load_existing_answers(gold_path: Path) -> dict[str, dict]:
    if not gold_path.exists():
        return {}
    with gold_path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return {
        row["case_id"]: {
            "my_verdict": row["my_verdict"],
            "my_failure_types": row["my_failure_types"],
            "my_note": row["my_note"],
        }
        for row in rows
        if row.get("my_verdict")
    }


def _parse_reasons(reasons_str: str) -> list[tuple[str, str, str]]:
    """Parse "CODE=value (weight); CODE=value (weight)" back into tuples."""
    items = []
    for part in reasons_str.split("; "):
        if not part:
            continue
        code_value, weight_str = part.rsplit(" (", 1)
        code, value = code_value.split("=", 1)
        items.append((code, value, weight_str.rstrip(")")))
    return items


def _display_case(row: dict, position: int, total: int) -> None:
    print(f"\n{'=' * 70}")
    print(f"Case {position}/{total}  ({row['case_id']})")
    print("=" * 70)

    print("\nReasons:")
    for i, (code, value, weight) in enumerate(_parse_reasons(row["reasons"]), start=1):
        tag = "  <-- PRIMARY" if i == 1 else ""
        print(f"  {i}. {code}={value}  (weight {weight}){tag}")

    print(f"\nConfidence: {row['confidence']}")
    print(f"Fallback: {row['fallback'] or '(none)'}")
    print(f"Excluded by: {row['excluded_by'] or '(none)'}")
    print(f"\nRecipe: {row['recipe_name']}  ({row['recipe_minutes'] or 'minutes unknown'} min)")

    print("\nProfile context (BACKGROUND ONLY — not a valid source for reasons):")
    print(f"  {row['profile_context']}")

    print(f"\nExplanation:\n  \"{row['explanation']}\"")

    print(f"\n{RULES_REMINDER}")


def _prompt_verdict() -> str:
    while True:
        answer = input("\nVerdict [p=pass, f=fail, b=back, q=quit]: ").strip().lower()
        if answer in ("p", "f", "b", "q"):
            return answer
        print("Please enter p, f, b, or q.")


def _prompt_failure_types() -> list[str]:
    options = ", ".join(f"{k}={v}" for k, v in FAILURE_TYPES.items())
    while True:
        raw = input(f"Failure types ({options})\n  e.g. '3 7': ").strip()
        numbers = raw.split()
        if numbers and all(n in FAILURE_TYPES for n in numbers):
            return [FAILURE_TYPES[n] for n in numbers]
        print("Enter one or more valid numbers, space-separated.")


def _prompt_note() -> str:
    return input("Note (optional, Enter to skip): ").strip()


def _prompt_bucket() -> str:
    options = ", ".join(f"{k}={v}" for k, v in BUCKETS.items())
    while True:
        raw = input(f"Bucket ({options}): ").strip()
        if raw in BUCKETS:
            return BUCKETS[raw]
        print("Enter 1, 2, or 3.")


def _prompt_change_reason() -> str:
    return input("Change reason (short): ").strip()


def _judgments_path_for(judge_version: str, generator_version: str = "v1") -> Path:
    """Mirrors judge.run._write_judgments' naming: v1 keeps the plain filename,
    v2+ gets a `_judge_{version}` marker."""
    suffix = "" if judge_version == "v1" else f"_judge_{judge_version}"
    return OUT_DIR / f"{generator_version}{suffix}_judgments.jsonl"


def _adjudicated_path_for(gold_path: Path) -> Path:
    """gold_labels.csv -> gold_labels_adjudicated.csv; gold_labels_fresh.csv -> gold_labels_fresh_adjudicated.csv."""
    return gold_path.with_name(f"{gold_path.stem}_adjudicated{gold_path.suffix}")


def _load_judgments(judgments_path: Path) -> dict[str, dict]:
    judgments = {}
    with judgments_path.open() as f:
        for line in f:
            row = json.loads(line)
            judgments[row["case_id"]] = row
    return judgments


def _load_eval_payloads() -> dict[str, dict]:
    payloads = {}
    with EVAL_SET_PATH.open() as f:
        for line in f:
            row = json.loads(line)
            payloads[row["case_id"]] = row["payload"]
    return payloads


def _load_existing_adjudications(adjudicated_path: Path) -> dict[str, dict]:
    if not adjudicated_path.exists():
        return {}
    with adjudicated_path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return {row["case_id"]: row for row in rows if row.get("adjudicated") == "yes"}


def _display_adjudication_case(gold_row: dict, judge_row: dict, payload: dict, position: int, total: int) -> None:
    print(f"\n{'=' * 70}")
    print(f"Adjudication {position}/{total}  ({gold_row['case_id']})")
    print("=" * 70)

    print("\nReasons:")
    for i, (code, value, weight) in enumerate(_parse_reasons(gold_row["reasons"]), start=1):
        tag = "  <-- PRIMARY" if i == 1 else ""
        print(f"  {i}. {code}={value}  (weight {weight}){tag}")

    print(f"\nConfidence: {gold_row['confidence']}")
    print(f"Fallback: {gold_row['fallback'] or '(none)'}")
    other_tags = payload["recipe"].get("other_tags") or []
    print(f"Recipe other_tags: {', '.join(other_tags) if other_tags else '(none)'}")

    print("\nProfile context (BACKGROUND ONLY — not a valid source for reasons):")
    print(f"  {gold_row['profile_context']}")

    print(f"\nExplanation:\n  \"{gold_row['explanation']}\"")

    print("\n--- Your original label ---")
    print(f"  Verdict: {gold_row['my_verdict']}")
    print(f"  Failure types: {gold_row['my_failure_types'] or '(none)'}")
    print(f"  Note: {gold_row['my_note'] or '(none)'}")

    print("\n--- Judge ---")
    judge_types = judge_row.get("failure_types") or []
    print(f"  Verdict: {judge_row['verdict']}")
    print(f"  Failure types: {', '.join(judge_types) if judge_types else '(none)'}")
    print(f"  Rationale: {judge_row.get('rationale', '(none)')}")


def _save_adjudicated(gold_rows: list[dict], adjudications: dict[str, dict], adjudicated_path: Path) -> None:
    with adjudicated_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ADJUDICATED_COLUMNS)
        writer.writeheader()
        for row in gold_rows:
            case_id = row["case_id"]
            out_row = {col: row.get(col, "") for col in COLUMNS}
            if case_id in adjudications:
                out_row.update(adjudications[case_id])
            else:
                out_row["adjudicated"] = "no"
                out_row["bucket"] = ""
                out_row["change_reason"] = ""
            writer.writerow(out_row)


def run_adjudicate(
    cases: list[str] | None = None, gold_path: Path = GOLD_PATH, judge_version: str | None = None,
) -> None:
    """Walk the verdict disagreements between `gold_path` and the matching judge
    output. With `cases`, only re-prompts that specific subset (e.g. a second
    pass) - every other case's prior adjudication is kept exactly as it is in
    the matching `*_adjudicated.csv`. `gold_path` is only ever read, never
    written - adjudications always go to a separate `*_adjudicated.csv`.

    `judge_version` picks which judge output to compare against (default:
    `v1` for the original `gold_labels.csv`, `v2` for anything else - the
    only other ruleset any gold file has been judged with so far)."""
    if judge_version is None:
        judge_version = "v1" if gold_path == GOLD_PATH else "v2"
    judgments_path = _judgments_path_for(judge_version)
    adjudicated_path = _adjudicated_path_for(gold_path)

    gold_rows = _load_gold_labels(gold_path)
    gold_by_id = {row["case_id"]: row for row in gold_rows}
    judgments = _load_judgments(judgments_path)
    payloads = _load_eval_payloads()

    print(f"Comparing {gold_path} against {judgments_path} (judge {judge_version}); saving to {adjudicated_path}.")

    all_disagreement_ids = [
        row["case_id"] for row in gold_rows
        if row["my_verdict"].strip().lower() != judgments[row["case_id"]]["verdict"]
    ]
    existing = _load_existing_adjudications(adjudicated_path)

    if cases:
        unknown = [c for c in cases if c not in all_disagreement_ids]
        if unknown:
            print(f"Note: {unknown} weren't in the original {len(all_disagreement_ids)} verdict disagreements - including anyway.")
        disagreement_ids = cases
        adjudications = dict(existing)  # keep every other case's prior adjudication intact
        for cid in cases:
            adjudications.pop(cid, None)  # force re-prompting just these cases
    else:
        disagreement_ids = all_disagreement_ids
        adjudications = {cid: existing[cid] for cid in existing if cid in disagreement_ids}

    total = len(disagreement_ids)

    index = 0
    while index < total and disagreement_ids[index] in adjudications:
        index += 1

    if index:
        print(f"Resuming adjudication: {index}/{total} already resolved.")
    else:
        print(f"Starting adjudication: 0/{total} disagreements to resolve.")

    try:
        while index < total:
            case_id = disagreement_ids[index]
            _display_adjudication_case(gold_by_id[case_id], judgments[case_id], payloads[case_id], index + 1, total)

            verdict = _prompt_verdict()
            if verdict == "q":
                print(f"\nStopped at {index}/{total}. Rerun the same command to resume.")
                return
            if verdict == "b":
                if index == 0:
                    print("Already at the first case.")
                    continue
                index -= 1
                adjudications.pop(disagreement_ids[index], None)
                continue

            failure_types = _prompt_failure_types() if verdict == "f" else []
            bucket = _prompt_bucket()
            change_reason = _prompt_change_reason()

            adjudications[case_id] = {
                "case_id": case_id,
                "my_verdict": "pass" if verdict == "p" else "fail",
                "my_failure_types": " ".join(failure_types),
                "adjudicated": "yes",
                "bucket": bucket,
                "change_reason": change_reason,
            }
            _save_adjudicated(gold_rows, adjudications, adjudicated_path)
            index += 1
            print(f"Saved. Progress: {index}/{total}")
    except (KeyboardInterrupt, EOFError):
        print(f"\n\nStopped at {index}/{total}. Rerun the same command to resume.")
        return

    print(f"\nAll {total} disagreements adjudicated.")


def _load_gold_labels(gold_path: Path = GOLD_PATH) -> list[dict]:
    with gold_path.open(newline="") as f:
        return list(csv.DictReader(f))


def _save(gold_path: Path, to_label_rows: list[dict], answers: dict[str, dict]) -> None:
    with gold_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in to_label_rows:
            out_row = dict(row)
            out_row.update(answers.get(row["case_id"], {}))
            writer.writerow(out_row)


def main(to_label_path: Path = TO_LABEL_PATH) -> None:
    gold_path = _gold_path_for(to_label_path)
    to_label_rows = _load_to_label(to_label_path)
    by_id = {row["case_id"]: row for row in to_label_rows}
    total = len(to_label_rows)

    order = list(by_id.keys())
    Random(SEED).shuffle(order)

    answers = _load_existing_answers(gold_path)
    index = 0
    while index < len(order) and order[index] in answers:
        index += 1

    if answers:
        print(f"Resuming ({gold_path}): {len(answers)}/{total} already labelled.")
    else:
        print(f"Starting ({gold_path}): 0/{total} labelled.")

    try:
        while index < len(order):
            case_id = order[index]
            _display_case(by_id[case_id], len(answers) + 1, total)

            verdict = _prompt_verdict()
            if verdict == "q":
                print(f"\nStopped at {len(answers)}/{total}. Rerun the same command to resume.")
                return
            if verdict == "b":
                if index == 0:
                    print("Already at the first case.")
                    continue
                index -= 1
                answers.pop(order[index], None)
                continue

            failure_types = _prompt_failure_types() if verdict == "f" else []
            note = _prompt_note()

            answers[case_id] = {
                "my_verdict": "pass" if verdict == "p" else "fail",
                "my_failure_types": " ".join(failure_types),
                "my_note": note,
            }
            _save(gold_path, to_label_rows, answers)
            print(f"Saved. Progress: {len(answers)}/{total}")
            index += 1
    except (KeyboardInterrupt, EOFError):
        print(f"\n\nStopped at {len(answers)}/{total}. Rerun the same command to resume.")
        return

    print(f"\nAll {total} cases labelled.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--adjudicate", action="store_true", help="resolve verdict disagreements with the judge")
    parser.add_argument(
        "--cases", default=None,
        help="with --adjudicate: comma-separated case_ids to re-prompt only (e.g. a second pass); "
             "every other case's prior adjudication is left exactly as it is",
    )
    parser.add_argument(
        "--file", type=Path, default=None,
        help="without --adjudicate: a to_label CSV to work through (writes to the matching gold_labels_*.csv "
             "alongside it). With --adjudicate: a gold_labels_*.csv to adjudicate directly (writes to the "
             "matching gold_labels_*_adjudicated.csv alongside it; the input file is never edited).",
    )
    parser.add_argument(
        "--judge-version", default=None, choices=["v1", "v2"],
        help="with --adjudicate: which judge output to compare against (default: v1 for gold_labels.csv, "
             "v2 for any other --file)",
    )
    args = parser.parse_args()
    if args.adjudicate:
        run_adjudicate(
            args.cases.split(",") if args.cases else None,
            gold_path=args.file if args.file is not None else GOLD_PATH,
            judge_version=args.judge_version,
        )
    else:
        main(args.file if args.file is not None else TO_LABEL_PATH)
