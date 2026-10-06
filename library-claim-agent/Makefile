.PHONY: setup pull build start stop clean clean-all reset \
        logs test test-unit fixtures health

# ── Project name (scopes all docker compose resources) ────────────────────────
PROJECT = library-claim-agent

# ── Base images required by Dockerfiles ───────────────────────────────────────
BASE_IMAGES = postgres:16-alpine redis:7-alpine livekit/livekit-server:latest \
              python:3.12-slim node:20-alpine nginx:alpine

# ── Detect docker compose command ─────────────────────────────────────────────
DC := $(shell \
    if docker compose version >/dev/null 2>&1; then echo "docker compose"; \
    elif command -v docker-compose >/dev/null 2>&1; then echo "docker-compose"; \
    else echo "MISSING"; fi)

# ═════════════════════════════════════════════════════════════════════════════
# MAIN WORKFLOW: make setup  (pull → build → start)
# ═════════════════════════════════════════════════════════════════════════════

# ── LOCAL DEV (7 services, no GPU, no LiveKit) ────────────────────────────────

local-up: _check
	@echo "→ Building + starting local 7-service stack..."
	@bash scripts/build-local.sh
	@$(DC) -f docker-compose.local.yml up -d
	@echo ""
	@echo "✓ Local stack running!"
	@echo "  App:  http://localhost:3000"
	@echo "  API:  http://localhost:8000/health"
	@echo "  Logs: make local-logs"
	@echo "  Stop: make local-down"

local-down:
	@$(DC) -f docker-compose.local.yml down

local-logs:
	@$(DC) -f docker-compose.local.yml logs -f --tail=100

local-restart: local-down local-up

local-health:
	@echo "Local stack health:"
	@curl -sf http://localhost:8000/health 2>/dev/null && echo "  ✓ backend" || echo "  ✗ backend"
	@$(DC) -f docker-compose.local.yml exec -T postgres pg_isready -q 2>/dev/null && echo "  ✓ postgres" || echo "  ✗ postgres"
	@$(DC) -f docker-compose.local.yml exec -T redis redis-cli ping 2>/dev/null | grep -q PONG && echo "  ✓ redis" || echo "  ✗ redis"
	@curl -sf http://localhost:3000 >/dev/null 2>/dev/null && echo "  ✓ frontend" || echo "  ✗ frontend"

# ── FULL PRODUCTION SETUP (10 services, GPU-ready) ───────────────────────────

setup: _check pull build _start-infra _start-all
	@echo ""
	@echo "✓ Setup complete!"
	@echo "  App:  http://localhost:3000"
	@echo "  API:  http://localhost:8000/health"

# ═════════════════════════════════════════════════════════════════════════════
# PULL: Download base images (handles flaky WSL2 networks with curl fallback)
# ═════════════════════════════════════════════════════════════════════════════

pull:
	@echo "→ Pulling base images..."
	@for img in $(BASE_IMAGES); do \
		bash scripts/pull_image.sh "$$img" || exit 1; \
	done
	@echo "✓ All base images ready"

# ═════════════════════════════════════════════════════════════════════════════
# BUILD: Build all service images from local Dockerfiles (no network needed)
# ═════════════════════════════════════════════════════════════════════════════

build:
	@echo "→ Building service images (offline, uses cached base images)..."
	@$(DC) build --parallel
	@echo "✓ All services built"

# ═════════════════════════════════════════════════════════════════════════════
# START / STOP
# ═════════════════════════════════════════════════════════════════════════════

start:
	$(DC) up -d

stop:
	$(DC) down

restart: stop start

# ═════════════════════════════════════════════════════════════════════════════
# CLEAN: Remove everything to free disk space
# ═════════════════════════════════════════════════════════════════════════════

clean:
	@echo "→ Stopping this project's services..."
	@$(DC) -p $(PROJECT) down --volumes --remove-orphans 2>/dev/null || true
	@echo "→ Removing this project's built images only..."
	@docker images --filter "reference=$(PROJECT)-*" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
	@docker images --filter "reference=$(PROJECT)_*" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
	@echo "✓ Project images + volumes removed (other projects untouched)"
	@echo "  Base images kept for fast rebuild"
	@echo "  Run 'make clean-all' to also remove base images"

clean-all: clean
	@echo "→ Removing base images used by this project..."
	@for img in $(BASE_IMAGES); do \
		echo "  removing $$img"; \
		docker rmi "$$img" 2>/dev/null || true; \
	done
	@echo "✓ All project images removed. Other projects untouched."
	@echo "  Run 'make setup' to rebuild from scratch."

# ═════════════════════════════════════════════════════════════════════════════
# TESTING
# ═════════════════════════════════════════════════════════════════════════════

fixtures:
	@python3 tests/create_fixtures.py 2>/dev/null || echo "(fixtures script not ready yet)"

test-unit: fixtures
	@python3 -m pytest tests/unit/ -v --tb=short

test: test-unit

# ═════════════════════════════════════════════════════════════════════════════
# LOGGING / DEBUGGING
# ═════════════════════════════════════════════════════════════════════════════

logs:
	$(DC) logs -f --tail=100

logs-backend:
	$(DC) logs -f backend agents

logs-workers:
	$(DC) logs -f worker-book-id worker-pricing worker-measurement

health:
	@echo "Service health:"
	@curl -sf http://localhost:8000/health 2>/dev/null && echo "  ✓ backend" || echo "  ✗ backend"
	@$(DC) exec -T postgres pg_isready -q 2>/dev/null && echo "  ✓ postgres" || echo "  ✗ postgres"
	@$(DC) exec -T redis redis-cli ping 2>/dev/null | grep -q PONG && echo "  ✓ redis" || echo "  ✗ redis"
	@curl -sf http://localhost:3000 >/dev/null 2>/dev/null && echo "  ✓ frontend" || echo "  ✗ frontend"

shell:
	$(DC) exec backend bash

shell-db:
	$(DC) exec postgres psql -U $${POSTGRES_USER:-claim_user} $${POSTGRES_DB:-library_claim}

# ═════════════════════════════════════════════════════════════════════════════
# DISK USAGE
# ═════════════════════════════════════════════════════════════════════════════

disk:
	@echo "Docker disk usage:"
	@docker system df
	@echo ""
	@echo "Images:"
	@docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | head -20

# ═════════════════════════════════════════════════════════════════════════════
# INTERNAL TARGETS
# ═════════════════════════════════════════════════════════════════════════════

_check:
	@command -v docker >/dev/null 2>&1 || (echo "ERROR: Docker not found" && exit 1)
	@[ "$(DC)" != "MISSING" ] || (echo "ERROR: Docker Compose not found" && exit 1)
	@test -f .env || (cp .env.example .env && echo "→ .env created — edit ANTHROPIC_API_KEY before first sweep")

_start-infra:
	@echo "→ Starting infrastructure..."
	@$(DC) up -d postgres redis livekit
	@echo "  Waiting for health checks..."
	@sleep 6

_start-all:
	@echo "→ Starting all services..."
	@$(DC) up -d
