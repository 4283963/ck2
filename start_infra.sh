#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "CK2 - 空拍照片过滤系统启动脚本"
echo "=========================================="
echo ""

check_docker_compose() {
    if command -v docker-compose &> /dev/null; then
        echo "docker-compose"
    elif docker compose version &> /dev/null; then
        echo "docker compose"
    else
        echo ""
    fi
}

DC=$(check_docker_compose)

if [ -z "$DC" ]; then
    echo "错误: 未找到 docker-compose 或 docker compose，请先安装 Docker"
    exit 1
fi

if [ ! -f .env ]; then
    echo "未找到 .env 文件，从 .env.example 复制..."
    cp .env.example .env
    echo "已创建 .env 文件，请根据需要修改配置"
fi

echo ""
echo "[1/4] 启动基础设施服务 (MySQL, MinIO, MQTT)..."
$DC up -d mysql minio mqtt

echo ""
echo "[2/4] 等待服务就绪..."
MAX_RETRIES=30
RETRY=0
while [ $RETRY -lt $MAX_RETRIES ]; do
    MYSQL_READY=$($DC exec -T mysql mysqladmin ping -h localhost -u${MYSQL_USER:-ck2_user} -p${MYSQL_PASSWORD:-ck2_pass_2024} --silent 2>/dev/null && echo "ok" || echo "no")
    MINIO_READY=$(curl -sf http://localhost:${MINIO_PORT:-9000}/minio/health/live 2>/dev/null && echo "ok" || echo "no")

    echo "  MySQL: $MYSQL_READY | MinIO: $MINIO_READY"

    if [ "$MYSQL_READY" = "ok" ] && [ "$MINIO_READY" = "ok" ]; then
        echo "基础设施服务已就绪!"
        break
    fi

    RETRY=$((RETRY + 1))
    sleep 3
done

if [ $RETRY -ge $MAX_RETRIES ]; then
    echo "警告: 等待超时，继续启动可能会失败，请检查容器状态"
fi

echo ""
echo "[3/4] 初始化数据库..."
if [ ! -d "venv" ]; then
    if command -v python3 &> /dev/null; then
        PYTHON=python3
    else
        PYTHON=python
    fi
    echo "创建 Python 虚拟环境..."
    $PYTHON -m venv venv
    source venv/bin/activate
    echo "安装依赖..."
    pip install --upgrade pip
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

python init_db.py

echo ""
echo "[4/4] 完成!"
echo ""
echo "使用方法:"
echo "  启动 Ingestion Service (端口 8000):"
echo "    source venv/bin/activate && uvicorn ingestion_service.main:app --host 0.0.0.0 --port 8000 --reload"
echo ""
echo "  启动 Detection Service (端口 8001):"
echo "    source venv/bin/activate && uvicorn detection_service.main:app --host 0.0.0.0 --port 8001 --reload"
echo ""
echo "  服务地址:"
echo "    Ingestion API:  http://localhost:8000/docs"
echo "    Detection API:  http://localhost:8001/docs"
echo "    MinIO Console:  http://localhost:${MINIO_CONSOLE_PORT:-9001}"
echo "    MySQL:          localhost:${MYSQL_PORT:-3306}"
echo "    MQTT:           localhost:${MQTT_PORT:-1883}"
echo ""
