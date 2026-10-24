"""Verify the local environment is ready before any pipeline step runs."""

import importlib
import sys
from pathlib import Path

REQUIRED_PACKAGES = ["pandas", "anthropic", "sklearn", "dotenv"]
REQUIRED_DIRS = [
    "data/raw",
    "data/processed",
    "data/gold",
    "schema",
    "generator/prompts",
    "judge",
    "results/cache",
    "notebooks",
]


def check_python_version() -> tuple[bool, str]:
    """Require Python 3.11+."""
    ok = sys.version_info >= (3, 11)
    return ok, f"Python {sys.version.split()[0]}"


def check_packages() -> list[tuple[bool, str]]:
    """Confirm each required package is importable."""
    results = []
    for name in REQUIRED_PACKAGES:
        try:
            importlib.import_module(name)
            results.append((True, name))
        except ImportError:
            results.append((False, name))
    return results


def check_dirs() -> list[tuple[bool, str]]:
    """Confirm the repo folder structure exists."""
    return [(Path(d).is_dir(), d) for d in REQUIRED_DIRS]


def check_env_file() -> tuple[bool, str]:
    """Confirm .env exists and ANTHROPIC_API_KEY is set (non-empty)."""
    from dotenv import dotenv_values

    env_path = Path(".env")
    if not env_path.is_file():
        return False, ".env file is missing"

    values = dotenv_values(env_path)
    key = values.get("ANTHROPIC_API_KEY")
    if not key:
        return False, "ANTHROPIC_API_KEY is empty in .env"
    return True, "ANTHROPIC_API_KEY is set"


def report(label: str, ok: bool, detail: str) -> None:
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {label}: {detail}")


def main() -> int:
    all_ok = True

    ok, detail = check_python_version()
    report("Python version", ok, detail)
    all_ok &= ok

    for ok, name in check_packages():
        report("Package", ok, name)
        all_ok &= ok

    for ok, name in check_dirs():
        report("Directory", ok, name)
        all_ok &= ok

    ok, detail = check_env_file()
    report("Environment", ok, detail)
    all_ok &= ok

    print()
    print("Setup OK" if all_ok else "Setup incomplete — see FAIL lines above")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
