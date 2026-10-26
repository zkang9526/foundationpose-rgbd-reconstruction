#!/usr/bin/env bash
# Independent native fallback for the Ubuntu 20.04 / RTX 3090 host.
set -euo pipefail
ROOT=/data/ZJC/foundationPos/FoundationPose-conda
PREFIX=/home/ni/anaconda3/envs/foundationpose
LOG=/data/ZJC/foundationPos/foundationpose_data/conda_setup
mkdir -p "$LOG" "$LOG/src"
source /home/ni/anaconda3/etc/profile.d/conda.sh
conda activate "$PREFIX"
export PIP_CONFIG_FILE=/dev/null
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_FIND_LINKS="$LOG/cached_wheels"
export CUDA_HOME=/usr/local/cuda-12.1
export PATH="$CUDA_HOME/bin:$PATH"
export TORCH_CUDA_ARCH_LIST=8.6
export MAX_JOBS=4
export CMAKE_PREFIX_PATH="$PREFIX"
export PYOPENGL_PLATFORM=egl
export OMP_NUM_THREADS=4
cd "$ROOT"
if [ -f "$LOG/cached_wheels/torch-2.4.1+cu121-cp311-cp311-linux_x86_64.whl" ]; then
  printf '%s  %s\n' '914d128e5abcbbe79ca1b9eb5311b185444f1b2d7117df555fe418487ecfb894' "$LOG/cached_wheels/torch-2.4.1+cu121-cp311-cp311-linux_x86_64.whl" | sha256sum --check
fi
python -m pip install --index-url https://mirrors.aliyun.com/pypi/simple/ --timeout 60 --retries 5 'setuptools<81' 'pybind11==2.13.6' 'cmake>=3.27,<4' ninja > "$LOG/02_build_tools.log" 2>&1
cat > "$LOG/constraints.txt" <<'EOF'
torch==2.4.1
torchvision==0.19.1
torchaudio==2.4.1
warp-lang==1.6.2
kornia==0.7.3
numpy==2.1.3
pybind11==2.13.6
setuptools<81
opencv-python==4.11.0.86
EOF
python -m pip install --index-url https://download.pytorch.org/whl/cu121 --timeout 60 --retries 5 'torch==2.4.1' 'torchvision==0.19.1' 'torchaudio==2.4.1' > "$LOG/03_torch.log" 2>&1
python -m pip install --index-url https://mirrors.aliyun.com/pypi/simple/ --timeout 60 --retries 5 -c "$LOG/constraints.txt" -r "$ROOT/requirements.txt" fvcore iopath > "$LOG/04_requirements.log" 2>&1
if [ -f "$LOG/pytorch3d-V0.7.8.tar.gz" ]; then
  if [ ! -f "$LOG/src/pytorch3d-0.7.8/setup.py" ]; then
    tar -xzf "$LOG/pytorch3d-V0.7.8.tar.gz" -C "$LOG/src"
  fi
  PYTORCH3D_SOURCE="$LOG/src/pytorch3d-0.7.8"
else
  if [ ! -f "$LOG/src/pytorch3d/setup.py" ]; then
    git clone --depth 1 --branch V0.7.8 https://github.com/facebookresearch/pytorch3d.git "$LOG/src/pytorch3d-complete" > "$LOG/05_pytorch3d_clone.log" 2>&1
    PYTORCH3D_SOURCE="$LOG/src/pytorch3d-complete"
  else
    PYTORCH3D_SOURCE="$LOG/src/pytorch3d"
  fi
fi
FORCE_CUDA=1 python -m pip install --no-build-isolation --no-deps "$PYTORCH3D_SOURCE" > "$LOG/06_pytorch3d_build.log" 2>&1
if [ ! -d "$LOG/src/nvdiffrast/.git" ]; then
  git clone --depth 1 --branch v0.3.3 https://github.com/NVlabs/nvdiffrast.git "$LOG/src/nvdiffrast" > "$LOG/07_nvdiffrast_clone.log" 2>&1
fi
python -m pip install --no-build-isolation --no-deps "$LOG/src/nvdiffrast" > "$LOG/08_nvdiffrast_install.log" 2>&1
cmake -S "$ROOT/mycpp" -B "$ROOT/mycpp/build" -DCMAKE_BUILD_TYPE=Release -Dpybind11_DIR="$(python -m pybind11 --cmakedir)" -DPYTHON_EXECUTABLE="$PREFIX/bin/python" -DPython3_ROOT_DIR="$PREFIX" > "$LOG/09_mycpp.log" 2>&1
cmake --build "$ROOT/mycpp/build" -j4 >> "$LOG/09_mycpp.log" 2>&1
python /home/ni/foundationpose_data/setup/verify_environment.py --repo "$ROOT" --output /home/ni/foundationpose_data/conda_verification.json > "$LOG/10_verify_environment.log" 2>&1
python /home/ni/foundationpose_data/setup/verify_demo.py --repo "$ROOT" --output /home/ni/foundationpose_data/demo_smoke_conda --frames 3 > "$LOG/11_verify_demo.log" 2>&1
python -m pip freeze > "$LOG/pip_freeze.txt"
python -m pip list --format=freeze > "$LOG/requirements.lock.txt"
conda list --explicit > "$LOG/conda_explicit.txt"
python -m pip check > "$LOG/pip_check.txt"
printf 'Conda fallback environment and three-frame demo PASSED\n'
