# Evolution API local, sem Docker

Instalada nesta máquina (`marcos-B550M-AORUS-ELITE`) para o projeto Barbe.

- Evolution API 2.3.7, tag oficial, commit `cd800f2976e1e5b682fbf86a01ee4d85ae61f370`.
- Aplicação: `/home/marcos/.local/opt/barbe-evolution-api`.
- Node.js existente: 20.20.2; dependências instaladas pelo `npm ci` do lockfile.
- API: `http://127.0.0.1:8085`, acessível somente nesta máquina.
- Redis: `127.0.0.1:6385`, dados em `/home/marcos/.local/share/barbe-redis`.
- Banco PostgreSQL e usuário próprios: `barbe_evolution`. O banco `barbe` permanece separado.
- Segredos: `.env` da Evolution e `.local-settings.json` do Barbe, ambos com permissão `600`, sem inclusão no Git.

O Redis foi instalado a partir dos pacotes oficiais Ubuntu (redis-server, redis-tools e bibliotecas), extraídos em `/home/marcos/.local/opt/barbe-redis`. Não requer Docker nem sudo para executar. Esses pacotes locais não são atualizados pelo apt automaticamente; sua atualização deve ser feita explicitamente junto à manutenção da instalação.

Os serviços systemd de usuário estão habilitados. `loginctl` está com `Linger=yes` para marcos, permitindo iniciar no boot e continuar sem sessão aberta.

```bash
systemctl --user status barbe-evolution barbe-redis --no-pager
systemctl --user restart barbe-evolution
systemctl --user list-timers barbe-lembretes.timer
journalctl --user -u barbe-evolution -n 50 --no-pager
journalctl --user -u barbe-lembretes -n 30 --no-pager
```

Os arquivos das unidades estão em `/home/marcos/.config/systemd/user/`. O timer `barbe-lembretes.timer` executa o comando Django de lembretes aproximadamente a cada minuto. Os lembretes permanecem sujeitos à opção de ativação de cada estabelecimento.

## Conectar o número

1. Abra `http://marcos.localhost:8000/painel/whatsapp/` como administrador.
2. Clique em **Conectar / gerar QR code**.
3. No celular: WhatsApp → Aparelhos conectados → Conectar aparelho.
4. Clique em **Verificar conexão** no painel.
5. Configure a mensagem, a antecedência e marque **Ativar lembretes automáticos**.

A configuração local do Django já aponta para esta Evolution. Se um processo antigo do Django ainda mostrar conexão pendente, reinicie esse processo. Não é necessário copiar a chave para o navegador.

## Manutenção

A API possui uma alteração local em `src/main.ts`: `server.listen` usa explicitamente `127.0.0.1`. Preserve esse vínculo ao atualizar e recompilar (`npm run build`) para não expor a API na rede. O Redis também aceita somente loopback. A telemetria está desativada. O armazenamento de histórico de conversas está desativado; dados de instância necessários à sessão são preservados.

Antes de atualizar a versão, faça backup do banco `barbe_evolution` e dos arquivos de configuração protegidos. Não use `git reset --hard` sem preservar a alteração de bind. Não altere o prefixo `barbe_tenant` após conectar os números. Não remova o banco nem os dados Redis para reiniciar os serviços.

Referência: [release oficial 2.3.7](https://github.com/evolution-foundation/evolution-api/releases/tag/2.3.7).
