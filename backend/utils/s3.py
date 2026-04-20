"""
utils/s3.py — S3 / S3-compatible object storage helpers.

Works with:
  - AWS S3        (set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET_NAME)
  - Cloudflare R2 (set all of the above + S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com)
  - MinIO / any S3-compatible store (set S3_ENDPOINT_URL accordingly)

Environment variables:
  AWS_ACCESS_KEY_ID      – access key
  AWS_SECRET_ACCESS_KEY  – secret key
  AWS_REGION             – region (default: eu-west-2)
  S3_BUCKET_NAME         – bucket name
  S3_ENDPOINT_URL        – optional custom endpoint (for R2/MinIO)
  S3_PUBLIC_BASE_URL     – optional override for the public URL base
                           e.g. https://media.lminventories.co.uk
                           If not set, the standard AWS URL is used.
"""

import os
import uuid
import base64
import io
import logging
from functools import lru_cache
from botocore.config import Config

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

def is_configured() -> bool:
    """Return True if S3 credentials and bucket are present."""
    return bool(
        os.environ.get('AWS_ACCESS_KEY_ID')
        and os.environ.get('AWS_SECRET_ACCESS_KEY')
        and os.environ.get('S3_BUCKET_NAME')
    )


def get_bucket() -> str:
    return os.environ.get('S3_BUCKET_NAME', '')


def _public_base() -> str:
    """Return the base URL used to construct public photo URLs."""
    custom = os.environ.get('S3_PUBLIC_BASE_URL', '').rstrip('/')
    if custom:
        return custom
    endpoint = os.environ.get('S3_ENDPOINT_URL', '').rstrip('/')
    bucket   = get_bucket()
    if endpoint:
        return f"{endpoint}/{bucket}"
    region = os.environ.get('AWS_REGION', 'eu-west-2')
    return f"https://{bucket}.s3.{region}.amazonaws.com"


def public_url(key: str) -> str:
    """Construct the public HTTPS URL for an object key."""
    return f"{_public_base()}/{key.lstrip('/')}"


# ── Client factory ────────────────────────────────────────────────────────────

def _make_client():
    """Create a boto3 S3 client from environment variables."""
    import boto3
    endpoint = os.environ.get('S3_ENDPOINT_URL')
    # R2 and other S3-compatible stores use their own region names.
    # When a custom endpoint is set, default to 'auto' unless explicitly overridden.
    default_region = 'auto' if endpoint else 'eu-west-2'
    kwargs = dict(
        aws_access_key_id     = os.environ.get('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key = os.environ.get('AWS_SECRET_ACCESS_KEY'),
        region_name           = os.environ.get('AWS_REGION', default_region),
        config                = Config(signature_version='s3v4'),
    )
    if endpoint:
        kwargs['endpoint_url'] = endpoint
    return boto3.client('s3', **kwargs)


# ── Key helpers ───────────────────────────────────────────────────────────────

def new_key(prefix: str, ext: str = 'jpg') -> str:
    """Generate a collision-resistant object key under the given prefix."""
    return f"{prefix.strip('/')}/{uuid.uuid4().hex}.{ext}"


def is_s3_url(value: str) -> bool:
    """Return True if value is already an HTTPS URL (not a base64 data URI)."""
    return isinstance(value, str) and (
        value.startswith('https://') or value.startswith('http://')
    )


def is_base64_uri(value: str) -> bool:
    """Return True if value is a base64 data URI (data:image/...;base64,...)."""
    return isinstance(value, str) and value.startswith('data:')


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_bytes(data: bytes, key: str, content_type: str = 'image/jpeg') -> str:
    """
    Upload raw bytes to S3 and return the public URL.
    Raises RuntimeError if S3 is not configured.
    """
    if not is_configured():
        raise RuntimeError('S3 is not configured (missing env vars)')
    client = _make_client()
    client.put_object(
        Bucket      = get_bucket(),
        Key         = key,
        Body        = data,
        ContentType = content_type,
    )
    url = public_url(key)
    log.debug('[S3] uploaded %d bytes → %s', len(data), url)
    return url


def upload_base64(data_uri: str, key: str) -> str:
    """
    Decode a base64 data URI and upload it to S3.
    Returns the public URL.
    """
    if ',' not in data_uri:
        raise ValueError('Not a valid data URI')
    header, b64 = data_uri.split(',', 1)
    content_type = 'image/jpeg'
    if 'image/png' in header:
        content_type = 'image/png'
    elif 'image/webp' in header:
        content_type = 'image/webp'
    data = base64.b64decode(b64)
    return upload_bytes(data, key, content_type)


# ── Pre-signed URLs (for direct mobile → S3 upload) ──────────────────────────

def presign_put(key: str, content_type: str = 'image/jpeg', expires: int = 900) -> str:
    """
    Generate a pre-signed PUT URL so the mobile app can upload directly to S3
    without routing the binary data through the Flask server.

    expires: URL validity in seconds (default 15 minutes).
    """
    if not is_configured():
        raise RuntimeError('S3 is not configured')
    client = _make_client()
    return client.generate_presigned_url(
        'put_object',
        Params   = {'Bucket': get_bucket(), 'Key': key, 'ContentType': content_type},
        ExpiresIn = expires,
    )


def presign_get(key: str, expires: int = 3600) -> str:
    """Generate a pre-signed GET URL for a private object."""
    if not is_configured():
        raise RuntimeError('S3 is not configured')
    client = _make_client()
    return client.generate_presigned_url(
        'get_object',
        Params    = {'Bucket': get_bucket(), 'Key': key},
        ExpiresIn = expires,
    )


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_object(key: str):
    """Delete an object. Silent if it doesn't exist."""
    if not is_configured():
        return
    try:
        _make_client().delete_object(Bucket=get_bucket(), Key=key)
        log.debug('[S3] deleted %s', key)
    except Exception as e:
        log.warning('[S3] delete failed for %s: %s', key, e)
