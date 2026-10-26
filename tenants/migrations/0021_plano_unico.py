from importlib import import_module

from django.db import migrations, models


def unificar_planos(apps, schema_editor):
    apps.get_model('tenants', 'Tenant').objects.using(
        schema_editor.connection.alias,
    ).exclude(plano='PROFISSIONAL').update(plano='PROFISSIONAL')


class Migration(migrations.Migration):
    dependencies = [('tenants', '0020_image_visibility')]

    operations = [
        migrations.RunSQL(
            import_module('tenants.migrations.0013_proteger_limite_profissionais').REVERSE,
            import_module('tenants.migrations.0013_proteger_limite_profissionais').SQL,
        ),
        migrations.RunPython(unificar_planos, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='tenant',
            name='plano',
            field=models.CharField(
                choices=[('PROFISSIONAL', 'Plano Profissional')],
                default='PROFISSIONAL', max_length=12,
            ),
        ),
        migrations.RemoveConstraint(model_name='tenant', name='tenant_plano_valido'),
        migrations.AddConstraint(
            model_name='tenant',
            constraint=models.CheckConstraint(
                condition=models.Q(plano='PROFISSIONAL'), name='tenant_plano_valido',
            ),
        ),
    ]
