#!/usr/bin/env bash
set -Eeuo pipefail
if [ "$(id -u)" -ne 0 ]; then
  printf 'Run this script with sudo.\n' >&2
  exit 2
fi
ROOT=/data/ZJC/foundationPos
RULE=/etc/udev/rules.d/99-foundationpose-d435i.rules
SOURCE="$ROOT/setup/99-foundationpose-d435i.rules"
if [ -f "$RULE" ] && ! cmp -s "$SOURCE" "$RULE"; then
  cp -p "$RULE" "$ROOT/foundationpose_data/camera_setup/99-foundationpose-d435i.rules.backup.$(date +%Y%m%d_%H%M%S)"
fi
install -m 0644 "$SOURCE" "$RULE"
udevadm control --reload-rules
count=0
for item in /sys/bus/usb/devices/*; do
  if [ -f "$item/idVendor" ] && [ -f "$item/idProduct" ] && \
     [ "$(cat "$item/idVendor")" = 8086 ] && [ "$(cat "$item/idProduct")" = 0b3a ]; then
    device_path=$(readlink -f "$item")
    udevadm trigger --action=add --parent-match="$device_path"
    udevadm trigger --action=add "$device_path"
    count=$((count+1))
  fi
done
udevadm settle --timeout=10
printf 'Installed D435i-only permissions; applied to %s connected camera(s).\n' "$count"
