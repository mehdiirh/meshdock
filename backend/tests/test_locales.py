"""Keep translated operational errors synchronized with the source code."""

import ast
from pathlib import Path

from babel.messages.pofile import read_po


def test_catalogs_cover_errors_and_have_matching_translations():
    root = Path(__file__).parents[1] / "app"
    catalogs = []
    for language in ("en", "fa"):
        with (root / "locales" / language / "LC_MESSAGES" / "messages.po").open("rb") as source:
            catalog = read_po(source, locale=language)
        catalogs.append({message.id for message in catalog if message.id})
        assert all(message.string for message in catalog if message.id)
    assert catalogs[0] == catalogs[1]
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("AppError", "OperationError") and node.args:
                    code = node.args[0]
                    if isinstance(code, ast.Constant):
                        assert code.value in catalogs[0], (path.name, code.value)
