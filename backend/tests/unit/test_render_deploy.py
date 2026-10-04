"""Phase 26: S3-compatible storage (Cloudflare R2) and worker concurrency."""

from app.core.config import Settings
from app.storage.s3 import S3ObjectStorage


def settings(**overrides) -> Settings:
    base = {
        "storage_backend": "s3",
        "aws_s3_bucket": "docunexa-files",
        "aws_region": "auto",
        "aws_access_key_id": "test-key",
        "aws_secret_access_key": "test-secret",
    }
    return Settings(**{**base, **overrides})


def test_aws_s3_keeps_server_side_encryption():
    store = S3ObjectStorage(settings(aws_region="ap-south-1"))
    assert store._extra_args("application/pdf") == {
        "ContentType": "application/pdf",
        "ServerSideEncryption": "AES256",
    }


def test_an_s3_compatible_endpoint_is_used_without_aws_encryption_headers():
    endpoint = "https://account-id.r2.cloudflarestorage.com"
    store = S3ObjectStorage(settings(aws_s3_endpoint_url=endpoint, aws_s3_kms_key_id="kms-1"))
    assert store._client.meta.endpoint_url == endpoint
    assert store._extra_args("image/png") == {"ContentType": "image/png"}


def test_worker_concurrency_is_a_setting():
    assert Settings().worker_max_jobs == 4
    assert Settings(worker_max_jobs=1).worker_max_jobs == 1
