#!/usr/bin/env bash
set -Eeuo pipefail
mkdir -p "$HOME/foundationpose_data/setup_logs"
exec > >(tee -a "$HOME/foundationpose_data/setup_logs/prepare_project.log") 2>&1
echo "Project preparation started: $(date -Is)"
if [ ! -e "$HOME/FoundationPose" ]; then
  git clone --recursive https://github.com/NVlabs/FoundationPose.git "$HOME/FoundationPose"
fi
cd "$HOME/FoundationPose"
git remote -v
git submodule update --init --recursive
git rev-parse HEAD | tee "$HOME/foundationpose_data/foundationpose_commit.txt"
nvidia-smi > "$HOME/foundationpose_data/nvidia-smi.txt"
echo '=== Official install instructions ==='
sed -n '65,155p' readme.md
echo '=== Build scripts ==='
cat build_all.sh build_all_conda.sh
echo '=== Dockerfile ==='
cat docker/dockerfile
echo '=== Pull official recommended image ==='
docker pull wenbowen123/foundationpose:latest
docker image inspect wenbowen123/foundationpose:latest --format '{{json .RepoDigests}}' \
  > "$HOME/foundationpose_data/foundationpose_image_digest.json"
echo "Project preparation finished: $(date -Is)"
