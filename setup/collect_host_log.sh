#!/usr/bin/env bash
set -Eeuo pipefail
DATA=/home/ni/foundationpose_data
cp /root/foundationpose_data/setup_logs/prepare_host.log "$DATA/setup_logs/prepare_host.log"
chown ni:ni "$DATA/setup_logs/prepare_host.log"
echo '=== Current Docker download files ==='
ls -lh /var/lib/docker/tmp
echo '=== Host setup log copied ==='
ls -lh "$DATA/setup_logs/prepare_host.log"
