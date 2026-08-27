#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$(readlink -f "$0")")"
docker compose --env-file .env logs --tail 200 -f ccobridge
