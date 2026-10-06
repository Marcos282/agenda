from django.db import migrations


SQL = """
CREATE FUNCTION combinado_limite_profissional() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE plano_atual varchar;
BEGIN
    IF NEW.ativo THEN
        SELECT plano INTO plano_atual FROM tenants_tenant WHERE id = NEW.tenant_id FOR UPDATE;
        IF plano_atual = 'INDIVIDUAL' AND EXISTS (
            SELECT 1 FROM profissionais_profissional WHERE tenant_id = NEW.tenant_id AND ativo AND id <> NEW.id
        ) THEN
            RAISE EXCEPTION 'O Plano Individual permite apenas um profissional ativo.' USING ERRCODE = '23514', CONSTRAINT = 'prof_plano_individual_limite';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER combinado_limite_profissional BEFORE INSERT OR UPDATE OF ativo, tenant_id ON profissionais_profissional
FOR EACH ROW EXECUTE FUNCTION combinado_limite_profissional();
CREATE FUNCTION combinado_limite_plano() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.plano = 'INDIVIDUAL' AND (SELECT count(*) FROM profissionais_profissional WHERE tenant_id = NEW.id AND ativo) > 1 THEN
        RAISE EXCEPTION 'Desative os demais profissionais antes de escolher o Plano Individual.' USING ERRCODE = '23514', CONSTRAINT = 'tenant_plano_individual_limite';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER combinado_limite_plano BEFORE UPDATE OF plano ON tenants_tenant
FOR EACH ROW EXECUTE FUNCTION combinado_limite_plano();
"""
REVERSE = """
DROP TRIGGER combinado_limite_plano ON tenants_tenant;
DROP FUNCTION combinado_limite_plano();
DROP TRIGGER combinado_limite_profissional ON profissionais_profissional;
DROP FUNCTION combinado_limite_profissional();
"""


class Migration(migrations.Migration):
    dependencies = [('tenants', '0012_tenant_plano_tenant_tenant_plano_valido')]
    operations = [migrations.RunSQL(SQL, REVERSE)]
