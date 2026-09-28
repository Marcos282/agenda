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
    return {
        'professionalId': profissional.pk,
        'date': data.isoformat(),
        'timeZone': profissional.tenant.timezone,
        'windows': windows,
        # Future adapter supplies client/service/start/end/value/status. No fake bookings.
        'appointments': [],
    }
