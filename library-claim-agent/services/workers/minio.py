"""
MinIO access for Celery workers (synchronous, boto3-based).
Workers cannot use the async aioboto3 client from the backend.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import boto3
import numpy as np
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
FRAMES_BUCKET = "sweep-frames"


def _get_client():
    return boto3.client(
        "s3",
        endpoint_url=f"http://{MINIO_ENDPOINT}",
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def load_crop_from_minio(s3_key: str) -> Optional[np.ndarray]:
    """
    Download a JPEG crop from MinIO and decode to BGR numpy array.
    Returns None if the object doesn't exist or decoding fails.
    """
    import cv2

    try:
        client = _get_client()
        resp = client.get_object(Bucket=FRAMES_BUCKET, Key=s3_key)
        data = resp["Body"].read()
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            logger.warning(f"cv2 could not decode image: {s3_key}")
        return img
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            logger.warning(f"Crop not found in MinIO: {s3_key}")
            return None
        raise
    except Exception as e:
        logger.error(f"Failed to load crop {s3_key}: {e}")
        return None


def load_frame_from_minio(s3_key: str) -> Optional[np.ndarray]:
    """Load a full frame (same as crop — kept separate for clarity)."""
    return load_crop_from_minio(s3_key)


def object_exists(s3_key: str, bucket: str = FRAMES_BUCKET) -> bool:
    """Check if an object exists in MinIO without downloading it."""
    try:
        _get_client().head_object(Bucket=bucket, Key=s3_key)
        return True
    except ClientError:
        return False
