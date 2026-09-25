from __future__ import annotations

import asyncio
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.core.config import Settings
from app.core.exceptions import NotFoundError


class S3ObjectStorage:
    """S3 storage for staging/production.

    In ECS, leave AWS_ACCESS_KEY_ID empty so boto3 uses the task IAM role —
    no long-lived keys in the environment. Objects are written with SSE.
    """

    def __init__(self, settings: Settings) -> None:
        assert settings.aws_s3_bucket, "AWS_S3_BUCKET is required for S3 storage"
        self.bucket = settings.aws_s3_bucket
        kwargs: dict[str, Any] = {"region_name": settings.aws_region}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id.get_secret_value()
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key.get_secret_value()
        self._client = boto3.client("s3", **kwargs)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )

    async def get(self, key: str) -> bytes:
        try:
            obj = await asyncio.to_thread(self._client.get_object, Bucket=self.bucket, Key=key)
        except ClientError as exc:
            raise NotFoundError("Stored object not found.") from exc
        return await asyncio.to_thread(obj["Body"].read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False
