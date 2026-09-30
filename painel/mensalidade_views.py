import json
from hashlib import sha256
from uuid import UUID

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from tenants.domains import is_development_public_host

from pagamentos.models import CheckoutAcesso, NotificacaoMercadoPago, PagamentoAcesso
from pagamentos.services import (
    CheckoutError, confirmar_pagamento, configurado, criar_checkout, preco_acesso,
)
from .decorators import admin_tenant_required


def versao_pagamentos(tenant):
    registros = list(PagamentoAcesso.objects.filter(checkout__tenant=tenant).values_list(
        'payment_id', 'status', 'creditado_em',
    )[:30])
    return sha256(repr((tenant.expira_em, registros)).encode()).hexdigest()


@admin_tenant_required
@never_cache
@require_http_methods(['GET', 'POST'])
def mensalidade(request):
    if request.method == 'GET' and request.GET.get('atualizar') == '1':
        # Poll only our database; do not call the provider every few seconds.
        return JsonResponse({'versao': versao_pagamentos(request.tenant)})
    if request.method == 'POST':
        if request.POST.get('acao') != 'pagar':
            messages.error(request, 'Solicitação de pagamento inválida.')
            return redirect('painel:mensalidade')
        diagnostico = {} if request.POST.get('diagnostico') == 'checkout' else None
        if (is_development_public_host(request.get_host()) or
                (settings.DEBUG and settings.DEV_PUBLIC_HOST and settings.DEV_TENANT_SUBDOMAIN
                 == request.tenant.subdomain)):
            origin = f'https://{settings.DEV_PUBLIC_HOST}'
        else:
            origin = f'https://{request.tenant.subdomain}.{settings.TENANT_BASE_DOMAIN}'
        try:
            checkout = criar_checkout(tenant_id=request.tenant.pk,
                                      retorno_url=origin + reverse('painel:mensalidade'),
                                      diagnostico=diagnostico)
        except CheckoutError as exc:
            messages.error(request, str(exc))
            if diagnostico is not None:
                diagnostico['erro'] = str(exc)
                request.session['checkout_diagnostico'] = diagnostico
                return redirect(f"{reverse('painel:mensalidade')}?diagnostico=checkout")
            return redirect('painel:mensalidade')
        if diagnostico is not None:
            request.session['checkout_diagnostico'] = diagnostico
            return redirect(f"{reverse('painel:mensalidade')}?diagnostico=checkout")
        return redirect(checkout.checkout_url)

    diagnostico = None
    if request.GET.get('diagnostico') == 'checkout':
        diagnostico = request.session.pop('checkout_diagnostico', None)
    payment_status = None
    checkout = None
    try:
        reference = UUID(request.GET.get('checkout', ''))
    except (ValueError, TypeError):
        reference = None
    if reference:
        checkout = CheckoutAcesso.objects.filter(pk=reference, tenant=request.tenant).first()
    if checkout:
        # The browser carries only identifiers. Its status=approved is never trusted.
        payment_id = request.GET.get('payment_id', '')
        if payment_id and configurado():
            try:
                record = confirmar_pagamento(payment_id, tenant_id=request.tenant.pk, checkout_id=checkout.pk)
                if record:
                    payment_status = record.status
            except CheckoutError:
                messages.info(request, 'A confirmação está pendente. Atualize a página em alguns instantes.')
        if not payment_status:
            latest = checkout.pagamentos.first()
            payment_status = latest.status if latest else 'pending'
        request.tenant.refresh_from_db()
    dias = request.tenant.dias_para_expirar
    expirado = request.tenant.acesso_expirado
    pagamentos = PagamentoAcesso.objects.filter(
        checkout__tenant=request.tenant,
    ).select_related('checkout')
    comprovantes = pagamentos.filter(status='approved', creditado_em__isnull=False).order_by('-creditado_em')
    pagamento_selecionado = None
    pagamento_id = request.GET.get('pagamento') or request.GET.get('payment_id', '')
    if pagamento_id:
        pagamento_selecionado = PagamentoAcesso.objects.filter(
            payment_id=pagamento_id, checkout__tenant=request.tenant,
        ).select_related('checkout').first()
    if pagamento_selecionado is None:
        pagamento_selecionado = pagamentos.first()
    if payment_status is None and pagamento_selecionado is not None:
        payment_status = pagamento_selecionado.status
    comprovante_selecionado = (
        comprovantes.filter(payment_id=pagamento_selecionado.pk).first()
        if pagamento_selecionado else None
    ) or comprovantes.first()
    notificacoes_recebimento = (
        NotificacaoMercadoPago.objects.filter(pagamento=pagamento_selecionado)
        if pagamento_selecionado else NotificacaoMercadoPago.objects.none()
    )
    return render(request, 'painel/mensalidade.html', {
        'valor_acesso': preco_acesso(),
        'checkout_configurado': configurado(),
        'modo_teste': not settings.MERCADO_PAGO_LIVE_MODE,
        'payment_status': payment_status,
        'dias_restantes': dias,
        'expira_hoje': dias == 0 and not expirado,
        'prazo_expirado': expirado,
        'data_expiracao': request.tenant.data_expiracao,
        'pagamentos': pagamentos[:10],
        'diagnostico_ativo': request.GET.get('diagnostico') == 'checkout',
        'diagnostico_json': json.dumps(diagnostico, ensure_ascii=False, indent=2) if diagnostico else None,
        'pagamentos_registrados': pagamentos[:30],
        'pagamento_selecionado': pagamento_selecionado,
        'notificacoes_recebimento': notificacoes_recebimento,
        'pagamento_aceito': bool(payment_status == 'approved' and pagamento_selecionado
                               and pagamento_selecionado.status == 'approved'
                               and pagamento_selecionado.creditado_em),
        'comprovantes': comprovantes,
        'comprovante_selecionado': comprovante_selecionado,
        'versao_pagamentos': versao_pagamentos(request.tenant),
        'aguardar_pagamento': CheckoutAcesso.objects.filter(
            tenant=request.tenant, expira_em__gt=timezone.now(),
        ).exclude(pagamentos__creditado_em__isnull=False).exists(),
    })
