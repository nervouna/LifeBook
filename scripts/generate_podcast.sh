#!/bin/bash
# Generate weekly podcast from the past 7 days and send to Feishu.
# Usage: crontab -e → 0 15 * * 0 /Users/damao/Develop/Projects/LifeBook/scripts/generate_podcast.sh

set -euo pipefail

export PATH="/opt/homebrew/bin:$PATH"
PROJECT_DIR="/Users/damao/Develop/Projects/LifeBook"
WEEK_AGO=$(date -v-7d +%Y-%m-%d)
TODAY=$(date +%Y-%m-%d)
LOG_FILE="${PROJECT_DIR}/logs/podcast_weekly_${TODAY}.log"

mkdir -p "${PROJECT_DIR}/logs"

echo "[$(date)] Starting weekly podcast generation (since ${WEEK_AGO})" >> "${LOG_FILE}"

"${PROJECT_DIR}/.venv/bin/lifebook" podcast-multi \
    --since "${WEEK_AGO}" \
    --limit 40 \
    --send \
    >> "${LOG_FILE}" 2>&1

echo "[$(date)] Done" >> "${LOG_FILE}"
