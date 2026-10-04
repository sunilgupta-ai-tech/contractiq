from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
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
        if settings.aws_s3_endpoint_url:  # Phase 26: S3-compatible store (R2, MinIO)
            kwargs["endpoint_url"] = settings.aws_s3_endpoint_url
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id.get_secret_value()
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key.get_secret_value()
        self._client = boto3.client("s3", **kwargs)
        # Phase 24: SSE-KMS with a customer-managed key when one is configured,
        # otherwise S3-managed AES-256. Objects are always encrypted at rest.
        # S3-compatible stores encrypt at rest themselves and may refuse AWS's
        # encryption headers (R2 does), so none are sent to them.
        self.kms_key_id = (
            None if settings.aws_s3_endpoint_url else settings.aws_s3_kms_key_id or None
        )
        if settings.aws_s3_endpoint_url:
            self.sse: str | None = None
        else:
            self.sse = "aws:kms" if self.kms_key_id else "AES256"

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            **self._extra_args(content_type),
        )

    async def put_file(self, key: str, path: str, content_type: str) -> None:
        # upload_file streams from disk and switches to multipart upload
        # above 8 MB, so a 1 GB file never sits in memory.
        await asyncio.to_thread(
            self._client.upload_file,
            path,
            self.bucket,
            key,
            ExtraArgs=self._extra_args(content_type),
        )

    def _extra_args(self, content_type: str) -> dict[str, str]:
        args = {"ContentType": content_type}
        if self.sse:
            args["ServerSideEncryption"] = self.sse
        if self.kms_key_id:
            args["SSEKMSKeyId"] = self.kms_key_id
        return args

    async def get(self, key: str) -> bytes:
        try:
            obj = await asyncio.to_thread(self._client.get_object, Bucket=self.bucket, Key=key)
        except ClientError as exc:
            raise NotFoundError("Stored object not found.") from exc
        return await asyncio.to_thread(obj["Body"].read)

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        try:
            obj = await asyncio.to_thread(self._client.get_object, Bucket=self.bucket, Key=key)
        except ClientError as exc:
            raise NotFoundError("Stored object not found.") from exc
        body = obj["Body"]
        try:
            while chunk := await asyncio.to_thread(body.read, 1024 * 1024):
                yield chunk
        finally:
            body.close()

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    async def delete_prefix(self, prefix: str) -> None:
        if not prefix.strip("/"):
            raise ValueError("Refusing to delete the whole bucket")
        await asyncio.to_thread(self._delete_prefix_sync, prefix)

    def _delete_prefix_sync(self, prefix: str) -> None:
        # S3 has no folders: list every key under the prefix (paginated,
        # 1000 per page) and delete each page in one batch request.
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if objects:
                self._client.delete_objects(
                    Bucket=self.bucket, Delete={"Objects": objects, "Quiet": True}
                )

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False
