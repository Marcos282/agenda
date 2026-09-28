from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import BaseUserCreationForm
from .models import User


class CadastroForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ("email",)

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tenant = tenant
        self.instance.tipo = User.Tipo.CLIENTE

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data['email'])
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Não foi possível cadastrar este e-mail.")
        return email


class LoginForm(forms.Form):
    email = forms.EmailField(label="E-mail")
    password = forms.CharField(label="Senha", strip=False, widget=forms.PasswordInput)

    def __init__(self, *args, request, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        if data.get('email') and data.get('password'):
            self.user = authenticate(self.request, email=data['email'], password=data['password'])
            if self.user is None:
                raise forms.ValidationError("E-mail ou senha inválidos para este estabelecimento.")
        return data


class EstabelecimentoForm(forms.Form):
    estabelecimento = forms.CharField(label='Endereço do estabelecimento', max_length=63)

    def clean_estabelecimento(self):
        from tenants.models import subdomain_validator
        value = self.cleaned_data['estabelecimento'].strip().lower()
        subdomain_validator(value)
        return value
