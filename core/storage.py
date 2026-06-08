from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Optional

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_PUBLIC_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PUBLIC_IMAGE_DIMENSION = 2200
IMAGE_OUTPUT_FORMAT = 'WEBP'
IMAGE_OUTPUT_CONTENT_TYPE = 'image/webp'


@dataclass(frozen=True)
class SupabaseStorageConfig:
    url: str
    service_key: str


def _normalize_storage_path(path: str) -> str:
    normalized = PurePosixPath(path).as_posix().strip('/')
    if not normalized:
        raise ValueError('Storage path is required.')
    if any(part in ('', '.', '..') for part in normalized.split('/')):
        raise ValueError('Invalid storage path.')
    return normalized


def get_supabase_storage_config() -> Optional[SupabaseStorageConfig]:
    url = getattr(settings, 'SUPABASE_URL', '') or ''
    key = getattr(settings, 'SUPABASE_SERVICE_KEY', '') or ''
    if not url or not key:
        return None
    return SupabaseStorageConfig(url=url, service_key=key)


def get_supabase_client():
    """
    Lazily construct a Supabase client for server-side usage.
    Keep this import local so the app can boot without supabase installed
    in environments where storage is disabled.
    """
    cfg = get_supabase_storage_config()
    if cfg is None:
        raise RuntimeError("Supabase storage is not configured (SUPABASE_URL / SUPABASE_SERVICE_KEY).")

    from supabase import create_client  # local import by design
    return create_client(cfg.url, cfg.service_key)


def upload_bytes_public(bucket: str, path: str, content: bytes, content_type: str) -> str:
    """
    Upload content to a public bucket and return the public URL.

    Notes:
    - This uses the service role key (server-side only).
    - The bucket must already exist and be configured public in Supabase.
    """
    safe_path = _normalize_storage_path(path)
    client = get_supabase_client()
    client.storage.from_(bucket).upload(
        path=safe_path,
        file=content,
        file_options={
            'cache-control': '3600',
            'content-type': str(content_type),
            'upsert': 'true',
        },
    )
    return client.storage.from_(bucket).get_public_url(safe_path)


def upload_uploaded_file_public(bucket: str, path: str, uploaded_file) -> str:
    content_type = getattr(uploaded_file, 'content_type', None) or 'application/octet-stream'
    content = uploaded_file.read()
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    return upload_bytes_public(bucket=bucket, path=path, content=content, content_type=content_type)


def prepare_public_image(uploaded_file, *, max_bytes: int = MAX_PUBLIC_IMAGE_BYTES) -> bytes:
    """
    Validate an uploaded image and normalize it to a compact WebP payload.

    Safety rails:
    - enforce a server-side byte limit
    - verify the file is a real image with Pillow
    - constrain very large dimensions before encoding
    """
    if uploaded_file is None:
        raise ValueError('Image file is required.')

    size = getattr(uploaded_file, 'size', None)
    if size and size > max_bytes:
        raise ValueError('Image must be 5MB or smaller.')

    raw_bytes = uploaded_file.read()
    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    if not raw_bytes:
        raise ValueError('Uploaded image is empty.')
    if len(raw_bytes) > max_bytes:
        raise ValueError('Image must be 5MB or smaller.')

    try:
        with Image.open(BytesIO(raw_bytes)) as img:
            img.verify()
        with Image.open(BytesIO(raw_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            if img.width * img.height > 25_000_000:
                raise ValueError('Image resolution is too large.')
            if img.width > MAX_PUBLIC_IMAGE_DIMENSION or img.height > MAX_PUBLIC_IMAGE_DIMENSION:
                img.thumbnail((MAX_PUBLIC_IMAGE_DIMENSION, MAX_PUBLIC_IMAGE_DIMENSION))

            if img.mode not in ('RGB', 'RGBA'):
                if 'A' in img.getbands():
                    img = img.convert('RGBA')
                else:
                    img = img.convert('RGB')

            out = BytesIO()
            img.save(out, format=IMAGE_OUTPUT_FORMAT, quality=82, method=6)
            return out.getvalue()
    except UnidentifiedImageError as exc:
        raise ValueError('Only JPEG, PNG, or WebP images are allowed.') from exc


def upload_public_image(bucket: str, path: str, uploaded_file) -> str:
    image_bytes = prepare_public_image(uploaded_file)
    return upload_bytes_public(
        bucket=bucket,
        path=path,
        content=image_bytes,
        content_type=IMAGE_OUTPUT_CONTENT_TYPE,
    )

