#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "=========================================="
echo "启动 Detection Service (端口 8001)"
echo "=========================================="

uvicorn detection_service.main:app \
    --host ${DETECTION_SERVICE_HOST:-0.0.0.0} \
    --port ${DETECTION_SERVICE_PORT:-8001} \
    --reload
