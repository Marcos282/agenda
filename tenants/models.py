from datetime import timedelta
from uuid import uuid4
from django.utils import timezone as django_timezone
from django.utils.translation import gettext_lazy as _

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MinValueValidator
from django.db import models, transaction
from .themes import THEME_CHOICES, ICONS
from .theme_uploads import theme_storage, theme_upload_path
from .pricing import monthly_price


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

    plano = models.CharField(max_length=12, choices=[(Plano.PROFISSIONAL, Plano.PROFISSIONAL.label)], default=Plano.PROFISSIONAL)

    @property
    def valor_plano(self):
        return monthly_price()

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
        help_text='Validade do acesso. Quando não informada, será definida como 60 dias após o cadastro.')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(plano="PROFISSIONAL"), name="tenant_plano_valido"),
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
        from .subscriptions import BILLING_TIMEZONE
        return django_timezone.localtime(cadastro, BILLING_TIMEZONE).date() + timedelta(days=60 if self._state.adding else 30)

    @property
    def assinatura(self):
        from .subscriptions import subscription_status
        return subscription_status(self)

    @property
    def agendamentos_bloqueados(self):
        return self.assinatura.bloqueado

    @property
    def dias_para_expirar(self):
        from .subscriptions import BILLING_TIMEZONE
        hoje = django_timezone.localdate(timezone=BILLING_TIMEZONE)
        return max(0, (self.data_expiracao - hoje).days)

    @property
    def acesso_expirado(self):
        from .subscriptions import BILLING_TIMEZONE
        hoje = django_timezone.localdate(timezone=BILLING_TIMEZONE)
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
            creating = self._state.adding
            super().save(*args, **kwargs)
            if creating:
                LogoAccount.open_for(self)

    def __str__(self):
        return self.nome




class TenantTheme(models.Model):
    """Independent visual configuration; never writes to Tenant or booking models."""
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='site_theme')
    style = models.CharField(max_length=32, choices=THEME_CHOICES, default='original')
    primary_color = models.CharField(max_length=7, default='#287454', validators=[
        RegexValidator(r'^#[0-9a-fA-F]{6}$', 'Informe uma cor hexadecimal válida.')])
    title = models.CharField('Título principal', max_length=150, blank=True)
    subtitle = models.CharField('Subtítulo', max_length=400, blank=True)
    description = models.TextField('Descrição do estabelecimento', max_length=1000, blank=True)
    button_text = models.CharField('Texto do botão principal', max_length=60, blank=True)
    icon = models.CharField('Ícone decorativo', max_length=4, choices=ICONS, blank=True)
    hero_image = models.ImageField('Imagem principal', storage=theme_storage, upload_to=theme_upload_path, blank=True)
    background_image = models.ImageField('Imagem de fundo', storage=theme_storage, upload_to=theme_upload_path, blank=True)
    logo_image = models.ImageField('Logomarca', storage=theme_storage, upload_to=theme_upload_path, blank=True)
    hero_image_enabled = models.BooleanField(default=True)
    background_image_enabled = models.BooleanField(default=True)
    logo_image_enabled = models.BooleanField(default=True)
    hero_transparent = models.BooleanField('Hero sem cor', default=False, help_text='Deixa o fundo do hero transparente, sem alterar o banner ou a logomarca.')
    updated_at = models.DateTimeField(auto_now=True)


class LogoSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(_('Geração de logomarcas habilitada'), default=False)
    initial_credits = models.PositiveIntegerField(_('Créditos iniciais'), default=3)

    class Meta:
        verbose_name = _('Configuração de logomarcas com IA')
        verbose_name_plural = _('Configuração de logomarcas com IA')
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name='logo_settings_singleton')]

    def __str__(self):
        return str(self._meta.verbose_name)


class LogoAccount(models.Model):
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='logo_account')
    enabled = models.BooleanField(_('Geração habilitada para este estabelecimento'), default=True)
    credits = models.PositiveIntegerField(_('Saldo de créditos'), default=3)

    class Meta:
        verbose_name = _('Créditos de logomarca')
        verbose_name_plural = _('Créditos de logomarcas')

    def __str__(self):
        return str(self.tenant)

    @classmethod
    def open_for(cls, tenant):
        initial = LogoSettings.objects.values_list('initial_credits', flat=True).first()
        return cls.objects.get_or_create(tenant=tenant, defaults={'credits': 3 if initial is None else initial})[0]


class LogoGeneration(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', _('Na fila')
        RUNNING = 'running', _('Gerando')
        READY = 'ready', _('Concluída')
        FAILED = 'failed', _('Falhou')

    ACTIVE = (Status.QUEUED, Status.RUNNING)

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='logo_generations')
    request_id = models.UUIDField(editable=False)
    status = models.CharField(_('Estado'), max_length=8, choices=Status, default=Status.QUEUED)
    brief = models.JSONField(default=dict, editable=False)
    image = models.ImageField(storage=theme_storage, upload_to=theme_upload_path, blank=True)
    model_name = models.CharField(_('Modelo da OpenAI'), max_length=100, blank=True)
    provider_request_id = models.CharField(_('ID da requisição na OpenAI'), max_length=150, blank=True)
    usage = models.JSONField(_('Consumo informado pela API'), default=dict, blank=True)
    error_code = models.CharField(_('Código do erro'), max_length=40, blank=True)
    created_at = models.DateTimeField(_('Solicitada em'), auto_now_add=True)
    started_at = models.DateTimeField(_('Iniciada em'), null=True, blank=True)
    finished_at = models.DateTimeField(_('Finalizada em'), null=True, blank=True)

    class Meta:
        verbose_name = _('Geração de logomarca')
        verbose_name_plural = _('Histórico de geração de logomarcas')
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'created_at']), models.Index(fields=['tenant', 'created_at'])]
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'request_id'], name='logo_request_idempotency'),
            models.UniqueConstraint(fields=['tenant'], condition=models.Q(status__in=['queued', 'running']),
                                    name='logo_one_active_generation'),
        ]
