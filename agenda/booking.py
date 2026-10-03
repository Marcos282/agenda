"""Reservations use real intervals; suggested times are calculated, never stored."""
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from catalogo.models import ProfissionalServico
from profissionais.models import Profissional
from .models import Agendamento, Disponibilidade


def instante_local(dia, hora, tenant):
    naive = datetime.combine(dia, hora)
    zone = ZoneInfo(tenant.timezone)
    local = naive.replace(tzinfo=zone)
    # Reject nonexistent/ambiguous local times instead of booking the wrong instant.
    utc = local.astimezone(dt_timezone.utc)
    if utc.astimezone(zone).replace(tzinfo=None) != naive or local.utcoffset() != local.replace(fold=1).utcoffset():
        raise ValidationError('Este horário é inválido ou ambíguo no fuso do estabelecimento. Escolha outro horário.')
    return utc


def janelas(tenant, profissional_id, dia):
    result = []
    for period in Disponibilidade.objects.for_tenant(tenant).disponiveis().filter(profissional_id=profissional_id, data=dia):
        try:
            start = instante_local(dia, period.hora_inicio, tenant)
            end = instante_local(dia, period.hora_fim, tenant)
        except ValidationError:
            continue
        if result and result[-1][1] == start:
            result[-1] = (result[-1][0], end)
        else:
            result.append((start, end))
    return result


def horarios_disponiveis(oferta, dia):
    now = timezone.now()
    duration = timedelta(minutes=oferta.duracao_minutos)
    windows = janelas(oferta.tenant, oferta.profissional_id, dia)
    if not windows:
        return []
    occupied = list(Agendamento.objects.for_tenant(oferta.tenant).filter(
        profissional_id=oferta.profissional_id, status__in=['CONFIRMADO', 'NAO_COMPARECEU'],
        inicio__lt=windows[-1][1], fim__gt=windows[0][0],
    ).order_by('inicio'))
    result = []
    zone = ZoneInfo(oferta.tenant.timezone)
    for start, end in windows:
        cursor = max(start, now)
        if cursor.second or cursor.microsecond:
            cursor = cursor.replace(second=0, microsecond=0) + timedelta(minutes=1)
        free = []
        for booking in occupied:
            if booking.fim <= cursor or booking.inicio >= end:
                continue
            if booking.inicio > cursor:
                free.append((cursor, booking.inicio))
            cursor = max(cursor, booking.fim)
        if cursor < end:
            free.append((cursor, end))
        for left, right in free:
            while right - left >= duration:
                local = left.astimezone(zone)
                try:
                    valid = instante_local(dia, local.time(), oferta.tenant) == left
                except ValidationError:
                    valid = False
                if valid:
                    result.append({'hora': local.strftime('%H:%M'), 'fim': (left + duration).astimezone(zone).strftime('%H:%M')})
                left += duration
    return result


def validar_cobertura(*, tenant, profissional_id, data, periodos):
    zone = ZoneInfo(tenant.timezone)
    # Include all confirmed reservations of this local date, even for inactive professionals.
    bookings = Agendamento.objects.for_tenant(tenant).filter(profissional_id=profissional_id, status__in=['CONFIRMADO', 'NAO_COMPARECEU'])
    bounds = []
    for start, end in sorted(periodos):
        left, right = instante_local(data, start, tenant), instante_local(data, end, tenant)
        if bounds and bounds[-1][1] == left:
            bounds[-1] = (bounds[-1][0], right)
        else:
            bounds.append((left, right))
    from django.db.models.functions import TruncDate
    for booking in bookings.annotate(dia_local=TruncDate('inicio', tzinfo=zone)).filter(dia_local=data):
        if booking.inicio.astimezone(zone).date() == data and not any(left <= booking.inicio and booking.fim <= right for left, right in bounds):
            raise ValidationError('Há agendamentos confirmados nesse período. Preserve os horários reservados antes de alterar a agenda.')


def periodos_com_reservas(*, tenant, profissional_id, data, existentes, desejados):
    zone = ZoneInfo(tenant.timezone)
    janelas_desejadas = [
        (instante_local(data, start, tenant), instante_local(data, end, tenant))
        for start, end in desejados
    ]
    bookings = Agendamento.objects.for_tenant(tenant).filter(
        profissional_id=profissional_id, status__in=['CONFIRMADO', 'NAO_COMPARECEU'],
    )
    from django.db.models.functions import TruncDate
    protegidos = set()
    for booking in bookings.annotate(dia_local=TruncDate('inicio', tzinfo=zone)).filter(dia_local=data):
        if booking.inicio.astimezone(zone).date() != data:
            continue
        if any(left <= booking.inicio and booking.fim <= right for left, right in janelas_desejadas):
            continue
        for start, end in existentes:
            left, right = instante_local(data, start, tenant), instante_local(data, end, tenant)
            if left < booking.fim and right > booking.inicio:
                protegidos.add((start, end))
    return protegidos


