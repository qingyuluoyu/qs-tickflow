#!/bin/bash
# TickFlow 裸机部署脚本 — Ubuntu 24.04, 不用 Docker
set -e
cd /home/ubuntu

echo "== 解压"
rm -rf tickflow
mkdir -p tickflow
unzip -q tickflow-server-full-20260818.zip -d tickflow

echo "== 修正 .env 的 DATA_DIR 为绝对路径(开发包里的相对路径在服务器上会指错)"
sed -i 's|^DATA_DIR=.*|# DATA_DIR(dev only, 见下行覆盖)|' tickflow/.env || true
echo "DATA_DIR=/home/ubuntu/tickflow/data" >> tickflow/.env

echo "== 安装后端依赖(uv sync, 清华 PyPI 镜像)"
cd tickflow/backend
export UV_DEFAULT_INDEX="https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"
export UV_PYTHON_INSTALL_MIRROR="https://registry.npmmirror.com/-/binary/python-build-standalone"
uv sync --no-dev --frozen

echo "== systemd 服务"
sudo tee /etc/systemd/system/tickflow.service > /dev/null << 'UNIT'
[Unit]
Description=TickFlow Stock Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/tickflow/backend
Environment=PYTHONUNBUFFERED=1
Environment=TZ=Asia/Shanghai
ExecStart=/home/ubuntu/tickflow/backend/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 3018
Restart=always
RestartSec=5
MemoryMax=2.5G

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now tickflow
sleep 12
systemctl --no-pager status tickflow | head -8
curl -s -o /dev/null -w "health:%{http_code}\n" http://127.0.0.1:3018/api/system/health || true
