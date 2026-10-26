#!/usr/bin/env bash
# Finish the inference dependency and record real GPU / model validation.
set -euo pipefail
ROOT=/data/ZJC/foundationPos/FoundationPose-conda
DATA=/data/ZJC/foundationPos/foundationpose_data
LOG="$DATA/conda_setup"
source /home/ni/anaconda3/etc/profile.d/conda.sh
conda activate /home/ni/anaconda3/envs/foundationpose
export PIP_CONFIG_FILE=/dev/null
export PIP_FIND_LINKS="$LOG/cached_wheels"
export CUDA_HOME=/usr/local/cuda-12.1
export PATH="$CUDA_HOME/bin:$PATH"
export TORCH_CUDA_ARCH_LIST=8.6
export MAX_JOBS=4
export OMP_NUM_THREADS=4
export PYOPENGL_PLATFORM=egl
cd "$ROOT"
python -m pip install --index-url https://mirrors.aliyun.com/pypi/simple/ --timeout 60 --retries 5 -c "$LOG/constraints.txt" 'kornia==0.7.3' > "$LOG/04_kornia.log" 2>&1
python -m pip freeze > "$LOG/pip_freeze.txt"
python -m pip list --format=freeze > "$LOG/requirements.lock.txt"
conda list --explicit > "$LOG/conda_explicit.txt"
python -m pip check > "$LOG/pip_check.txt"
python "$DATA/setup/verify_environment.py" --repo "$ROOT" --output "$DATA/conda_verification.json" > "$LOG/10_verify_environment.log" 2>&1
python "$DATA/setup/verify_demo.py" --repo "$ROOT" --output "$DATA/demo_smoke_conda" --frames 3 > "$LOG/11_verify_demo.log" 2>&1
printf 'Conda fallback environment and three-frame demo PASSED\n'
