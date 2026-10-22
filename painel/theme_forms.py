from django import forms
from tenants.models import TenantTheme
from tenants.theme_uploads import optimize_image


class AppearanceForm(forms.ModelForm):
    class Meta:
        model = TenantTheme
        fields = ['style', 'primary_color']


class ContentForm(forms.ModelForm):
    IMAGE_ACTIONS = [('show', 'Ativar imagem'), ('hide', 'Desativar sem remover'), ('remove', 'Remover imagem do site')]
    hero_image_action = forms.ChoiceField(label='Imagem principal: exibição', choices=IMAGE_ACTIONS, required=False)
    background_image_action = forms.ChoiceField(label='Imagem de fundo: exibição', choices=IMAGE_ACTIONS, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ('hero_image', 'background_image'):
            self.fields[field + '_action'].initial = 'show' if getattr(self.instance, field + '_enabled') else 'hide'
        self.order_fields(['title', 'subtitle', 'description', 'button_text', 'icon',
                           'hero_image', 'hero_image_action', 'background_image', 'background_image_action'])

    def clean(self):
        cleaned = super().clean()
        for field in ('hero_image', 'background_image'):
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
        for field in ('hero_image_enabled', 'background_image_enabled'):
            values[field] = getattr(self.instance, field)
        return values

    class Meta:
        model = TenantTheme
        fields = ['title', 'subtitle', 'description', 'button_text', 'icon', 'hero_image', 'background_image']
        widgets = {'description': forms.Textarea(attrs={'rows': 3}),
                   'hero_image': forms.FileInput(), 'background_image': forms.FileInput()}

    def clean_hero_image(self):
        return self.clean_upload('hero_image')

    def clean_background_image(self):
        return self.clean_upload('background_image')

    def clean_upload(self, field):
        upload = self.cleaned_data.get(field)
        if field in self.files and upload:
            return optimize_image(upload)
        return upload
