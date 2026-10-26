from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def monthly_price():
    try:
        value = Decimal(str(settings.PLATFORM_MONTHLY_PRICE))
        if (value.is_finite() and 0 < value <= Decimal('999999.99')
                and value == value.quantize(Decimal('.01'))):
            return value
    except (InvalidOperation, ValueError, TypeError):
        pass
    raise ImproperlyConfigured('PLATFORM_MONTHLY_PRICE deve ser um valor positivo em reais, com até duas casas decimais.')
