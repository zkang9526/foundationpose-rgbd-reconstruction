#!/usr/bin/env bash
set -Eeuo pipefail
if [ "$(docker inspect foundationpose --format '{{.State.Running}}')" != true ]; then
  docker start foundationpose >/dev/null
fi
exec docker exec -it -w /workspace/FoundationPose foundationpose bash
