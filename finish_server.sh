#!/bin/bash
# TickFlow 部署收尾:离线装依赖 + systemd(前半段解压/.env 已完成)
set -e
cd /home/ubuntu

echo "== 解开 wheelhouse"
if [ ! -d wheelhouse ]; then tar xzf wheelhouse.tgz; fi
ls wheelhouse | wc -l

echo "== 重建 venv 并离线安装依赖"
cd /home/ubuntu/tickflow/backend
rm -rf .venv
uv venv --python /usr/bin/python3 .venv
uv pip install --python .venv/bin/python --no-index --find-links /home/ubuntu/wheelhouse -r /home/ubuntu/tickflow-req.txt
.venv/bin/python -c "import fastapi, pandas, uvicorn; print('deps ok')"

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
