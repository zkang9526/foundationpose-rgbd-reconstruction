#!/usr/bin/env bash
set -Eeuo pipefail
REPO=/data/ZJC/foundationPos/FoundationPose
DATA=/data/ZJC/foundationPos/foundationpose_data
mkdir -p "$DATA/setup_logs"
exec > >(tee -a "$DATA/setup_logs/create_container.log") 2>&1
cd "$REPO"
git lfs install --local
docker image inspect wenbowen123/foundationpose:latest --format '{{json .RepoDigests}}' > "$DATA/foundationpose_image_digest.json"
docker tag wenbowen123/foundationpose:latest foundationpose:local
if docker container inspect foundationpose >/dev/null 2>&1; then
  echo 'Container foundationpose already exists; checking its mounts before reuse.'
  docker inspect foundationpose --format '{{json .Mounts}}'
  exit 2
fi
docker run -d --name foundationpose \
  --gpus all --ipc=host --network=host \
  --env NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics \
  --env TORCH_CUDA_ARCH_LIST=8.6 --env MAX_JOBS=4 \
  --mount "type=bind,source=$REPO,target=/workspace/FoundationPose" \
  --mount "type=bind,source=$DATA,target=/data" \
  --workdir /workspace/FoundationPose \
  foundationpose:local sleep infinity
docker exec foundationpose nvidia-smi
docker exec foundationpose bash -lc 'python --version; nvcc --version; python -m pip freeze' > "$DATA/packages_before_build.txt"
docker exec foundationpose bash -lc 'set -e; cd /workspace/FoundationPose; bash build_all.sh' \
  2>&1 | tee "$DATA/setup_logs/build_all.log"
docker exec foundationpose bash -lc 'cd /workspace/FoundationPose; python check_env.py --demo-data' \
  2>&1 | tee "$DATA/setup_logs/check_env.log"
echo "Container setup completed: $(date -Is)"
