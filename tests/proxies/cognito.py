"""A token for the smoke-test user, from Cognito's public InitiateAuth endpoint (ADR 0007).

No AWS credentials and no boto3: the smoke-test app client allows USER_PASSWORD_AUTH, so a plain
HTTPS call with the user's name and password returns an access token. The password never appears
in an error message.
"""

import json
import urllib.error
import urllib.request

from tests.proxies.base_proxy import ProxyError

ENDPOINT = "https://cognito-idp.{region}.amazonaws.com/"  # AWS's, not a deployment's


def endpoint_for(region: str) -> str:
    return ENDPOINT.format(region=region)


def cognito_token(
    client_id: str, username: str, password: str, region: str, timeout: float, endpoint=None
) -> str:
    body = {
        "AuthFlow": "USER_PASSWORD_AUTH",
        "ClientId": client_id,
        "AuthParameters": {"USERNAME": username, "PASSWORD": password},
    }
    request = urllib.request.Request(  # noqa: S310 (Cognito's endpoint, or a test server)
        endpoint or endpoint_for(region),
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:  # noqa: S310
            answer = json.loads(reply.read())
    except urllib.error.HTTPError as exc:
        reason = json.loads(exc.read() or b"{}").get("__type", exc.code)
        raise ProxyError(f"could not sign in as {username}: {reason}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise ProxyError(f"could not reach Cognito: {exc}") from None
    if "ChallengeName" in answer:
        raise ProxyError(
            f"{username} must answer {answer['ChallengeName']}: give it a permanent password "
            "(aws cognito-idp admin-set-user-password --permanent, docs/RUNBOOK.md)"
        )
    return answer["AuthenticationResult"]["AccessToken"]
