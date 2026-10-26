#!/usr/bin/env bash
set -u
ROOT=/data/ZJC/foundationPos
PROBE="$ROOT/setup/probe_camera_environment.py"
printf '\n--- System Python ---\n'
python3 "$PROBE"
printf '\n--- FoundationPose Conda ---\n'
/home/ni/anaconda3/envs/foundationpose/bin/python "$PROBE"
printf '\n--- FoundationPose Docker ---\n'
if [ "$(docker inspect foundationpose --format '{{.State.Running}}')" = true ]; then
  docker exec -i foundationpose /opt/conda/envs/my/bin/python < "$PROBE"
else
  printf 'Container is not running; probe skipped.\n'
fi
printf '\n--- RealSense OS packages ---\n'
dpkg-query -W '*realsense*' 2>/dev/null || true
printf '\n--- RealSense udev rules ---\n'
find /etc/udev/rules.d /lib/udev/rules.d -maxdepth 1 -iname '*realsense*' -print 2>/dev/null
printf '\n--- Device permission groups ---\n'
id
printf '\n--- Existing camera helpers ---\n'
find "$ROOT" -maxdepth 3 \( -name 'capture_realsense.py' -o -name 'run_rgbd_folder.py' -o -name 'fp-camera-env' \) -print
printf '\n--- Existing camera environments outside project ---\n'
for path in /home/ni/fp-camera-env/bin/python "$ROOT/camera-env/bin/python" "$ROOT/.camera-venv/bin/python"; do
  if [ -x "$path" ]; then
    "$path" "$PROBE"
  fi
done
