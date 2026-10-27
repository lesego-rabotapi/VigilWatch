"""Check that every environment together stays inside one AWS account's free tier.

`terraform validate` sees one environment at a time, but dev and prod share an account and so share
its 25 DynamoDB units, 10 alarms and 10 custom metrics. Standard library only, so the Terraform CI
job can run it without installing anything.

    python scripts/free_tier_budget.py            # exit 1 and a reason per problem if over budget
"""

import argparse
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


def parse_tfvars(text: str) -> dict:
    """The flat HCL subset the environment files use: numbers, booleans, strings, string lists."""
    values = {}
    for key, raw in re.findall(r"^(\w+)\s*=\s*(.+?)\s*$", text, flags=re.MULTILINE):
        raw = raw.split("#")[0].strip()
        if raw.startswith("["):
            values[key] = re.findall(r'"([^"]*)"', raw)
        elif raw.startswith('"'):
            values[key] = raw.strip('"')
        elif raw in ("true", "false"):
            values[key] = raw == "true"
        else:
            values[key] = float(raw) if "." in raw else int(raw)
    return values


def load(envs: Path) -> dict[str, dict]:
    return {
        path.parent.name: parse_tfvars(path.read_text(encoding="utf-8"))
        for path in sorted(envs.glob("*/terraform.tfvars"))
    }


def violations(envs: Path = ENVS) -> list[str]:
    environments = load(envs)
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
        print(f"over the free tier: {problem}")
    if not problems:
        print(f"free tier: OK for {sorted(load(args.envs))}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
