from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_reputation_history(apps, schema_editor):
    Reputacao = apps.get_model('agenda', 'ReputacaoCliente')
    Auditoria = apps.get_model('agenda', 'ReputacaoClienteAuditoria')
    database = schema_editor.connection.alias
    for rating in Reputacao.objects.using(database).select_related('agendamento').iterator():
        updates = {'data_atendimento': rating.agendamento.inicio}
        if rating.tipo == 'AUSENTE' and rating.pontuacao == 1:
            Auditoria.objects.using(database).create(
                tenant_id=rating.tenant_id,
                reputacao_id=rating.pk,
                tipo_anterior=rating.tipo,
                pontuacao_anterior=rating.pontuacao,
                tipo_novo=rating.tipo,
                pontuacao_nova=0,
            )
            updates['pontuacao'] = 0
        Reputacao.objects.using(database).filter(pk=rating.pk).update(**updates)


def restore_legacy_absence_scores(apps, schema_editor):
    Reputacao = apps.get_model('agenda', 'ReputacaoCliente')
    Auditoria = apps.get_model('agenda', 'ReputacaoClienteAuditoria')
    database = schema_editor.connection.alias
    ids = Auditoria.objects.using(database).filter(
        tipo_anterior='AUSENTE', pontuacao_anterior=1, tipo_novo='AUSENTE', pontuacao_nova=0,
    ).values_list('reputacao_id', flat=True)
    Reputacao.objects.using(database).filter(pk__in=ids).update(pontuacao=1)
    Reputacao.objects.using(database).update(data_atendimento=None)


class Migration(migrations.Migration):
    dependencies = [
        ('agenda', '0011_agendamento_conclusao_confirmada_em'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='reputacaocliente',
            name='data_atendimento',
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name='reputacaocliente',
            name='registrado_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='avaliacoes_reputacao_registradas', to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name='ReputacaoClienteAuditoria',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo_anterior', models.CharField(choices=[('CONCLUIDO', 'Compareceu'), ('ATRASADO', 'Chegou atrasado'), ('DESMARCOU', 'Desmarcou'), ('AUSENTE', 'Cliente ausente')], max_length=12)),
                ('pontuacao_anterior', models.PositiveSmallIntegerField()),
                ('tipo_novo', models.CharField(choices=[('CONCLUIDO', 'Compareceu'), ('ATRASADO', 'Chegou atrasado'), ('DESMARCOU', 'Desmarcou'), ('AUSENTE', 'Cliente ausente')], max_length=12)),
                ('pontuacao_nova', models.PositiveSmallIntegerField()),
                ('alterado_em', models.DateTimeField(auto_now_add=True)),
                ('alterado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='correcoes_reputacao', to=settings.AUTH_USER_MODEL)),
                ('reputacao', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name='alteracoes', to='agenda.reputacaocliente')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenants.tenant')),
            ],
            options={'ordering': ['-alterado_em', '-pk']},
        ),
        migrations.AddConstraint(
            model_name='reputacaocliente',
            constraint=models.UniqueConstraint(fields=('id', 'tenant'), name='reputacao_id_tenant_unique'),
        ),
        migrations.AddConstraint(
            model_name='reputacaoclienteauditoria',
            constraint=models.UniqueConstraint(fields=('id', 'tenant'), name='reputacao_audit_id_tenant_unique'),
        ),
        migrations.RemoveConstraint(
            model_name='reputacaocliente',
            name='reputacao_tipo_pontos_validos',
        ),
        migrations.RunPython(backfill_reputation_history, restore_legacy_absence_scores),
        migrations.AlterField(
            model_name='reputacaocliente',
            name='data_atendimento',
            field=models.DateTimeField(),
        ),
        migrations.AddConstraint(
            model_name='reputacaocliente',
            constraint=models.CheckConstraint(condition=(
                models.Q(('pontuacao', 4), ('tipo', 'CONCLUIDO')) |
                models.Q(('pontuacao', 3), ('tipo', 'ATRASADO')) |
                models.Q(('pontuacao', 2), ('tipo', 'DESMARCOU')) |
                models.Q(('pontuacao', 0), ('tipo', 'AUSENTE'))
            ), name='reputacao_tipo_pontos_validos'),
        ),
        migrations.RunSQL(
            'ALTER TABLE agenda_reputacaoclienteauditoria ADD CONSTRAINT reputacao_auditoria_tenant_fk '
            'FOREIGN KEY (reputacao_id, tenant_id) REFERENCES agenda_reputacaocliente (id, tenant_id) '
            'DEFERRABLE INITIALLY IMMEDIATE',
            'ALTER TABLE agenda_reputacaoclienteauditoria DROP CONSTRAINT reputacao_auditoria_tenant_fk',
        ),
    ]
