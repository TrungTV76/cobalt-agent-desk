#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVER_PY="${REPO_ROOT}/server.py"
PID_FILE="${REPO_ROOT}/cobalt_desk.pid"
OUT_LOG="${REPO_ROOT}/cobalt_desk.log"
ERR_LOG="${REPO_ROOT}/cobalt_desk.err.log"

PORT=18780
REPO_PATH=""
DEMO=0
NO_BROWSER=0
BACKGROUND=0
ACTION="start"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --repo) REPO_PATH="$2"; shift 2 ;;
    --demo) DEMO=1; shift ;;
    --no-browser) NO_BROWSER=1; shift ;;
    --background) BACKGROUND=1; shift ;;
    --stop) ACTION="stop"; shift ;;
    --restart) ACTION="restart"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "Error: python3 (3.10+) not found in PATH." >&2
  exit 1
fi

stop_instance() {
  if [[ -f "${PID_FILE}" ]]; then
    local saved_pid
    saved_pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [[ "${saved_pid}" =~ ^[0-9]+$ ]] && kill -0 "${saved_pid}" 2>/dev/null; then
      kill "${saved_pid}" 2>/dev/null || true
    fi
    rm -f "${PID_FILE}"
  fi
}

open_url() {
  local target_url="$1"
  [[ "${NO_BROWSER}" -eq 1 ]] && return 0
  if [[ "$(uname -s)" == "Darwin" ]]; then
    open "${target_url}" >/dev/null 2>&1 || true
  elif [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]] && command -v xdg-open >/dev/null 2>&1; then
    xdg-open "${target_url}" >/dev/null 2>&1 || true
  fi
}

if [[ "${ACTION}" == "stop" ]]; then
  stop_instance
  echo "[Cobalt Agent Desk] Stopped instance."
  exit 0
fi

if [[ "${ACTION}" == "restart" ]]; then
  stop_instance
  sleep 0.3
fi

export PYTHONUTF8=1
ARGS=("${SERVER_PY}" "--port" "${PORT}")
[[ "${DEMO}" -eq 1 ]] && ARGS+=("--demo")
[[ -n "${REPO_PATH}" ]] && ARGS+=("--repo" "${REPO_PATH}")

if [[ "${BACKGROUND}" -eq 1 ]]; then
  rm -f "${OUT_LOG}" "${ERR_LOG}"
  nohup "${PYTHON_BIN}" "${ARGS[@]}" >"${OUT_LOG}" 2>"${ERR_LOG}" &
  BG_PID=$!
  echo "${BG_PID}" > "${PID_FILE}"
  sleep 0.6
  ACTUAL_URL="http://127.0.0.1:${PORT}"
  if [[ -f "${OUT_LOG}" ]]; then
    PARSED_URL="$(grep -Eo 'http://127\.0\.0\.1:[0-9]+' "${OUT_LOG}" | head -n 1 || true)"
    [[ -n "${PARSED_URL}" ]] && ACTUAL_URL="${PARSED_URL}"
  fi
  echo "[Cobalt Agent Desk] Started in background (PID=${BG_PID}) -> ${ACTUAL_URL}"
  open_url "${ACTUAL_URL}"
  exit 0
fi

if [[ "${NO_BROWSER}" -eq 0 ]]; then
  if [[ "$(uname -s)" == "Darwin" || -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
    ARGS+=("--open-browser")
  fi
fi

exec "${PYTHON_BIN}" "${ARGS[@]}"
