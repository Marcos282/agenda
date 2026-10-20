"""Tenant-scoped reputation; one mutable outcome per reservation."""
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from profissionais.models import Profissional
from usuarios.validators import preparar_whatsapp

from .models import Agendamento, ReputacaoCliente, ReputacaoClienteAuditoria

PONTOS = {'CONCLUIDO': 4, 'ATRASADO': 3, 'DESMARCOU': 2, 'AUSENTE': 0}
TIPOS_AVALIADOS = ('CONCLUIDO', 'ATRASADO', 'AUSENTE')
MIN_AVALIACOES = 3
PESOS_RECENTES = Decimal('0.70')
PESOS_HISTORICO = Decimal('0.30')


def _formatar_estrelas(media):
    preenchimentos = []
    for indice in range(4):
        preenchido = min(max(media - Decimal(indice), Decimal('0')), Decimal('1'))
        preenchimentos.append(int((preenchido * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)))
    return preenchimentos


def resumir(quantidade=0, media=None, *, pontuais=0, atrasos=0, faltas=0,
            media_recente=None, media_historica=None):
    disponivel = quantidade >= MIN_AVALIACOES and media is not None
    if not disponivel:
        return {
            'quantidade': quantidade,
            'pontuais': pontuais,
            'atrasos': atrasos,
            'faltas': faltas,
            'media': None,
            'nota': None,
            'media_recente': media_recente,
            'media_historica': media_historica,
            'estrelas': None,
            'preenchimentos': [],
            'disponivel': False,
            'rotulo': 'Cliente Novo — Reputação em formação',
        }

    nota_bruta = Decimal(str(media))
    nota = nota_bruta.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return {
        'quantidade': quantidade,
        'pontuais': pontuais,
        'atrasos': atrasos,
        'faltas': faltas,
        'media': nota_bruta,
        'nota': nota,
        'media_recente': media_recente,
        'media_historica': media_historica,
        'estrelas': nota_bruta,
        'preenchimentos': _formatar_estrelas(nota_bruta),
        'disponivel': True,
        'rotulo': f'{nota:.2f}/4',
    }


def _resumir_avaliacoes(avaliacoes):
    if not avaliacoes:
        return resumir()

    pontuacoes = [Decimal(pontuacao) for _, pontuacao, _ in avaliacoes]
    quantidade = len(pontuacoes)
    media_historica = sum(pontuacoes, Decimal('0')) / Decimal(quantidade)
    recentes = pontuacoes[-5:]
    media_recente = sum(recentes, Decimal('0')) / Decimal(len(recentes))
    reputacao = PESOS_RECENTES * media_recente + PESOS_HISTORICO * media_historica
    tipos = [tipo for _, _, tipo in avaliacoes]
    return resumir(
        quantidade,
        reputacao,
        pontuais=tipos.count('CONCLUIDO'),
        atrasos=tipos.count('ATRASADO'),
        faltas=tipos.count('AUSENTE'),
        media_recente=media_recente,
        media_historica=media_historica,
    )


def _avaliacoes_validas(query):
    rows = query.filter(
        tipo__in=TIPOS_AVALIADOS,
        agendamento__fim__lte=timezone.now(),
    ).order_by('data_atendimento', 'agendamento_id').values_list(
        'data_atendimento', 'pontuacao', 'tipo',
    )
    return list(rows)


def _resumir_por_whatsapp(tenant, numeros=None):
    query = ReputacaoCliente.objects.for_tenant(tenant)
    if numeros is not None:
        query = query.filter(whatsapp_normalizado__in=numeros)
    rows = query.filter(
        tipo__in=TIPOS_AVALIADOS,
        agendamento__fim__lte=timezone.now(),
    ).order_by('whatsapp_normalizado', 'data_atendimento', 'agendamento_id').values_list(
        'whatsapp_normalizado', 'data_atendimento', 'pontuacao', 'tipo',
    )
    grouped = {}
    for numero, data_atendimento, pontuacao, tipo in rows:
        grouped.setdefault(numero, []).append((data_atendimento, pontuacao, tipo))
    return {numero: _resumir_avaliacoes(avaliacoes) for numero, avaliacoes in grouped.items()}


def calculate_customer_reputation(customer, tenant):
    """Calculate raw reputation for a tenant-scoped WhatsApp identity."""
    raw_number = customer if isinstance(customer, str) else getattr(customer, 'whatsapp', '')
    number = preparar_whatsapp(raw_number)
    if not number:
        return resumir()
    query = ReputacaoCliente.objects.for_tenant(tenant).filter(whatsapp_normalizado=number)
    return _resumir_avaliacoes(_avaliacoes_validas(query))


def reputacoes(tenant, numeros=None):
    return _resumir_por_whatsapp(tenant, numeros)


def numero_agendamento(booking):
    return preparar_whatsapp(booking.cliente_whatsapp or booking.whatsapp_contato)


def reputacao_agendamento(booking, ratings):
    return ratings.get(numero_agendamento(booking), resumir())


