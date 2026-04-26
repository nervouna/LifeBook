#!/bin/bash
# Generate daily podcast from yesterday's notes and send to Feishu.
# Usage: crontab -e → 0 8 * * * /Users/damao/Develop/Projects/LifeBook/scripts/generate_podcast.sh

set -euo pipefail

PROJECT_DIR="/Users/damao/Develop/Projects/LifeBook"
YESTERDAY=$(date -v-1d +%Y-%m-%d)
LOG_FILE="${PROJECT_DIR}/logs/podcast_${YESTERDAY}.log"

mkdir -p "${PROJECT_DIR}/logs"

echo "[$(date)] Starting podcast generation for ${YESTERDAY}" >> "${LOG_FILE}"

"${PROJECT_DIR}/.venv/bin/lifebook" podcast-multi \
    --since "${YESTERDAY}" \
    --limit 10 \
    --send \
    >> "${LOG_FILE}" 2>&1

echo "[$(date)] Done" >> "${LOG_FILE}"
