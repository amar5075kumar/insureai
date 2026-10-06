# Stage 1: export yolov8n.onnx (throw-away — only the 13 MB ONNX file is kept)
# NOTE: torch+CUDA (~2 GB) is downloaded here but NOT present in the final image.
# This stage runs once; subsequent builds use Docker layer cache.
# On networks blocking download.pytorch.org, torch installs from standard PyPI.
FROM python:3.12-slim AS model-exporter
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libxcb1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir ultralytics
WORKDIR /export
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx', imgsz=640)"

# Stage 2: lean runtime — no PyTorch, no CUDA (~300 MB total)
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir uv && uv pip install --system --no-cache -r requirements.txt

# Copy ONNX model from exporter stage
RUN mkdir -p /app/models
COPY --from=model-exporter /export/yolov8n.onnx /app/models/yolov8n.onnx

COPY . .

CMD ["python", "vision_worker.py"]
