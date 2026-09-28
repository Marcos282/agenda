from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("usuarios", "0004_user_tenant_user_tipo_user_user_tenant_tipo_idx_and_more")]
    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE usuarios_cliente
                ADD CONSTRAINT cliente_user_same_tenant_fk
                FOREIGN KEY (user_id, tenant_id)
                REFERENCES usuarios_user (id, tenant_id)
                DEFERRABLE INITIALLY IMMEDIATE
            """,
            reverse_sql="ALTER TABLE usuarios_cliente DROP CONSTRAINT cliente_user_same_tenant_fk",
        ),
    ]
