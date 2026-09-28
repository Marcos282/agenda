"""Explicit scoping helpers, not an implicit/global tenant context."""
from django.core.exceptions import ValidationError
from django.db import models


class TenantQuerySet(models.QuerySet):
    def for_tenant(self, tenant):
        if tenant is None or tenant.pk is None:
            raise ValueError("Um tenant persistido é obrigatório.")
        return self.filter(tenant_id=tenant.pk)

    def ativos(self):
        return self.filter(ativo=True)


class TenantOwnedModel(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    objects = TenantQuerySet.as_manager()
    tenant_relations = ()

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        for name in self.tenant_relations:
            field = self._meta.get_field(name)
            related_id = getattr(self, field.attname)
            if related_id is None:
                continue  # Required-field validation handles missing values.
            related = field.remote_field.model.objects.filter(pk=related_id, tenant_id=self.tenant_id).first()
            if related is None or related.tenant_id != self.tenant_id:
                raise ValidationError("Os registros relacionados devem pertencer ao mesmo estabelecimento.")
            if (self._state.adding or self.ativo) and not related.ativo:
                raise ValidationError("Ative o profissional e o serviço antes de criar ou ativar este registro.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
