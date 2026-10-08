from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.http.request import split_domain_port
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_http_methods
from tenants.domains import tenant_base_domain_for_host
from tenants.models import Tenant, subdomain_validator
from .models import User


class RegistroForm(forms.Form):
    subdomain = forms.CharField(label='Subdomínio', max_length=63, widget=forms.TextInput(attrs={'placeholder':'seunegocio', 'autocomplete':'off', 'autocapitalize':'none', 'spellcheck':'false', 'aria-describedby':'domain-suffix'}))
    email = forms.EmailField(label='E-mail', widget=forms.EmailInput(attrs={'autocomplete':'email'}))
    password1 = forms.CharField(label='Senha', strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}), help_text=password_validation.password_validators_help_text_html())
    password2 = forms.CharField(label='Confirmar senha', strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))

    def clean_subdomain(self):
        value = self.cleaned_data['subdomain'].lower()
        subdomain_validator(value)
        if value in {'www', 'admin', 'api', 'mail', 'smtp', 'suporte', 'app', 'painel', 'registro', 'static', 'media', 'localhost'}:
            raise forms.ValidationError('Este subdomínio está reservado. Escolha outro.')
        if Tenant.objects.filter(subdomain=value).exists():
            raise forms.ValidationError('Este subdomínio já está em uso. Escolha outro.')
        return value

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data['email'])
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Não foi possível cadastrar este e-mail. Se já tem uma conta, use a recuperação de senha.')
        return email

    def clean(self):
        data = super().clean()
        password = data.get('password1')
        if password:
            try:
                password_validation.validate_password(password, User(email=data.get('email', '')))
            except ValidationError as exc:
                self.add_error('password1', exc)
        if password and data.get('password2') and password != data['password2']:
            self.add_error('password2', 'As senhas não coincidem.')
        return data


def tenant_login_url(request, tenant, destino='/painel/'):
    _, port = split_domain_port(request.get_host())
    suffix = ':' + port if port else ''
    base_domain = tenant_base_domain_for_host(request.get_host())
    return f'{request.scheme}://{tenant.subdomain}.{base_domain}{suffix}{reverse("login")}?next={destino}'


@require_http_methods(['GET', 'POST'])
def registro(request):
    if request.tenant is not None:
        raise Http404
    form = RegistroForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                tenant = Tenant.objects.create(
                    nome=form.cleaned_data['subdomain'],
                    subdomain=form.cleaned_data['subdomain'],
                    plano=Tenant.Plano.PROFISSIONAL,
                )
                User.objects.create_user(email=form.cleaned_data['email'], password=form.cleaned_data['password1'], tenant=tenant, tipo=User.Tipo.ADMIN)
        except (IntegrityError, ValidationError):
            form.add_error(None, 'Não foi possível concluir o cadastro. Confira se o subdomínio ou o e-mail já está em uso.')
        else:
            request.session['registro_tenant'] = tenant.pk
            return redirect('registro_concluido')
    return render(request, 'usuarios/registro.html', {'form':form})


@require_http_methods(['GET'])
def registro_concluido(request):
    if request.tenant is not None:
        raise Http404
    tenant = Tenant.objects.filter(pk=request.session.get('registro_tenant'), ativo=True).first()
    if not tenant:
        return redirect('registro')
    return render(request, 'usuarios/registro_concluido.html', {'estabelecimento':tenant, 'acesso_url':reverse('login')})


def can_reset(user, request):
    if not user or not user.is_active or not user.tenant_id or not user.tenant.ativo:
        return False
    if request.tenant:
        return user.tenant_id == request.tenant.pk
    return user.tipo == User.Tipo.ADMIN


class RecuperarForm(PasswordResetForm):
    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.fields['email'].label = 'E-mail'

    def get_users(self, email):
        return (user for user in super().get_users(email) if can_reset(user, self.request))


class RecuperarSenha(PasswordResetView):
    form_class = RecuperarForm
    template_name = 'usuarios/recuperar_senha.html'
    email_template_name = 'usuarios/recuperar_email.txt'
    subject_template_name = 'usuarios/recuperar_assunto.txt'
    success_url = reverse_lazy('senha_email_enviado')

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), 'request':self.request}


class RedefinirSenha(PasswordResetConfirmView):
    template_name = 'usuarios/redefinir_senha.html'
    success_url = reverse_lazy('senha_redefinida')

    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        return user if can_reset(user, self.request) else None

    def form_valid(self, form):
        self.request.session['senha_acesso_url'] = tenant_login_url(self.request, self.user.tenant, '/painel/' if self.user.tipo == User.Tipo.ADMIN else '/conta/')
        return super().form_valid(form)


@require_http_methods(['GET'])
def senha_redefinida(request):
    return render(request, 'usuarios/senha_redefinida.html', {'acesso_url':request.session.pop('senha_acesso_url', reverse('home'))})
