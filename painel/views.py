from django.contrib import messages
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from agenda.models import Disponibilidade
from catalogo.models import Servico, ProfissionalServico
from profissionais.models import Profissional
from .decorators import admin_tenant_required
from .forms import CadastroResponsavelForm, ProfissionalForm, ServicoForm, ProfissionalServicoForm, DisponibilidadeForm


CONFLICTS = {
    'disp_sem_sobreposicao': 'Já existe um período ativo sobreposto. Confira os horários.',
    'prof_servico_tenant_unique': 'Este serviço já está vinculado ao profissional. Edite o vínculo existente.',
    'ps_prof_same_tenant_fk': 'Profissional inválido para este estabelecimento.',
    'ps_servico_same_tenant_fk': 'Serviço inválido para este estabelecimento.',
    'disp_prof_same_tenant_fk': 'Profissional inválido para este estabelecimento.',
}


def scoped_object(request, model, pk, **filters):
    query = model.objects.for_tenant(request.tenant).filter(**filters)
    if request.method == 'POST':
        query = query.select_for_update()
    return get_object_or_404(query, pk=pk)


def page(request, query):
    return Paginator(query, 30).get_page(request.GET.get('page'))


def edit_form(request, form, title, back_url, profissional=None):
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                if isinstance(form.instance, ProfissionalServico):
                    # Serializes new links against concurrent service deactivation.
                    Servico.objects.for_tenant(request.tenant).select_for_update().get(pk=form.instance.servico_id)
                form.save()
        except ValidationError as exc:
            form.add_error(None, ' '.join(exc.messages))
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.__cause__, 'diag', None), 'constraint_name', None)
            if constraint not in CONFLICTS:
                raise
            form.add_error(None, CONFLICTS[constraint])
        else:
            messages.success(request, 'Alterações salvas.')
            return redirect(back_url)
    return render(request, 'painel/form.html', {
        'form': form, 'titulo': title, 'voltar': back_url, 'profissional': profissional,
    })


@admin_tenant_required
@require_http_methods(['GET'])
def inicio(request):
    return render(request, 'painel/inicio.html')


@admin_tenant_required
@require_http_methods(['GET', 'POST'])
def meu_cadastro(request):
    form = CadastroResponsavelForm(
        request.POST if request.method == 'POST' else None,
        user=request.user,
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Cadastro salvo com sucesso.')
        return redirect('painel:meu_cadastro')
    return render(request, 'painel/meu_cadastro.html', {
        'form': form,
        'endereco_publico': f'{request.tenant.subdomain}.{settings.STORE_BASE_DOMAIN}',
    })


@admin_tenant_required
@require_http_methods(['GET'])
def profissionais(request):
    return render(request, 'painel/profissionais.html', {
        'page_obj': page(request, Profissional.objects.for_tenant(request.tenant)),
    })


@admin_tenant_required
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def profissional_editar(request, pk=None):
    instance = scoped_object(request, Profissional, pk) if pk is not None else None
    form = ProfissionalForm(request.POST if request.method == 'POST' else None, request.FILES or None,
                            tenant=request.tenant, instance=instance)
    return edit_form(request, form, 'Editar profissional' if instance else 'Novo profissional', reverse('painel:profissionais'))


@admin_tenant_required
@require_http_methods(['GET'])
def profissional_foto(request, pk):
    profissional = scoped_object(request, Profissional, pk)
    if not profissional.foto:
        raise Http404
    try:
        response = FileResponse(profissional.foto.open('rb'), content_type='image/jpeg')
    except FileNotFoundError:
        raise Http404
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@admin_tenant_required
@require_http_methods(['GET'])
def servicos(request):
    return render(request, 'painel/servicos.html', {'page_obj': page(request, Servico.objects.for_tenant(request.tenant))})


@admin_tenant_required
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def servico_editar(request, pk=None):
    instance = scoped_object(request, Servico, pk) if pk is not None else None
    form = ServicoForm(request.POST if request.method == 'POST' else None, tenant=request.tenant, instance=instance)
    return edit_form(request, form, 'Editar serviço' if instance else 'Novo serviço', reverse('painel:servicos'))


@admin_tenant_required
@require_http_methods(['GET'])
def vinculos(request, profissional_id):
    profissional = scoped_object(request, Profissional, profissional_id)
    query = ProfissionalServico.objects.for_tenant(request.tenant).filter(profissional=profissional).select_related('servico')
    return render(request, 'painel/vinculos.html', {'profissional': profissional, 'page_obj': page(request, query)})


@admin_tenant_required
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def vinculo_editar(request, profissional_id, pk=None):
    profissional = scoped_object(request, Profissional, profissional_id)
    instance = scoped_object(request, ProfissionalServico, pk, profissional=profissional) if pk is not None else None
    form = ProfissionalServicoForm(request.POST if request.method == 'POST' else None,
                                    tenant=request.tenant, profissional=profissional, instance=instance)
    return edit_form(request, form, 'Editar serviço do profissional' if instance else 'Adicionar serviço',
                     reverse('painel:vinculos', args=[profissional.pk]), profissional)


@admin_tenant_required
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def disponibilidade_editar(request, profissional_id, pk=None):
    profissional = scoped_object(request, Profissional, profissional_id)
    instance = scoped_object(request, Disponibilidade, pk, profissional=profissional) if pk is not None else None
    form = DisponibilidadeForm(request.POST if request.method == 'POST' else None,
                               tenant=request.tenant, profissional=profissional, instance=instance)
    return edit_form(request, form, 'Editar período' if instance else 'Abrir período',
                     reverse('painel:disponibilidades', args=[profissional.pk]), profissional)


@admin_tenant_required
@require_http_methods(['GET', 'POST'])
def configuracoes(request):
    # Retired configuration: keep old bookmarks useful without mutating legacy data.
    if request.method == 'POST':
        from django.http import HttpResponseGone
        return HttpResponseGone('A configuração de grade foi descontinuada. Use a agenda diária.')
    return redirect('painel:agenda')
