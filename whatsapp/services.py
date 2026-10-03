"""Message rendering shared by confirmations, reminders and future events."""
from zoneinfo import ZoneInfo
from django.core.exceptions import ValidationError
from .models import validate_message


def message_values(tenant, booking):
    if tenant.pk != booking.tenant_id:
        raise ValidationError('A mensagem deve pertencer ao estabelecimento do agendamento.')
    local = booking.inicio.astimezone(ZoneInfo(tenant.timezone))
    return dict(cliente=booking.cliente_nome, servico=booking.servico_nome,
                profissional=booking.profissional_nome, empresa=tenant.nome,
                estabelecimento=tenant.nome, data=local.strftime('%d/%m/%Y'),
                horario=local.strftime('%H:%M'), hora=local.strftime('%H:%M'))


def renderizar_mensagem_agendamento(booking, template, *, tenant=None):
    validate_message(template)
    return template.format(**message_values(tenant or booking.tenant, booking))


def enviar_confirmacao_agendamento(*, tenant_id, agendamento_id):
    from .confirmations import send_confirmation
    return send_confirmation(tenant_id=tenant_id, agendamento_id=agendamento_id)
