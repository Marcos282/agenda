"""Owner notices through the existing Evolution transport, never customer reminders."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from tenants.models import Tenant
from tenants.subscriptions import subscription_status
from usuarios.validators import normalizar_whatsapp
from .models import AvisoAssinatura
from .providers import get_provider
from .evolution import configured

MESSAGES = {
    'antes': 'Olá! Sua assinatura do Tá Combinado vence em 3 dias. Renove para continuar recebendo agendamentos normalmente.',
    'vencimento': 'Olá! Sua assinatura do Tá Combinado venceu. Você possui 3 dias de tolerância para realizar a renovação.',
    'bloqueio': 'Olá! Sua assinatura do Tá Combinado está expirada e os novos agendamentos foram temporariamente suspensos. Regularize sua assinatura para reativar o serviço.',
}


def enviar_aviso_assinatura(tenant_id, *, now=None):
    if not configured():
        return False
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=tenant_id)
        if not tenant.ativo:
            return False
        state = subscription_status(tenant, now=now)
        etapa = ('bloqueio' if state.bloqueado else 'vencimento' if state.dias == 0 and not state.tolerancia
                 else 'antes' if state.dias == 3 else None)
        if etapa is None:
            return False
        try:
            number = normalizar_whatsapp(tenant.telefone)
        except ValidationError:
            return False
        claim, created = AvisoAssinatura.objects.get_or_create(
            tenant=tenant, data_expiracao=tenant.data_expiracao, etapa=etapa)
        if not created:
            return False
    # The claim is committed before contacting the provider. Never retry an
    # uncertain delivery automatically, including after a process crash.
    try:
        get_provider().send_text(tenant, number, MESSAGES[etapa])
    except Exception:
        claim.status = 'INCERTO'
    else:
        claim.status = 'ENVIADO'
        claim.enviado_em = timezone.now()
    claim.save(update_fields=['status', 'enviado_em'])
    return claim.status == 'ENVIADO'
