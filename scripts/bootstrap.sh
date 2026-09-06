#!/bin/sh
set -eu

REPO="Nagumo-Ryunosuke/github-agent-bridge"
REF="${AGENT_BRIDGE_REF:-main}"
ARCHIVE_URL="https://github.com/${REPO}/archive/refs/heads/${REF}.zip"
STATE_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/github-agent-bridge"
VENV="$STATE_ROOT/venv"
BIN_DIR="$HOME/.local/bin"
YES=0
SKIP_CODEX=0
SKIP_LOGIN=0
TTY_DEVICE=""

if [ -r /dev/tty ] && [ -w /dev/tty ]; then
  TTY_DEVICE="/dev/tty"
fi

usage() {
  cat <<'EOF'
Usage: bootstrap.sh [--yes] [--skip-codex] [--skip-login]

One-command installer for github-agent-bridge on Linux/macOS.
This script is POSIX-sh compatible so it does not require bash on minimal Linux systems.

  --yes         Accept the single machine-change confirmation non-interactively.
  --skip-codex  Install dispatch/Desktop prerequisites only; background Codex review is disabled.
  --skip-login  Install binaries only; do not start gh/codex browser login.

Environment:
  AGENT_BRIDGE_REF=<branch>  Install a repository branch instead of main.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --skip-codex) SKIP_CODEX=1 ;;
    --skip-login) SKIP_LOGIN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\n==> %s\n' "$*"; }

if [ "$YES" -ne 1 ]; then
  cat <<'EOF'
github-agent-bridge will now prepare this user account.

It may:
  * install Python when it is missing;
  * create/update a private user virtual environment;
  * install missing Git, GitHub CLI and Codex CLI using native/official installers;
  * install the shared Skill under ~/.agents/skills/github-agent-bridge;
  * start GitHub and ChatGPT/Codex login flows.

System package installation may request sudo once. GitHub and Codex authentication
remain interactive and are never bypassed or stored by github-agent-bridge.
EOF
  if [ -z "$TTY_DEVICE" ]; then
    echo "No interactive terminal is available for confirmation." >&2
    echo "Rerun with --yes only if you have already reviewed these machine changes." >&2
    exit 2
  fi
  printf 'Proceed? [y/N] ' >"$TTY_DEVICE"
  IFS= read -r answer <"$TTY_DEVICE" || answer=""
  case "$answer" in
    y|Y|yes|YES|Yes) ;;
    *) echo "No changes made."; exit 2 ;;
  esac
fi

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "Need root privileges for: $* (sudo was not found)" >&2
    exit 1
  fi
}

python_ok() {
  command -v python3 >/dev/null 2>&1 &&
    python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1
}

install_python_linux() {
  if command -v python3 >/dev/null 2>&1; then
    return
  fi
  say "Installing Python 3"
  if command -v apt-get >/dev/null 2>&1; then
    run_root apt-get update
    run_root apt-get install -y python3 python3-venv python3-pip
  elif command -v dnf >/dev/null 2>&1; then
    run_root dnf install -y python3 python3-pip
  elif command -v yum >/dev/null 2>&1; then
    run_root yum install -y python3 python3-pip
  elif command -v zypper >/dev/null 2>&1; then
    run_root zypper --non-interactive install python3 python3-pip
  elif command -v pacman >/dev/null 2>&1; then
    run_root pacman -S --needed --noconfirm python python-pip
  elif command -v apk >/dev/null 2>&1; then
    run_root apk add python3 py3-pip
  else
    echo "No supported package manager was found to install Python 3." >&2
    exit 1
  fi
}

ensure_venv_support_linux() {
  if python3 -m venv --help >/dev/null 2>&1; then
    return
  fi
  say "Installing Python venv support"
  if command -v apt-get >/dev/null 2>&1; then
    run_root apt-get install -y python3-venv
  elif command -v apk >/dev/null 2>&1; then
    run_root apk add py3-pip
  else
    echo "Python is present but the venv module is unavailable. Install the distribution's Python venv package." >&2
    exit 1
  fi
  if ! python3 -m venv --help >/dev/null 2>&1; then
    echo "Python venv support is still unavailable after package installation." >&2
    exit 1
  fi
}

install_homebrew() {
  if command -v brew >/dev/null 2>&1; then
    return
  fi
  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to install Homebrew on macOS." >&2
    exit 1
  fi
  say "Installing Homebrew for required macOS packages"
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

OS="$(uname -s 2>/dev/null || echo unknown)"
ARCH="$(uname -m 2>/dev/null || echo unknown)"
say "Detected ${OS} / ${ARCH}"

case "$OS" in
  Linux)
    install_python_linux
    if ! python_ok; then
      echo "Python >= 3.9 is required. Current distribution Python: $(python3 --version 2>&1 || echo unavailable)" >&2
      echo "Install a supported Python >=3.9 build for this distribution/architecture, then rerun the same command." >&2
      exit 1
    fi
    ensure_venv_support_linux
    ;;
  Darwin)
    if ! python_ok; then
      install_homebrew
      brew install python
    fi
    ;;
  *)
    echo "Automatic bootstrap is not available for OS=${OS} architecture=${ARCH}." >&2
    echo "The Skill is architecture-neutral, but this installer currently supports Linux/macOS; use bootstrap.ps1 on Windows." >&2
    exit 1
    ;;
esac

if ! python_ok; then
  echo "Python >= 3.9 is required. Current: $(python3 --version 2>&1 || echo unavailable)" >&2
  exit 1
fi

say "Installing github-agent-bridge into ${VENV}"
mkdir -p "$STATE_ROOT" "$BIN_DIR"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install --upgrade "$ARCHIVE_URL"
ln -sf "$VENV/bin/agent-bridge" "$BIN_DIR/agent-bridge"
export PATH="$BIN_DIR:$HOME/.local/bin:$HOME/bin:$PATH"

say "Installing the shared Codex Skill"
"$VENV/bin/agent-bridge" skill install --scope user

set -- env install --yes
if [ "$SKIP_CODEX" -eq 1 ]; then
  set -- "$@" --skip-codex
fi

LOGIN_DEFERRED=0
if [ "$SKIP_LOGIN" -eq 1 ]; then
  set -- "$@" --skip-login
elif [ -z "$TTY_DEVICE" ]; then
  # A piped bootstrap has no useful stdin for interactive gh/codex login when
  # there is no controlling terminal. Complete binary installation now and
  # leave authentication for a later interactive `agent-bridge env install`.
  set -- "$@" --skip-login
  LOGIN_DEFERRED=1
fi

say "Installing/checking external prerequisites"
if [ -n "$TTY_DEVICE" ]; then
  "$VENV/bin/agent-bridge" "$@" <"$TTY_DEVICE"
else
  "$VENV/bin/agent-bridge" "$@"
fi

cat <<EOF

Installation complete.

Skill:       \$HOME/.agents/skills/github-agent-bridge
CLI:         ${BIN_DIR}/agent-bridge
Environment: ${VENV}
Platform:    ${OS} / ${ARCH}

Open or restart Codex App/CLI so it reloads the Skill. Then open a target Git repository
and ask Codex to use \$github-agent-bridge. On first use it will run readiness checks,
ask only for unresolved permission/authentication steps, and continue setup.
EOF

if [ "$LOGIN_DEFERRED" -eq 1 ]; then
  cat <<'EOF'

Authentication was deferred because no controlling terminal was available.
From an interactive terminal run:

  agent-bridge env install

This will start any still-required GitHub and Codex login flows.
EOF
fi
