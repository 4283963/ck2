#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "=========================================="
echo "启动 Ingestion Service (端口 8000)"
echo "=========================================="

uvicorn ingestion_service.main:app \
    --host ${INGESTION_SERVICE_HOST:-0.0.0.0} \
    --port ${INGESTION_SERVICE_PORT:-8000} \
    --reload
