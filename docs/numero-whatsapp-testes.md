# Número liberado para testes

O WhatsApp `21990921092` (`+5521990921092`) está liberado dos limites diário/futuro de quantidade de agendamentos e do bloqueio de novas reservas, exclusivamente no tenant com subdomínio `marcos`.

Outros números e outros estabelecimentos seguem suas configurações normais. A exceção não libera horários ocupados, horários passados, acesso a outro tenant, clientes inativos ou autenticação administrativa. Não remove registros de bloqueio do banco: apenas ignora seu efeito para esse par autorizado durante as reservas.

O console `/teste/` e `zapp.py` já enviam mensagens avulsas pelo provider, sem aplicar limites de reservas ou espera de 30 dias. O lembrete automático continua exigindo atendimento realizado, 30 dias e uma mensagem por atendimento. A exceção de reservas não altera o bloqueio de destinatários do lembrete automático.

Configuração no `.env` do servidor:

```dotenv
WHATSAPP_TEST_RECIPIENTS=marcos:21990921092
```

Esse é o padrão quando a variável não existe. Para desativar após os testes:

```dotenv
WHATSAPP_TEST_RECIPIENTS=
```

Após publicar o código ou alterar a configuração, reinicie o serviço da aplicação. Não há migration para esta alteração.

```bash
cd /var/www/html/combinado
git pull --ff-only
sudo systemctl restart combinado
```

Arquivos: `barbe/settings.py`, `usuarios/validators.py`, `agenda/booking.py`, `agenda/test_numero_teste.py` e esta documentação.
