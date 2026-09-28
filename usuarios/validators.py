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


def validate_whatsapp(value):
    normalizar_whatsapp(value)
