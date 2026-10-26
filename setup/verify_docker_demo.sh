#!/usr/bin/env bash
set -Eeuo pipefail
DATA=/data/ZJC/foundationPos/foundationpose_data
docker exec foundationpose /opt/conda/envs/my/bin/python /data/setup/verify_demo.py --output /data/demo_smoke \
  2>&1 | tee "$DATA/setup_logs/demo_smoke.log"
docker exec foundationpose /opt/conda/envs/my/bin/python -m pip freeze > "$DATA/packages_after_build.txt"
docker inspect foundationpose --format '{{json .Mounts}}' > "$DATA/container_mounts.json"
docker update --restart unless-stopped foundationpose
docker commit foundationpose foundationpose:ready-20261010 > "$DATA/foundationpose_ready_image_id.txt"
docker exec foundationpose chown -R 1000:1000 /data/demo_smoke /data/environment_verification.json
echo "Docker inference verification and image snapshot completed: $(date -Is)"
