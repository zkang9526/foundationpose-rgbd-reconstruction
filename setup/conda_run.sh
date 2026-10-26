#!/usr/bin/env bash
# Execute FoundationPose commands in the verified, isolated native environment.
set -euo pipefail
source /home/ni/anaconda3/etc/profile.d/conda.sh
conda activate /home/ni/anaconda3/envs/foundationpose
export CUDA_HOME=/usr/local/cuda-12.1
export PATH="$CUDA_HOME/bin:$PATH"
export TORCH_CUDA_ARCH_LIST=8.6
export MAX_JOBS=4
export PYOPENGL_PLATFORM=egl
export OMP_NUM_THREADS=4
cd /data/ZJC/foundationPos/FoundationPose-conda
if [ "$#" -eq 0 ]; then
  exec python run_demo.py --debug 0 --debug_dir /data/ZJC/foundationPos/foundationpose_data/demo_full_conda
fi
exec "$@"
