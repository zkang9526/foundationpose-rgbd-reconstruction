#!/usr/bin/env bash
set -Eeuo pipefail
echo 'Waiting for the official image download to finish.'
deadline=$((SECONDS + 7200))
until docker image inspect wenbowen123/foundationpose:latest >/dev/null 2>&1; do
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo 'Image did not become available within two hours.' >&2
    exit 1
  fi
  sleep 5
done
bash "$HOME/foundationpose_data/setup/create_container.sh"
