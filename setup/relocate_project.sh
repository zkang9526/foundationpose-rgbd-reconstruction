#!/usr/bin/env bash
set -Eeuo pipefail
DEST=/data/ZJC/foundationPos
test -d "$DEST"
test -w "$DEST"
for source in /home/ni/FoundationPose /home/ni/foundationpose_data /home/ni/FoundationPose-conda; do
  target="$DEST/$(basename "$source")"
  case "$target" in "$DEST"/*) ;; *) echo 'Unexpected target path' >&2; exit 1;; esac
  if [ -L "$source" ]; then
    [ "$(readlink -f "$source")" = "$target" ] || { echo "Unexpected symlink: $source" >&2; exit 1; }
    continue
  fi
  [ -d "$source" ] || continue
  [ ! -e "$target" ] || { echo "Target already exists: $target" >&2; exit 1; }
  mv -- "$source" "$target"
  ln -s -- "$target" "$source"
  echo "$source -> $target"
done
echo '=== Project directory ==='
ls -lah "$DEST"
echo '=== Compatibility paths ==='
ls -ld /home/ni/FoundationPose /home/ni/FoundationPose-conda /home/ni/foundationpose_data
