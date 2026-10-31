#!/usr/bin/env bash
# Print an environment's release record, "<commit> <bundle sha256>", or nothing if that
# environment was never released. Any other failure fails: a wrong bucket name or a missing
# permission is not "nothing released yet".
#
#   bash scripts/release.sh <state bucket> <dev|prod>                # what runs there now
#   bash scripts/release.sh <state bucket> history/<env>/<commit>    # whether it was released
#   bash scripts/release.sh <state bucket> <env>.deploying           # the last deploy started
set -euo pipefail

bucket="$1"
key="releases/$2"

listed="$(aws s3api list-objects-v2 --bucket "$bucket" --prefix "$key" \
  --query "Contents[?Key=='$key'].Key" --output text)"
if [ "$listed" != "$key" ]; then
  exit 0
fi

record="$(aws s3 cp "s3://$bucket/$key" - --only-show-errors)"
if ! [[ "$record" =~ ^[0-9a-f]{40}\ [A-Za-z0-9+/]{43}=$ ]]; then
  echo "::error::$key is not '<commit> <bundle sha256>': '$record'" >&2
  exit 1
fi
printf '%s\n' "$record"
