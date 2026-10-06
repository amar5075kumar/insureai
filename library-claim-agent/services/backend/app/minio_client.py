"""
MinIO (S3-compatible) client for the backend service.
Provides async upload/download helpers.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)

_session = aioboto3.Session()


@asynccontextmanager
async def get_s3() -> AsyncIterator:
    """Async S3 client context manager."""
    async with _session.client(
        "s3",
        endpoint_url=settings.minio_endpoint_url,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    ) as client:
        yield client


async def upload_bytes(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload bytes to MinIO. Returns the object key."""
    async with get_s3() as s3:
        await s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    return key


async def download_bytes(bucket: str, key: str) -> bytes | None:
    """Download object from MinIO. Returns None if not found."""
    async with get_s3() as s3:
        try:
            resp = await s3.get_object(Bucket=bucket, Key=key)
            return await resp["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise


async def object_exists(bucket: str, key: str) -> bool:
    """Check if an object exists without downloading it."""
    async with get_s3() as s3:
        try:
            await s3.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False


async def ensure_buckets() -> None:
    """Create required buckets if they don't exist. Called at startup."""
    async with get_s3() as s3:
        for bucket in [settings.frames_bucket, settings.packets_bucket]:
            try:
                await s3.head_bucket(Bucket=bucket)
                logger.debug(f"Bucket '{bucket}' exists")
            except ClientError:
                await s3.create_bucket(Bucket=bucket)
                logger.info(f"Created bucket '{bucket}'")
