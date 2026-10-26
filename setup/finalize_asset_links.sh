#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/data/ZJC/foundationPos
DATA="$ROOT/foundationpose_data/conda_setup"
mkdir -p "$ROOT/.assets_download"
for name in \
  'torch-2.4.1+cu121-cp311-cp311-linux_x86_64.whl' \
  'open3d-0.19.0-cp311-cp311-manylinux_2_31_x86_64.whl' \
  'warp_lang-1.6.2-py3-none-manylinux2014_x86_64.whl'; do
  target="$ROOT/.assets_download/$name"
  if [ ! -e "$target" ]; then
    ln "$DATA/cached_wheels/$name" "$target"
  fi
done
target="$ROOT/.assets_download/pytorch3d-V0.7.8.tar.gz"
if [ ! -e "$target" ]; then
  ln "$DATA/pytorch3d-V0.7.8.tar.gz" "$target"
fi
printf 'Additional downloaded files are present in %s\n' "$ROOT/.assets_download"
