import re
from zoneinfo import ZoneInfo

from django.core.paginator import Paginator
from django.db.models import CharField, Count, Exists, F, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce, Concat, NullIf, Trim
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from agenda.models import Agendamento
from usuarios.models import User, ContatoCliente
from usuarios.validators import normalizar_whatsapp
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


def grupos_por_whatsapp(tenant, termo='', whatsapp=None):
    """One panel identity per number, including account and legacy contact records."""
    clientes = clientes_do_tenant(tenant)
    contatos = ContatoCliente.objects.for_tenant(tenant).annotate(
        nome_exibicao=F('nome'), email=Value('', output_field=CharField()))
    if whatsapp is not None:
        clientes = clientes.filter(whatsapp=whatsapp)
        contatos = contatos.filter(whatsapp=whatsapp)
    scoped = Q(agendamentos__tenant=tenant)
    counts = dict(
        total=Count('agendamentos', filter=scoped),
        confirmados=Count('agendamentos', filter=scoped & Q(agendamentos__status='CONFIRMADO')),
        cancelados=Count('agendamentos', filter=scoped & Q(agendamentos__status='CANCELADO')),
        faltas=Count('agendamentos', filter=scoped & Q(agendamentos__status='NAO_COMPARECEU')),
    )
    columns = ('pk', 'nome_exibicao', 'email', 'whatsapp', 'is_active', 'date_joined',
               'total', 'confirmados', 'cancelados', 'faltas')
    grupos = {}
    digits = re.sub(r'[^0-9]', '', termo) if re.fullmatch(r'[+0-9\s().-]+', termo) else ''
    for origem, queryset, relation in [('conta', clientes, 'cliente_id'), ('contato', contatos, 'contato_id')]:
        history = Agendamento.objects.for_tenant(tenant).filter(**{relation: OuterRef('pk')}, cliente_nome__icontains=termo)
        rows = queryset.annotate(**counts, nome_historico=Exists(history)).values(*columns, 'nome_historico').order_by('pk')
        for row in rows:
            # Blank legacy numbers must never combine unrelated customers.
            key = row['whatsapp'] or (origem, row['pk'])
            matches = not termo or row['nome_historico'] or any(
                termo.casefold() in value.casefold() for value in [row['nome_exibicao'], row['email']]
            ) or bool(digits and digits in row['whatsapp'])
            if key not in grupos:
                grupos[key] = dict(row, origem=origem, corresponde=matches)
            else:
                group = grupos[key]
                for counter in counts:
                    group[counter] += row[counter]
                if group['nome_exibicao'] == group['email'] and row['nome_exibicao'] != row['email']:
                    group['nome_exibicao'] = row['nome_exibicao']
                group['is_active'] |= row['is_active']
                group['date_joined'] = min(group['date_joined'], row['date_joined'])
                group['corresponde'] |= matches
    return sorted((group for group in grupos.values() if group['corresponde']),
                  key=lambda group: (group['nome_exibicao'].casefold(), group['whatsapp'], group['pk']))


def agendamentos_por_whatsapp(tenant, whatsapp):
    return Agendamento.objects.for_tenant(tenant).filter(
        Q(cliente__tenant=tenant, cliente__whatsapp=whatsapp) |
        Q(contato__tenant=tenant, contato__whatsapp=whatsapp))


@admin_tenant_required
@require_http_methods(['GET'])
def lista(request):
    termo = request.GET.get('q', '').strip()[:150]
    return render(request, 'painel/clientes.html', {
        'page_obj': Paginator(grupos_por_whatsapp(request.tenant, termo), 10).get_page(request.GET.get('page')),
        'termo': termo,
    })


def historico_do_numero(request, whatsapp):
    grupos = grupos_por_whatsapp(request.tenant, whatsapp=whatsapp)
    if not grupos:
        raise Http404
    return render_historico(request, grupos[0], agendamentos_por_whatsapp(request.tenant, whatsapp))


@admin_tenant_required
@require_http_methods(['GET'])
def whatsapp_historico(request, whatsapp):
    try:
        numero = normalizar_whatsapp(whatsapp)
    except ValidationError:
        raise Http404
    return historico_do_numero(request, numero)


@admin_tenant_required
@require_http_methods(['GET'])
def historico(request, pk):
    if pk > 9223372036854775807:
        raise Http404
    cliente = get_object_or_404(clientes_do_tenant(request.tenant), pk=pk)
    if cliente.whatsapp:
        return historico_do_numero(request, cliente.whatsapp)
    return render_historico(request, cliente, Agendamento.objects.for_tenant(request.tenant).filter(cliente=cliente))


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
    if cliente.whatsapp:
        return historico_do_numero(request, cliente.whatsapp)
    return render_historico(request, cliente, Agendamento.objects.for_tenant(request.tenant).filter(contato=cliente), contato=True)
