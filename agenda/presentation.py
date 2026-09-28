"""Presentation payload: real intervals in local seconds, never persisted ticks."""


def seconds(value):
    return value.hour * 3600 + value.minute * 60 + value.second


def label(value):
    return value.strftime('%H:%M')


def timeline_payload(profissional, data, periodos):
    windows = [{
        'id': p.pk, 'start': seconds(p.hora_inicio), 'end': seconds(p.hora_fim),
        'startLabel': label(p.hora_inicio), 'endLabel': label(p.hora_fim),
    } for p in periodos]
    from zoneinfo import ZoneInfo
    from django.db.models.functions import TruncDate
    from .models import Agendamento
    from django.urls import reverse
    from django.utils import timezone
    bookings = Agendamento.objects.for_tenant(profissional.tenant).filter(profissional=profissional, status__in=['CONFIRMADO', 'NAO_COMPARECEU']).annotate(dia_local=TruncDate('inicio', tzinfo=ZoneInfo(profissional.tenant.timezone))).filter(dia_local=data)
    return {
        'professionalId': profissional.pk,
        'date': data.isoformat(),
        'timeZone': profissional.tenant.timezone,
        'windows': windows,
        'appointments': [{'id': a.pk, 'cliente': a.cliente_nome, 'servico': a.servico_nome,
            'inicio': a.inicio.isoformat(), 'fim': a.fim.isoformat(), 'valor': str(a.valor),
            'cancelUrl': reverse('painel:agendamento_cancelar', args=[a.pk]) if a.status == 'CONFIRMADO' and a.inicio > timezone.now() else None,
            'noShowUrl': reverse('painel:agendamento_falta', args=[a.pk]) if a.status == 'CONFIRMADO' and a.inicio <= timezone.now() else None,
            'statusLabel': a.get_status_display(), 'status': a.status, 'inicio_label': a.inicio.astimezone(ZoneInfo(profissional.tenant.timezone)).strftime('%H:%M'),
            'fim_label': a.fim.astimezone(ZoneInfo(profissional.tenant.timezone)).strftime('%H:%M')} for a in bookings],
    }
