from io import BytesIO
import re

from PIL import Image, ImageOps
from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.core.files.base import ContentFile
from profissionais.models import Profissional
from catalogo.models import Servico, ProfissionalServico
from agenda.models import Disponibilidade
from usuarios.validators import normalizar_whatsapp


class LimiteAgendamentosForm(forms.Form):
    limite_agendamentos_cliente_dia = forms.IntegerField(
        label='Máximo de agendamentos por WhatsApp por dia', min_value=1, max_value=32767,
        help_text='Escolha 1 para impedir duas ou mais reservas do mesmo WhatsApp no mesmo dia, mesmo com nomes, serviços ou profissionais diferentes. Reservas canceladas não contam.',
        widget=forms.NumberInput(attrs={'min': 1, 'max': 32767}))


class CadastroResponsavelForm(forms.Form):
    first_name = forms.CharField(label='Nome', max_length=150, widget=forms.TextInput(attrs={'autocomplete': 'name'}))
    email = forms.EmailField(label='Login (e-mail)', disabled=True)
    cpf = forms.CharField(
        label='CPF',
        max_length=14,
        widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'off', 'placeholder': '000.000.000-00'}),
    )
    telefone = forms.CharField(
        label='Telefone / WhatsApp',
        max_length=40,
        widget=forms.TextInput(attrs={'type': 'tel', 'autocomplete': 'tel', 'placeholder': '(11) 99999-9999'}),
    )
    endereco = forms.CharField(label='Endereço', max_length=200, widget=forms.TextInput(attrs={'autocomplete': 'address-line1'}))
    bairro = forms.CharField(label='Bairro', max_length=100)
    numero_endereco = forms.CharField(label='Número', max_length=20)
    cidade = forms.CharField(label='Cidade', max_length=100, widget=forms.TextInput(attrs={'autocomplete': 'address-level2'}))
    estado = forms.ChoiceField(
        label='Estado (UF)',
        choices=[('', 'Selecione')] + [(uf, uf) for uf in (
            'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS',
            'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC',
            'SP', 'SE', 'TO',
        )],
        widget=forms.Select(attrs={'autocomplete': 'address-level1'}),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.initial['email'] = user.email
        if not self.is_bound:
            self.initial.update({
                'first_name': user.get_full_name(),
                'cpf': user.cpf,
                'telefone': user.whatsapp,
                'endereco': user.endereco,
                'bairro': user.bairro,
                'numero_endereco': user.numero_endereco,
                'cidade': user.cidade,
                'estado': user.estado,
            })

    def clean_first_name(self):
        return ' '.join(self.cleaned_data['first_name'].split())

    def clean_cpf(self):
        cpf = re.sub(r'\D', '', self.cleaned_data['cpf'])
        if len(cpf) != 11 or len(set(cpf)) == 1:
            raise forms.ValidationError('Informe um CPF válido.')
        primeiro = sum(int(digito) * peso for digito, peso in zip(cpf[:9], range(10, 1, -1))) * 10 % 11
        primeiro = 0 if primeiro == 10 else primeiro
        segundo = sum(int(digito) * peso for digito, peso in zip(cpf[:10], range(11, 1, -1))) * 10 % 11
        segundo = 0 if segundo == 10 else segundo
        if cpf[-2:] != f'{primeiro}{segundo}':
            raise forms.ValidationError('Informe um CPF válido.')
        return cpf

    def clean_telefone(self):
        try:
            return normalizar_whatsapp(self.cleaned_data['telefone'])
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages) from exc

    def save(self):
        self.user.first_name = self.cleaned_data['first_name']
        self.user.last_name = ''
        for field in (
            'cpf', 'endereco', 'bairro', 'numero_endereco', 'cidade', 'estado',
        ):
            setattr(self.user, field, self.cleaned_data[field])
        self.user.whatsapp = self.cleaned_data['telefone']
        self.user.save(update_fields=[
            'first_name', 'last_name', 'cpf', 'whatsapp', 'endereco',
            'bairro', 'numero_endereco', 'cidade', 'estado',
        ])
        return self.user


class TenantForm(forms.ModelForm):
    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tenant = tenant


class ProtectedPhotoInput(forms.ClearableFileInput):
    template_name = 'painel/foto_widget.html'
    photo_url = ''

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['photo_url'] = self.photo_url
        return context


class ProfissionalForm(TenantForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        widget = ProtectedPhotoInput()
        if self.instance.pk:
            widget.photo_url = reverse('painel:profissional_foto', args=[self.instance.pk])
        self.fields['foto'].widget = widget

    class Meta:
        model = Profissional
        fields = ('nome', 'telefone', 'email', 'foto', 'ativo')
        labels = {'email': 'E-mail'}

    def clean_foto(self):
        foto = self.cleaned_data.get('foto')
        if not foto or not hasattr(foto, 'content_type'):
            return foto
        if foto.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Envie uma foto de até 5 MB.')
        foto.seek(0)
        with Image.open(foto) as original:
            if original.width > 4096 or original.height > 4096:
                raise forms.ValidationError('A foto deve ter no máximo 4096 × 4096 pixels.')
            output = BytesIO()
            # Re-encode to a known format, stripping embedded data and metadata.
            ImageOps.exif_transpose(original).convert('RGB').save(output, format='JPEG', quality=85)
        return ContentFile(output.getvalue(), name='foto.jpg')


class ServicoForm(TenantForm):
    class Meta:
        model = Servico
        fields = ('nome', 'ativo')


class ProfissionalServicoForm(TenantForm):
    def __init__(self, *args, profissional, tenant, **kwargs):
        super().__init__(*args, tenant=tenant, **kwargs)
        self.instance.profissional = profissional
        # Existing service is immutable; an inactive link can still be deactivated.
        if self.instance.pk:
            self.fields.pop('servico')
        else:
            vinculados = ProfissionalServico.objects.for_tenant(tenant).filter(
                profissional=profissional).values_list('servico_id', flat=True)
            self.fields['servico'].queryset = Servico.objects.for_tenant(tenant).ativos().exclude(pk__in=vinculados)
            self.fields['servico'].help_text = (
                'Apenas serviços ainda não vinculados aparecem aqui. '
                'Para alterar ou reativar um serviço já vinculado, volte à lista e edite o registro existente.')
            self.fields['servico'].error_messages['invalid_choice'] = (
                'Este serviço já está vinculado ou não está disponível para este profissional. '
                'Volte à lista para editar ou reativar o vínculo existente.')

    class Meta:
        model = ProfissionalServico
        fields = ('servico', 'valor', 'duracao_minutos', 'ativo')
        labels = {'servico': 'Serviço', 'valor': 'Valor (R$)', 'duracao_minutos': 'Duração (minutos)'}


class DisponibilidadeForm(TenantForm):
    def __init__(self, *args, profissional, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.profissional = profissional
        self.fields['data'].help_text = 'Não é possível abrir períodos em uma data passada.'
        if not self.instance.pk:
            from django.utils import timezone
            from zoneinfo import ZoneInfo
            self.fields['data'].widget.attrs['min'] = timezone.localdate(timezone=ZoneInfo(self.instance.tenant.timezone)).isoformat()

    class Meta:
        model = Disponibilidade
        fields = ('data', 'hora_inicio', 'hora_fim', 'ativo')
        labels = {'hora_inicio': 'Início', 'hora_fim': 'Fim'}
        widgets = {
            'data': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'hora_inicio': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
            'hora_fim': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
        }