def gravar_avaliacao(booking, tipo, *, corrigir=False, administrador=None):
    """Caller must hold the reservation's professional lock."""
    numero = numero_agendamento(booking)
    if not numero:
        return None
    defaults = {
        'tenant': booking.tenant,
        'whatsapp_normalizado': numero,
        'data_atendimento': booking.inicio,
        'tipo': tipo,
        'pontuacao': PONTOS[tipo],
        'registrado_por': administrador,
    }
    rating, created = ReputacaoCliente.objects.get_or_create(agendamento=booking, defaults=defaults)
    if not created and corrigir and (rating.tipo != tipo or rating.pontuacao != PONTOS[tipo]):
        ReputacaoClienteAuditoria.objects.create(
            tenant=rating.tenant,
            reputacao=rating,
            tipo_anterior=rating.tipo,
            pontuacao_anterior=rating.pontuacao,
            tipo_novo=tipo,
            pontuacao_nova=PONTOS[tipo],
            alterado_por=administrador,
        )
        rating.tipo = tipo
        rating.pontuacao = PONTOS[tipo]
        rating.save(update_fields=['tipo', 'pontuacao'])
    return rating


@transaction.atomic
def avaliar_automaticamente(*, tenant, agendamento_id):
    booking = Agendamento.objects.for_tenant(tenant).get(pk=agendamento_id)
    Profissional.objects.for_tenant(tenant).select_for_update().get(pk=booking.profissional_id)
    booking = Agendamento.objects.for_tenant(tenant).select_for_update(of=('self',)).select_related('cliente', 'contato').get(pk=booking.pk)
    if booking.status == 'CANCELADO':
        tipo = 'DESMARCOU'
    elif booking.status == 'NAO_COMPARECEU':
        tipo = 'AUSENTE'
    elif booking.fim <= timezone.now():
        tipo = 'CONCLUIDO'
    else:
        return None
    if not numero_agendamento(booking):
        return None
    return gravar_avaliacao(booking, tipo)


def atualizar_reputacoes(tenant):
    pendentes = Agendamento.objects.for_tenant(tenant).filter(avaliacao_reputacao__isnull=True).filter(
        Q(status__in=['CANCELADO', 'NAO_COMPARECEU']) | Q(status='CONFIRMADO', fim__lte=timezone.now()))
    for pk in pendentes.values_list('pk', flat=True).iterator():
        avaliar_automaticamente(tenant=tenant, agendamento_id=pk)


@transaction.atomic
def registrar_atraso(*, tenant, administrador, agendamento_id):
    if not administrador.is_active or administrador.tipo != 'ADMIN' or administrador.tenant_id != tenant.pk:
        raise PermissionDenied('Apenas administradores deste estabelecimento podem avaliar.')
    booking = Agendamento.objects.for_tenant(tenant).get(pk=agendamento_id)
    Profissional.objects.for_tenant(tenant).select_for_update().get(pk=booking.profissional_id)
    booking = Agendamento.objects.for_tenant(tenant).select_for_update().get(pk=booking.pk)
    if booking.status != 'CONFIRMADO' or booking.inicio > timezone.now():
        raise ValidationError('O atraso só pode ser registrado em atendimento confirmado que já começou.')
    return gravar_avaliacao(booking, 'ATRASADO', corrigir=True, administrador=administrador)


@transaction.atomic
def confirmar_conclusao(*, tenant, administrador, agendamento_id):
    """Explicit confirmation of a performed visit, separate from presumed ratings."""
    from tenants.models import Tenant
    if not administrador.is_active or administrador.tipo != 'ADMIN' or administrador.tenant_id != tenant.pk:
        raise PermissionDenied('Apenas administradores deste estabelecimento podem confirmar o atendimento.')
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    booking = Agendamento.objects.for_tenant(tenant).get(pk=agendamento_id)
    Profissional.objects.for_tenant(tenant).select_for_update().get(pk=booking.profissional_id)
    booking = Agendamento.objects.for_tenant(tenant).select_for_update().get(pk=booking.pk)
    if booking.status != 'CONFIRMADO' or booking.fim > timezone.now():
        raise ValidationError('Só é possível confirmar a conclusão de um atendimento confirmado após seu término.')
    tipo = 'ATRASADO' if ReputacaoCliente.objects.for_tenant(tenant).filter(
        agendamento=booking, tipo='ATRASADO').exists() else 'CONCLUIDO'
    rating = gravar_avaliacao(booking, tipo, corrigir=True, administrador=administrador)
    if not booking.conclusao_confirmada_em:
        booking.conclusao_confirmada_em = timezone.now()
        booking.save(update_fields=['conclusao_confirmada_em', 'atualizado_em'])
    return rating


@transaction.atomic
def corrigir_avaliacao(*, tenant, administrador, agendamento_id, tipo):
    if not administrador.is_active or administrador.tipo != 'ADMIN' or administrador.tenant_id != tenant.pk:
        raise PermissionDenied('Apenas administradores deste estabelecimento podem corrigir avaliações.')
    if tipo not in TIPOS_AVALIADOS:
        raise ValidationError('Tipo de avaliação inválido.')
    booking = Agendamento.objects.for_tenant(tenant).get(pk=agendamento_id)
    Profissional.objects.for_tenant(tenant).select_for_update().get(pk=booking.profissional_id)
    booking = Agendamento.objects.for_tenant(tenant).select_for_update().get(pk=booking.pk)
    if booking.fim > timezone.now():
        raise ValidationError('Só é possível corrigir um atendimento após seu término.')
    rating = ReputacaoCliente.objects.for_tenant(tenant).filter(agendamento=booking).first()
    if rating is None or rating.tipo == 'DESMARCOU':
        raise ValidationError('Não há uma avaliação de atendimento corrigível para este agendamento.')
    return gravar_avaliacao(booking, tipo, corrigir=True, administrador=administrador)