def validar_limite_agendamentos(*, tenant, whatsapp, dia):
    """Count this number's noncancelled bookings on the chosen local date."""
    from django.db.models import Q
    from django.db.models.functions import TruncDate
    from usuarios.validators import normalizar_whatsapp

    numero = normalizar_whatsapp(whatsapp)
    # The caller holds the tenant lock, including reservations for other professionals.
    agendamentos = Agendamento.objects.for_tenant(tenant).filter(
        Q(cliente_whatsapp=numero) |
        (Q(cliente_whatsapp='') & (Q(cliente__whatsapp=numero) | Q(contato__whatsapp=numero))),
        status__in=['CONFIRMADO', 'NAO_COMPARECEU'],
    )
    quantidade = agendamentos.annotate(dia_local=TruncDate('inicio', tzinfo=ZoneInfo(tenant.timezone))).filter(dia_local=dia).count()
    mensagem_duplicidade = 'No momento não é possível fazer agendamento para esse número, pois já consta agendamento.'
    if quantidade >= tenant.limite_agendamentos_cliente_dia:
        raise ValidationError(mensagem_duplicidade)

    futuros = agendamentos.filter(inicio__gt=timezone.now()).count()
    if futuros >= tenant.limite_agendamentos_cliente_futuros:
        raise ValidationError(mensagem_duplicidade)



@transaction.atomic
def reservar(*, tenant, cliente, oferta_id, dia, hora, nome, valor_exibido, duracao_exibida, contato=None):
    from usuarios.validators import normalizar_whatsapp
    if (cliente is None) == (contato is None):
        raise ValidationError('Informe um cliente ou contato para o agendamento.')
    pessoa = cliente if cliente is not None else contato
    if not pessoa.is_active or pessoa.tenant_id != tenant.pk or not tenant.ativo:
        raise ValidationError('Cliente inválido para este estabelecimento.')
    if not pessoa.whatsapp:
        raise ValidationError('O cliente precisa cadastrar o WhatsApp em Minha conta antes de agendar.')
    numero = normalizar_whatsapp(pessoa.whatsapp)
    from tenants.models import Tenant
    from usuarios.models import WhatsAppBloqueado
    # Serialize blocking and reservations across professionals in this establishment.
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk, ativo=True)
    if WhatsAppBloqueado.objects.for_tenant(tenant).filter(whatsapp=numero).exists():
        raise ValidationError('Este WhatsApp está bloqueado para novos agendamentos neste estabelecimento.')
    validar_limite_agendamentos(tenant=tenant, whatsapp=numero, dia=dia)

    oferta = ProfissionalServico.objects.for_tenant(tenant).get(pk=oferta_id)
    # The same lock is used by daily opening edits and cancellation.
    Profissional.objects.for_tenant(tenant).select_for_update().get(pk=oferta.profissional_id)
    oferta = ProfissionalServico.objects.for_tenant(tenant).disponiveis().select_for_update().select_related('profissional', 'servico').get(pk=oferta_id)
    if str(oferta.valor) != str(valor_exibido) or oferta.duracao_minutos != duracao_exibida:
        raise ValidationError('O preço ou a duração mudou. Confira os dados atualizados e escolha novamente.')
    if hora.second or hora.microsecond:
        raise ValidationError('Escolha um horário sem segundos.')
    inicio = instante_local(dia, hora, tenant)
    if inicio <= timezone.now():
        raise ValidationError('Escolha um horário futuro.')
    duration = timedelta(minutes=oferta.duracao_minutos)
    if not any(left <= inicio and right - inicio >= duration for left, right in janelas(tenant, oferta.profissional_id, dia)):
        raise ValidationError('O serviço não cabe em um período aberto. Escolha outro horário.')
    fim = inicio + duration
    if Agendamento.objects.for_tenant(tenant).filter(profissional_id=oferta.profissional_id, status__in=['CONFIRMADO', 'NAO_COMPARECEU'], inicio__lt=fim, fim__gt=inicio).exists():
        raise ValidationError('Esse horário acabou de ser reservado. Escolha outro horário.')
    booking = Agendamento(tenant=tenant, cliente=cliente, contato=contato, oferta=oferta, profissional=oferta.profissional,
        inicio=inicio, fim=fim, valor=oferta.valor, duracao_minutos=oferta.duracao_minutos,
        cliente_nome=nome, cliente_whatsapp=numero, servico_nome=oferta.servico.nome, profissional_nome=oferta.profissional.nome)
    booking.save()
    from whatsapp.services import enviar_confirmacao_agendamento
    transaction.on_commit(lambda: enviar_confirmacao_agendamento(tenant_id=tenant.pk, agendamento_id=booking.pk), robust=True)
    return booking


