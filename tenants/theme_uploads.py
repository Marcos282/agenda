from io import BytesIO
from uuid import uuid4
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage


def theme_storage():
    # Served only through the tenant-scoped endpoint, never MEDIA_URL.
    return FileSystemStorage(location=Path(settings.BASE_DIR) / 'private-theme-media')


def theme_upload_path(instance, filename):
    return f'tenants/{instance.tenant_id}/{uuid4().hex}.webp'


def optimize_image(upload, *, keep_transparency=False, max_size=1920):
    if upload.size > 5 * 1024 * 1024:
        raise ValidationError('A imagem deve ter no máximo 5 MB.')
    try:
        with Image.open(upload) as source:
            if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                raise ValidationError('Use uma imagem JPG, PNG ou WebP.')
            if source.width * source.height > 20_000_000:
                raise ValidationError('A imagem deve ter no máximo 20 megapixels.')
            source.load()
            image = ImageOps.exif_transpose(source)
            image = image.convert('RGBA' if keep_transparency and image.mode in ('RGBA', 'LA', 'P') else 'RGB')
            image.thumbnail((max_size, max_size))
            output = BytesIO()
            image.save(output, format='WEBP', quality=85)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError('Imagem inválida.') from exc
    return ContentFile(output.getvalue(), name=f'{uuid4().hex}.webp')
