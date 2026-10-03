"""Post-commit confirmation; a persistent claim prevents repeated sends."""
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from agenda.models import Agendamento
from usuarios.validators import normalizar_whatsapp
from .models import Configuracao, Confirmacao, Lembrete
from .reminders import render_template
from . import evolution


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
        text = render_template(config.mensagem_confirmacao, booking.tenant, booking)
        evolution.send_text(booking.tenant, numero, text)
    except (evolution.EvolutionError, ValidationError):
        claim.status = Lembrete.Status.INCERTO
        claim.erro = 'Não foi possível confirmar o envio. Verifique a conexão e a conversa do cliente; não haverá repetição automática.'
    else:
        claim.status = Lembrete.Status.ENVIADO
        claim.enviado_em = timezone.now()
    claim.save(update_fields=['status', 'erro', 'enviado_em'])
    return claim.status == Lembrete.Status.ENVIADO
