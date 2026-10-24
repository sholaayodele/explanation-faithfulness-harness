"""Shared whole-word ingredient-term matching, used by data_prep and schema/validator."""

import re


def mentions_term(ingredient: str, term: str) -> bool:
    """Whole-word match (plus optional trailing 's'), not a bare prefix.

    A bare prefix match would wrongly catch unrelated words that merely start
    with the term, e.g. "ham" inside "hamburger" or "beef" inside "beefsteak".
    Works for multi-word terms too (e.g. "hot dog"), matched as a phrase.
    """
    return re.search(r"\b" + re.escape(term) + r"s?\b", ingredient, re.IGNORECASE) is not None
