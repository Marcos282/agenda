"""Daily return reminders based on the last recorded, completed attendance."""
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from agenda.models import ReputacaoCliente
from profissionais.models import Profissional
from tenants.models import Tenant
from usuarios.models import WhatsAppBloqueado
from usuarios.validators import normalizar_whatsapp
from .models import Configuracao, LembreteRetorno, validate_return_message
from .providers import get_provider

logger = logging.getLogger(__name__)


def ultimos_atendimentos(tenant, agora, numero=None):
    # DISTINCT ON must happen before testing the 30-day cutoff: an old visit must
    # never win over a more recent visit with the same number and a different name.
    query = ReputacaoCliente.objects.for_tenant(tenant).filter(
        tipo__in=[ReputacaoCliente.Tipo.CONCLUIDO, ReputacaoCliente.Tipo.ATRASADO],
        agendamento__tenant=tenant, agendamento__status='CONFIRMADO',
        agendamento__fim__lte=agora,
        agendamento__conclusao_confirmada_em__isnull=False,
        agendamento__profissional__tenant=tenant, agendamento__oferta__tenant=tenant,
        agendamento__oferta__servico__tenant=tenant,
    ).filter(Q(agendamento__cliente__tenant=tenant) | Q(agendamento__contato__tenant=tenant))
    if numero is not None:
        query = query.filter(whatsapp_normalizado=numero)
    return query.select_related('agendamento__cliente', 'agendamento__contato').order_by(
        'whatsapp_normalizado', '-agendamento__fim', '-agendamento_id').distinct('whatsapp_normalizado')


def elegivel(avaliacao, tenant, agora):
    booking = avaliacao.agendamento
    pessoa = booking.cliente if booking.cliente_id else booking.contato
    if pessoa is None or pessoa.tenant_id != tenant.pk or not pessoa.is_active:
        return False
    zone = ZoneInfo(tenant.timezone)
    limite = agora.astimezone(zone).date() - timedelta(days=30)
    if booking.fim.astimezone(zone).date() > limite:
        return False
    return not WhatsAppBloqueado.objects.for_tenant(tenant).filter(
        whatsapp=avaliacao.whatsapp_normalizado).exists()


def renderizar_mensagem_retorno(tenant, booking, template):
    if booking.tenant_id != tenant.pk:
        raise ValidationError('Atendimento de outro estabelecimento.')
    validate_return_message(template)
    return template.format(
        nome=booking.cliente_nome.strip() or 'cliente',
        estabelecimento=tenant.nome.strip() or 'nosso estabelecimento',
        profissional=booking.profissional_nome.strip() or 'nossa equipe',
        ultimo_atendimento=booking.fim.astimezone(ZoneInfo(tenant.timezone)).strftime('%d/%m/%Y'),
    )


def enviar_retorno(*, tenant_id, agendamento_id, numero, agora=None):
    agora = agora or timezone.now()
    # Persist a claim in its own transaction BEFORE any network request. A crash
    # after the API accepts a message leaves PROCESSANDO, never an automatic resend.
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=tenant_id)
        config = Configuracao.objects.select_for_update().get(tenant=tenant)
        if not tenant.ativo or not config.retornos_ativos:
            return 'ignorados'
        latest = ultimos_atendimentos(tenant, agora, numero).first()
        if latest is None or latest.agendamento_id != agendamento_id or not elegivel(latest, tenant, agora):
            return 'ignorados'
        claim, created = LembreteRetorno.objects.get_or_create(
            agendamento=latest.agendamento, defaults={'destinatario': numero})
        if not created and claim.status not in [claim.Status.ERRO, claim.Status.IGNORADO]:
            return 'ignorados'
        claim.status = claim.Status.PROCESSANDO
        claim.erro = ''
        claim.save(update_fields=['status', 'erro'])

    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=tenant_id)
        config = Configuracao.objects.select_for_update().get(tenant=tenant)
        claim = LembreteRetorno.objects.select_for_update().get(
            pk=claim.pk, agendamento__tenant=tenant)
        # Attendance corrections use this same professional lock.
        Profissional.objects.for_tenant(tenant).select_for_update().get(
            pk=latest.agendamento.profissional_id)
        latest = ultimos_atendimentos(tenant, agora, numero).first()
        if (not tenant.ativo or not config.retornos_ativos or latest is None
                or latest.agendamento_id != agendamento_id or not elegivel(latest, tenant, agora)):
            claim.status = claim.Status.IGNORADO
            claim.save(update_fields=['status'])
            return 'ignorados'
        claim.tentado_em = timezone.now()
        try:
            booking = latest.agendamento
            claim.destinatario = normalizar_whatsapp(booking.cliente_whatsapp or booking.whatsapp_contato)
            if claim.destinatario != numero:
                raise ValidationError('WhatsApp diferente do atendimento concluído.')
            claim.mensagem = renderizar_mensagem_retorno(tenant, booking, config.mensagem_retorno)
        except (ValidationError, ValueError):
            claim.status = claim.Status.ERRO
            claim.erro = 'Confira o WhatsApp e as variáveis da mensagem de retorno. Nenhum envio foi iniciado.'
            outcome = 'erros'
        else:
            # Save the attempted number/message for audit even if transport fails.
            claim.save(update_fields=['destinatario', 'mensagem', 'tentado_em'])
            try:
                response = get_provider().send_text(tenant, claim.destinatario, claim.mensagem)
                if not isinstance(response, dict) or not response.get('message_id'):
                    raise ValueError('O provider não confirmou a aceitação da mensagem.')
            except Exception as exc:
                claim.status = claim.Status.INCERTO
                claim.erro = 'Não foi possível confirmar o envio. Confira a conversa antes de tentar novamente; não haverá repetição automática.'
                logger.error('Retorno WhatsApp incerto tenant=%s agendamento=%s tipo=%s',
                    tenant.pk, agendamento_id, type(exc).__name__)
                outcome = 'incertos'
            else:
                claim.status = claim.Status.ENVIADO
                claim.enviado_em = timezone.now()
                claim.resposta_api = {'message_id': str(response['message_id'])}
                outcome = 'enviados'
        claim.save(update_fields=['destinatario', 'mensagem', 'tentado_em', 'status',
                                 'erro', 'enviado_em', 'resposta_api'])
        return outcome


def processar_retornos(agora=None):
    agora = agora or timezone.now()
    counts = dict(enviados=0, erros=0, incertos=0, ignorados=0)
    configs = Configuracao.objects.filter(retornos_ativos=True, tenant__ativo=True).select_related('tenant')
    for config in configs.iterator():
        for latest in ultimos_atendimentos(config.tenant, agora).iterator():
            try:
                if not elegivel(latest, config.tenant, agora):
                    continue
                outcome = enviar_retorno(tenant_id=config.tenant_id,
                    agendamento_id=latest.agendamento_id, numero=latest.whatsapp_normalizado, agora=agora)
                counts[outcome] += 1
            except Exception as exc:
                # A broken customer/tenant must not stop other establishments.
                # The durable claim, if created, remains PROCESSANDO for review.
                logger.error('Falha no retorno WhatsApp tenant=%s agendamento=%s tipo=%s',
                    config.tenant_id, latest.agendamento_id, type(exc).__name__)
                counts['erros'] += 1
    return counts
