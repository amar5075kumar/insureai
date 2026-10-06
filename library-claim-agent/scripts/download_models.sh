#!/usr/bin/env bash
# Download all required model weights.
# Run via: make pull-models   OR   bash scripts/download_models.sh
# Models are placed in ./models/ (gitignored).
set -euo pipefail

MODELS_DIR="$(cd "$(dirname "$0")/.." && pwd)/models"
echo "→ Models directory: $MODELS_DIR"

mkdir -p \
    "$MODELS_DIR/whisper" \
    "$MODELS_DIR/yolo" \
    "$MODELS_DIR/depth_anything" \
    "$MODELS_DIR/realesrgan" \
    "$MODELS_DIR/sam2"

# ── Whisper (downloaded by faster-whisper on first use) ──────────────────────
echo "→ Pre-caching Whisper medium..."
docker compose exec -T backend python -c "
from faster_whisper import WhisperModel
print('  Checking Whisper medium...')
WhisperModel('medium', download_root='/app/models/whisper', device='cpu', compute_type='int8')
print('  ✓ Whisper medium ready')
" 2>/dev/null || echo "  (backend not ready — Whisper downloads on first use)"

# ── YOLOv8m ──────────────────────────────────────────────────────────────────
YOLO_PATH="$MODELS_DIR/yolo/yolov8m.pt"
if [ ! -f "$YOLO_PATH" ]; then
    echo "→ Downloading YOLOv8m (52MB)..."
    curl -L --progress-bar -o "$YOLO_PATH" \
        "https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8m.pt"
    echo "  ✓ YOLOv8m"
else
    echo "  ✓ YOLOv8m already downloaded"
fi

# ── Depth Anything v2 ViT-L metric indoor (1.3GB) ────────────────────────────
DEPTH_PATH="$MODELS_DIR/depth_anything/depth_anything_v2_metric_indoor_vitl.pth"
if [ ! -f "$DEPTH_PATH" ]; then
    echo "→ Downloading Depth Anything v2 ViT-L (1.3GB — this may take a few minutes)..."
    curl -L --progress-bar -o "$DEPTH_PATH" \
        "https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-Indoor-Large/resolve/main/depth_anything_v2_metric_indoor_vitl.pth"
    echo "  ✓ Depth Anything v2 ViT-L"
else
    echo "  ✓ Depth Anything v2 ViT-L already downloaded"
fi

# ── Real-ESRGAN x4plus (65MB) ────────────────────────────────────────────────
SR_PATH="$MODELS_DIR/realesrgan/RealESRGAN_x4plus.pth"
if [ ! -f "$SR_PATH" ]; then
    echo "→ Downloading Real-ESRGAN x4plus (65MB)..."
    curl -L --progress-bar -o "$SR_PATH" \
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
    echo "  ✓ Real-ESRGAN"
else
    echo "  ✓ Real-ESRGAN already downloaded"
fi

# ── SAM2 hiera-base+ (300MB) ─────────────────────────────────────────────────
SAM2_PATH="$MODELS_DIR/sam2/sam2_hiera_base_plus.pt"
if [ ! -f "$SAM2_PATH" ]; then
    echo "→ Downloading SAM2 hiera-base+ (300MB)..."
    curl -L --progress-bar -o "$SAM2_PATH" \
        "https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_base_plus.pt"
    echo "  ✓ SAM2"
else
    echo "  ✓ SAM2 already downloaded"
fi

# ── Ollama LLaMA 3.1 8B ──────────────────────────────────────────────────────
echo "→ Pulling Ollama LLaMA 3.1 8B (4.7GB)..."
docker compose exec -T ollama ollama pull llama3.1:8b 2>/dev/null \
    || echo "  (Ollama not ready — run: docker compose exec ollama ollama pull llama3.1:8b)"

echo ""
echo "✓ Model downloads complete!"
echo "  Sizes:"
du -sh "$MODELS_DIR"/*/  2>/dev/null | sort -h || true
