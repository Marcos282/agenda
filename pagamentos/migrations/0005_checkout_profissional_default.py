from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('pagamentos', '0004_remove_checkoutacesso_checkout_acesso_plano_valido_and_more'),
        ('tenants', '0021_plano_unico'),
    ]

    operations = [
        migrations.AlterField(
            model_name='checkoutacesso',
            name='plano',
            field=models.CharField(
                choices=[('INDIVIDUAL', 'Plano Individual'), ('PROFISSIONAL', 'Plano Profissional')],
                default='PROFISSIONAL', max_length=12,
            ),
        ),
    ]
