from django.core.exceptions import ValidationError
from django.utils import timezone
from zoneinfo import ZoneInfo


def validar_inicio_abertura(*, tenant, data):
    hoje = timezone.localdate(timezone=ZoneInfo(tenant.timezone))
    if data < hoje:
        raise ValidationError('Não é possível abrir a agenda em uma data passada. Escolha hoje ou uma data futura.')
