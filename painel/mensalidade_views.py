import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .decorators import admin_tenant_required


def checkout_assinatura():
    plan_id = settings.MERCADO_PAGO_SUBSCRIPTION_PLAN_ID.strip()
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,120}', plan_id):
        return None
    return 'https://www.mercadopago.com.br/subscriptions/checkout?' + urlencode({'preapproval_plan_id': plan_id})


def valor_mensal():
    try:
        value = Decimal(str(settings.PLATFORM_MONTHLY_PRICE))
        if value.is_finite() and 0 < value <= Decimal('999999.99') and value == value.quantize(Decimal('0.01')):
            return value
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


@admin_tenant_required
@never_cache
@require_GET
def mensalidade(request):
    dias = request.tenant.dias_para_expirar
    return render(request, 'painel/mensalidade.html', {
        'checkout_url': checkout_assinatura(),
        'valor_mensal': valor_mensal(),
        'dias_restantes': max(0, dias),
        'expira_hoje': dias == 0,
        'prazo_expirado': dias < 0,
        'data_expiracao': request.tenant.data_expiracao,
    })
