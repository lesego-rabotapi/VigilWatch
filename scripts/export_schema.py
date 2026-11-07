"""Export standalone JSON Schemas from docs/openapi.yaml.

    python scripts/export_schema.py          # rewrite tests/contract/checks_response.schema.json

The OpenAPI document is the source of truth. Component references are inlined as `$defs` so the
result validates with a plain JSON Schema validator and can be read by the frontend tests.
"""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs" / "openapi.yaml"
SCHEMA_PATH = ROOT / "tests" / "contract" / "checks_response.schema.json"

COMPONENT_PREFIX = "#/components/schemas/"
DEFS_PREFIX = "#/$defs/"
DIALECT = "https://json-schema.org/draft/2020-12/schema"


def load_spec(path: Path = SPEC_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _rewrite(node):
    """Deep copy with component references pointing at local $defs."""
    if isinstance(node, dict):
        return {
            key: (DEFS_PREFIX + value[len(COMPONENT_PREFIX) :])
            if key == "$ref" and isinstance(value, str) and value.startswith(COMPONENT_PREFIX)
            else _rewrite(value)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_rewrite(item) for item in node]
    return node


def _refs(node) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and value.startswith(DEFS_PREFIX):
                found.add(value[len(DEFS_PREFIX) :])
            else:
                found |= _refs(value)
    elif isinstance(node, list):
        for item in node:
            found |= _refs(item)
    return found


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def build_schema(name: str, spec: dict | None = None) -> dict:
    components = (spec or load_spec())["components"]["schemas"]
    root = _rewrite(components[name])

    needed: set[str] = set()
    pending = _refs(root)
    while pending:
        current = pending.pop()
        if current in needed:
            continue
        needed.add(current)
        pending |= _refs(_rewrite(components[current]))

    schema = {"$schema": DIALECT, "$id": f"https://vigilwatch/contract/{_snake(name)}.schema.json"}
    schema.update(root)
    if needed:
        schema["$defs"] = {n: _rewrite(components[n]) for n in sorted(needed)}
    return schema


def main() -> None:
    SCHEMA_PATH.write_text(
        json.dumps(build_schema("ChecksResponse"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {SCHEMA_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
