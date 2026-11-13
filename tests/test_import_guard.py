"""Constitution principle 2: no compiler imports another compiler.

Asked of all four compilers by agenteco-needs-compiler-import-guard-v0_1
(operator ruling 2026-11-13). Each seat writes its own copy — a shared checker
would itself be an import between compilers.

The source is READ, never imported: importing would run module-level code and
would only see what this interpreter happens to load, so a conditional or
lazily-imported peer could slip past.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "sync_compiler"

# The other three compilers. `sync_compiler` is ours and is absent on purpose.
PEER_PACKAGES = ("rbac_compiler", "agent_compile", "image_compile")


def _imported_names(tree: ast.AST) -> list[str]:
    """Every module name this file imports, as written."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` has module None; relative imports cannot name a
            # peer package, so they are simply skipped rather than crashing.
            if node.level == 0 and node.module:
                names.append(node.module)
    return names


def _is_peer(name: str) -> str | None:
    """The peer package `name` belongs to, or None.

    Matches the package and anything under it, so `rbac_compiler.models` is
    caught, while a module merely starting with those letters is not.
    """
    for peer in PEER_PACKAGES:
        if name == peer or name.startswith(peer + "."):
            return peer
    return None


def _python_files() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_the_guard_is_actually_looking_at_something() -> None:
    """Guard the guard.

    A path typo would make the import test sweep an empty list and pass while
    checking nothing — the failure shape this estate has hit repeatedly, where
    a check stays green in the exact case it exists for. So assert the package
    is there and that real modules were found before trusting a pass.
    """
    assert PACKAGE.is_dir(), f"package directory not found: {PACKAGE}"
    files = _python_files()
    assert len(files) >= 5, f"expected the whole package, found {len(files)} file(s)"
    assert any(f.name == "compiler.py" for f in files), "compiler.py not in the sweep"


def test_no_other_compiler_is_imported() -> None:
    """sync_compiler imports none of rbac_compiler, agent_compile, image_compile."""
    offences: list[str] = []

    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for name in _imported_names(tree):
            peer = _is_peer(name)
            if peer is not None:
                offences.append(f"{path.relative_to(PACKAGE.parent.parent)}: imports {name}")

    assert not offences, (
        "constitution principle 2: no compiler imports another.\n"
        + "\n".join(offences)
    )


@pytest.mark.parametrize("peer", PEER_PACKAGES)
def test_the_check_recognises_each_peer(peer: str) -> None:
    """The matcher itself, so a typo in PEER_PACKAGES cannot silently disarm it."""
    assert _is_peer(peer) == peer
    assert _is_peer(f"{peer}.models") == peer
    assert _is_peer(f"{peer}x") is None          # not a prefix match
    assert _is_peer("sync_compiler.models") is None   # our own package
