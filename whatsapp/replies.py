"""Tenant-scoped, durable reminder replies and a conservative delivery outbox."""
from datetime import datetime, timedelta, timezone as utc
from functools import partial

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from agenda.booking import cancelar
from agenda.models import Agendamento
from profissionais.models import Profissional
from tenants.models import Tenant
from usuarios.validators import normalizar_whatsapp
from . import evolution
from .models import Configuracao, Lembrete, RespostaLembrete, RetornoResposta
from .reminders import render_template


def parse_messages(payload):
    if not isinstance(payload, dict):
        raise ValueError('Invalid envelope')
    if str(payload.get('event', '')).lower().replace('_', '.') != 'messages.upsert':
        return []
    items = payload.get('data')
    items = items if isinstance(items, list) else [items]
    if len(items) > 100:
        raise ValueError('Batch too large')
    parsed = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Invalid message')
        key, message = item.get('key') or {}, item.get('message') or {}
        if not isinstance(key, dict) or not isinstance(message, dict):
            raise ValueError('Invalid message')
        if key.get('fromMe') is not False:
            continue
        jid = key.get('remoteJid', '')
        if not isinstance(jid, str):
            raise ValueError('Invalid sender')
        if jid.endswith('@lid'):
            jid = key.get('remoteJidAlt', '')
        if not isinstance(jid, str) or not jid.endswith('@s.whatsapp.net'):
            continue
        number = normalizar_whatsapp('+' + jid.split('@')[0])
        for wrapper in ('ephemeralMessage', 'viewOnceMessage'):
            if isinstance(message.get(wrapper), dict):
                message = message[wrapper].get('message') or {}
        extended = message.get('extendedTextMessage') or {}
        if not isinstance(extended, dict):
            raise ValueError('Invalid text')
        text = message.get('conversation') or extended.get('text')
        if not isinstance(text, str) or not text.strip():
            continue
        message_id = key.get('id')
        if not isinstance(message_id, str) or not 1 <= len(message_id) <= 200:
            raise ValueError('Invalid identifier')
        # Missing provider time cannot safely identify a reply to a new reminder.
        timestamp = item.get('messageTimestamp')
        if isinstance(timestamp, bool) or not str(timestamp).isdigit():
            continue
        try:
            occurred = datetime.fromtimestamp(int(timestamp), tz=utc.utc)
        except (OverflowError, OSError, ValueError):
            raise ValueError('Invalid time') from None
        context = extended.get('contextInfo') or message.get('contextInfo') or {}
        if not isinstance(context, dict):
            raise ValueError('Invalid context')
        quoted = context.get('stanzaId', '')
        if not isinstance(quoted, str) or len(quoted) > 200:
            raise ValueError('Invalid context')
        parsed.append(dict(message_id=message_id, number=number,
            option=text.strip() if text.strip() in {'1', '2'} else 'OUTRO',
            occurred=occurred, quoted=quoted))
    return parsed


def _enqueue(event, text):
    delivery = RetornoResposta.objects.create(resposta=event, mensagem=text)
    transaction.on_commit(partial(deliver_return, delivery.pk), robust=True)


@transaction.atomic
def process_reply(tenant, incoming):
    # Serializes distinct messages from the same client too, not only webhook retries.
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    instance = evolution.instance(tenant)
    event, created = RespostaLembrete.objects.get_or_create(
        tenant=tenant, instancia=instance, mensagem_id=incoming['message_id'],
        defaults={'destinatario': incoming['number'], 'opcao': incoming['option'],
                  'ocorrido_em': incoming['occurred']})
    if not created:
        return event
    now = timezone.now()
    config = Configuracao.objects.filter(tenant=tenant).first()
    text = None
    result = 'SEM_LEMBRETE'
    if not tenant.ativo or not config or not (config.confirmar_presenca_whatsapp or config.cancelar_whatsapp):
        result = 'DESATIVADO'
    elif incoming['occurred'] > now + timedelta(minutes=2):
        result = 'DATA_INVALIDA'
    else:
        candidates = Lembrete.objects.filter(agendamento__tenant=tenant,
            instancia=instance, destinatario=incoming['number'],
            status=Lembrete.Status.ENVIADO, mensagem_id__gt='', enviado_em__isnull=False)
        if incoming['quoted']:
            # A wrong/foreign quoted id MUST NOT fall back to phone matching.
            candidates = candidates.filter(mensagem_id=incoming['quoted'])
        else:
            candidates = candidates.filter(valido_ate__gt=now,
                enviado_em__lte=incoming['occurred'] + timedelta(seconds=2))
        ids = list(candidates.values_list('pk', flat=True)[:2])
        if len(ids) > 1:
            result = 'AMBIGUO'
            text = ('Há mais de um lembrete possível. Use a opção Responder do WhatsApp '
                    'na mensagem do agendamento desejado e digite 1 ou 2. Nenhum agendamento foi alterado.')
        elif ids:
            reminder = Lembrete.objects.get(pk=ids[0])
            # Match the existing cancellation lock order before locking the booking.
            Profissional.objects.select_for_update().get(pk=reminder.agendamento.profissional_id, tenant=tenant)
            booking = Agendamento.objects.select_for_update().get(pk=reminder.agendamento_id, tenant=tenant)
            reminder = Lembrete.objects.select_for_update().get(pk=reminder.pk)
            event.lembrete = reminder
            result, template = _apply(config, reminder, booking, incoming, now)
            text = render_template(template, tenant, booking) if template else None
    event.resultado = result
    event.save(update_fields=['resultado', 'lembrete'])
    if text:
        _enqueue(event, text)
    return event


