"""
Application configuration loaded from environment variables.
All settings have sensible defaults for local development.
No secrets have defaults — they must be set in .env.
"""
from __future__ import annotations

import os
import sys

# Allow importing config/ from the repo root when running inside Docker
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from config.sweep_profiles import ProfileConfig, get_profile  # noqa: E402


class Settings:
    # ── Core ─────────────────────────────────────────────────────────
    sweep_profile: str = os.environ.get("SWEEP_PROFILE", "standard")
    debug: bool = os.environ.get("DEBUG", "false").lower() == "true"

    # ── Database ─────────────────────────────────────────────────────
    database_url: str = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://claim_user:dev_password@localhost:5432/library_claim"
    )

    # ── Redis ────────────────────────────────────────────────────────
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # ── MinIO / S3 ───────────────────────────────────────────────────
    minio_endpoint: str = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
    minio_access_key: str = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key: str = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    minio_use_ssl: bool = os.environ.get("MINIO_USE_SSL", "false").lower() == "true"
    frames_bucket: str = "sweep-frames"
    packets_bucket: str = "claim-packets"

    # ── LiveKit ──────────────────────────────────────────────────────
    livekit_url: str = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
    livekit_api_key: str = os.environ.get("LIVEKIT_API_KEY", "devkey")
    livekit_api_secret: str = os.environ.get("LIVEKIT_API_SECRET", "devsecret_32_chars_min")

    # ── LLM providers ────────────────────────────────────────────────
    ollama_url: str = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")

    # ── CORS ─────────────────────────────────────────────────────────
    cors_origins: list[str] = [
        o.strip()
        for o in os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:3000,http://localhost:5173,http://localhost:4173"
        ).split(",")
        if o.strip()
    ]

    @property
    def profile(self) -> ProfileConfig:
        """Active sweep profile — computed once, cached for life of the process."""
        if not hasattr(self, "_profile"):
            object.__setattr__(self, "_profile", get_profile())
        return self._profile  # type: ignore[attr-defined]

    frames_dir: str = os.environ.get("FRAMES_DIR", "/app/frame_data")
    frames_storage: str = os.environ.get("FRAMES_STORAGE", "filesystem")

    @property
    def minio_endpoint_url(self) -> str:
        scheme = "https" if self.minio_use_ssl else "http"
        return f"{scheme}://{self.minio_endpoint}"


# Module-level singleton
settings = Settings()
