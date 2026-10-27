"""Check that every environment together stays inside one AWS account's free tier.

`terraform validate` sees one environment at a time, but dev and prod share an account and so share
its 25 DynamoDB units, 10 alarms and 10 custom metrics. Standard library only, so the Terraform CI
job can run it without installing anything.

    python scripts/free_tier_budget.py            # exit 1 and a reason per problem if over budget
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENVS = ROOT / "terraform" / "envs"

FREE_CAPACITY_UNITS = 25  # provisioned RCU and WCU each, per account
FREE_ALARMS = 10
FREE_CUSTOM_METRICS = 10
TABLES_PER_ENVIRONMENT = 2
CHECKER_CUSTOM_METRICS = 7  # see lambda/uptime_check.py _emf


_TOKEN = re.compile(
    r"""
      (?P<skip>\s+|\#[^\n]*|//[^\n]*|/\*.*?\*/)
    | (?P<string>"(?:[^"\\]|\\.)*")
    | (?P<number>-?\d+(?:\.\d+)?)
    | (?P<word>[A-Za-z_][\w-]*)
    | (?P<punct>[=\[\],{}()])
    """,
    re.VERBOSE | re.DOTALL,
)


def _tokens(text: str) -> list[tuple[str, str]]:
    tokens, pos = [], 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match:
            raise ValueError(f"cannot read {text[pos : pos + 20]!r}")
        if match.lastgroup != "skip":
            tokens.append((match.lastgroup, match.group()))
        pos = match.end()
    return tokens


def _value(kind: str, raw: str):
    if kind == "string":
        return json.loads(raw)
    if kind == "number":
        return float(raw) if "." in raw else int(raw)
    if raw in ("true", "false"):
        return raw == "true"
    raise ValueError(f"unsupported value {raw!r}")


def parse_tfvars(text: str) -> dict:
    """The HCL subset the environment files use: numbers, booleans, strings and lists of them,
    with any comment style. Anything else (maps, expressions) is an error, never a guess."""
    tokens, values, i = _tokens(text), {}, 0
    while i < len(tokens):
        if tokens[i][0] != "word" or tokens[i + 1 : i + 2] != [("punct", "=")]:
            raise ValueError(f"expected 'name = value' at {tokens[i][1]!r}")
        key, i = tokens[i][1], i + 2
        if i >= len(tokens):
            raise ValueError(f"{key} has no value")
        if tokens[i] == ("punct", "["):
            items, i = [], i + 1
            while i < len(tokens) and tokens[i] != ("punct", "]"):
                if tokens[i] != ("punct", ","):
                    try:
                        items.append(_value(*tokens[i]))
                    except ValueError as error:
                        raise ValueError(f"{key}: {error}") from None
                i += 1
            if i == len(tokens):
                raise ValueError(f"{key}: list is not closed")
            values[key] = items
        else:
            try:
                values[key] = _value(*tokens[i])
            except ValueError as error:
                raise ValueError(f"{key}: {error}") from None
        i += 1
    return values


def load(envs: Path) -> dict[str, dict]:
    return {
        path.parent.name: parse_tfvars(path.read_text(encoding="utf-8"))
        for path in sorted(envs.glob("*/terraform.tfvars"))
    }


REQUIRED = ("dynamodb_capacity", "enabled_alarms", "metrics_enabled")


def violations(envs: Path = ENVS) -> list[str]:
    environments = load(envs)
    if not environments:
        return [f"no environments found under {envs} (expected */terraform.tfvars)"]
    missing = [
        f"{name}: {key} is not set"
        for name, values in environments.items()
        for key in REQUIRED
        if key not in values
    ]
    if missing:
        return missing
    problems = []

    units = sum(TABLES_PER_ENVIRONMENT * v["dynamodb_capacity"] for v in environments.values())
    if units > FREE_CAPACITY_UNITS:
        problems.append(
            f"DynamoDB capacity: {units} units across {sorted(environments)}, "
            f"free tier is {FREE_CAPACITY_UNITS}"
        )

    alarms = sum(len(v["enabled_alarms"]) for v in environments.values())
    if alarms > FREE_ALARMS:
        problems.append(f"CloudWatch alarms: {alarms} in total, {FREE_ALARMS} are free")

    publishing = [name for name, v in environments.items() if v["metrics_enabled"]]
    metrics = CHECKER_CUSTOM_METRICS * len(publishing)
    if metrics > FREE_CUSTOM_METRICS:
        problems.append(
            f"custom metrics: {publishing} would publish {metrics}, {FREE_CUSTOM_METRICS} are free"
        )
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--envs", type=Path, default=ENVS)
    args = parser.parse_args(argv)
    problems = violations(args.envs)
    for problem in problems:
        print(f"free tier check failed: {problem}")
    if not problems:
        print(f"free tier: OK for {sorted(load(args.envs))}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
