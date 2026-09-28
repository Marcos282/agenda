from datetime import date
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from catalogo.models import ProfissionalServico
from tenants.decorators import tenant_required
from .booking import cancelar, horarios_disponiveis, reservar
from .customer_forms import ConfirmarAgendamentoForm, DataAgendamentoForm
from .models import Agendamento


def oferta_publica(request, pk):
    if pk > 9223372036854775807:
        raise Http404
    return get_object_or_404(ProfissionalServico.objects.for_tenant(request.tenant).disponiveis().select_related('servico', 'profissional', 'tenant'), pk=pk)


@tenant_required
@require_http_methods(['GET'])
def escolher_data(request, oferta_id):
    oferta = oferta_publica(request, oferta_id)
    hoje = timezone.localdate(timezone=ZoneInfo(request.tenant.timezone))
    form = DataAgendamentoForm(request.GET or None, initial={'data': hoje})
    if form.is_bound and form.is_valid():
        return redirect('agenda:horarios', oferta_id=oferta.pk, dia=form.cleaned_data['data'].isoformat())
    return render(request, 'agenda/escolher_data.html', {'oferta': oferta, 'form': form, 'hoje': hoje.isoformat()})


@tenant_required
@require_http_methods(['GET', 'POST'])
def horarios(request, oferta_id, dia):
    oferta = oferta_publica(request, oferta_id)
    try:
        data = date.fromisoformat(dia)
    except ValueError:
        raise Http404
    if data.isoformat() != dia:
        raise Http404
    if request.method == 'POST' and not request.user.is_authenticated:
        return redirect(reverse('login') + '?' + urlencode({'next': request.path}))
    quote = signing.dumps({'oferta': oferta.pk, 'valor': str(oferta.valor), 'duracao': oferta.duracao_minutos}, salt='agendamento')
    form = ConfirmarAgendamentoForm(request.POST if request.method == 'POST' else None,
        initial={'nome': request.user.get_full_name() if request.user.is_authenticated else '', 'cotacao': quote,
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
                    request.user.whatsapp = form.cleaned_data['whatsapp']
                    request.user.save(update_fields=['whatsapp'])
                    booking = reservar(tenant=request.tenant, cliente=request.user, oferta_id=oferta.pk,
                        dia=data, hora=form.cleaned_data['hora'], nome=form.cleaned_data['nome'],
                        valor_exibido=quoted['valor'], duracao_exibida=quoted['duracao'])
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
                return redirect('agenda:detalhe', pk=booking.pk)
    return render(request, 'agenda/horarios.html', {
        'oferta': oferta, 'dia': data, 'horarios': horarios_disponiveis(oferta, data), 'form': form,
        'login_url': reverse('login') + '?' + urlencode({'next': request.path}),
        'cadastro_url': reverse('cadastro') + '?' + urlencode({'next': request.path}),
    }, status=status)


@tenant_required
@login_required
@require_http_methods(['GET'])
def meus_agendamentos(request):
    bookings = Agendamento.objects.for_tenant(request.tenant).filter(cliente=request.user).order_by('-inicio', '-pk')
    from django.core.paginator import Paginator
    return render(request, 'agenda/meus_agendamentos.html', {'agendamentos': Paginator(bookings, 15).get_page(request.GET.get('page'))})


@tenant_required
@login_required
@require_http_methods(['GET', 'POST'])
def detalhe(request, pk):
    if pk > 9223372036854775807:
        raise Http404
    booking = get_object_or_404(Agendamento.objects.for_tenant(request.tenant).filter(cliente=request.user), pk=pk)
    error = None
    if request.method == 'POST':
        try:
            cancelar(tenant=request.tenant, cliente=request.user, agendamento_id=booking.pk)
        except ValidationError as exc:
            error = ' '.join(exc.messages)
        else:
            messages.success(request, 'Agendamento cancelado. O horário voltou a ficar disponível.')
            return redirect('agenda:detalhe', pk=booking.pk)
    return render(request, 'agenda/detalhe.html', {'agendamento': booking, 'erro': error,
        'pode_cancelar': booking.status == 'CONFIRMADO' and booking.inicio > timezone.now()}, status=409 if error else 200)
