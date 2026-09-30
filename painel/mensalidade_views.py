from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone
from tenants.models import Tenant
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from tenants.mercado_pago import MercadoPagoError, configured
from tenants.checkout_pro import create_checkout, pending_checkout, approve_payment
from .decorators import admin_tenant_required


def valor_mensal():
    try:
        value = Decimal(str(settings.PLATFORM_MONTHLY_PRICE))
        if value.is_finite() and 0 < value <= Decimal('999999.99') and value == value.quantize(Decimal('0.01')):
            return value
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


def _context(request, amount, debug_info=None, payment_error=None, checkout_url=None):
    dias = request.tenant.dias_para_expirar
    pending = pending_checkout(request.tenant)
    return {
        'checkout_configurado': configured() and amount is not None,
        'checkout_url': checkout_url or (pending.checkout_url if pending else ''),
        'assinatura_status': request.tenant.mercado_pago_assinatura_status,
        'assinatura_ativa': request.tenant.mercado_pago_assinatura_status == 'authorized',
        'valor_mensal': amount,
        'dias_restantes': max(0, dias),
        'expira_hoje': dias == 0,
        'prazo_expirado': dias < 0,
        'data_expiracao': request.tenant.data_expiracao,
        'debug_info': debug_info or request.tenant.mercado_pago_diagnostico,
        'webhook_info': request.tenant.mercado_pago_ultimo_webhook,
        'payment_error': payment_error,
        'payment_debug': True,
    }


@admin_tenant_required
@never_cache
@require_http_methods(['GET', 'POST'])
def mensalidade(request):
    amount = valor_mensal()
    if request.method == 'GET' and request.GET.get('payment_id'):
        try:
            approve_payment(request.GET['payment_id'], tenant_id=request.tenant.pk)
            request.tenant.refresh_from_db()
        except MercadoPagoError:
            messages.info(request, 'A confirmação está pendente. Atualize a página em alguns instantes.')
    if request.method == 'POST':
        if request.POST.get('acao') != 'pagar':
            messages.error(request, 'Solicitação de pagamento inválida.')
            return redirect('painel:mensalidade')
        if amount is None or not configured():
            messages.error(request, 'O pagamento online ainda não está configurado.')
            return redirect('painel:mensalidade')
        diagnostics = {}
        try:
            checkout_url = create_checkout(
                tenant_id=request.tenant.pk,
                amount=amount,
                diagnostics=diagnostics,
            )
        except MercadoPagoError as exc:
            diagnostics = exc.diagnostics or diagnostics
            diagnostics['at'] = timezone.now().isoformat()
            Tenant.objects.filter(pk=request.tenant.pk).update(mercado_pago_diagnostico=diagnostics)
            return render(request, 'painel/mensalidade.html', _context(
                request, amount, debug_info=diagnostics, payment_error=str(exc),
            ))
        diagnostics['at'] = timezone.now().isoformat()
        Tenant.objects.filter(pk=request.tenant.pk).update(mercado_pago_diagnostico=diagnostics)
        request.tenant.refresh_from_db()
        return render(request, 'painel/mensalidade.html', _context(
            request, amount, debug_info=diagnostics, checkout_url=checkout_url,
        ))

    return render(request, 'painel/mensalidade.html', _context(request, amount))
