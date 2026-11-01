#!/usr/bin/env bash
# Prepare configuration without starting containers, creating data or changing timers.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PRODUCTION_DIR="${PRODUCTION_DIR:-/opt/acessilia/core}"
PREPARE_ONLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prepare-only|--no-timer) PREPARE_ONLY=true; shift ;;
    --production-dir) PRODUCTION_DIR="$2"; shift 2 ;;
    --help|-h)
      echo "Usage: $0 --prepare-only [--production-dir /opt/acessilia/core]"
      echo "--no-timer is a preparation-only compatibility alias."
      echo "Run as the deployment user; parent directories must already be writable."
      exit 0 ;;
    *) echo "Unsupported option: $1. Use --help; registry login is separate." >&2; exit 1 ;;
  esac
done
if [ "$PREPARE_ONLY" != true ]; then
  echo "Explicit --prepare-only is required. Activation and timers are separate steps." >&2
  exit 1
fi
exec python3 "$SCRIPT_DIR/production_deploy.py" prepare --directory "$PRODUCTION_DIR"