def _apply(config, reminder, booking, incoming, now):
    if (not reminder.valido_ate or booking.inicio != reminder.valido_ate
            or normalizar_whatsapp(booking.whatsapp_contato) != reminder.destinatario
            or now >= reminder.valido_ate or booking.inicio <= now
            or incoming['occurred'] < reminder.enviado_em - timedelta(seconds=2)
            or incoming['occurred'] >= reminder.valido_ate or booking.conclusao_confirmada_em):
        return 'EXPIRADO', None
    if booking.status != Agendamento.Status.CONFIRMADO:
        return 'INATIVO', None
    confirm = config.confirmar_presenca_whatsapp and reminder.permite_confirmar
    cancel = config.cancelar_whatsapp and reminder.permite_cancelar
    if incoming['option'] == '1':
        if not confirm:
            return 'DESATIVADO', None
        if reminder.presenca_confirmada_em:
            return 'JA_CONFIRMADO', None
        reminder.presenca_confirmada_em = now
        reminder.save(update_fields=['presenca_confirmada_em'])
        return 'CONFIRMADO', ('✅ {cliente}, sua presença está confirmada!\n\n'
            '📅 {data}\n⏰ {hora}\n💈 {estabelecimento}\n\nAguardamos você!')
    if incoming['option'] == '2':
        if not cancel:
            return 'DESATIVADO', None
        if now > booking.inicio - timedelta(minutes=config.cancelamento_antecedencia_minutos):
            return 'FORA_DO_PRAZO', ('Olá, {cliente}!\n\nO prazo para cancelamento automático '
                'do seu agendamento já terminou.\n\nEntre em contato diretamente com '
                '{estabelecimento} para verificar a possibilidade de cancelamento.')
        cancelar(tenant=booking.tenant, cliente=booking.cliente, agendamento_id=booking.pk)
        reminder.cancelado_pelo_cliente_em = now
        reminder.save(update_fields=['cancelado_pelo_cliente_em'])
        return 'CANCELADO', ('❌ {cliente}, seu agendamento do dia {data} às {hora} foi cancelado '
            'com sucesso.\n\nO horário foi liberado.\n\nEsperamos você em uma próxima oportunidade!')
    options = []
    if confirm:
        options.append('Digite 1 para CONFIRMAR.')
    if cancel:
        options.append('Digite 2 para CANCELAR.')
    return 'ORIENTADO', '\n'.join(options) or None


def deliver_return(pk):
    with transaction.atomic():
        delivery = RetornoResposta.objects.select_for_update().get(pk=pk)
        if (delivery.status not in {RetornoResposta.Status.PENDENTE, RetornoResposta.Status.FALHA}
                or delivery.proxima_tentativa_em > timezone.now() or delivery.tentativas >= 5):
            return False
        delivery.status = RetornoResposta.Status.PROCESSANDO
        delivery.tentativas += 1
        delivery.save(update_fields=['status', 'tentativas'])
    # Committed claim before network I/O: ambiguous failures are never blindly retried.
    try:
        event = delivery.resposta
        metadata = evolution.send_text(event.tenant, event.destinatario, delivery.mensagem)
        if not isinstance(metadata, dict) or not metadata.get('message_id'):
            raise evolution.EvolutionError('Invalid delivery metadata')
    except (evolution.EvolutionError, ValidationError, OSError, ValueError) as exc:
        safe = isinstance(exc, evolution.EvolutionError) and exc.retry_safe
        delivery.status = RetornoResposta.Status.FALHA if safe else RetornoResposta.Status.INCERTO
        delivery.erro = ('Envio rejeitado antes de aceitar a mensagem.' if safe
                        else 'Envio incerto: confira a conversa antes de repetir.')
        delivery.proxima_tentativa_em = timezone.now() + timedelta(minutes=2 ** delivery.tentativas)
    else:
        delivery.status = RetornoResposta.Status.ENVIADO
        delivery.mensagem_id = metadata['message_id']
        delivery.enviado_em = timezone.now()
        delivery.erro = ''
    delivery.save()
    return delivery.status == RetornoResposta.Status.ENVIADO


def process_returns():
    ids = RetornoResposta.objects.filter(status__in=['PENDENTE', 'FALHA'],
        tentativas__lt=5, proxima_tentativa_em__lte=timezone.now()).values_list('pk', flat=True)
    return sum(deliver_return(pk) for pk in ids.iterator())


def confirmation_indicator(booking):
    try:
        reminder = booking.lembrete
    except Lembrete.DoesNotExist:
        reminder = None
    if reminder and reminder.cancelado_pelo_cliente_em:
        return '🔴 Cancelado pelo cliente'
    if reminder and reminder.presenca_confirmada_em:
        return '🟢 Confirmado pelo cliente'
    if (reminder and reminder.status == 'ENVIADO' and reminder.mensagem_id
            and (reminder.permite_confirmar or reminder.permite_cancelar)
            and reminder.valido_ate and reminder.valido_ate > timezone.now()
            and booking.status == 'CONFIRMADO'):
        return '🟡 Aguardando confirmação'
    return '⚪ Sem resposta'
