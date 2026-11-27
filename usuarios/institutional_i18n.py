from urllib.parse import urlsplit

from django.conf import settings
from django.http import Http404
from django.http.request import split_domain_port
from django.middleware.locale import LocaleMiddleware
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import translation
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_POST

from .seo_segments import SEGMENTS

DEFAULT = 'pt-br'
LANGUAGES = (
    (DEFAULT, 'pt-BR', 'pt_BR', '🇧🇷', 'Português'),
    ('en', 'en', 'en_US', '🇺🇸', 'English'),
    ('es', 'es', 'es_ES', '🇪🇸', 'Español'),
    ('fr', 'fr', 'fr_FR', '🇫🇷', 'Français'),
    ('it', 'it', 'it_IT', '🇮🇹', 'Italiano'),
    ('de', 'de', 'de_DE', '🇩🇪', 'Deutsch'),
)
CODES = {item[0] for item in LANGUAGES}
PAGES = {'home': '/', **{f'agenda-online-{slug}': f'/agenda-online-{slug}/' for slug in SEGMENTS}}
ROUTES = {path: name for name, path in PAGES.items()}


def localized_path(page, language):
    path = reverse(page)
    return path if language == DEFAULT else '/' + language + path


def is_institutional_host(request):
    host, _ = split_domain_port(request.get_host().lower())
    return request.tenant is None and (
        host == urlsplit(settings.PLATFORM_PUBLIC_URL).hostname
        or (settings.DEBUG and host in {'localhost', '127.0.0.1', '[::1]'})
    )


class InstitutionalLocaleMiddleware(LocaleMiddleware):
    def __call__(self, request):
        first, _, rest = request.path_info[1:].partition('/')
        explicit = first if first in CODES - {DEFAULT} else None
        path = '/' + rest if explicit else request.path_info
        page = ROUTES.get(path)
        if not explicit and path == '/inicio/':
            page = 'home'
        if not page or not is_institutional_host(request):
            if explicit and page:
                raise Http404
            return self.get_response(request)

        with translation.override(explicit or DEFAULT):
            if explicit:
                request.LANGUAGE_CODE = explicit
            else:
                super().process_request(request)
            language = request.LANGUAGE_CODE
            if not explicit and language != DEFAULT and request.method in {'GET', 'HEAD'}:
                query = request.GET.urlencode()
                response = redirect(localized_path(page, language) + ('?' + query if query else ''))
            else:
                request.institutional_page = page
                response = self.get_response(request)
                response.headers.setdefault('Content-Language', language)
            if not explicit:
                patch_vary_headers(response, ('Accept-Language', 'Cookie'))
            return response


def language_context(request):
    page = getattr(request, 'institutional_page', None)
    if not page:
        return {}
    root = settings.PLATFORM_PUBLIC_URL.rstrip('/')
    code = request.LANGUAGE_CODE
    options = [
        {'code': key, 'tag': tag, 'locale': locale, 'flag': flag, 'label': label,
         'url': root + localized_path(page, key)}
        for key, tag, locale, flag, label in LANGUAGES
    ]
    return {
        'institutional_page': page,
        'language_options': options,
        'current_language': next(item for item in options if item['code'] == code),
        'institutional_home': localized_path('home', code),
    }


@require_POST
def select_language(request):
    language = request.POST.get('language')
    page = request.POST.get('page')
    if not is_institutional_host(request) or language not in CODES or page not in PAGES:
        raise Http404
    response = redirect(localized_path(page, language))
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME, language, max_age=settings.LANGUAGE_COOKIE_AGE,
        secure=settings.LANGUAGE_COOKIE_SECURE or request.is_secure(), httponly=True, samesite='Lax',
    )
    return response
