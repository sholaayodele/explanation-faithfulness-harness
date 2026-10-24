"""Run the validator over every payload in schema/examples/ and report pass/fail."""

import json
from pathlib import Path

from schema.validator import validate_payload

_EXAMPLES_DIR = Path(__file__).parent / "examples"


def main() -> int:
    paths = sorted(_EXAMPLES_DIR.glob("*.json"))
    failures = 0
    for path in paths:
        with path.open() as f:
            payload = json.load(f)
        errors = validate_payload(payload)
        if errors:
            failures += 1
            print(f"[FAIL] {path.name}")
            for error in errors:
                print(f"         - {error}")
        else:
            print(f"[PASS] {path.name}")
    print(f"\n{len(paths) - failures}/{len(paths)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
