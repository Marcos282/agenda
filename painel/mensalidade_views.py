from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from tenants.mercado_pago import MercadoPagoError, configured, create_subscription
from .decorators import admin_tenant_required


def valor_mensal():
    try:
        value = Decimal(str(settings.PLATFORM_MONTHLY_PRICE))
        if value.is_finite() and 0 < value <= Decimal('999999.99') and value == value.quantize(Decimal('0.01')):
            return value
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


def _context(request, amount, debug_info=None, payment_error=None, debug_enabled=False, checkout_url=None):
    dias = request.tenant.dias_para_expirar
    return {
        'checkout_configurado': configured() and amount is not None,
        'checkout_url': checkout_url or request.tenant.mercado_pago_checkout_url,
        'assinatura_status': request.tenant.mercado_pago_assinatura_status,
        'assinatura_ativa': request.tenant.mercado_pago_assinatura_status == 'authorized',
        'valor_mensal': amount,
        'dias_restantes': max(0, dias),
        'expira_hoje': dias == 0,
        'prazo_expirado': dias < 0,
        'data_expiracao': request.tenant.data_expiracao,
        'debug_info': debug_info or {},
        'payment_error': payment_error,
        'payment_debug': debug_enabled,
    }


@admin_tenant_required
@never_cache
@require_http_methods(['GET', 'POST'])
def mensalidade(request):
    amount = valor_mensal()
    if request.method == 'POST':
        if request.POST.get('acao') != 'assinar':
            messages.error(request, 'Solicitação de pagamento inválida.')
            return redirect('painel:mensalidade')
        if amount is None or not configured():
            messages.error(request, 'O pagamento online ainda não está configurado.')
            return redirect('painel:mensalidade')
        debug_enabled = request.POST.get('debug_mp') == '1'
        diagnostics = {} if debug_enabled else None
        test_payer_email = settings.MERCADO_PAGO_TEST_PAYER_EMAIL.strip() if settings.DEBUG else ''
        try:
            checkout_url = create_subscription(
                tenant_id=request.tenant.pk,
                payer_email=test_payer_email or request.user.email,
                amount=amount,
                diagnostics=diagnostics,
            )
        except MercadoPagoError as exc:
            if debug_enabled:
                return render(request, 'painel/mensalidade.html', _context(
                    request, amount, debug_info=exc.diagnostics or diagnostics,
                    payment_error=str(exc), debug_enabled=True,
                ))
            messages.error(request, str(exc))
            return redirect('painel:mensalidade')
        if debug_enabled:
            return render(request, 'painel/mensalidade.html', _context(
                request, amount, debug_info=diagnostics, debug_enabled=True,
                checkout_url=checkout_url,
            ))
        return redirect(checkout_url)

    return render(request, 'painel/mensalidade.html', _context(request, amount))
