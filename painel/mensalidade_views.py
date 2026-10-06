import json
from hashlib import sha256
from uuid import UUID

from django.conf import settings
from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from tenants.models import Tenant
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
    CheckoutError, confirmar_pagamento, configurado, criar_checkout,
)
from .decorators import admin_tenant_required


class EscolhaPlanoForm(forms.Form):
    plano = forms.ChoiceField(choices=Tenant.Plano.choices)


def versao_pagamentos(tenant):
    registros = list(PagamentoAcesso.objects.filter(checkout__tenant=tenant).values_list(
        'payment_id', 'status', 'creditado_em',
    )[:30])
    return sha256(repr((tenant.expira_em, tenant.plano, registros)).encode()).hexdigest()


@admin_tenant_required
@never_cache
@require_http_methods(['GET', 'POST'])
def mensalidade(request):
    if request.method == 'GET' and request.GET.get('atualizar') == '1':
        # Poll only our database; do not call the provider every few seconds.
        return JsonResponse({'versao': versao_pagamentos(request.tenant)})
    comprar_plano = request.method == 'POST' and request.POST.get('acao') == 'comprar_plano'
    if request.method == 'POST' and request.POST.get('acao') in ('escolher_plano', 'comprar_plano'):
        form = EscolhaPlanoForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    tenant = Tenant.objects.select_for_update().get(pk=request.tenant.pk)
                    tenant.plano = form.cleaned_data['plano']
                    tenant.full_clean()
            except ValidationError as exc:
                messages.error(request, ' '.join(exc.messages))
                return redirect('painel:mensalidade')
            else:
                request.session.pop('checkout_previa', None)
                comprar_plano = True
        else:
            messages.error(request, 'Escolha um plano válido.')
            return redirect('painel:mensalidade')
        if not comprar_plano:
            return redirect('painel:mensalidade')
    if request.method == 'POST':
        if request.POST.get('acao') not in ('pagar', 'enviar', 'comprar_plano', 'escolher_plano'):
            messages.error(request, 'Solicitação de pagamento inválida.')
            return redirect('painel:mensalidade')
        preparar = request.POST.get('acao') == 'pagar'
        previa = request.session.get('checkout_previa', {})
        if not preparar and not comprar_plano and (previa.get('tenant_id') != request.tenant.pk or not previa.get('checkout_id')):
            messages.error(request, 'Confira o JSON da cobrança antes de enviar.')
            return redirect('painel:mensalidade')
        diagnostico = {}
        interromper_checkout = request.POST.get('diagnostico') == 'checkout'
        if (is_development_public_host(request.get_host()) or
                (settings.DEBUG and settings.DEV_PUBLIC_HOST and settings.DEV_TENANT_SUBDOMAIN
                 == request.tenant.subdomain)):
            origin = f'https://{settings.DEV_PUBLIC_HOST}'
        else:
            origin = f'https://{request.tenant.subdomain}.{settings.TENANT_BASE_DOMAIN}'
        try:
            checkout = criar_checkout(tenant_id=request.tenant.pk,
                                      retorno_url=origin + reverse('painel:mensalidade'),
                                      diagnostico=diagnostico, preparar=preparar,
                                      checkout_id=None if preparar or comprar_plano else previa['checkout_id'],
                                      plano=form.cleaned_data['plano'] if comprar_plano else previa.get('plano') if not preparar else None)
        except CheckoutError as exc:
            messages.error(request, str(exc))
            if diagnostico is not None:
                diagnostico['erro'] = str(exc)
                request.session['checkout_diagnostico'] = diagnostico
                return redirect(f"{reverse('painel:mensalidade')}?diagnostico=checkout")
            return redirect('painel:mensalidade')
        if preparar:
            request.session['checkout_previa'] = {
                'tenant_id': request.tenant.pk, 'checkout_id': str(checkout.pk), 'plano': checkout.plano,
            }
            return render(request, 'painel/checkout_previa.html', {
                'previa_json': json.dumps(diagnostico, ensure_ascii=False, indent=2),
                'checkout_existente': bool(checkout.preferencia_id),
                'token_configurado': bool(settings.MERCADO_PAGO_ACCESS_TOKEN),
                'modo_teste': not settings.MERCADO_PAGO_LIVE_MODE,
                'diagnostico_ativo': interromper_checkout,
            })
        request.session['ultimo_checkout_diagnostico'] = {
            'tenant_id': request.tenant.pk, 'checkout_id': str(checkout.pk), 'dados': diagnostico,
        }
        return redirect(checkout.checkout_url)

    diagnostico = None
    if request.GET.get('diagnostico') == 'checkout':
        diagnostico = request.session.pop('checkout_diagnostico', None)
    retorno_campos = ('checkout', 'collection_id', 'collection_status', 'payment_id', 'status',
                      'external_reference', 'payment_type', 'merchant_order_id', 'preference_id',
                      'site_id', 'processing_mode', 'merchant_account_id')
    retorno = {key: request.GET[key][:300] for key in retorno_campos if key in request.GET}
    confirmacao = {}
    ultimo = request.session.get('ultimo_checkout_diagnostico', {})
    if not diagnostico and ultimo.get('tenant_id') == request.tenant.pk:
        if not retorno or ultimo.get('checkout_id') == retorno.get('checkout'):
            diagnostico = ultimo.get('dados')
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
                record = confirmar_pagamento(payment_id, tenant_id=request.tenant.pk, checkout_id=checkout.pk,
                                             diagnostico=confirmacao)
                confirmacao['pagamento_validado'] = record is not None
                confirmacao['dias_creditados'] = bool(record and record.creditado_em)
                if record:
                    payment_status = record.status
            except CheckoutError as exc:
                confirmacao['erro'] = str(exc)
                messages.info(request, 'A confirmação está pendente. Atualize a página em alguns instantes.')
        if not configurado():
            confirmacao['erro'] = 'Configuração de pagamento incompleta neste servidor.'
        if not payment_status:
            latest = checkout.pagamentos.first()
            payment_status = latest.status if latest else 'pending'
        request.tenant.refresh_from_db()
    if retorno and not checkout:
        confirmacao['erro'] = 'Checkout não encontrado para este estabelecimento neste servidor.'
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
        comprovantes.filter(payment_id=request.GET.get('pagamento')).first()
        if request.GET.get('pagamento') else None
    )
    # Only expose notifications whose payment belongs to the authenticated tenant.
    # Browser-supplied IDs alone cannot establish ownership of an unlinked webhook.
    pagamentos_notificacoes = pagamentos
    if pagamento_id:
        pagamentos_notificacoes = pagamentos_notificacoes.filter(payment_id=pagamento_id)
    elif checkout:
        pagamentos_notificacoes = pagamentos_notificacoes.filter(checkout=checkout)
    notificacoes_recebimento = NotificacaoMercadoPago.objects.filter(
        payment_id__in=pagamentos_notificacoes.values('payment_id'),
    )[:20]
    return render(request, 'painel/mensalidade.html', {
        'valor_acesso': request.tenant.valor_plano,
        'planos': [
            {'id': Tenant.Plano.INDIVIDUAL, 'nome': 'Plano Individual', 'valor': '30,00', 'agenda': '1 agenda / profissional ativo'},
            {'id': Tenant.Plano.PROFISSIONAL, 'nome': 'Plano Profissional', 'valor': '50,00', 'agenda': 'Profissionais e agendas ilimitados'},
        ],
        'checkout_configurado': configurado(),
        'modo_teste': not settings.MERCADO_PAGO_LIVE_MODE,
        'payment_status': payment_status,
        'dias_restantes': dias,
        'expira_hoje': dias == 0 and not expirado,
        'prazo_expirado': expirado,
        'data_expiracao': request.tenant.data_expiracao,
        'pagamentos': pagamentos[:10],
        'diagnostico_ativo': request.GET.get('diagnostico') == 'checkout',
        'retorno_json': json.dumps(retorno, ensure_ascii=False, indent=2) if retorno else None,
        'confirmacao_json': json.dumps(confirmacao, ensure_ascii=False, indent=2) if confirmacao else None,
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


@admin_tenant_required
@never_cache
@require_http_methods(['GET'])
def comprovante(request, payment_id):
    from django.shortcuts import get_object_or_404
    pagamento = get_object_or_404(
        PagamentoAcesso.objects.select_related('checkout'),
        payment_id=payment_id, checkout__tenant=request.tenant,
        status='approved', creditado_em__isnull=False,
    )
    return render(request, 'painel/comprovante_pagamento.html', {'pagamento': pagamento})
