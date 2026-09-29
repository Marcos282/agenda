from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0007_contatocliente'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='cpf',
            field=models.CharField(blank=True, default='', max_length=11, verbose_name='CPF'),
        ),
        migrations.AddField(
            model_name='user',
            name='endereco',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name='Endereço'),
        ),
        migrations.AddField(
            model_name='user',
            name='bairro',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='Bairro'),
        ),
        migrations.AddField(
            model_name='user',
            name='numero_endereco',
            field=models.CharField(blank=True, default='', max_length=20, verbose_name='Número'),
        ),
        migrations.AddField(
            model_name='user',
            name='cidade',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='Cidade'),
        ),
        migrations.AddField(
            model_name='user',
            name='estado',
            field=models.CharField(blank=True, default='', max_length=2, verbose_name='Estado (UF)'),
        ),
    ]
