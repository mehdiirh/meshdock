"""Compile gettext catalogs at build time; fail on missing or empty translations."""

from pathlib import Path

from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po

root = Path(__file__).parent / "app" / "locales"
catalogs = {}
for lang in ("en", "fa"):
    path = root / lang / "LC_MESSAGES" / "messages.po"
    with path.open("rb") as source:
        cat = read_po(source, locale=lang)
    for message in cat:
        if message.id and not message.string:
            raise ValueError(f"{lang}: untranslated {message.id}")
    catalogs[lang] = {m.id for m in cat if m.id}
    with path.with_suffix(".mo").open("wb") as target:
        write_mo(target, cat)
if catalogs["en"] != catalogs["fa"]:
    raise ValueError("Catalog IDs differ between locales")
