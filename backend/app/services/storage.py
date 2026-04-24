"""Thin boto3 S3 wrapper. Async is cooperative only — boto3 is sync; we
run calls in the default executor so they don't block the event loop."""
import asyncio

import boto3
from botocore.exceptions import ClientError

from app.config import get_settings


class Storage:
    def __init__(self) -> None:
        s = get_settings()
        self._bucket = s.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url or None,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key or None,
            aws_secret_access_key=s.s3_secret_key or None,
        )

    async def _run(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    async def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        await self._run(
            self._client.put_object,
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type,
        )

    async def get_object(self, key: str) -> bytes:
        try:
            r = await self._run(self._client.get_object, Bucket=self._bucket, Key=key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                raise KeyError(key) from e
            raise
        return r["Body"].read()

    async def delete_object(self, key: str) -> None:
        await self._run(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def presigned_get(self, key: str, expires: int = 3600) -> str:
        return await self._run(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires,
        )
