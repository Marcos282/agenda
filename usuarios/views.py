from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from tenants.decorators import tenant_required
from .forms import CadastroForm, LoginForm


@require_http_methods(["GET"])
def home(request, profissional_id=None):
    from django.conf import settings
    from django.core.paginator import Paginator
    from django.db.models import Count, Q
    from django.http.request import split_domain_port
    from catalogo.models import ProfissionalServico
    from profissionais.models import Profissional
    from tenants.models import Tenant
    from .forms import EstabelecimentoForm

    if request.tenant is None and profissional_id is not None:
        from django.http import Http404
        raise Http404

    if request.tenant is None:
        form = EstabelecimentoForm(request.GET if 'estabelecimento' in request.GET else None)
        if form.is_bound and form.is_valid():
            tenant = Tenant.objects.filter(subdomain=form.cleaned_data['estabelecimento'], ativo=True).first()
            if tenant:
                _, port = split_domain_port(request.get_host())
                suffix = ':' + port if port else ''
                return redirect(f'{request.scheme}://{tenant.subdomain}.{settings.TENANT_BASE_DOMAIN}{suffix}/')
            form.add_error('estabelecimento', 'Estabelecimento não encontrado. Confira o endereço informado.')
        return render(request, 'usuarios/plataforma.html', {
            'estabelecimento_form': form,
            'sales_url': getattr(settings, 'PLATFORM_SALES_URL', ''),
        })

    ofertas = ProfissionalServico.objects.for_tenant(request.tenant).disponiveis().select_related('profissional', 'servico')
    total_servicos = ofertas.values('servico_id').distinct().count()
    equipe = Profissional.objects.for_tenant(request.tenant).ativos().annotate(
        total_servicos=Count('servicos', filter=Q(servicos__ativo=True, servicos__servico__ativo=True, servicos__tenant=request.tenant))
    )
    termo = request.GET.get('q', '').strip()[:100]
    from django.http import Http404
    from django.shortcuts import get_object_or_404
    from django.urls import reverse

    # Canonicalize old links and the filter form to the professional route.
    if 'profissional' in request.GET:
        selected = request.GET['profissional']
        if selected and (not selected.isdecimal() or len(selected) > 18):
            raise Http404
        destination = reverse('home_profissional', args=[int(selected)]) if selected else reverse('home')
        params = request.GET.copy()
        params.pop('profissional')
        for key in list(params):
            if not params[key]:
                params.pop(key)
        query = params.urlencode()
        return redirect(destination + ('?' + query if query else '') + '#servicos')
    if profissional_id is not None:
        if profissional_id > 9223372036854775807:
            raise Http404
        profissional = get_object_or_404(equipe, pk=profissional_id)
        ofertas = ofertas.filter(profissional=profissional)
    if termo:
        ofertas = ofertas.filter(Q(servico__nome__icontains=termo) | Q(profissional__nome__icontains=termo))
    return render(request, 'usuarios/home.html', {
        'ofertas': Paginator(ofertas.order_by('servico__nome', 'profissional__nome', 'pk'), 9).get_page(request.GET.get('page')),
        'equipe': equipe, 'total_servicos': total_servicos, 'total_profissionais': equipe.count(),
        'termo': termo, 'profissional_selecionado': str(profissional_id) if profissional_id is not None else '',
    })


@tenant_required
@require_http_methods(["GET", "POST"])
def cadastro(request):
    if request.user.is_authenticated:
        return redirect('conta')
    form = CadastroForm(request.POST if request.method == 'POST' else None, tenant=request.tenant)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError as exc:
            # A simultaneous registration can pass form validation before the unique check.
            name = getattr(getattr(exc.__cause__, 'diag', None), 'constraint_name', None)
            if name not in {'user_email_ci_unique', 'usuarios_user_email_key'}:
                raise
            form.add_error('email', 'Não foi possível cadastrar este e-mail.')
        else:
            return redirect('login')
    return render(request, 'usuarios/form.html', {'form': form, 'titulo': 'Criar conta', 'botao': 'Cadastrar'})


@tenant_required
@require_http_methods(["GET", "POST"])
def entrar(request):
    if request.user.is_authenticated:
        return redirect('conta')
    form = LoginForm(request.POST if request.method == 'POST' else None, request=request)
    if request.method == 'POST' and form.is_valid():
        login(request, form.user)
        return redirect('conta')
    return render(request, 'usuarios/form.html', {'form': form, 'titulo': 'Entrar', 'botao': 'Entrar'})


@tenant_required
@login_required
def conta(request):
    return render(request, 'usuarios/conta.html')


sair = tenant_required(LogoutView.as_view())


@tenant_required
@require_http_methods(['GET'])
def loja(request, item_id=None):
    from django.core.paginator import Paginator
    from django.db.models import Q
    from django.http import QueryDict
    from django.shortcuts import get_object_or_404
    from catalogo.models import ProfissionalServico
    from profissionais.models import Profissional

    catalogo = ProfissionalServico.objects.for_tenant(request.tenant).disponiveis().select_related('servico', 'profissional')
    item = get_object_or_404(catalogo, pk=item_id) if item_id is not None else None
    termo = request.GET.get('q', '').strip()[:100]
    profissional = request.GET.get('profissional', '')
    ordem = request.GET.get('ordem', 'nome')
    ordenacoes = {'nome': ('servico__nome', 'pk'), 'menor-preco': ('valor', 'pk'),
                  'maior-preco': ('-valor', 'pk'), 'duracao': ('duracao_minutos', 'pk')}
    if ordem not in ordenacoes:
        ordem = 'nome'
    ofertas = catalogo.exclude(pk=item.pk) if item else catalogo
    if termo:
        ofertas = ofertas.filter(Q(servico__nome__icontains=termo) | Q(profissional__nome__icontains=termo))
    if profissional:
        if not profissional.isdecimal() or len(profissional) > 18:
            ofertas = ofertas.none()
        else:
            ofertas = ofertas.filter(profissional_id=int(profissional))
    filtros = QueryDict(mutable=True)
    filtros.update({'q': termo, 'profissional': profissional, 'ordem': ordem})
    return render(request, 'usuarios/loja.html', {
        'item': item, 'ofertas': Paginator(ofertas.order_by(*ordenacoes[ordem]), 12).get_page(request.GET.get('page')),
        'equipe': Profissional.objects.for_tenant(request.tenant).ativos(),
        'termo': termo, 'profissional_selecionado': profissional, 'ordem': ordem, 'filtros': filtros.urlencode(),
    })
