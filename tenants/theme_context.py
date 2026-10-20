import base64
from django.urls import reverse
from .models import TenantTheme
from .themes import tokens


def site_theme(request):
    preview = getattr(request, '_theme_preview', None)
    if not getattr(request, 'tenant', None):
        return {}
    namespace = getattr(request.resolver_match, 'namespace', '')
    if preview is None and (namespace == 'painel' or request.path.startswith(('/admin/', '/whatsapp/'))):
        return {}
    theme = preview if preview is not None else TenantTheme.objects.filter(tenant=request.tenant).first()
    if theme is None:
        return {}
    media = {}
    for field in ('hero_image', 'background_image'):
        image = getattr(theme, field)
        if image:
            if preview is not None and not image._committed:
                image.open()
                media[field] = 'data:image/webp;base64,' + base64.b64encode(image.read()).decode()
            else:
                media[field] = reverse('theme_image', args=[field]) + f'?v={theme.updated_at.timestamp() if theme.updated_at else 0}'
    return {'site_theme': theme, 'theme_active': theme.style != 'original',
            'theme_tokens': tokens(theme.style, theme.primary_color), 'theme_media': media,
            'theme_preview': preview is not None}
