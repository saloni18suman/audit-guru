#!/usr/bin/env bash
#
# Bootstrap an Amazon Linux 2023 EC2 instance for AnomaGuard.
# Run as ec2-user after cloning the repo to /home/ec2-user/anomaguard.
#
#   bash deploy/setup-ec2.sh
#
# Prerequisites (configured via the console/CLI before running this):
#   - The instance has the IAM role from deploy/iam-policy.json attached.
#   - Config values are stored in SSM Parameter Store under /anomaguard/*
#     (see DEPLOY.md). At minimum: GROQ_API_KEY, S3_BUCKET_NAME.
#   - Security group allows inbound TCP 8501 from your IP.
#
set -euo pipefail

APP_DIR="/home/ec2-user/anomaguard"
cd "$APP_DIR"

echo "==> Installing system packages…"
sudo dnf install -y python3.11 python3.11-pip git

echo "==> Creating virtual environment…"
python3.11 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> Pre-building the FAISS policy index…"
./venv/bin/python -c "from rag.policy_rag import get_policy_context; get_policy_context('hotel travel'); print('RAG ready')"

echo "==> Installing systemd services…"
sudo cp deploy/anomaguard-web.service    /etc/systemd/system/
sudo cp deploy/anomaguard-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now anomaguard-worker.service
sudo systemctl enable --now anomaguard-web.service

echo "==> Done. Service status:"
sudo systemctl --no-pager status anomaguard-web.service    || true
sudo systemctl --no-pager status anomaguard-worker.service || true

PUBLIC_IP="$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 || echo '<ec2-public-ip>')"
echo
echo "AnomaGuard is starting at: http://${PUBLIC_IP}:8501"
