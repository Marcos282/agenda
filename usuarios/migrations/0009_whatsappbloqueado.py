from django.db import migrations, models
import django.db.models.deletion
import usuarios.validators


class Migration(migrations.Migration):
    dependencies = [
        ('usuarios', '0008_user_owner_profile_address'),
        ('tenants', '0009_remove_payment_integration'),
    ]
    operations = [
        migrations.CreateModel(
            name='WhatsAppBloqueado',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('whatsapp', models.CharField(max_length=16, validators=[usuarios.validators.validate_whatsapp])),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenants.tenant')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('tenant', 'whatsapp'), name='whatsapp_bloqueado_tenant_uniq')]},
        ),
    ]
