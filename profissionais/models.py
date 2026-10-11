from uuid import uuid4
from django.db import models, transaction
from django.core.exceptions import ValidationError
from tenants.models import Tenant
from tenants.base import TenantOwnedModel


def foto_path(instance, filename):
    return f'tenants/{instance.tenant_id}/profissionais/{uuid4().hex}.jpg'


def foto_fundo_path(instance, filename):
    return f'tenants/{instance.tenant_id}/profissionais/fundos/{uuid4().hex}.jpg'


class Profissional(TenantOwnedModel):
    nome = models.CharField(max_length=150)
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    foto = models.ImageField(upload_to=foto_path, blank=True)
    foto_fundo = models.ImageField('Foto de fundo', upload_to=foto_fundo_path, blank=True)

    class Meta:
        ordering = ['nome', 'pk']
        constraints = [models.UniqueConstraint(fields=['id', 'tenant'], name='prof_id_tenant_unique')]
        indexes = [models.Index(fields=['tenant', 'ativo'], name='prof_tenant_ativo_idx')]

    def clean(self):
        super().clean()
        if self.ativo and self.tenant_id:
            plano = Tenant.objects.filter(pk=self.tenant_id).values_list('plano', flat=True).first()
            if plano == Tenant.Plano.INDIVIDUAL and type(self).objects.filter(
                    tenant_id=self.tenant_id, ativo=True).exclude(pk=self.pk).exists():
                raise ValidationError('O Plano Individual permite apenas um profissional ativo. Desative o profissional atual ou escolha o Plano Profissional para liberar agendas ilimitadas.')

    def save(self, *args, **kwargs):
        with transaction.atomic():
            Tenant.objects.select_for_update().get(pk=self.tenant_id)
            return super().save(*args, **kwargs)

    def __str__(self):
        return self.nome
