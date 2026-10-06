#!/usr/bin/env bash
# Build the minimal local dev stack for CozmoAI Library Claim Agent.
#
# Builds (in order): postgres, redis, backend, agents, vision, frontend
# Skips:             livekit, worker-book-id, worker-pricing, worker-measurement
#
# Usage:
#   ./scripts/build-local.sh           # normal build
#   ./scripts/build-local.sh --no-cache  # force full rebuild

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
BUILD_SERVICES=(postgres redis backend agents vision worker-lite frontend)
SKIP_SERVICES=(livekit worker-book-id worker-pricing worker-measurement)
BASE_IMAGE="python:3.12-slim"
PULL_ATTEMPTS=3
PULL_SLEEP=5

# ── Colors ────────────────────────────────────────────────────────────────────
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
  BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
  RED="" GREEN="" YELLOW="" BLUE="" BOLD="" RESET=""
fi

info()    { printf '%s→  %s%s\n' "${YELLOW}" "$*" "${RESET}"; }
success() { printf '%s✓  %s%s\n' "${GREEN}"  "$*" "${RESET}"; }
fail()    { printf '%s✗  %s%s\n' "${RED}"    "$*" "${RESET}" >&2; }
section() { printf '\n%s══ %s ══%s\n' "${BLUE}" "$*" "${RESET}"; }

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd -- "${PROJECT_DIR}"

# ── Args ──────────────────────────────────────────────────────────────────────
NO_CACHE=""
[[ "${1:-}" == "--no-cache" ]] && NO_CACHE="--no-cache"

export COMPOSE_PROJECT_NAME=library-claim-agent
export DOCKER_BUILDKIT=1

# ── Preflight ─────────────────────────────────────────────────────────────────
section "Pre-flight"

command -v docker >/dev/null || { fail "docker not found"; exit 1; }
docker compose version >/dev/null 2>&1 || { fail "docker compose v2 not found"; exit 1; }
docker info >/dev/null 2>&1 || { fail "Docker daemon not running"; exit 1; }
[[ -f docker-compose.yml ]] || { fail "docker-compose.yml not found in ${PROJECT_DIR}"; exit 1; }
[[ -f .env ]] || info "WARNING: .env not found — runtime will likely fail"

printf '  Project dir: %s\n' "${PROJECT_DIR}"
printf '  Skipping:    %s\n' "${SKIP_SERVICES[*]}"
[[ -n "${NO_CACHE}" ]] && printf '  Mode:        --no-cache\n'

# ── Pull base image ───────────────────────────────────────────────────────────
section "Base image"
info "Pulling ${BASE_IMAGE} (needed by backend, agents, vision)..."

pulled=false
for (( i = 1; i <= PULL_ATTEMPTS; i++ )); do
  if docker pull "${BASE_IMAGE}"; then
    pulled=true
    break
  fi
  if (( i < PULL_ATTEMPTS )); then
    info "Attempt ${i}/${PULL_ATTEMPTS} failed — retrying in ${PULL_SLEEP}s..."
    sleep "${PULL_SLEEP}"
  fi
done
"${pulled}" || { fail "Could not pull ${BASE_IMAGE} after ${PULL_ATTEMPTS} attempts"; exit 1; }
success "Base image ready"

# ── Build each service ────────────────────────────────────────────────────────
section "Building services"

declare -A BUILD_TIMES
TOTAL_START=$(date +%s)

for svc in "${BUILD_SERVICES[@]}"; do
  info "Building ${svc}..."
  t0=$(date +%s)

  if docker compose build ${NO_CACHE} "${svc}" 2>&1; then
    elapsed=$(( $(date +%s) - t0 ))
    BUILD_TIMES["${svc}"]="${elapsed}"
    success "${svc} — ${elapsed}s"
  else
    elapsed=$(( $(date +%s) - t0 ))
    fail "${svc} FAILED after ${elapsed}s"
    exit 1
  fi
done

TOTAL=$(( $(date +%s) - TOTAL_START ))

# ── Summary ───────────────────────────────────────────────────────────────────
section "Summary"

printf '\n%sBuild times:%s\n' "${BOLD}" "${RESET}"
for svc in "${BUILD_SERVICES[@]}"; do
  t="${BUILD_TIMES[${svc}]:-?}"
  printf '  %s✓%s  %-14s %ss\n' "${GREEN}" "${RESET}" "${svc}" "${t}"
done
printf '  %s%-14s %ss%s\n' "${BOLD}" "TOTAL" "${TOTAL}" "${RESET}"

printf '\n%sImages:%s\n' "${BOLD}" "${RESET}"
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" \
  | grep -E "REPOSITORY|library-claim-agent-(postgres|redis|backend|agents|vision|frontend)" \
  || true

printf '\n%s✓ Done! To start the stack:%s\n' "${GREEN}" "${RESET}"
printf '  docker compose -f docker-compose.local.yml up -d\n'
printf '  open http://localhost:3000\n\n'
