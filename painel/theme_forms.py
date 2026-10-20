from django import forms
from tenants.models import TenantTheme
from tenants.theme_uploads import optimize_image


class AppearanceForm(forms.ModelForm):
    class Meta:
        model = TenantTheme
        fields = ['style', 'primary_color']


class ContentForm(forms.ModelForm):
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
