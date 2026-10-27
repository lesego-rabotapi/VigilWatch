"""Render the exact IAM policy of each Lambda function from the Terraform compute module.

The documents are built from names and variables only, so Terraform can print them without an AWS
account or credentials. The enforcement test (tests/mock/test_iam_policies.py) attaches them to IAM
users in moto and runs the handlers as those users.

    python scripts/render_iam_policies.py            # prints {function: policy}
"""

import functools
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "terraform" / "modules" / "compute"

# Match the names and ARNs the moto fixtures use (account 123456789012 is moto's default).
DEFAULTS = {
    "name_prefix": "vigilwatch",
    "aws_region": "af-south-1",
    "account_id": "123456789012",
    "bundle_path": "bundle.zip",
    "bundle_sha256": "47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=",
    "endpoints_table": "vigilwatch-endpoints",
    "history_table": "vigilwatch-history",
    "endpoints_table_arn": "arn:aws:dynamodb:af-south-1:123456789012:table/vigilwatch-endpoints",
    "history_table_arn": "arn:aws:dynamodb:af-south-1:123456789012:table/vigilwatch-history",
    "sns_topic_arn": "arn:aws:sns:af-south-1:123456789012:vigilwatch-alerts",
}


def available() -> bool:
    return shutil.which("terraform") is not None


def _terraform(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(  # noqa: S603 - fixed argument list, no shell
        ["terraform", *args],  # noqa: S607
        cwd=MODULE,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"terraform {' '.join(args[:2])} failed:\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def _console(values: tuple) -> str:
    flags = [f"-var={name}={value}" for name, value in values]
    return _terraform("console", "-no-color", *flags, stdin="jsonencode(local.function_policies)\n")


# What terraform prints when .terraform is missing, stale or half-initialised. Any other error is
# in the module itself, and re-initialising would only download providers to hide it.
_NOT_INITIALISED = re.compile(
    r"terraform init|dependency lock file|not installed|required provider|module not installed",
    re.IGNORECASE,
)


@functools.cache
def _render(values: tuple) -> str:
    try:
        printed = _console(values)
    except RuntimeError as error:
        if not _NOT_INITIALISED.search(str(error)):
            raise
        # Initialise once and try again. -upgrade because the module's lock file is git-ignored
        # and an old one may pin a provider that is no longer cached.
        _terraform("init", "-backend=false", "-input=false", "-no-color", "-upgrade")
        printed = _console(values)
    return printed


def render(overrides: dict | None = None) -> dict[str, dict]:
    """{function: policy document}, rendered once per set of values (a fresh copy every call)."""
    values = tuple(sorted({**DEFAULTS, **(overrides or {})}.items()))
    # The console prints the value as a quoted string literal, which is also valid JSON.
    documents = json.loads(json.loads(_render(values).strip()))
    return {name: json.loads(document) for name, document in documents.items()}


def render_or_error(overrides: dict | None = None) -> tuple[dict | None, str | None]:
    """For test collection, where an exception would abort the whole run: (policies, None) or
    (None, why)."""
    try:
        return render(overrides), None
    except (RuntimeError, OSError, ValueError) as error:
        return None, str(error)


def clear_cache() -> None:
    _render.cache_clear()


if __name__ == "__main__":
    if not available():
        sys.exit("terraform is not installed")
    print(json.dumps(render(), indent=2))
