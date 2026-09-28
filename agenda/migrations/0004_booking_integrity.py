from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('agenda', '0003_agendamento'),
        ('usuarios', '0005_cliente_tenant_integrity'),
        ('catalogo', '0003_profissionalservico_ps_id_tenant_prof_unique'),
    ]
    operations = [
        migrations.RunSQL(
            'ALTER TABLE agenda_agendamento ADD CONSTRAINT ag_cliente_tenant_fk '
            'FOREIGN KEY (cliente_id, tenant_id) REFERENCES usuarios_user (id, tenant_id) DEFERRABLE INITIALLY IMMEDIATE',
            'ALTER TABLE agenda_agendamento DROP CONSTRAINT ag_cliente_tenant_fk',
        ),
        migrations.RunSQL(
            'ALTER TABLE agenda_agendamento ADD CONSTRAINT ag_oferta_tenant_prof_fk '
            'FOREIGN KEY (oferta_id, tenant_id, profissional_id) REFERENCES catalogo_profissionalservico (id, tenant_id, profissional_id) DEFERRABLE INITIALLY IMMEDIATE',
            'ALTER TABLE agenda_agendamento DROP CONSTRAINT ag_oferta_tenant_prof_fk',
        ),
        migrations.RunSQL(
            "ALTER TABLE agenda_agendamento ADD CONSTRAINT ag_duracao_intervalo CHECK (fim - inicio = duracao_minutos * INTERVAL '1 minute')",
            'ALTER TABLE agenda_agendamento DROP CONSTRAINT ag_duracao_intervalo',
        ),
    ]