@transaction.atomic
def cancelar(*, tenant, cliente, agendamento_id):
    booking = Agendamento.objects.for_tenant(tenant).get(pk=agendamento_id, cliente=cliente)
    Profissional.objects.for_tenant(tenant).select_for_update().get(pk=booking.profissional_id)
    booking = Agendamento.objects.for_tenant(tenant).select_for_update().get(pk=booking.pk, cliente=cliente)
    if booking.status == Agendamento.Status.CANCELADO:
        from .reputation import gravar_avaliacao
        gravar_avaliacao(booking, 'DESMARCOU', corrigir=True)
        return booking
    if booking.status != Agendamento.Status.CONFIRMADO:
        raise ValidationError('Somente agendamentos confirmados podem ser cancelados.')
    if booking.inicio <= timezone.now():
        raise ValidationError('Não é possível cancelar um atendimento que já começou.')
    booking.status = Agendamento.Status.CANCELADO
    booking.cancelado_em = timezone.now()
    booking.save(update_fields=['status', 'cancelado_em', 'atualizado_em'])
    from .reputation import gravar_avaliacao
    gravar_avaliacao(booking, 'DESMARCOU', corrigir=True)
    return booking


def cancelar_pelo_painel(*, tenant, administrador, agendamento_id):
    from django.core.exceptions import PermissionDenied
    if not administrador.is_active or administrador.tipo != 'ADMIN' or administrador.tenant_id != tenant.pk:
        raise PermissionDenied('Apenas administradores deste estabelecimento podem cancelar pelo painel.')
    booking = Agendamento.objects.for_tenant(tenant).select_related('cliente').get(pk=agendamento_id)
    return cancelar(tenant=tenant, cliente=booking.cliente, agendamento_id=booking.pk)


@transaction.atomic
def registrar_falta(*, tenant, administrador, agendamento_id):
    from django.core.exceptions import PermissionDenied
    if not administrador.is_active or administrador.tipo != 'ADMIN' or administrador.tenant_id != tenant.pk:
        raise PermissionDenied('Apenas administradores deste estabelecimento podem registrar faltas.')
    booking = Agendamento.objects.for_tenant(tenant).get(pk=agendamento_id)
    Profissional.objects.for_tenant(tenant).select_for_update().get(pk=booking.profissional_id)
    booking = Agendamento.objects.for_tenant(tenant).select_for_update().get(pk=booking.pk)
    if booking.status == Agendamento.Status.NAO_COMPARECEU:
        from .reputation import gravar_avaliacao
        gravar_avaliacao(booking, 'AUSENTE', corrigir=True)
        return booking
    if booking.status != Agendamento.Status.CONFIRMADO:
        raise ValidationError('Somente agendamentos confirmados podem ser marcados como falta.')
    now = timezone.now()
    if booking.inicio > now:
        raise ValidationError('A falta só pode ser registrada após o horário de início do atendimento.')
    booking.status = Agendamento.Status.NAO_COMPARECEU
    booking.nao_compareceu_em = now
    booking.save(update_fields=['status', 'nao_compareceu_em', 'atualizado_em'])
    from .reputation import gravar_avaliacao
    gravar_avaliacao(booking, 'AUSENTE', corrigir=True)
    return booking


@transaction.atomic
def reservar_por_whatsapp(*, tenant, nome, whatsapp, acesso_publico=False, **dados):
    from uuid import uuid4
    from tenants.models import Tenant
    from usuarios.models import ContatoCliente
    from usuarios.validators import normalizar_whatsapp

    nome = ' '.join(nome.split())
    if not nome or len(nome) > 150:
        raise ValidationError('Informe o nome do cliente, com até 150 caracteres.')
    whatsapp = normalizar_whatsapp(whatsapp)
    # Serialize contact lookup/creation, including requests for different professionals.
    Tenant.objects.select_for_update().get(pk=tenant.pk, ativo=True)
    contato = ContatoCliente.objects.for_tenant(tenant).filter(whatsapp=whatsapp).order_by('pk').first()
    if contato is None:
        contato = ContatoCliente.objects.create(tenant=tenant, nome=nome, whatsapp=whatsapp)
    # Keep the existing contact name; each booking records the name supplied this time.
    booking = reservar(tenant=tenant, cliente=None, contato=contato, nome=nome, **dados)
    if acesso_publico:
        booking.acesso_token = uuid4()
        booking.save(update_fields=['acesso_token'])
    return booking


@transaction.atomic
def reservar_pelo_painel(*, tenant, administrador, nome, whatsapp, **dados):
    from django.core.exceptions import PermissionDenied
    if not administrador.is_active or administrador.tipo != 'ADMIN' or administrador.tenant_id != tenant.pk:
        raise PermissionDenied('Apenas administradores deste estabelecimento podem agendar pelo painel.')
    return reservar_por_whatsapp(tenant=tenant, nome=nome, whatsapp=whatsapp, **dados)
