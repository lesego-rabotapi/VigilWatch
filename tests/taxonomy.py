"""Test taxonomy helpers: which layer a test belongs to and whether it is marked correctly."""

from pathlib import PurePosixPath

LAYERS = ("unit", "mock", "integration", "contract", "bdd", "e2e", "policy")

_DIRECTORY_LAYERS = {
    "unit": "unit",
    "mock": "mock",
    "integration": "integration",
    "contract": "contract",
    "step_defs": "bdd",
    "e2e": "e2e",
}


def layer_for(relative: str) -> str | None:
    """Layer implied by a test file's location under tests/, or None if it has none."""
    parts = PurePosixPath(relative.replace("\\", "/")).parts
    if len(parts) < 2 or parts[0] != "tests":
        return None
    if len(parts) == 2:
        name = parts[1]
        return "policy" if name.startswith("test_") and name.endswith(".py") else None
    return _DIRECTORY_LAYERS.get(parts[1])


def find_unmarked(items) -> list:
    """Items that do not carry exactly one layer marker."""
    return [item for item in items if len({m.name for m in item.iter_markers()} & set(LAYERS)) != 1]
