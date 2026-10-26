#!/usr/bin/env bash
set -u
echo '=== CUDA ==='
readlink -f /usr/local/cuda
/usr/local/cuda/bin/nvcc --version
/usr/local/cuda-12.1/bin/nvcc --version
echo '=== Docker images / runtimes ==='
docker images
docker info --format '{{json .Runtimes}}'
echo '=== Conda environments ==='
/home/ni/anaconda3/bin/conda env list
echo '=== NVIDIA packages ==='
dpkg-query -W '*nvidia-container*' '*libnvidia-container*' 2>/dev/null || true
echo '=== Connectivity ==='
for url in https://github.com/NVlabs/FoundationPose.git https://registry-1.docker.io/v2/ https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list https://pypi.org/simple/pip/; do
  curl -I -L --connect-timeout 10 --max-time 20 "$url" 2>&1 | tail -n 7
done
echo '=== Disk ==='
df -h / /data
