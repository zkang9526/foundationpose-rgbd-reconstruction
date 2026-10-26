#!/usr/bin/env bash
set -Eeuo pipefail
TARGET_HOME="$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)"
LOG_DIR="$TARGET_HOME/foundationpose_data/setup_logs"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/prepare_host.log") 2>&1
echo "Host preparation started: $(date -Is)"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y git git-lfs curl wget ca-certificates gnupg lsb-release build-essential cmake ninja-build python3-venv unzip
if ! command -v nvidia-ctk >/dev/null 2>&1; then
  curl --fail --location --retry 3 https://nvidia.github.io/libnvidia-container/gpgkey -o /tmp/foundationpose_nvidia_key.asc
  gpg --dearmor --yes --output /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg /tmp/foundationpose_nvidia_key.asc
  curl --fail --location --retry 3 https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-container-toolkit
fi
if docker ps --format '{{.ID}}' | grep -q .; then
  echo 'Docker has running containers; defer runtime reconfiguration/restart.'
  exit 2
fi
if [ -f /etc/docker/daemon.json ]; then
  cp -a /etc/docker/daemon.json "/etc/docker/daemon.json.before-foundationpose-$(date +%Y%m%d%H%M%S)"
fi
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker
echo "Host preparation finished: $(date -Is)"
