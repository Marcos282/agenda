from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('catalogo', '0001_initial')]
    operations = [
        migrations.RunSQL(
            'ALTER TABLE catalogo_profissionalservico ADD CONSTRAINT ps_prof_same_tenant_fk '
            'FOREIGN KEY (profissional_id, tenant_id) REFERENCES profissionais_profissional (id, tenant_id) '
            'DEFERRABLE INITIALLY IMMEDIATE',
            'ALTER TABLE catalogo_profissionalservico DROP CONSTRAINT ps_prof_same_tenant_fk',
        ),
        migrations.RunSQL(
            'ALTER TABLE catalogo_profissionalservico ADD CONSTRAINT ps_servico_same_tenant_fk '
            'FOREIGN KEY (servico_id, tenant_id) REFERENCES catalogo_servico (id, tenant_id) '
            'DEFERRABLE INITIALLY IMMEDIATE',
            'ALTER TABLE catalogo_profissionalservico DROP CONSTRAINT ps_servico_same_tenant_fk',
        ),
    ]
