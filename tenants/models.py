from datetime import timedelta
from decimal import Decimal
from django.utils import timezone as django_timezone

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MinValueValidator
from django.db import models, transaction


subdomain_validator = RegexValidator(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
    "Use um subdomínio de até 63 caracteres: letras minúsculas, números e hífens internos.",
)


def validate_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError("Informe um timezone IANA válido.")


class Tenant(models.Model):
    class Plano(models.TextChoices):
        INDIVIDUAL = 'INDIVIDUAL', 'Plano Individual'
        PROFISSIONAL = 'PROFISSIONAL', 'Plano Profissional'

    plano = models.CharField(max_length=12, choices=Plano.choices, default=Plano.INDIVIDUAL)

    @property
    def valor_plano(self):
        return {self.Plano.INDIVIDUAL: Decimal('30.00'), self.Plano.PROFISSIONAL: Decimal('50.00')}[self.plano]

    def clean(self):
        super().clean()
        if self.pk and self.plano == self.Plano.INDIVIDUAL:
            from profissionais.models import Profissional
            if Profissional.objects.filter(tenant_id=self.pk, ativo=True).count() > 1:
                raise ValidationError('Para escolher o Plano Individual, escolha qual profissional permanecerá ativo e desative os demais. Nenhum cadastro será excluído.')

    nome = models.CharField(max_length=150)
    razao_social = models.CharField("Razão social", max_length=200, blank=True, default="")
    telefone = models.CharField("Telefone de contato", max_length=40, blank=True, default="")
    cnpj = models.CharField("CNPJ", max_length=18, blank=True, default="")
    endereco_publico = models.CharField("Endereço do estabelecimento", max_length=400, blank=True, default="")
    subdomain = models.CharField(max_length=100, unique=True, validators=[subdomain_validator])
    timezone = models.CharField(max_length=50, default="America/Sao_Paulo", validators=[validate_timezone])
    # Legacy setting retained for compatibility; not used by the daily agenda.
    intervalo_grade_minutos = models.PositiveIntegerField(default=15, validators=[MinValueValidator(1)])
    limite_agendamentos_cliente_dia = models.PositiveSmallIntegerField(
        'Máximo de agendamentos por cliente por dia', default=2, validators=[MinValueValidator(1)])
    limite_agendamentos_cliente_futuros = models.PositiveSmallIntegerField(
        'Limite de agendamentos futuros por WhatsApp', default=2, validators=[MinValueValidator(1)])
    ativo = models.BooleanField(default=True)
    expira_em = models.DateField('Data de expiração', null=True, blank=True,
        help_text='Validade do acesso. Quando não informada, será definida como 30 dias após o cadastro.')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(plano__in=["INDIVIDUAL", "PROFISSIONAL"]), name="tenant_plano_valido"),
            models.CheckConstraint(condition=models.Q(limite_agendamentos_cliente_futuros__gte=1), name="tenant_limite_agendamentos_futuros_positivo"),
            models.CheckConstraint(condition=models.Q(limite_agendamentos_cliente_dia__gte=1), name="tenant_limite_ag_dia_positivo"),
            models.CheckConstraint(condition=models.Q(intervalo_grade_minutos__gt=0), name="tenant_grade_positiva"),
            models.CheckConstraint(condition=models.Q(subdomain__regex=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"), name="tenant_subdomain_valid"),
        ]

    @property
    def cpf_publico(self):
        if self.cnpj or not self.pk:
            return ''
        from usuarios.models import User
        cpf = (User.objects.filter(tenant_id=self.pk, tipo=User.Tipo.ADMIN)
               .exclude(cpf='').order_by('pk').values_list('cpf', flat=True).first())
        if not cpf:
            return ''
        return f'{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}'

    @property
    def whatsapp_url(self):
        from usuarios.validators import normalizar_whatsapp
        if not self.telefone:
            return ''
        try:
            return 'https://wa.me/' + normalizar_whatsapp(self.telefone).lstrip('+')
        except ValidationError:
            return ''

    @property
    def data_expiracao(self):
        if self.expira_em:
            return self.expira_em
        cadastro = self.criado_em or django_timezone.now()
        return django_timezone.localtime(cadastro, ZoneInfo(self.timezone)).date() + timedelta(days=30)

    @property
    def dias_para_expirar(self):
        hoje = django_timezone.localdate(timezone=ZoneInfo(self.timezone))
        return max(0, (self.data_expiracao - hoje).days)

    @property
    def acesso_expirado(self):
        hoje = django_timezone.localdate(timezone=ZoneInfo(self.timezone))
        return self.data_expiracao < hoje

    def save(self, *args, **kwargs):
        validate_timezone(self.timezone)
        if self.expira_em is None:
            self.expira_em = self.data_expiracao
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'expira_em'}
        self.subdomain = self.subdomain.strip().lower()
        with transaction.atomic():
            if self.pk:
                type(self).objects.select_for_update().filter(pk=self.pk).first()
            self.full_clean()
            return super().save(*args, **kwargs)

    def __str__(self):
        return self.nome
