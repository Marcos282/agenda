from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from catalogo.models import ProfissionalServico
from tenants.decorators import tenant_required
from .booking import cancelar, horarios_disponiveis, reservar, reservar_por_whatsapp
from .customer_forms import ConfirmarAgendamentoForm, DataAgendamentoForm
from .models import Agendamento


def oferta_publica(request, pk):
    if pk > 9223372036854775807:
        raise Http404
    return get_object_or_404(ProfissionalServico.objects.for_tenant(request.tenant).disponiveis().select_related('servico', 'profissional', 'tenant'), pk=pk)


def data_horarios(value):
    try:
        data = date.fromisoformat(value)
    except ValueError:
        raise Http404
    if data.isoformat() != value:
        raise Http404
    return data


@tenant_required
@never_cache
@require_http_methods(['GET'])
def escolher_data(request, oferta_id):
    oferta = oferta_publica(request, oferta_id)
    hoje = timezone.localdate(timezone=ZoneInfo(request.tenant.timezone))
    try:
        dia = max(hoje, date.fromisoformat(request.GET.get('dia', hoje.isoformat())))
    except ValueError:
        dia = hoje
    form = DataAgendamentoForm(request.GET if 'data' in request.GET else None, initial={'data': dia})
    if form.is_bound and form.is_valid():
        return redirect('agenda:horarios', oferta_id=oferta.pk, dia=form.cleaned_data['data'].isoformat())
    return render(request, 'agenda/escolher_data.html', {
        'oferta': oferta, 'form': form, 'hoje': hoje.isoformat(), 'dia_selecionado': dia,
        'horarios': horarios_disponiveis(oferta, dia),
        'dia_anterior': dia - timedelta(days=1) if dia > hoje else None,
        'proximo_dia': dia + timedelta(days=1) if dia < date.max else None,
    })


@tenant_required
@never_cache
@require_http_methods(['GET'])
def horarios_atualizar(request, oferta_id, dia):
    oferta = oferta_publica(request, oferta_id)
    data = data_horarios(dia)
    return JsonResponse({'horarios': horarios_disponiveis(oferta, data)})


@tenant_required
@never_cache
@require_http_methods(['GET', 'POST'])
def horarios(request, oferta_id, dia):
    oferta = oferta_publica(request, oferta_id)
    data = data_horarios(dia)
    quote = signing.dumps({'oferta': oferta.pk, 'valor': str(oferta.valor), 'duracao': oferta.duracao_minutos}, salt='agendamento')
    form = ConfirmarAgendamentoForm(request.POST if request.method == 'POST' else None,
        initial={'nome': request.user.get_full_name() if request.user.is_authenticated else '', 'cotacao': quote,
                 'hora': request.GET.get('hora', ''),
                 'whatsapp': request.user.whatsapp if request.user.is_authenticated else ''})
    status = 200
    if request.method == 'POST':
        status = 400
        if form.is_valid():
            try:
                quoted = signing.loads(form.cleaned_data['cotacao'], salt='agendamento', max_age=86400)
                if quoted['oferta'] != oferta.pk:
                    raise signing.BadSignature
                with transaction.atomic():
                    dados = dict(tenant=request.tenant, oferta_id=oferta.pk,
                        dia=data, hora=form.cleaned_data['hora'], nome=form.cleaned_data['nome'],
                        valor_exibido=quoted['valor'], duracao_exibida=quoted['duracao'])
                    if request.user.is_authenticated:
                        request.user.whatsapp = form.cleaned_data['whatsapp']
                        request.user.save(update_fields=['whatsapp'])
                        booking = reservar(cliente=request.user, **dados)
                    else:
                        booking = reservar_por_whatsapp(whatsapp=form.cleaned_data['whatsapp'], acesso_publico=True, **dados)
            except signing.BadSignature:
                form.add_error(None, 'A seleção expirou. Recarregue a página e escolha o horário novamente.')
            except ValidationError as exc:
                form.add_error(None, exc)
                status = 409
            except ProfissionalServico.DoesNotExist:
                form.add_error(None, 'Este serviço não está mais disponível.')
                status = 409
            except IntegrityError as exc:
                if getattr(getattr(exc.__cause__, 'diag', None), 'constraint_name', None) != 'ag_sem_sobreposicao':
                    raise
                form.add_error(None, 'Esse horário acabou de ser reservado. Escolha outro horário.')
                status = 409
            else:
                messages.success(request, 'Agendamento confirmado! Seu horário está reservado.')
                if booking.acesso_token:
                    lembrar_reserva(request, booking)
                    return redirect('agenda:acompanhar', token=booking.acesso_token)
                return redirect('agenda:detalhe', pk=booking.pk)
    return render(request, 'agenda/horarios.html', {
        'oferta': oferta, 'dia': data, 'horarios': horarios_disponiveis(oferta, data), 'form': form,
    }, status=status)


@tenant_required
@never_cache
@require_http_methods(['GET'])
def meus_agendamentos(request):
    bookings = reservas_acessiveis(request).order_by('-inicio', '-pk')
    from django.core.paginator import Paginator
    return render(request, 'agenda/meus_agendamentos.html', {'agendamentos': Paginator(bookings, 15).get_page(request.GET.get('page'))})


@tenant_required
@never_cache
@require_http_methods(['GET', 'POST'])
def detalhe(request, pk):
    if pk > 9223372036854775807:
        raise Http404
    booking = get_object_or_404(reservas_acessiveis(request), pk=pk)
    link = request.build_absolute_uri(reverse('agenda:acompanhar', args=[booking.acesso_token])) if booking.acesso_token else None
    return render_detalhe(request, booking, link)


def render_detalhe(request, booking, link_acesso=None):
    error = None
    if request.method == 'POST':
        try:
            cancelar(tenant=request.tenant, cliente=booking.cliente, agendamento_id=booking.pk)
        except ValidationError as exc:
            error = ' '.join(exc.messages)
        else:
            messages.success(request, 'Agendamento cancelado. O horário voltou a ficar disponível.')
            return redirect(request.path)
    return render(request, 'agenda/detalhe.html', {'agendamento': booking, 'erro': error,
        'link_acesso': link_acesso,
        'pode_cancelar': booking.status == 'CONFIRMADO' and booking.inicio > timezone.now()}, status=409 if error else 200)


def lembrar_reserva(request, booking):
    key = f'reservas_visitante_{request.tenant.pk}'
    ids = request.session.get(key, [])
    request.session[key] = [pk for pk in ids if pk != booking.pk][-99:] + [booking.pk]


def reservas_acessiveis(request):
    ids = request.session.get(f'reservas_visitante_{request.tenant.pk}', [])
    allowed = Q(pk__in=ids, acesso_token__isnull=False, cliente__isnull=True)
    if request.user.is_authenticated:
        allowed |= Q(cliente=request.user)
    return Agendamento.objects.for_tenant(request.tenant).filter(allowed)


@tenant_required
@never_cache
@require_http_methods(['GET', 'POST'])
def acompanhar(request, token):
    booking = get_object_or_404(Agendamento.objects.for_tenant(request.tenant),
        acesso_token=token, cliente__isnull=True)
    lembrar_reserva(request, booking)
    response = render_detalhe(request, booking, request.build_absolute_uri(request.path))
    response['Referrer-Policy'] = 'same-origin'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response
