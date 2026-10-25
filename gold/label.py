"""Terminal labelling tool: data/gold/to_label.csv -> data/gold/gold_labels.csv.

Shows only facts (reasons, confidence, fallback, excluded_by, recipe, profile
context, explanation) - never the judge's verdict, rationale or rule-check
results, and never suggests an answer. Saves after every case, so quitting
("q") and rerunning resumes where you left off. "b" revisits the previous case.

Usage: python -m gold.label
"""

import csv
from pathlib import Path
from random import Random

SEED = 11
TO_LABEL_PATH = Path("data/gold/to_label.csv")
GOLD_PATH = Path("data/gold/gold_labels.csv")

FAILURE_TYPES = {
    "1": "fabrication",
    "2": "misattribution",
    "3": "non_causal_reason",
    "4": "omission",
    "5": "overclaiming",
    "6": "profile_contradiction",
    "7": "sensitive_inference",
}

COLUMNS = [
    "case_id", "reasons", "confidence", "fallback", "excluded_by",
    "recipe_name", "recipe_minutes", "profile_context", "explanation",
    "my_verdict", "my_failure_types", "my_note",
]

RULES_REMINDER = (
    "Rules: 1 Grounded (customer claims must come from reasons; meal facts may come from recipe fields) | "
    "2 Primary reason stated | 3 Calibrated (no overclaiming at low confidence/fallback) | "
    "4 Safe (no excluded ingredients, no health tags, no sensitive inferences)"
)


def _load_to_label() -> list[dict]:
    with TO_LABEL_PATH.open(newline="") as f:
        return list(csv.DictReader(f))


def _load_existing_answers() -> dict[str, dict]:
    if not GOLD_PATH.exists():
        return {}
    with GOLD_PATH.open(newline="") as f:
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


def _save(to_label_rows: list[dict], answers: dict[str, dict]) -> None:
    with GOLD_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in to_label_rows:
            out_row = dict(row)
            out_row.update(answers.get(row["case_id"], {}))
            writer.writerow(out_row)


def main() -> None:
    to_label_rows = _load_to_label()
    by_id = {row["case_id"]: row for row in to_label_rows}
    total = len(to_label_rows)

    order = list(by_id.keys())
    Random(SEED).shuffle(order)

    answers = _load_existing_answers()
    index = 0
    while index < len(order) and order[index] in answers:
        index += 1

    if answers:
        print(f"Resuming: {len(answers)}/{total} already labelled.")
    else:
        print(f"Starting: 0/{total} labelled.")

    try:
        while index < len(order):
            case_id = order[index]
            _display_case(by_id[case_id], len(answers) + 1, total)

            verdict = _prompt_verdict()
            if verdict == "q":
                print(f"\nStopped at {len(answers)}/{total}. Run `python -m gold.label` again to resume.")
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
            _save(to_label_rows, answers)
            print(f"Saved. Progress: {len(answers)}/{total}")
            index += 1
    except (KeyboardInterrupt, EOFError):
        print(f"\n\nStopped at {len(answers)}/{total}. Run `python -m gold.label` again to resume.")
        return

    print(f"\nAll {total} cases labelled.")


if __name__ == "__main__":
    main()
