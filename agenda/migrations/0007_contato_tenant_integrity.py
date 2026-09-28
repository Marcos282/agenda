from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('agenda', '0006_agendamento_contato_alter_agendamento_cliente_and_more')]
    operations = [migrations.RunSQL(
        'ALTER TABLE agenda_agendamento ADD CONSTRAINT ag_contato_tenant_fk '
        'FOREIGN KEY (contato_id, tenant_id) REFERENCES usuarios_contatocliente (id, tenant_id) DEFERRABLE INITIALLY IMMEDIATE',
        'ALTER TABLE agenda_agendamento DROP CONSTRAINT ag_contato_tenant_fk',
    )]
