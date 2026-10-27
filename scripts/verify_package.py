"""Load the Lambda bundle on its own and call each handler the way Lambda would.

Tests run against the repository, where every module is importable. A bundle can still be broken:
a module left out, a dependency the runtime does not ship, an import that only works from the
repository root. CI runs this inside the public.ecr.aws/lambda/python:3.12 image, with no network:

    docker run --rm --network none -v "$PWD/bundle.zip:/bundle.zip:ro" \
      -v "$PWD/scripts:/verify:ro" --entrypoint python3 public.ecr.aws/lambda/python:3.12 \
      -I /verify/verify_package.py /bundle.zip

Each handler is imported from the extracted bundle only. Those that can answer without AWS get a
request their own validation rejects, so the whole path up to the first AWS call runs. Standard
library only, so it runs in the bare runtime image.
"""

import importlib
import os
import sys
import tempfile
import zipfile
from pathlib import Path

# The handlers terraform/modules/compute deploys (a test keeps the two lists equal).
HANDLERS = (
    "uptime_check.lambda_handler",
    "register_endpoint.lambda_handler",
    "get_checks.lambda_handler",
)
# Requests rejected before any AWS call, and the status each handler must answer with.
PROBES = {
    "register_endpoint.lambda_handler": ({"version": "2.0", "body": "{}"}, 400),
    "get_checks.lambda_handler": ({"version": "2.0", "queryStringParameters": {}}, 400),
}
# The settings Terraform gives the functions, with values that cannot reach a real resource.
ENVIRONMENT = {
    "AWS_REGION": "af-south-1",
    "AWS_DEFAULT_REGION": "af-south-1",
    "ENDPOINTS_TABLE": "verify-endpoints",
    "HISTORY_TABLE": "verify-history",
    "SNS_TOPIC_ARN": "arn:aws:sns:af-south-1:000000000000:verify",
}


class _Context:
    aws_request_id = "verify-package"
    function_name = "verify-package"


def _check(handler: str, root: Path) -> str | None:
    """None when the handler is fine, otherwise what is wrong with it."""
    module_name, function_name = handler.rsplit(".", 1)
    try:
        module = importlib.import_module(module_name)
        function = getattr(module, function_name)
    except Exception as error:  # noqa: BLE001 - any import failure is the finding
        return f"cannot import: {type(error).__name__}: {error}"
    if not Path(module.__file__).resolve().is_relative_to(root):
        return f"imported from {module.__file__}, not from the bundle"
    if handler not in PROBES:
        return None if callable(function) else f"{function_name} is not callable"
    event, expected = PROBES[handler]
    try:
        answer = function(event, _Context())
    except Exception as error:  # noqa: BLE001
        return f"raised {type(error).__name__}: {error}"
    status = answer.get("statusCode") if isinstance(answer, dict) else answer
    return None if status == expected else f"answered {status}, expected {expected}"


def verify(bundle: Path) -> list[str]:
    for name, value in ENVIRONMENT.items():
        os.environ.setdefault(name, value)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(root)  # noqa: S202 - our own build output
        sys.path.insert(0, str(root))
        problems = []
        for handler in HANDLERS:
            problem = _check(handler, root)
            print(f"{'FAIL' if problem else 'ok  '} {handler}{': ' + problem if problem else ''}")
            if problem:
                problems.append(handler)
        return problems


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: verify_package.py BUNDLE.zip", file=sys.stderr)
        return 2
    return 1 if verify(Path(args[0])) else 0


if __name__ == "__main__":
    sys.exit(main())
