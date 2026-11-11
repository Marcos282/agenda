from django.conf import settings
from django.core.checks import Error, Warning, register

from . import turnstile


@register()
def turnstile_keys(app_configs, **kwargs):
    if not turnstile.enabled(use_database=False):
        return []
    missing = [name for name in ('TURNSTILE_PUBLIC_SITE_KEY', 'TURNSTILE_PUBLIC_SECRET_KEY',
                                 'TURNSTILE_AUTH_SITE_KEY', 'TURNSTILE_AUTH_SECRET_KEY')
               if not getattr(settings, name)]
    if not missing:
        return []
    return [Error('Cloudflare Turnstile ativo sem as chaves: ' + ', '.join(missing) + '.',
                  hint='Configure as variáveis no ambiente ou defina TURNSTILE_ENABLED=false apenas em desenvolvimento.',
                  id='usuarios.E001')]


@register()
def turnstile_production_configuration(app_configs, **kwargs):
    if not settings.TURNSTILE_ENABLED:
        if not settings.DEBUG and not settings.RUNNING_TESTS:
            return [Error(
                'Cloudflare Turnstile não pode ser desativado em produção.',
                hint='Defina TURNSTILE_ENABLED=true e configure as chaves dos dois widgets.',
                id='usuarios.E004',
            )]
        return []
    if settings.DEBUG:
        if not settings.TURNSTILE_VERIFY_HOSTNAME:
            return [Warning(
                'TURNSTILE_VERIFY_HOSTNAME=false é ignorado: hostnames de tokens reais são sempre verificados.',
                hint='Remova a configuração ou defina TURNSTILE_VERIFY_HOSTNAME=true.',
                id='usuarios.W001',
            )]
        return []
    errors = []
    test_keys = [
        name for name, keys in (
            ('TURNSTILE_PUBLIC_SITE_KEY', turnstile.TEST_SITE_KEYS),
            ('TURNSTILE_PUBLIC_SECRET_KEY', turnstile.TEST_SECRET_KEYS),
            ('TURNSTILE_AUTH_SITE_KEY', turnstile.TEST_SITE_KEYS),
            ('TURNSTILE_AUTH_SECRET_KEY', turnstile.TEST_SECRET_KEYS),
        ) if getattr(settings, name) in keys
    ]
    if test_keys:
        errors.append(Error(
            'Chaves de teste do Cloudflare Turnstile não são permitidas em produção: ' + ', '.join(test_keys) + '.',
            hint='Configure chaves reais para os dois widgets.',
            id='usuarios.E002',
        ))
    if not settings.TURNSTILE_VERIFY_HOSTNAME:
        errors.append(Error(
            'A validação do hostname do Cloudflare Turnstile não pode ser desativada em produção.',
            hint='Defina TURNSTILE_VERIFY_HOSTNAME=true.',
            id='usuarios.E003',
        ))
    return errors
