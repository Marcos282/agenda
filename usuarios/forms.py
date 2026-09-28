from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import BaseUserCreationForm
from .models import User
from .validators import normalizar_whatsapp


class WhatsAppField(forms.CharField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('label', 'WhatsApp')
        kwargs.setdefault('max_length', 40)
        kwargs.setdefault('widget', forms.TextInput(attrs={'type': 'tel', 'autocomplete': 'tel', 'placeholder': '(11) 99999-9999'}))
        kwargs.setdefault('help_text', 'Informe DDD e número. Para um número internacional, inclua + e o código do país.')
        super().__init__(*args, **kwargs)

    def clean(self, value):
        return normalizar_whatsapp(super().clean(value))


class WhatsAppForm(forms.ModelForm):
    whatsapp = WhatsAppField()

    class Meta:
        model = User
        fields = ('whatsapp',)


class CadastroForm(BaseUserCreationForm):
    whatsapp = WhatsAppField()

    class Meta:
        model = User
        fields = ("email", "whatsapp")
        labels = {"email": "E-mail"}

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
