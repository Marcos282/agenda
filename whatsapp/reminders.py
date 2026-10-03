from datetime import timedelta
from zoneinfo import ZoneInfo
from django.db import transaction
from django.utils import timezone
from agenda.models import Agendamento
from usuarios.validators import normalizar_whatsapp
from .models import Configuracao, Lembrete, validate_message
from . import evolution
from django.core.exceptions import ValidationError


def render_template(template, tenant, booking):
    if tenant.pk != booking.tenant_id:
        raise ValidationError('A mensagem deve pertencer ao estabelecimento do agendamento.')
    validate_message(template)
    local = booking.inicio.astimezone(ZoneInfo(tenant.timezone))
    return template.format(cliente=booking.cliente_nome, servico=booking.servico_nome,
        profissional=booking.profissional_nome, estabelecimento=tenant.nome,
        data=local.strftime('%d/%m/%Y'), hora=local.strftime('%H:%M'))


def render_message(config, booking):
    return render_template(config.mensagem_lembrete, config.tenant, booking)


def process_reminders():
    sent = 0
    for config in Configuracao.objects.filter(lembretes_ativos=True, tenant__ativo=True).select_related('tenant').iterator():
        try:
            if evolution.state(config.tenant) != 'open':
                continue
        except evolution.EvolutionError:
            continue
        now = timezone.now()
        ids = Agendamento.objects.filter(tenant=config.tenant, status=Agendamento.Status.CONFIRMADO,
            inicio__gt=now, inicio__lte=now + timedelta(minutes=config.antecedencia_minutos), lembrete__isnull=True).values_list('pk', flat=True)
        for pk in ids.iterator():
            # Persist the claim BEFORE network I/O. A crash or ambiguous response must not duplicate messages.
            with transaction.atomic():
                booking = Agendamento.objects.select_for_update().get(pk=pk)
                claim, created = Lembrete.objects.get_or_create(agendamento=booking)
            if not created:
                continue
            with transaction.atomic():
                booking = Agendamento.objects.select_for_update().get(pk=pk)
                config.refresh_from_db()
                now = timezone.now()
                if (not config.lembretes_ativos or booking.status != Agendamento.Status.CONFIRMADO
                        or booking.inicio <= now or booking.inicio > now + timedelta(minutes=config.antecedencia_minutos)):
                    claim.delete()
                    continue
                try:
                    number = normalizar_whatsapp(booking.whatsapp_contato)
                    if not number:
                        raise ValidationError('WhatsApp ausente.')
                    evolution.send_text(config.tenant, number, render_message(config, booking))
                except (evolution.EvolutionError, ValidationError):
                    claim.status = Lembrete.Status.INCERTO
                    claim.erro = 'Não foi possível confirmar o envio. Verifique a conexão e a conversa do cliente; não haverá repetição automática.'
                else:
                    claim.status = Lembrete.Status.ENVIADO
                    claim.enviado_em = timezone.now()
                    sent += 1
                claim.save()
    return sent
