from io import BytesIO
from PIL import Image, ImageOps
from django import forms
from django.urls import reverse
from django.core.files.base import ContentFile
from profissionais.models import Profissional
from catalogo.models import Servico, ProfissionalServico
from agenda.models import Disponibilidade


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
            self.fields['servico'].queryset = Servico.objects.for_tenant(tenant).ativos()

    class Meta:
        model = ProfissionalServico
        fields = ('servico', 'valor', 'duracao_minutos', 'ativo')
        labels = {'servico': 'Serviço', 'valor': 'Valor (R$)', 'duracao_minutos': 'Duração (minutos)'}


class DisponibilidadeForm(TenantForm):
    def __init__(self, *args, profissional, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.profissional = profissional

    class Meta:
        model = Disponibilidade
        fields = ('data', 'hora_inicio', 'hora_fim', 'ativo')
        labels = {'hora_inicio': 'Início', 'hora_fim': 'Fim'}
        widgets = {
            'data': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'hora_inicio': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
            'hora_fim': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
        }

