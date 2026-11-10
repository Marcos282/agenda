from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from agenda.models import Agendamento
from usuarios.validators import normalizar_whatsapp
from tenants.models import Tenant
from .models import Configuracao, Lembrete, INTERACTIVE_MESSAGE
from . import evolution
from django.core.exceptions import ValidationError


def render_template(template, tenant, booking):
    from .services import renderizar_mensagem_agendamento
    return renderizar_mensagem_agendamento(booking, template, tenant=tenant)


def render_message(config, booking):
    if config.confirmar_presenca_whatsapp or config.cancelar_whatsapp:
        options = []
        if config.confirmar_presenca_whatsapp:
            options.append('✅ Digite 1 para CONFIRMAR.')
        if config.cancelar_whatsapp:
            options.append('❌ Digite 2 para CANCELAR.')
        template = INTERACTIVE_MESSAGE.replace('{opcoes}', '\n\n'.join(options))
        if not config.confirmar_presenca_whatsapp:
            template = template.replace('Por favor, confirme sua presença:', 'Se precisar cancelar:')
        return render_template(template, config.tenant, booking)
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
                Tenant.objects.select_for_update().get(pk=config.tenant_id)
                booking = Agendamento.objects.select_for_update().get(pk=pk)
                claim, created = Lembrete.objects.get_or_create(agendamento=booking)
            if not created:
                continue
            with transaction.atomic():
                # A very fast inbound reply must wait for delivery metadata to
                # commit instead of being mistaken for an unrelated message.
                Tenant.objects.select_for_update().get(pk=config.tenant_id)
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
                    claim.instancia = evolution.instance(config.tenant)
                    claim.destinatario = number
                    claim.permite_confirmar = config.confirmar_presenca_whatsapp
                    claim.permite_cancelar = config.cancelar_whatsapp
                    claim.valido_ate = booking.inicio
                    response = evolution.send_text(config.tenant, number, render_message(config, booking))
                    claim.mensagem_id = response.get('message_id', '') if isinstance(response, dict) else ''
                except (evolution.EvolutionError, ValidationError):
                    claim.status = Lembrete.Status.INCERTO
                    claim.erro = 'Não foi possível confirmar o envio. Verifique a conexão e a conversa do cliente; não haverá repetição automática.'
                else:
                    claim.status = Lembrete.Status.ENVIADO
                    claim.enviado_em = timezone.now()
                    sent += 1
                claim.save()
    return sent
