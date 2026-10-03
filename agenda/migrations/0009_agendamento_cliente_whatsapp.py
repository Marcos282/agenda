from django.db import migrations, models


def preencher_whatsapp(apps, schema_editor):
    Agendamento = apps.get_model('agenda', 'Agendamento')
    db = schema_editor.connection.alias
    bookings = Agendamento.objects.using(db).select_related('cliente', 'contato')
    for booking in bookings.iterator(chunk_size=1000):
        pessoa = booking.cliente if booking.cliente_id else booking.contato
        if pessoa and pessoa.tenant_id == booking.tenant_id and pessoa.whatsapp:
            Agendamento.objects.using(db).filter(pk=booking.pk).update(cliente_whatsapp=pessoa.whatsapp)


class Migration(migrations.Migration):
    dependencies = [
        ('agenda', '0008_agendamento_acesso_token'),
        ('tenants', '0010_tenant_limite_agendamentos_cliente_dia'),
        ('usuarios', '0009_whatsappbloqueado'),
    ]
    operations = [
        migrations.AddField(model_name='agendamento', name='cliente_whatsapp',
            field=models.CharField(blank=True, default='', max_length=16)),
        migrations.RunPython(preencher_whatsapp, migrations.RunPython.noop),
    ]
