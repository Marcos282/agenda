"""Atomic daily configuration preserving confirmed reservations."""
import hashlib
import hmac
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from profissionais.models import Profissional
from .models import Disponibilidade


def revisao_dia(periodos):
    value = '|'.join(f'{p.pk}:{p.hora_inicio}:{p.hora_fim}:{p.atualizado_em.isoformat()}' for p in periodos)
    return hashlib.sha256(value.encode()).hexdigest()


@transaction.atomic
def configurar_dia(*, tenant, profissional_id, data, periodos, revisao):
    profissional = Profissional.objects.for_tenant(tenant).select_for_update().get(pk=profissional_id)
    query = Disponibilidade.objects.for_tenant(tenant).filter(profissional=profissional, data=data, ativo=True)
    atuais = list(query.select_for_update().order_by('hora_inicio', 'pk'))
    if not hmac.compare_digest(revisao_dia(atuais).encode(), (revisao or '').encode()):
        raise ValidationError('A agenda foi alterada em outra tela. Recarregue a página antes de salvar novamente.')
    if periodos and not profissional.ativo:
        raise ValidationError('Este profissional está inativo. Ative-o antes de abrir a agenda.')
    periodos = sorted(periodos)
    existentes = {(p.hora_inicio, p.hora_fim) for p in atuais}
    from .validation import validar_inicio_abertura
    previous_end = None
    for start, end in periodos:
        if (start, end) not in existentes:
            validar_inicio_abertura(tenant=tenant, data=data)
        if start >= end:
            raise ValidationError('O fim de cada período deve ser posterior ao início.')
        if previous_end is not None and start < previous_end:
            raise ValidationError('Os períodos se sobrepõem.')
        previous_end = end
    from .booking import periodos_com_reservas, validar_cobertura
    preservados = periodos_com_reservas(
        tenant=tenant, profissional_id=profissional.pk, data=data,
        existentes=[(p.hora_inicio, p.hora_fim) for p in atuais], desejados=periodos,
    )
    periodos = sorted([*periodos, *preservados])
    sem_sobreposicao = []
    for start, end in periodos:
        if sem_sobreposicao and start < sem_sobreposicao[-1][1]:
            previous_start, previous_end = sem_sobreposicao[-1]
            sem_sobreposicao[-1] = (previous_start, max(previous_end, end))
        else:
            sem_sobreposicao.append((start, end))
    periodos = sem_sobreposicao
    validar_cobertura(tenant=tenant, profissional_id=profissional.pk, data=data, periodos=periodos)
    desejados = set(periodos)
    removidos = [p.pk for p in atuais if (p.hora_inicio, p.hora_fim) not in desejados]
    query.filter(pk__in=removidos).update(ativo=False, atualizado_em=timezone.now())
    for inicio, fim in periodos:
        if (inicio, fim) not in existentes:
            Disponibilidade.objects.create(
                tenant=tenant, profissional=profissional, data=data,
                hora_inicio=inicio, hora_fim=fim, ativo=True,
            )
