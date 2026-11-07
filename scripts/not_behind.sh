#!/usr/bin/env bash
# Fail if a commit is older than what an environment runs: the commit of its last deploy
# (releases/<env>.deploying) or of its last release (releases/<env>). Both are checked, so a
# marker that a re-run moved backwards cannot hide a newer release. Run inside a checkout with
# the history of main.
#
#   bash scripts/not_behind.sh <state bucket> <env> <commit>
set -euo pipefail

bucket="$1"
environment="$2"
sha="$3"
here="$(dirname "$0")"

for key in "$environment.deploying" "$environment"; do
  record="$(bash "$here/release.sh" "$bucket" "$key")"
  current="${record%% *}"
  if [ -z "$current" ] || [ "$current" = "$sha" ]; then
    continue
  fi
  status=0
  git merge-base --is-ancestor "$sha" "$current" || status=$?
  case "$status" in
    0) echo "::error::$environment runs $current (releases/$key), which is newer than $sha: refusing to go behind it (a re-run?)"
       exit 1 ;;
    1) ;; # not behind this one
    *) echo "::error::cannot compare $sha with $current (releases/$key): git exit $status"
       exit 1 ;;
  esac
done
