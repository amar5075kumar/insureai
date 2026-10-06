"""
YOLOv8 object detection using ONNX Runtime (no PyTorch / no CUDA required).

BookDetector: detects book spines in a frame.
ItemDetector: detects non-book room contents.

Both use the yolov8n.onnx model (6 MB, COCO pretrained).
If a fine-tuned ONNX model exists at /app/models/yolo/yolov8m-books.onnx it is preferred.

Preprocessing: letterbox resize to 640×640, RGB, float32 [0,1].
Postprocessing: decode [1,84,8400] YOLOv8 output → NMS → original coords.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_COCO_BOOK_CLASS = 73

_LIBRARY_ITEM_CLASSES = {
    57: "sofa",
    56: "chair",
    58: "potted_plant",
    62: "tv",
    63: "laptop",
    67: "cell_phone",
    74: "clock",
    75: "vase",
    60: "dining_table",
    59: "bed",
    65: "remote",
    79: "keyboard",
    66: "scissors",
}

_MODEL_SIZE = 640


@dataclass
class SpineDetection:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    bbox_width: float
    bbox_height: float

    @property
    def area(self) -> float:
        return self.bbox_width * self.bbox_height

    @property
    def aspect_ratio(self) -> float:
        return self.bbox_height / max(self.bbox_width, 1.0)


@dataclass
class ItemDetection:
    x1: float
    y1: float
    x2: float
    y2: float
    category: str
    confidence: float


def _preprocess(frame: np.ndarray) -> Tuple[np.ndarray, float]:
    """
    Letterbox-resize to 640×640, convert BGR→RGB, normalise to [0,1].
    Returns (tensor [1,3,640,640], scale_factor).
    Padding is added to bottom/right only so offset is always (0,0).
    """
    h, w = frame.shape[:2]
    scale = _MODEL_SIZE / max(h, w)
    nh, nw = int(h * scale), int(w * scale)
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.zeros((_MODEL_SIZE, _MODEL_SIZE, 3), dtype=np.uint8)
    canvas[:nh, :nw] = resized
    rgb = canvas[:, :, ::-1].astype(np.float32) / 255.0
    tensor = rgb.transpose(2, 0, 1)[np.newaxis]  # [1,3,H,W]
    return tensor, scale


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float = 0.45) -> List[int]:
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: List[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= iou_thr]
    return keep


def _postprocess(
    output: np.ndarray,
    scale: float,
    orig_hw: Tuple[int, int],
    conf_thr: float,
    iou_thr: float = 0.45,
) -> List[Tuple[float, float, float, float, int, float]]:
    """
    Decode YOLOv8 output [1, 84, 8400].
    Returns list of (x1, y1, x2, y2, class_id, confidence) in original frame coords.
    """
    pred = output[0]          # [84, 8400]
    cxcywh = pred[:4].T       # [8400, 4]
    class_scores = pred[4:].T # [8400, 80]

    class_ids = class_scores.argmax(axis=1)
    confidences = class_scores.max(axis=1)

    mask = confidences >= conf_thr
    if not mask.any():
        return []

    cxcywh = cxcywh[mask]
    class_ids = class_ids[mask]
    confidences = confidences[mask]

    cx, cy, w, h = cxcywh[:, 0], cxcywh[:, 1], cxcywh[:, 2], cxcywh[:, 3]
    x1 = cx - w / 2
    y1 = cy - h / 2
    x2 = cx + w / 2
    y2 = cy + h / 2
    boxes = np.stack([x1, y1, x2, y2], axis=1)

    keep = _nms(boxes, confidences, iou_thr)
    boxes = boxes[keep]
    class_ids = class_ids[keep]
    confidences = confidences[keep]

    oh, ow = orig_hw
    results = []
    for (bx1, by1, bx2, by2), cls, conf in zip(boxes, class_ids, confidences):
        bx1 = float(max(0.0, bx1 / scale))
        by1 = float(max(0.0, by1 / scale))
        bx2 = float(min(ow, bx2 / scale))
        by2 = float(min(oh, by2 / scale))
        results.append((bx1, by1, bx2, by2, int(cls), float(conf)))
    return results


def _load_session(model_path: str):
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.inter_op_num_threads = 2
    opts.intra_op_num_threads = 2
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(model_path, sess_options=opts, providers=["CPUExecutionProvider"])


class BookDetector:
    def __init__(self) -> None:
        fine_tuned = "/app/models/yolo/yolov8m-books.onnx"
        default = "/app/models/yolov8n.onnx"

        if os.path.exists(fine_tuned):
            model_path = fine_tuned
            self._fine_tuned = True
        elif os.path.exists(default):
            model_path = default
            self._fine_tuned = False
        else:
            raise FileNotFoundError(
                f"No ONNX model found at {default} or {fine_tuned}. "
                "Rebuild the vision image to regenerate it."
            )

        self._session = _load_session(model_path)
        self._input_name = self._session.get_inputs()[0].name
        logger.info(f"BookDetector loaded: {model_path} (ONNX/CPU)")

    def detect(self, frame: np.ndarray, min_conf: float = 0.25) -> List[SpineDetection]:
        tensor, scale = _preprocess(frame)
        output = self._session.run(None, {self._input_name: tensor})[0]
        detections = _postprocess(output, scale, frame.shape[:2], min_conf)

        spines: List[SpineDetection] = []
        for x1, y1, x2, y2, cls, conf in detections:
            w, h = x2 - x1, y2 - y1
            if self._fine_tuned:
                if cls != 0:
                    continue
            else:
                if cls != _COCO_BOOK_CLASS:
                    continue
                # Books standing on a shelf: taller than wide (aspect > 1.2).
                # Original threshold was 2.5 (spine-only) but real shelf books
                # photographed straight-on have ratios of 1.5–2.0.
                if h / max(w, 1.0) < 1.2:
                    continue
            spines.append(SpineDetection(x1=x1, y1=y1, x2=x2, y2=y2, confidence=conf, bbox_width=w, bbox_height=h))

        return sorted(spines, key=lambda s: s.x1)


class ItemDetector:
    def __init__(self) -> None:
        default = "/app/models/yolov8n.onnx"
        if not os.path.exists(default):
            raise FileNotFoundError(
                f"No ONNX model found at {default}. Rebuild the vision image."
            )
        self._session = _load_session(default)
        self._input_name = self._session.get_inputs()[0].name
        logger.info(f"ItemDetector loaded: {default} (ONNX/CPU)")

    def detect(self, frame: np.ndarray, min_conf: float = 0.45) -> List[ItemDetection]:
        tensor, scale = _preprocess(frame)
        output = self._session.run(None, {self._input_name: tensor})[0]
        detections = _postprocess(output, scale, frame.shape[:2], min_conf)

        items: List[ItemDetection] = []
        seen: set[str] = set()
        for x1, y1, x2, y2, cls, conf in detections:
            if cls in (_COCO_BOOK_CLASS, 0):
                continue
            if cls not in _LIBRARY_ITEM_CLASSES:
                continue
            category = _LIBRARY_ITEM_CLASSES[cls]
            if category in seen:
                continue
            seen.add(category)
            items.append(ItemDetection(x1=x1, y1=y1, x2=x2, y2=y2, category=category, confidence=conf))

        return items
