#!/bin/bash
# TickFlow 阿里云裸机部署 — Ubuntu 24.04, /root 下, 系统 python3.12 + 离线 wheelhouse
set -e
cd /root

echo "== 解压部署包"
rm -rf tickflow
mkdir -p tickflow
unzip -q tickflow-aliyun-20260819.zip -d tickflow

echo "== 修正 .env 的 DATA_DIR 为绝对路径"
sed -i 's|^DATA_DIR=.*|# DATA_DIR(dev only, 见下行覆盖)|' tickflow/.env || true
echo "DATA_DIR=/root/tickflow/data" >> tickflow/.env

echo "== 建 venv 并离线安装依赖"
apt-get install -y python3.12-venv >/dev/null 2>&1 || true
cd /root/tickflow/backend
rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install --no-index --find-links /root/wheelhouse -r /root/tickflow-req-linux2.txt -q
.venv/bin/pip install --no-index --find-links /root/wheelhouse -q requests
.venv/bin/python -c "import fastapi, pandas, uvicorn, requests; print('deps ok')"

echo "== systemd 服务"
cat > /etc/systemd/system/tickflow.service << 'UNIT'
[Unit]
Description=TickFlow Stock Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/tickflow/backend
Environment=PYTHONUNBUFFERED=1
Environment=TZ=Asia/Shanghai
ExecStart=/root/tickflow/backend/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 3018
Restart=always
RestartSec=5
MemoryMax=2.2G
MemorySwapMax=3G

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now tickflow
sleep 15
systemctl --no-pager status tickflow | head -6
curl -s -o /dev/null -w "health:%{http_code}\n" http://127.0.0.1:3018/api/system/health || true
