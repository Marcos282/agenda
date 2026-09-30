from django.conf import settings
from django.http.request import split_domain_port


def is_development_public_host(host):
    domain, _ = split_domain_port(host.lower())
    return bool(settings.DEBUG and settings.DEV_PUBLIC_HOST and domain == settings.DEV_PUBLIC_HOST)


def tenant_base_domain_for_host(host):
    domain, _ = split_domain_port(host.lower())
    if settings.DEBUG and domain == settings.DEV_PUBLIC_HOST:
        return domain
    if settings.DEBUG and (
        domain in {'localhost', '127.0.0.1', '[::1]'}
        or domain.endswith('.localhost')
    ):
        return 'localhost'
    return settings.TENANT_BASE_DOMAIN
