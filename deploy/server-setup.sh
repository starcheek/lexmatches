#!/bin/bash
# One-time server setup (Ubuntu 24.04, as root). Safe to run again.
#   scp deploy/server-setup.sh root@<server>:/root/ && ssh root@<server> bash /root/server-setup.sh <domain>
# Installs Docker, adds swap and a firewall, creates the `deploy` user and /opt/lexmatches with a .env
# holding fresh random secrets. API keys are NOT set here: add them to /opt/lexmatches/.env afterwards.
set -euo pipefail
DOMAIN="${1:?usage: server-setup.sh <domain>   e.g. server-setup.sh read.example.com}"
APP=/opt/lexmatches
IP="$(curl -fsS -4 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"

# 2 GB swap: the images are built on this machine and a 2 GB server needs the headroom
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
sysctl -q -w vm.swappiness=20 && echo 'vm.swappiness=20' > /etc/sysctl.d/60-swappiness.conf

export DEBIAN_FRONTEND=noninteractive
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh >/dev/null
apt-get install -y -qq rsync curl >/dev/null

ufw allow OpenSSH >/dev/null && ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null && ufw --force enable >/dev/null

# deploy user: SSH key only, may run docker (which is root-equivalent on this machine)
id deploy >/dev/null 2>&1 || adduser --disabled-password --gecos "" deploy >/dev/null
usermod -aG docker deploy
install -d -o deploy -g deploy "$APP"
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
touch /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys && chmod 600 /home/deploy/.ssh/authorized_keys

# Key pair for the GitHub workflow: the public half is authorised here, the private half goes into the
# GitHub secret DROPLET_SSH_KEY (deploy/README.md) and should then be deleted from the server.
if [ ! -f /root/gh-deploy ] && ! grep -q github-deploy /home/deploy/.ssh/authorized_keys; then
  ssh-keygen -q -t ed25519 -f /root/gh-deploy -N "" -C github-deploy
  cat /root/gh-deploy.pub >> /home/deploy/.ssh/authorized_keys
fi

if [ ! -f "$APP/.env" ]; then
  r() { openssl rand -hex "$1"; }
  cat > "$APP/.env" <<EOF
# Server settings. Options: .env.example in the repo. After a change: cd $APP && sh deploy/remote-deploy.sh
# The site's domain; its DNS A record must point at this server ($IP). Caddy gets the HTTPS certificate.
SITE_DOMAIN=$DOMAIN
JWT_SECRET=$(r 32)
ADMIN_TOKEN=$(r 24)
POSTGRES_PASSWORD=$(r 16)
S3_SECRET_KEY=$(r 16)

# Translation (empty = mock translator)
ANTHROPIC_API_KEY=
# Speech: xai = Grok voices (needs the key; without it the local Piper voice is used)
TTS_PROVIDER=xai
XAI_API_KEY=
XAI_VOICE=eve
PIPER_PRELOAD=fr

# Small server
MAX_UPLOAD_MB=25
BOOK_WORKERS=1
EOF
  chown deploy:deploy "$APP/.env" && chmod 600 "$APP/.env"
fi

echo "docker: $(docker --version | cut -d, -f1) / $(docker compose version --short)"
echo "swap:   $(free -m | awk '/Swap/ {print $2}') MB"
echo "domain: $(grep '^SITE_DOMAIN=' "$APP/.env" | cut -d= -f2)"
echo "deploy key for GitHub: $([ -f /root/gh-deploy ] && echo /root/gh-deploy || echo 'already handed over')"
