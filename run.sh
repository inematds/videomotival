#!/usr/bin/env bash
# Atalhos do videomotival. Uso: ./run.sh web | check | video "<tema>" <segundos> [--auto]
set -euo pipefail
cd "$(dirname "$0")"
case "${1:-web}" in
  web)   exec python3 -m videomotival serve --port "${PORT:-8030}" ;;
  check) exec python3 -m videomotival check ;;
  video) shift; topic="$1"; secs="$2"; shift 2; exec python3 -m videomotival create --topic "$topic" --duration "$secs" "$@" ;;
  *)     exec python3 -m videomotival "$@" ;;
esac
