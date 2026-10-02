"""Run VigilWatch locally: dashboard + API on one port, AWS mocked by moto.

    pip install -r requirements-dev.txt
    python scripts/local_api.py            # http://127.0.0.1:8787

Emulates API Gateway (routes, CORS, payload v2.0) and CloudFront (static files,
generated config.js, security headers) around the real Lambda handlers. The
scheduled checker runs in a background thread. Probes hit the real internet.
Also used to exercise the e2e smoke tests without an AWS account:

    API_URL=http://127.0.0.1:8787 DASHBOARD_URL=http://127.0.0.1:8787 pytest -m e2e tests/e2e
"""

import argparse
import json
import mimetypes
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
STATIC_SUFFIXES = {".html", ".css", ".js", ".png", ".svg", ".ico"}
CSP = "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'"

sys.path.insert(0, str(ROOT / "lambda"))


def start_mock_aws():
    env = {
        "AWS_ACCESS_KEY_ID": "local",
        "AWS_SECRET_ACCESS_KEY": "local",
        "AWS_DEFAULT_REGION": "af-south-1",
        "ENDPOINTS_TABLE": "vigilwatch-endpoints",
        "HISTORY_TABLE": "vigilwatch-history",
    }
    for key, value in env.items():
        os.environ[key] = value

    import boto3
    from moto import mock_aws

    mock = mock_aws()
    mock.start()

    dynamodb = boto3.client("dynamodb")
    capacity = {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}
    dynamodb.create_table(
        TableName=env["ENDPOINTS_TABLE"],
        KeySchema=[{"AttributeName": "endpoint_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "endpoint_id", "AttributeType": "S"}],
        ProvisionedThroughput=capacity,
    )
    dynamodb.create_table(
        TableName=env["HISTORY_TABLE"],
        KeySchema=[
            {"AttributeName": "endpoint_id", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "endpoint_id", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        ProvisionedThroughput=capacity,
    )
    topic = boto3.client("sns").create_topic(Name="vigilwatch-alerts")["TopicArn"]
    os.environ["SNS_TOPIC_ARN"] = topic
    return mock


class Handler(BaseHTTPRequestHandler):
    server_version = "VigilWatchLocal/1.0"
    routes: dict = {}

    def _origin(self):
        return f"http://{self.headers.get('Host', '')}"

    def _send(self, status, body: bytes, content_type, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.headers.get("Origin")
        if origin and origin == self._origin():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self._send(
            204,
            b"",
            "text/plain",
            {
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                "Access-Control-Allow-Headers": "content-type",
                "Access-Control-Max-Age": "3600",
            },
        )

    def do_POST(self):  # noqa: N802
        self._api()

    def do_GET(self):  # noqa: N802
        path = urlsplit(self.path).path
        if ("GET", path) in self.routes:
            self._api()
        else:
            self._static(path)

    def _api(self):
        parts = urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode() if length else None
        event = {
            "version": "2.0",
            "routeKey": f"{self.command} {parts.path}",
            "rawPath": parts.path,
            "rawQueryString": parts.query,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "queryStringParameters": dict(parse_qsl(parts.query)) or None,
            "requestContext": {"http": {"method": self.command, "path": parts.path}},
            "body": body,
            "isBase64Encoded": False,
        }
        handler = self.routes.get((self.command, parts.path))
        if handler is None:
            self._send(404, b'{"message":"Not Found"}', "application/json")
            return
        result = handler(event, None)
        headers = dict(result.get("headers", {}))
        content_type = headers.pop("Content-Type", "application/json")
        self._send(result["statusCode"], result["body"].encode(), content_type, headers)

    def _static(self, path):
        security = {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY"}
        if path == "/config.js":
            config = json.dumps({"apiBase": self._origin()})
            body = f"window.VIGILWATCH_CONFIG = {config};\n".encode()
            self._send(200, body, "application/javascript", security)
            return
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (FRONTEND / relative).resolve()
        allowed = (
            target.is_relative_to(FRONTEND)
            and target.is_file()
            and target.suffix in STATIC_SUFFIXES
            and "tests" not in target.relative_to(FRONTEND).parts
            and "node_modules" not in target.relative_to(FRONTEND).parts
        )
        if not allowed:
            self._send(404, b"Not Found", "text/plain")
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), content_type, security)

    def log_message(self, fmt, *args):
        sys.stderr.write(
            f"[local] {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}\n"
        )


def run_checker_forever(interval, stop):
    import uptime_check

    while not stop.wait(interval):
        try:
            print("[checker]", uptime_check.lambda_handler({}, None))
        except Exception as exc:  # keep the dev loop alive
            print("[checker] failed:", exc)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--check-every", type=float, default=60, help="seconds; 0 disables")
    args = parser.parse_args(argv)

    start_mock_aws()
    import get_checks
    import register_endpoint

    Handler.routes = {
        ("POST", "/register"): register_endpoint.lambda_handler,
        ("GET", "/checks"): get_checks.lambda_handler,
    }

    stop = threading.Event()
    if args.check_every > 0:
        threading.Thread(
            target=run_checker_forever, args=(args.check_every, stop), daemon=True
        ).start()

    server = HTTPServer((args.host, args.port), Handler)
    print(f"VigilWatch local: http://{args.host}:{args.port}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
