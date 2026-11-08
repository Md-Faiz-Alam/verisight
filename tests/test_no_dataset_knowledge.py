"""Production code must know nothing about the datasets used to evaluate it."""

import ast
from pathlib import Path

import verisight

SOURCE = Path(verisight.__file__).parent
EVALUATION_ONLY_WORDS = frozenset(
    {
        "poutcome",
        "pdays",
        "euribor3m",
        "penicillin",
        "streptomycin",
        "neomycin",
        "bacteria",
        "antibiotic",
        "gentoo",
        "adelie",
        "chinstrap",
        "spielberg",
        "roberta",
        "waseca",
        "vvs1",
        "texas",
        "seattle",
        "earthquake",
        "disaster",
        "reservoir",
        "orchard",
        "co2",
    }
)


def _code_strings(path: Path) -> list[str]:
    """Every string a program can act on: docstrings describe, so they are skipped."""
    tree = ast.parse(path.read_text("utf-8"))
    documents = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in documents
    ]


def test_code_contains_no_words_from_evaluation_datasets() -> None:
    found = {
        (path.name, word)
        for path in SOURCE.rglob("*.py")
        for text in _code_strings(path)
        for word in EVALUATION_ONLY_WORDS
        if word in text.casefold()
    }

    assert found == set()


def test_code_never_imports_the_evaluation_material() -> None:
    imported = {
        path.name
        for path in SOURCE.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text("utf-8")))
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").split(".")[0] in {"evaluation", "scripts", "tests"}
    }

    assert imported == set()
