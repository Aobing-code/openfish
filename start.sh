#!/bin/bash
# OpenFish 启动脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 检查Python版本
python3 --version >/dev/null 2>&1 || { echo "Error: python3 not found"; exit 1; }

# 检查依赖
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "Installing dependencies..."
pip install -q -r requirements.txt

# 启动服务
echo "Starting OpenFish..."
exec python -m app.main "$@"
