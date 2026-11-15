"""Subscription calendar shared by requests, bookings and scheduled notices."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.utils import timezone

BILLING_TIMEZONE = ZoneInfo('America/Sao_Paulo')


@dataclass(frozen=True)
class SubscriptionStatus:
    cor: str
    dias: int
    bloqueado: bool
    tolerancia: bool
    horas_restantes: int

    @property
    def aviso(self):
        return self.cor != 'verde'


def subscription_status(tenant, *, now=None):
    now = now or timezone.now()
    hoje = now.astimezone(BILLING_TIMEZONE).date()
    dias = (tenant.data_expiracao - hoje).days
    # Expiration day remains usable; the next three complete calendar days
    # are the grace period. Block at midnight starting the fourth day.
    limite = datetime.combine(tenant.data_expiracao + timedelta(days=4), time.min, BILLING_TIMEZONE)
    bloqueado = now >= limite
    tolerancia = dias < 0 and not bloqueado
    cor = ('vermelho' if bloqueado else 'laranja' if tolerancia else
           'amarelo' if dias <= 3 else 'azul' if dias <= 7 else 'verde')
    segundos = max(0, (limite - now.astimezone(BILLING_TIMEZONE)).total_seconds())
    return SubscriptionStatus(cor, max(0, dias), bloqueado, tolerancia, int((segundos + 3599) // 3600))
