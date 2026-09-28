from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('agenda', '0001_initial')]
    operations = [
        migrations.RunSQL(
            'ALTER TABLE agenda_disponibilidade ADD CONSTRAINT disp_prof_same_tenant_fk '
            'FOREIGN KEY (profissional_id, tenant_id) REFERENCES profissionais_profissional (id, tenant_id) '
            'DEFERRABLE INITIALLY IMMEDIATE',
            'ALTER TABLE agenda_disponibilidade DROP CONSTRAINT disp_prof_same_tenant_fk',
        ),
    ]
