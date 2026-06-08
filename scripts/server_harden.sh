#!/bin/bash
# ============================================================================
# DineFlow — Ubuntu 24.04 VPS Hardening Script
# ============================================================================
# Run this as root on the fresh VPS BEFORE deploying the application.
# ============================================================================

set -e

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

echo "[1/5] Updating system packages..."
apt-get update && apt-get upgrade -y

echo "[2/5] Installing security tools (UFW, Fail2Ban)..."
apt-get install -y ufw fail2ban unattended-upgrades

echo "[3/5] Configuring UFW Firewall..."
# Default deny incoming, allow outgoing
ufw default deny incoming
ufw default allow outgoing

# Allow SSH, HTTP, HTTPS
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp

# Enable firewall
echo "y" | ufw enable

echo "[4/5] Configuring Fail2Ban..."
cat << 'EOF' > /etc/fail2ban/jail.local
[DEFAULT]
bantime  = 1h
findtime  = 10m
maxretry = 5

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
EOF
systemctl restart fail2ban
systemctl enable fail2ban

echo "[5/5] Securing SSH..."
sed -i 's/#PermitRootLogin yes/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

echo "==============================================="
echo " Server Hardening Complete!"
echo "==============================================="
echo "Please ensure you have SSH keys set up before logging out,"
echo "as password authentication for SSH is now disabled."
