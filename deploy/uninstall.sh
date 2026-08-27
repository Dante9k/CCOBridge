#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$(readlink -f "$0")")"
docker compose --env-file .env down
printf '%s\n' 'Gateway container removed; image, .env, and API key preserved.'
