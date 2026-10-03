from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [('tenants', '0009_remove_payment_integration')]
    operations = [
        migrations.AddField(
            model_name='tenant', name='limite_agendamentos_cliente_dia',
            field=models.PositiveSmallIntegerField(default=2, validators=[django.core.validators.MinValueValidator(1)],
                verbose_name='Máximo de agendamentos por cliente por dia')),
        migrations.AddConstraint(model_name='tenant', constraint=models.CheckConstraint(
            condition=models.Q(limite_agendamentos_cliente_dia__gte=1), name='tenant_limite_ag_dia_positivo')),
    ]
