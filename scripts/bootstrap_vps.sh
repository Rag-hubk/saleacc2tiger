#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SUDO=""
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "ERROR: run as root or install sudo."
    exit 1
  fi
fi

install_docker_apt() {
  $SUDO apt-get update -y
  $SUDO apt-get install -y ca-certificates curl gnupg lsb-release
  $SUDO install -m 0755 -d /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    $SUDO chmod a+r /etc/apt/keyrings/docker.gpg
  fi

  . /etc/os-release
  ARCH="$($SUDO dpkg --print-architecture)"
  DISTRO_CODENAME="${VERSION_CODENAME:-$UBUNTU_CODENAME}"

  echo \
    "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${ID} ${DISTRO_CODENAME} stable" \
    | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null

  $SUDO apt-get update -y
  $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  $SUDO systemctl enable docker --now
}

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Installing..."
  if command -v apt-get >/dev/null 2>&1; then
    install_docker_apt
  else
    echo "ERROR: automatic Docker install is supported for Debian/Ubuntu (apt) only."
    exit 1
  fi
fi

if ! groups "$USER" | grep -q '\bdocker\b'; then
  $SUDO usermod -aG docker "$USER" || true
  echo "User added to docker group: $USER"
  echo "If docker permission errors appear, relogin once and re-run this script."
fi

bash "$ROOT_DIR/scripts/deploy_docker.sh"
