"""S3-compatible object storage (MinIO in docker compose)."""
import logging
import time

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import settings

log = logging.getLogger(__name__)
_client = None


def client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name="us-east-1",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
    return _client


def ensure_bucket(retries: int = 30) -> None:
    """Create the bucket if missing; retries while object storage is still starting."""
    for attempt in range(retries):
        try:
            client().head_bucket(Bucket=settings.s3_bucket)
            return
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchBucket", "NotFound"):
                client().create_bucket(Bucket=settings.s3_bucket)
                log.info("created bucket %s", settings.s3_bucket)
                return
            last = e
        except Exception as e:  # connection refused while minio boots
            last = e
        time.sleep(1)
    raise RuntimeError(f"object storage unavailable: {last}")


def put(key: str, data: bytes, content_type: str) -> None:
    client().put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)


def get(key: str) -> bytes | None:
    try:
        return client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise


def exists(key: str) -> bool:
    try:
        client().head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except ClientError:
        return False


def delete(key: str) -> None:
    client().delete_object(Bucket=settings.s3_bucket, Key=key)


def book_pdf_key(user_id, book_id) -> str:
    return f"{user_id}/{book_id}.pdf"


def book_file_key(user_id, book_id, source_format: str | None) -> str:
    """The uploaded original: PDFs keep their historical key (GET /api/books/{id}/pdf), other formats `.source`."""
    return book_pdf_key(user_id, book_id) if source_format in (None, "pdf") else f"{user_id}/{book_id}.source"
