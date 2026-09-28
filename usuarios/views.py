from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from tenants.decorators import tenant_required
from .forms import CadastroForm, LoginForm


def home(request):
    return render(request, 'usuarios/home.html')


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
