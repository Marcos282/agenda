from django import forms
from tenants.models import TenantTheme
from tenants.theme_uploads import optimize_image


class AppearanceForm(forms.ModelForm):
    class Meta:
        model = TenantTheme
        fields = ['style', 'primary_color']


class ContentForm(forms.ModelForm):
    IMAGE_ACTIONS = [('show', 'Ativar imagem'), ('hide', 'Desativar sem remover'), ('remove', 'Remover imagem do site')]
    hero_image_action = forms.ChoiceField(label='Banner Desktop: exibição', choices=IMAGE_ACTIONS, required=False)
    background_image_action = forms.ChoiceField(label='Banner Mobile: exibição', choices=IMAGE_ACTIONS, required=False)
    logo_image_action = forms.ChoiceField(label='Logomarca: exibição', choices=IMAGE_ACTIONS, required=False)
    IMAGE_FIELDS = ('hero_image', 'background_image', 'logo_image')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.IMAGE_FIELDS:
            self.fields[field + '_action'].initial = 'show' if getattr(self.instance, field + '_enabled') else 'hide'
        self.order_fields(['title', 'subtitle', 'description', 'button_text', 'icon',
                           'hero_image', 'hero_image_action', 'background_image', 'background_image_action',
                           'logo_image', 'logo_image_action', 'hero_transparent'])

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
        fields = ['title', 'subtitle', 'description', 'button_text', 'icon', 'hero_image', 'background_image', 'logo_image', 'hero_transparent']
        widgets = {'description': forms.Textarea(attrs={'rows': 3}),
                   'hero_image': forms.FileInput(), 'background_image': forms.FileInput(),
                   'logo_image': forms.FileInput()}
        labels = {'hero_image': 'Banner Desktop', 'background_image': 'Banner Mobile', 'logo_image': 'Logomarca'}
        help_texts = {'hero_image': 'Recomendado: 1920x700 px',
                      'background_image': 'Recomendado: 1080x1350 px',
                      'logo_image': 'PNG ou WebP com fundo transparente. Recomendado: 600x200 px. Exibida centralizada sobre o banner.'}

    def clean_hero_image(self):
        return self.clean_upload('hero_image')

    def clean_background_image(self):
        return self.clean_upload('background_image')

    def clean_logo_image(self):
        return self.clean_upload('logo_image', keep_transparency=True, max_size=800)

    def clean_upload(self, field, **options):
        upload = self.cleaned_data.get(field)
        if field in self.files and upload:
            return optimize_image(upload, **options)
        return upload
