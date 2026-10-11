import re
from django.core.exceptions import ValidationError


def normalizar_whatsapp(value):
    """Normalize Brazilian national numbers or explicit international numbers."""
    raw = (value or '').strip()
    error = 'Informe um WhatsApp com DDD, como (11) 99999-9999. Para outros países, use + e o código do país.'
    if not raw or not re.fullmatch(r'\+?[0-9 ()\-]+', raw):
        raise ValidationError(error)
    digits = re.sub(r'[^0-9]', '', raw)
    if raw.startswith('+'):
        if not re.fullmatch(r'[1-9][0-9]{7,14}', digits):
            raise ValidationError(error)
    elif len(digits) in (10, 11):
        digits = '55' + digits
    elif not (digits.startswith('55') and len(digits) in (12, 13)):
        raise ValidationError(error)
    national = digits[2:] if digits.startswith('55') else digits
    if digits.startswith('55') and not re.fullmatch(r'[1-9][0-9](?:9[0-9]{8}|[2-5][0-9]{7})', national):
        raise ValidationError(error)
    if len(set(national)) == 1:
        raise ValidationError(error)
    return '+' + digits


def preparar_whatsapp(value):
    """Normalize valid numbers while preserving other supplied contact values."""
    raw = ' '.join(str(value or '').split())
    if not raw:
        return ''
    try:
        return normalizar_whatsapp(raw)
    except ValidationError:
        return raw


def validate_whatsapp(value):
    """Compatibility hook for historical migrations; WhatsApp format is not restricted."""


def whatsapp_liberado_para_testes(tenant, value):
    """Allow quantity/block exceptions only for the configured tenant/number pair."""
    from django.conf import settings
    try:
        numero = normalizar_whatsapp(value)
    except ValidationError:
        return False
    for entry in getattr(settings, 'WHATSAPP_TEST_RECIPIENTS', '').split(','):
        subdomain, separator, phone = entry.strip().partition(':')
        if not separator or subdomain != tenant.subdomain:
            continue
        try:
            if normalizar_whatsapp(phone) == numero:
                return True
        except ValidationError:
            continue
    return False
