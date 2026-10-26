#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/data/ZJC/foundationPos
ENV="$ROOT/.camera-venv"
DATA="$ROOT/foundationpose_data/camera_setup"
CACHE="$ROOT/foundationpose_data/conda_setup/cached_wheels"
mkdir -p "$DATA"
exec > >(tee -a "$DATA/prepare_camera.log") 2>&1
if [ -e "$ENV" ] && [ ! -f "$ENV/.foundationpose-camera-env" ]; then
  printf 'Existing camera environment is not managed by this script: %s\n' "$ENV" >&2
  exit 2
fi
if [ ! -x "$ENV/bin/python" ]; then
  /home/ni/anaconda3/envs/foundationpose/bin/python -m venv "$ENV"
  printf 'Dedicated D435i capture environment\n' > "$ENV/.foundationpose-camera-env"
fi
"$ENV/bin/python" -m pip install --no-index --no-deps \
  "$ROOT/.assets_download/numpy-1.26.4-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl" \
  "$ROOT/.assets_download/pyrealsense2-2.55.1.6486-cp311-cp311-manylinux1_x86_64.whl" \
  "$CACHE/pillow-12.3.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
"$ENV/bin/python" -m pip check
"$ENV/bin/python" -m pip freeze > "$DATA/requirements.lock.txt"
"$ENV/bin/python" - <<'PY'
from importlib.metadata import version
import numpy
import pyrealsense2
from PIL import Image
print('Camera SDK:', version('pyrealsense2'))
print('NumPy:', numpy.__version__)
print('Pillow:', version('Pillow'))
print('Camera environment imports passed')
PY
