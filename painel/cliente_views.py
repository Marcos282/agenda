import re
from zoneinfo import ZoneInfo

from django.core.paginator import Paginator
from django.db.models import CharField, Count, Exists, F, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce, Concat, NullIf, Trim
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from agenda.models import Agendamento
from usuarios.models import User, ContatoCliente
from .agenda_views import agenda_url
from .decorators import admin_tenant_required


def clientes_do_tenant(tenant):
    history = Agendamento.objects.for_tenant(tenant).filter(cliente_id=OuterRef('pk'))
    # Keep former customers with booking history visible even if their role changes.
    return User.objects.filter(tenant=tenant).annotate(
        tem_historico=Exists(history),
        nome_conta=Trim(Concat('first_name', Value(' '), 'last_name')),
        nome_exibicao=Coalesce(
            NullIf(Trim(Concat('first_name', Value(' '), 'last_name')), Value('')),
            Subquery(history.order_by('-criado_em', '-pk').values('cliente_nome')[:1]),
            'email', output_field=CharField(),
        ),
    ).filter(Q(tipo=User.Tipo.CLIENTE) | Q(tem_historico=True))


@admin_tenant_required
@require_http_methods(['GET'])
def lista(request):
    termo = request.GET.get('q', '').strip()[:150]
    clientes = clientes_do_tenant(request.tenant)
    if termo:
        historico = Agendamento.objects.for_tenant(request.tenant).filter(cliente_id=OuterRef('pk'), cliente_nome__icontains=termo)
        clientes = clientes.annotate(nome_historico=Exists(historico))
        match = Q(nome_conta__icontains=termo) | Q(email__icontains=termo) | Q(nome_historico=True)
        if re.fullmatch(r'[+0-9\s().-]+', termo):
            digits = re.sub(r'[^0-9]', '', termo)
            if digits:
                match |= Q(whatsapp__contains=digits)
        clientes = clientes.filter(match)
    scoped = Q(agendamentos__tenant=request.tenant)
    clientes = clientes.annotate(
        total=Count('agendamentos', filter=scoped),
        faltas=Count('agendamentos', filter=scoped & Q(agendamentos__status='NAO_COMPARECEU')),
        origem=Value('conta', output_field=CharField()),
    )
    contatos = ContatoCliente.objects.for_tenant(request.tenant)
    if termo:
        contact_match = Q(nome__icontains=termo)
        if re.fullmatch(r'[+0-9\s().-]+', termo):
            digits = re.sub(r'[^0-9]', '', termo)
            if digits:
                contact_match |= Q(whatsapp__contains=digits)
        contatos = contatos.filter(contact_match)
    contatos = contatos.annotate(nome_exibicao=F('nome'), email=Value('', output_field=CharField()),
        total=Count('agendamentos', filter=scoped),
        faltas=Count('agendamentos', filter=scoped & Q(agendamentos__status='NAO_COMPARECEU')),
        origem=Value('contato', output_field=CharField()))
    columns = ('pk', 'nome_exibicao', 'email', 'whatsapp', 'is_active', 'total', 'faltas', 'origem')
    clientes = clientes.values(*columns).union(contatos.values(*columns), all=True).order_by('nome_exibicao', 'origem', 'pk')
    return render(request, 'painel/clientes.html', {
        'page_obj': Paginator(clientes, 10).get_page(request.GET.get('page')), 'termo': termo,
    })


@admin_tenant_required
@require_http_methods(['GET'])
def historico(request, pk):
    if pk > 9223372036854775807:
        raise Http404
    cliente = get_object_or_404(clientes_do_tenant(request.tenant), pk=pk)
    bookings = Agendamento.objects.for_tenant(request.tenant).filter(cliente=cliente)
    return render_historico(request, cliente, bookings)


def render_historico(request, cliente, bookings, contato=False):
    resumo = bookings.aggregate(total=Count('pk'), confirmados=Count('pk', filter=Q(status='CONFIRMADO')),
        cancelados=Count('pk', filter=Q(status='CANCELADO')), faltas=Count('pk', filter=Q(status='NAO_COMPARECEU')))
    page = Paginator(bookings.order_by('-inicio', '-pk'), 15).get_page(request.GET.get('page'))
    for booking in page:
        day = timezone.localtime(booking.inicio, ZoneInfo(request.tenant.timezone)).date()
        booking.link_agenda = agenda_url(booking.profissional_id, day)
    return render(request, 'painel/cliente_historico.html', {'cliente': cliente, 'page_obj': page, 'resumo': resumo, 'contato': contato})



@admin_tenant_required
@require_http_methods(['GET'])
def contato_historico(request, pk):
    if pk > 9223372036854775807:
        raise Http404
    cliente = get_object_or_404(ContatoCliente.objects.for_tenant(request.tenant).annotate(nome_exibicao=F('nome')), pk=pk)
    bookings = Agendamento.objects.for_tenant(request.tenant).filter(contato=cliente)
    return render_historico(request, cliente, bookings, contato=True)
