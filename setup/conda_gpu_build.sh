#!/usr/bin/env bash
# Build the two GPU packages and local C++ module after PyTorch is installed.
set -euo pipefail
ROOT=/data/ZJC/foundationPos/FoundationPose-conda
LOG=/data/ZJC/foundationPos/foundationpose_data/conda_setup
source /home/ni/anaconda3/etc/profile.d/conda.sh
conda activate /home/ni/anaconda3/envs/foundationpose
export PIP_CONFIG_FILE=/dev/null
export CUDA_HOME=/usr/local/cuda-12.1
export PATH="$CUDA_HOME/bin:$PATH"
export TORCH_CUDA_ARCH_LIST=8.6
export MAX_JOBS=4
export OMP_NUM_THREADS=4
export CMAKE_PREFIX_PATH="$CONDA_PREFIX"
export PYOPENGL_PLATFORM=egl
python - <<'PY'
import torch
print('Torch:', torch.__version__, 'CUDA:', torch.version.cuda, 'available:', torch.cuda.is_available(), flush=True)
assert torch.cuda.is_available()
value = torch.eye(4, device='cuda')
assert torch.equal(value @ value, value)
print('GPU:', torch.cuda.get_device_name(0), 'CUDA computation passed', flush=True)
PY
if [ ! -f "$LOG/src/pytorch3d-0.7.8/setup.py" ]; then
  tar -xzf "$LOG/pytorch3d-V0.7.8.tar.gz" -C "$LOG/src"
fi
sha256sum "$LOG/pytorch3d-V0.7.8.tar.gz" > "$LOG/pytorch3d_archive_sha256.txt"
FORCE_CUDA=1 python -m pip install --no-build-isolation --no-deps "$LOG/src/pytorch3d-0.7.8" > "$LOG/06_pytorch3d_build.log" 2>&1
python -m pip install --no-build-isolation --no-deps "$LOG/src/nvdiffrast" > "$LOG/08_nvdiffrast_install.log" 2>&1
cmake -S "$ROOT/mycpp" -B "$ROOT/mycpp/build" -DCMAKE_BUILD_TYPE=Release -Dpybind11_DIR="$(python -m pybind11 --cmakedir)" -DPYTHON_EXECUTABLE="$CONDA_PREFIX/bin/python" -DPython3_ROOT_DIR="$CONDA_PREFIX" > "$LOG/09_mycpp.log" 2>&1
cmake --build "$ROOT/mycpp/build" -j4 >> "$LOG/09_mycpp.log" 2>&1
printf 'Native extensions built\n'
