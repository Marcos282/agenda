"""Post-commit confirmation; a persistent claim prevents repeated sends."""
import logging

from django.db import transaction
from django.utils import timezone
from agenda.models import Agendamento
from usuarios.validators import normalizar_whatsapp
from .models import Configuracao, Confirmacao, Lembrete
from .services import renderizar_mensagem_agendamento
from .providers import get_provider

logger = logging.getLogger(__name__)


def send_confirmation(*, tenant_id, agendamento_id):
    booking = Agendamento.objects.select_related('tenant', 'cliente', 'contato').get(pk=agendamento_id, tenant_id=tenant_id)
    config, _ = Configuracao.objects.get_or_create(tenant=booking.tenant)
    if not config.confirmacoes_ativas or not booking.tenant.ativo or booking.status != 'CONFIRMADO':
        return False
    with transaction.atomic():
        claim, created = Confirmacao.objects.get_or_create(agendamento=booking)
    if not created:
        return False
    try:
        numero = normalizar_whatsapp(booking.cliente_whatsapp or booking.whatsapp_contato)
        text = renderizar_mensagem_agendamento(booking, config.mensagem_confirmacao)
        claim.destinatario = numero
        claim.mensagem = text
        claim.save(update_fields=['destinatario', 'mensagem'])
        response = get_provider().send_text(booking.tenant, numero, text)
        claim.resposta_api = response if isinstance(response, dict) else {}
    except Exception as exc:
        # Provider failures must never undo the reservation or expose API secrets.
        logger.error('Falha na confirmação WhatsApp tenant=%s agendamento=%s tipo=%s',
                     tenant_id, agendamento_id, type(exc).__name__)
        claim.status = Lembrete.Status.INCERTO
        claim.erro = 'Não foi possível confirmar o envio. Verifique a conexão e a conversa do cliente; não haverá repetição automática.'
    else:
        claim.status = Lembrete.Status.ENVIADO
        claim.enviado_em = timezone.now()
    claim.save(update_fields=['status', 'erro', 'enviado_em', 'resposta_api'])
    return claim.status == Lembrete.Status.ENVIADO
