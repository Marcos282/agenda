from django import forms
from tenants.models import TenantTheme
from tenants.theme_uploads import optimize_image


class AppearanceForm(forms.ModelForm):
    class Meta:
        model = TenantTheme
        fields = ['style', 'primary_color']


class ContentForm(forms.ModelForm):
    IMAGE_ACTIONS = [('show', 'Ativar imagem'), ('hide', 'Desativar sem remover'), ('remove', 'Remover imagem do site')]
    logo_image_action = forms.ChoiceField(label='Logomarca: exibição', choices=IMAGE_ACTIONS, required=False)
    IMAGE_FIELDS = ('logo_image',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.IMAGE_FIELDS:
            self.fields[field + '_action'].initial = 'show' if getattr(self.instance, field + '_enabled') else 'hide'
        self.order_fields(['icon', 'logo_image', 'logo_image_action', 'hero_transparent'])

    def clean(self):
        cleaned = super().clean()
        for field in self.IMAGE_FIELDS:
            action = cleaned.get(field + '_action') or ('show' if getattr(self.instance, field + '_enabled') else 'hide')
            if action == 'remove':
                if field in self.files:
                    self.add_error(field, 'Escolha entre enviar uma nova imagem ou remover a imagem atual.')
                else:
                    cleaned[field] = ''
            setattr(self.instance, field + '_enabled', action != 'hide')
        return cleaned

    def visual_values(self):
        values = {field: self.cleaned_data[field] for field in self._meta.fields}
        for field in (name + '_enabled' for name in self.IMAGE_FIELDS):
            values[field] = getattr(self.instance, field)
        return values

    class Meta:
        model = TenantTheme
        # Excluded content and banner fields must never enter update defaults.
        fields = ['icon', 'logo_image', 'hero_transparent']
        widgets = {'logo_image': forms.FileInput()}
        labels = {'logo_image': 'Logomarca'}
        help_texts = {'logo_image': 'PNG ou WebP com fundo transparente. Recomendado: 600x200 px, ou 300x300px. Exibida centralizada sobre o banner.'}

    def clean_logo_image(self):
        return self.clean_upload('logo_image', keep_transparency=True, max_size=800)

    def clean_upload(self, field, **options):
        upload = self.cleaned_data.get(field)
        if field in self.files and upload:
            return optimize_image(upload, **options)
        return upload
