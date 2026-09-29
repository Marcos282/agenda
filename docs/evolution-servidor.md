# Evolution no servidor do Combinado — sem Docker

Servidor: `186.216.63.206`, usuário SSH `marcos`.
Projeto Django: `/var/www/html/combinado`, ambiente virtual `venv`.
Domínio configurado: `tacombinado.net`.

## Componentes

- Evolution API 2.3.7, commit oficial `cd800f2976e1e5b682fbf86a01ee4d85ae61f370`, em `/home/marcos/.local/opt/combinado-evolution`.
- Node 22.23.3 em `/home/marcos/.local/opt/combinado-node` (link para a distribuição oficial; checksum SHA-256 conferido).
- PostgreSQL: banco e usuário próprios `combinado_evolution`, separados do banco Django.
- Redis 7.0.15 em `/home/marcos/.local/opt/combinado-redis`; pacotes Ubuntu extraídos para uso sem root. Dados em `/home/marcos/.local/share/combinado-redis`.
- API escuta somente `127.0.0.1:8085`; Redis somente `127.0.0.1:6385`. Não abrir essas portas no firewall.
- Chave nova, específica deste servidor, gravada no `.env` da Evolution e no `.env` do projeto, ambos com permissão 600. Não copiar a chave da máquina local.
- Prefixo de instâncias: `combinado_tenant`. Não alterar depois de conectar números.
- Backup do `.env` anterior em `/home/marcos/.config/combinado-backups/`, com acesso restrito.

## Serviços

Os serviços são do systemd **do usuário marcos**. Execute conectado como marcos:

```bash
systemctl --user status combinado-evolution combinado-redis --no-pager
systemctl --user restart combinado-evolution
systemctl --user list-timers combinado-lembretes.timer
journalctl --user -u combinado-evolution -n 50 --no-pager
journalctl --user -u combinado-lembretes -n 30 --no-pager
```

`Linger=yes` permite que iniciem no boot e continuem sem sessão SSH aberta. A API reinicia em caso de falha. O timer processa lembretes aproximadamente a cada minuto, usando o ambiente e o banco do projeto em `/var/www/html/combinado`.

O Gunicorn existente continua no serviço de sistema `combinado.service`. Para futuras alterações de ambiente:

```bash
sudo systemctl restart combinado
```

## Conectar WhatsApp

No subdomínio do estabelecimento, abra `/painel/whatsapp/` como administrador, gere o QR code, escaneie pelo celular e verifique o status. A configuração de lembretes é individual por estabelecimento e precisa ser ativada no painel. Cadastre/ative o tenant antes de acessar seu subdomínio.

O endereço `127.0.0.1:8085` é interno ao servidor: o administrador usa o painel Django público, não precisa acessar a porta da Evolution pelo navegador. O Evolution Manager separado foi desativado porque a conexão é feita pelo painel.

## Build

A verificação TypeScript foi concluída no servidor, mas o empacotamento atingiu o limite de heap de 1 GB. Foi usado o diretório `dist` previamente compilado e validado na máquina local, da mesma tag e commit, com hashes iguais de `src/main.ts` e `package-lock.json`. As dependências e o cliente Prisma foram instalados/gerados no próprio servidor. Para futuras atualizações, prefira compilar em uma máquina com mais memória e transferir apenas os artefatos da versão correspondente.

## Manutenção

A instalação não usa Docker nem altera o Node/Redis de outros projetos. Os binários instalados no diretório pessoal **não são atualizados automaticamente pelo apt**. Atualize explicitamente após backup do banco e configurações.

Preserve a alteração local em `src/main.ts` que vincula `server.listen` a `127.0.0.1` quando atualizar/recompilar a Evolution. A API tem telemetria e gravação de histórico de conversas desativadas; as informações necessárias à sessão são preservadas.

Não remova o banco ou os dados Redis para reiniciar. Logs podem conter informações de conexão: não publique seu conteúdo integral ou chaves.

Referência da versão: https://github.com/evolution-foundation/evolution-api/releases/tag/2.3.7
