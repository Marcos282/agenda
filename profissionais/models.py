from uuid import uuid4
from django.db import models
from tenants.base import TenantOwnedModel


def foto_path(instance, filename):
    return f'tenants/{instance.tenant_id}/profissionais/{uuid4().hex}.jpg'


class Profissional(TenantOwnedModel):
    nome = models.CharField(max_length=150)
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    foto = models.ImageField(upload_to=foto_path, blank=True)

    class Meta:
        ordering = ['nome', 'pk']
        constraints = [models.UniqueConstraint(fields=['id', 'tenant'], name='prof_id_tenant_unique')]
        indexes = [models.Index(fields=['tenant', 'ativo'], name='prof_tenant_ativo_idx')]

    def __str__(self):
        return self.nome
