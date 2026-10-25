"""Deterministic rule checks for the judge - layer 1, run before the LLM.

health_term_found, excluded_ingredient_found and minutes_mismatch are
BINDING: judge/run.py enforces them in code after the LLM responds, rather
than asking the LLM to honor them as instructions. time_phrase_without_time_fit
and health_synonym_hint are hints only, shown to the LLM for its own judgment.
"""

import re

from ingredient_matching import EXCLUSION_FORMS, mentions_term

# Canonical health tags - binding.
HEALTH_TERMS = [
    "low-calorie", "low-carb", "low-sodium", "low-cholesterol", "healthy",
    "low calorie", "low carb", "low sodium", "low cholesterol",
]
# Context-dependent synonyms - hint only, not binding (per Shola: "light" etc.
# aren't always a health claim, so they don't force a fail on their own).
# v1: all three are hints. v2 (ruling 1A): "light" becomes a binding check of
# its own (conditional on the recipe having a health other_tag), so it's
# dropped from the generic hint list there - see check_rules_v2.
HEALTH_SYNONYM_HINTS = ["light", "guilt-free", "good for you"]
HEALTH_SYNONYM_HINTS_V2 = ["guilt-free", "good for you"]
LIGHT_TERM = "light"

TIME_PHRASE_PATTERNS = [
    re.compile(r"your\s+\d+[\s-]*minute\w*", re.IGNORECASE),
    re.compile(r"time limit", re.IGNORECASE),
    re.compile(r"cooking window", re.IGNORECASE),
    re.compile(r"schedule", re.IGNORECASE),
]

MINUTE_PATTERN = re.compile(r"(\d+)[\s-]*minutes?", re.IGNORECASE)
LIMIT_CONTEXT_KEYWORDS = ["limit", "window", "within your", "under"]
LIMIT_CONTEXT_WINDOW = 20  # characters of context checked on each side of a number


def _is_limit_context(explanation: str, match: re.Match) -> bool:
    start = max(0, match.start() - LIMIT_CONTEXT_WINDOW)
    end = min(len(explanation), match.end() + LIMIT_CONTEXT_WINDOW)
    context = explanation[start:end].lower()
    return any(keyword in context for keyword in LIMIT_CONTEXT_KEYWORDS)


def check_minutes_mismatch(explanation: str, recipe_minutes: int | None, max_cook_minutes: int | None) -> bool:
    """True only if a *stated cook time* (not a time limit/window mention) != recipe.minutes.

    A number is treated as a time limit, not a stated cook time, when it sits near a
    limit-indicating phrase ("X-minute limit/window", "within your X minutes", "under
    X minutes"), or when it equals the profile's max_cook_minutes and differs from the
    recipe's actual minutes (ambiguous - could just be restating the limit).
    """
    stated_cook_times = []
    for match in MINUTE_PATTERN.finditer(explanation):
        number = int(match.group(1))
        if _is_limit_context(explanation, match):
            continue
        if max_cook_minutes is not None and number == max_cook_minutes and number != recipe_minutes:
            continue
        stated_cook_times.append(number)

    if not stated_cook_times:
        return False
    if recipe_minutes is None:
        return True
    return any(t != recipe_minutes for t in stated_cook_times)


def _shared_checks(payload: dict, explanation: str) -> dict:
    """Checks identical across judge prompt versions: excluded ingredient,
    minutes mismatch, the time-phrase hint, and word count."""
    recipe = payload["recipe"]
    reasons = payload["reasons"]
    excluded_by = payload["excluded_by"]
    max_cook_minutes = payload["profile_context"]["max_cook_minutes"]

    excluded_ingredient_found = any(
        mentions_term(explanation, term)
        for code in excluded_by
        for term in EXCLUSION_FORMS.get(code, [])
    )

    minutes_mismatch = check_minutes_mismatch(explanation, recipe.get("minutes"), max_cook_minutes)

    has_time_fit = any(r["code"] == "TIME_FIT" for r in reasons)
    time_phrase_without_time_fit = []
    if not has_time_fit:
        for pattern in TIME_PHRASE_PATTERNS:
            match = pattern.search(explanation)
            if match:
                time_phrase_without_time_fit.append(match.group(0))

    return {
        "excluded_ingredient_found": excluded_ingredient_found,
        "minutes_mismatch": minutes_mismatch,
        "time_phrase_without_time_fit": time_phrase_without_time_fit,
        "word_count": len(explanation.split()),
    }


def check_rules(payload: dict, explanation: str) -> dict:
    """v1 rule checks - frozen, matches judge_v1.txt and its cached outputs exactly."""
    health_term_found = any(mentions_term(explanation, term) for term in HEALTH_TERMS)
    health_synonym_hint = [s for s in HEALTH_SYNONYM_HINTS if s.lower() in explanation.lower()]
    return {
        "health_term_found": health_term_found,
        "health_synonym_hint": health_synonym_hint,
        **_shared_checks(payload, explanation),
    }


def check_rules_v2(payload: dict, explanation: str) -> dict:
    """v2 rule checks (ruling 1A): "light" is a binding health violation only
    when the recipe has a health tag in other_tags; otherwise it's an allowed
    flavour word, not even a hint."""
    recipe = payload["recipe"]
    health_term_found = any(mentions_term(explanation, term) for term in HEALTH_TERMS)
    if recipe.get("other_tags") and mentions_term(explanation, LIGHT_TERM):
        health_term_found = True
    health_synonym_hint = [s for s in HEALTH_SYNONYM_HINTS_V2 if s.lower() in explanation.lower()]
    return {
        "health_term_found": health_term_found,
        "health_synonym_hint": health_synonym_hint,
        **_shared_checks(payload, explanation),
    }
