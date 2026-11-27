import json
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_safe
from django.urls import reverse
from django.utils.translation import gettext as _

from .institutional_i18n import DEFAULT, LANGUAGES, PAGES, is_institutional_host, language_context, localized_path
from tenants.pricing import monthly_price

from .seo_segments import SEGMENTS


def platform_url():
    value = settings.PLATFORM_PUBLIC_URL
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
            or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ImproperlyConfigured('PLATFORM_PUBLIC_URL deve ser a URL HTTPS da plataforma, sem caminho ou parâmetros.')
    return value.rstrip('/') + '/'


def page_metadata(title, description, url, data):
    return {
        'seo_title': title, 'seo_description': description, 'seo_url': url,
        'seo_json': json.dumps(data, ensure_ascii=False).replace('<', '\\u003c'),
    }


def institutional_url(name):
    return platform_url().rstrip('/') + reverse(name)


def platform_metadata(locale=None):
    current = (locale or {}).get('current_language', {})
    url = current.get('url') or platform_url()
    title = _('Tá Combinado | Sistema de Agendamento Online para Profissionais')
    description = _(
        'Organize seus agendamentos com o Tá Combinado. Ideal para salões, barbearias, '
        'podólogos, dentistas e profissionais autônomos. Experimente 30 dias grátis.'
    )
    data = {
        '@context': 'https://schema.org',
        '@graph': [
            {'@type': 'Organization', '@id': url + '#organization', 'name': 'Tá Combinado', 'url': url},
            {'@type': 'WebSite', '@id': url + '#website', 'name': 'Tá Combinado',
             'url': url, 'inLanguage': current.get('tag', 'pt-BR'), 'publisher': {'@id': url + '#organization'}},
            {'@type': 'SoftwareApplication', 'name': 'Tá Combinado', 'url': url,
             'applicationCategory': 'BusinessApplication', 'operatingSystem': 'Web',
             'description': description,
             'offers': [
                 {'@type': 'Offer', 'name': _('Plano Profissional'), 'price': f'{monthly_price():.2f}',
                  'priceCurrency': 'BRL', 'description': _('Acesso por 30 dias com profissionais e agendas ilimitados.')},
             ]},
        ],
    }
    return page_metadata(title, description, url, data)


@require_safe
def segment_page(request, segment):
    if request.tenant is not None:
        raise Http404
    content = SEGMENTS[segment]
    title = f"{content['title']} | Tá Combinado"
    locale = language_context(request)
    current = locale.get('current_language', {})
    url = current.get('url') or institutional_url(f'agenda-online-{segment}')
    breadcrumbs = {
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': _('Início'), 'item': platform_url().rstrip('/') + localized_path('home', current.get('code', DEFAULT))},
            {'@type': 'ListItem', 'position': 2, 'name': str(content['label']), 'item': url},
        ],
    }
    return render(request, 'usuarios/seo_segment.html', {
        'segment': content,
        **locale,
        **page_metadata(title, str(content['description']), url, breadcrumbs),
    })


def tenant_metadata(*, tenant, profissional=None, address=''):
    root = f'https://{tenant.subdomain}.{settings.STORE_BASE_DOMAIN}'
    path = reverse('home_profissional', args=[profissional.pk]) if profissional else reverse('home')
    url = root + path
    name = f'{profissional.nome} — {tenant.nome}' if profissional else tenant.nome
    title = f'{name} | Serviços e agendamento online'
    description = f'Conheça os serviços de {name} e agende seu horário online.'
    if address:
        description += f' Endereço: {address}.'
    business = {'@type': 'Organization', '@id': root + '/#estabelecimento', 'name': tenant.nome, 'url': root + '/'}
    if address:
        business['address'] = address
    data = {'@context': 'https://schema.org', '@graph': [
        business,
        {'@type': 'WebPage', '@id': url + '#pagina', 'name': title, 'description': description,
         'url': url, 'inLanguage': 'pt-BR', 'about': {'@id': business['@id']}},
    ]}
    return {'seo_title': title, 'seo_description': description, 'seo_url': url,
            'seo_json': json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')}


@require_GET
def robots(request):
    if settings.DEBUG:
        text = 'User-agent: *\nDisallow: /\n'
    elif request.tenant is None:
        text = f'User-agent: *\nAllow: /\nSitemap: {platform_url()}sitemap.xml\n'
    else:
        text = f'User-agent: *\nAllow: /\nSitemap: https://{request.tenant.subdomain}.{settings.STORE_BASE_DOMAIN}/sitemap.xml\n'
    return HttpResponse(text, content_type='text/plain; charset=utf-8')


@require_GET
def sitemap(request):
    location = ''
    if not settings.DEBUG and request.tenant is None:
        pages = ['home', 'manual', 'politica_privacidade', *(f'agenda-online-{segment}' for segment in SEGMENTS)]
        urls = [institutional_url(name) for name in pages]
        if is_institutional_host(request):
            urls.extend(platform_url().rstrip('/') + localized_path(name, code)
                        for code, *_ in LANGUAGES if code != DEFAULT for name in PAGES)
        location = ''.join(f'<url><loc>{escape(url)}</loc></url>' for url in urls)
    elif not settings.DEBUG and request.tenant is not None:
        from profissionais.models import Profissional
        root = f'https://{request.tenant.subdomain}.{settings.STORE_BASE_DOMAIN}'
        paths = [reverse('home')]
        paths.extend(reverse('home_profissional', args=[pk]) for pk in
                     Profissional.objects.for_tenant(request.tenant).ativos().values_list('pk', flat=True)[:49999])
        location = ''.join(f'<url><loc>{escape(root + path)}</loc></url>' for path in paths)
    return HttpResponse(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + location + '</urlset>',
        content_type='application/xml',
    )


class SearchIndexMiddleware:
    private_prefixes = (
        '/painel/', '/admin/', '/login/', '/logout/', '/conta/', '/registro',
        '/cadastro/', '/agendamentos/', '/pagamentos/', '/integracoes/',
        '/lembrar-senha/', '/redefinir-senha/', '/senha-redefinida/',
        '/teste', '/testezap', '/whatsapp/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        filtered_search = bool(request.GET.get('q')) and (request.path_info == '/' or request.path_info.startswith('/profissional/'))
        if settings.DEBUG or request.path_info.startswith(self.private_prefixes):
            response['X-Robots-Tag'] = 'noindex, nofollow'
        elif filtered_search:
            response['X-Robots-Tag'] = 'noindex, follow'
        return response
