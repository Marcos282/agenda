"""Tenant-scoped reputation; one mutable outcome per reservation."""
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone
from profissionais.models import Profissional
from usuarios.validators import normalizar_whatsapp
from .models import Agendamento, ReputacaoCliente

PONTOS = {'CONCLUIDO': 4, 'ATRASADO': 3, 'DESMARCOU': 2, 'AUSENTE': 1}
MIN_AVALIACOES = 3
LIMITES_ESTRELAS = ((Decimal('3.5'), 4), (Decimal('2.5'), 3), (Decimal('1.5'), 2), (Decimal('0'), 1))


def resumir(quantidade=0, media=None):
    estrelas = None
    if quantidade >= MIN_AVALIACOES:
        estrelas = next(n for limite, n in LIMITES_ESTRELAS if Decimal(str(media)) >= limite)
    simbolos = '★' * estrelas + '☆' * (4 - estrelas) if estrelas else 'Cliente Novo'
    return {'quantidade': quantidade, 'media': media, 'estrelas': estrelas, 'rotulo': simbolos}


def reputacoes(tenant, numeros=None):
    query = ReputacaoCliente.objects.for_tenant(tenant)
    if numeros is not None:
        query = query.filter(whatsapp_normalizado__in=numeros)
    return {row['whatsapp_normalizado']: resumir(row['quantidade'], row['media']) for row in
            query.values('whatsapp_normalizado').annotate(quantidade=Count('pk'), media=Avg('pontuacao'))}


def numero_agendamento(booking):
    return normalizar_whatsapp(booking.cliente_whatsapp or booking.whatsapp_contato)


def reputacao_agendamento(booking, ratings):
    try:
        return ratings.get(numero_agendamento(booking), resumir())
    except ValidationError:
        return resumir()


def gravar_avaliacao(booking, tipo, *, corrigir=False):
    """Caller must hold the reservation's professional lock."""
    try:
        numero = numero_agendamento(booking)
    except ValidationError:
        return None  # Legacy reservations without a valid identity remain unrated.
    defaults = {'tenant': booking.tenant, 'whatsapp_normalizado': numero, 'tipo': tipo, 'pontuacao': PONTOS[tipo]}
    rating, created = ReputacaoCliente.objects.get_or_create(agendamento=booking, defaults=defaults)
    if not created and corrigir and rating.tipo != tipo:
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
    # Legacy records with no valid number remain unrated, never merged.
    try:
        numero_agendamento(booking)
    except ValidationError:
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
    return gravar_avaliacao(booking, 'ATRASADO', corrigir=True)


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
    # Preserve a manual late outcome while correcting any stale presumed rating.
    tipo = 'ATRASADO' if ReputacaoCliente.objects.for_tenant(tenant).filter(
        agendamento=booking, tipo='ATRASADO').exists() else 'CONCLUIDO'
    rating = gravar_avaliacao(booking, tipo, corrigir=True)
    if not booking.conclusao_confirmada_em:
        booking.conclusao_confirmada_em = timezone.now()
        booking.save(update_fields=['conclusao_confirmada_em', 'atualizado_em'])
    return rating
