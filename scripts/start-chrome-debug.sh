#!/usr/bin/env bash
# Start Chrome in CDP debug mode for Zero-Token credential capture.
# Usage: ./scripts/start-chrome-debug.sh [PORT]

set -euo pipefail

PORT="${1:-9222}"
PROFILE_DIR="${HOME}/.copaw/chrome-profile"
mkdir -p "${PROFILE_DIR}"

# Detect Chrome binary
CHROME=""
for candidate in \
    google-chrome \
    google-chrome-stable \
    chromium \
    chromium-browser \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do
    if command -v "${candidate}" &>/dev/null || [ -x "${candidate}" ]; then
        CHROME="${candidate}"
        break
    fi
done

if [ -z "${CHROME}" ]; then
    echo "Error: Chrome/Chromium not found. Please install Google Chrome." >&2
    exit 1
fi

URLS=(
    "https://chat.deepseek.com"
    "https://claude.ai"
    "https://chatgpt.com"
    "https://chat.qwen.ai"
    "https://kimi.moonshot.cn"
    "https://www.doubao.com/chat"
    "https://gemini.google.com"
    "https://grok.com"
    "https://chatglm.cn"
)

echo "Starting Chrome with CDP on port ${PORT}..."
echo "Profile: ${PROFILE_DIR}"
echo "Opening login pages for 9 AI platforms..."

"${CHROME}" \
    --remote-debugging-port="${PORT}" \
    --user-data-dir="${PROFILE_DIR}" \
    --no-first-run \
    --no-default-browser-check \
    "${URLS[@]}" &

echo "Chrome started (PID: $!)"
echo ""
echo "Please log in to each platform, then run:"
echo "  copaw zero-token login --all"
