"""Gettext catalogs; message IDs remain stable API error/event codes."""

import gettext
from functools import lru_cache
from pathlib import Path

LOCALES = Path(__file__).with_name("locales")


@lru_cache(maxsize=2)
def catalog(lang):
    return gettext.translation("messages", localedir=LOCALES, languages=[lang])


def translate(code, language="en"):
    return catalog("fa" if language.lower().startswith("fa") else "en").gettext(code)
