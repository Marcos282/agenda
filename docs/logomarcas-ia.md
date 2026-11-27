# Logomarcas com IA

A geração está em **Personalização → Conteúdo do Site**. Cada estabelecimento recebe três créditos na migração ou no cadastro. O saldo só diminui quando uma imagem válida é salva. **Minhas logomarcas** permite baixar ou aplicar as imagens já geradas. O upload manual continua disponível.

## Configuração da OpenAI

1. No projeto da [plataforma da OpenAI](https://platform.openai.com/), configure o faturamento e confirme que o projeto tem acesso ao modelo escolhido. Crie uma chave do projeto para o backend com acesso ao endpoint de geração de imagens.
2. No arquivo `.env` ao lado de `manage.py`, configure os valores abaixo. Restrinja a leitura do arquivo à conta do serviço e mantenha-o fora do Git.

   ```dotenv
   OPENAI_API_KEY=<chave do projeto>
   OPENAI_IMAGE_MODEL=gpt-image-2.5-flare
   ```

3. O modelo deve aceitar `1024x1024`, `quality=high`, fundo transparente e PNG na [API oficial de imagens](https://developers.openai.com/api/reference/resources/images/methods/generate). O valor de `OPENAI_IMAGE_MODEL` é opcional e fica registrado por solicitação. A chave é obrigatória e lida diretamente de `.env` pelo processo da fila.

A geração é cobrada pela OpenAI conforme o modelo e o consumo. Créditos do Tá Combinado são um limite interno para o lojista. Uma resposta inválida, um timeout ou uma interrupção pode ter consumo no provedor mesmo quando nenhum crédito é descontado. A fila não repete automaticamente essas solicitações. O modelo pode errar a escrita do nome, que deve ser conferida na prévia antes de aplicar.

## Desenvolvimento e teste

No diretório `agenda/`, com o ambiente virtual ativo e o PostgreSQL configurado:

```bash
python manage.py migrate
python manage.py test painel.test_logo_generation
python manage.py runserver
```

Em outro terminal, execute `python manage.py process_logo_generation`. A opção `--once` processa até um pedido e encerra. Os testes automatizados simulam a API e não exigem uma chave. Execute também `python manage.py test painel.test_logo_browser` para testar o fluxo em desktop e mobile com Chrome em `/usr/bin/google-chrome`.

Para um teste real, habilite **Configuração de logomarcas com IA** no Django Admin. Em **Créditos de logomarcas**, confira se o estabelecimento de teste está habilitado. Acesse seu subdomínio como administrador, gere uma imagem e verifique a prévia, o saldo, o download e a aplicação no site. Faça uma geração nova para testar **Gerar novamente**. Em **Histórico de geração de logomarcas**, confira o estado, a identificação do pedido no provedor, o consumo informado e o código de erro, quando houver.

## Implantação em produção

1. Mantenha a geração desativada durante a implantação. Faça backup do PostgreSQL e do diretório `private-theme-media/`.
2. Instale o código. Execute `python manage.py migrate` e `python manage.py collectstatic --noinput` com o ambiente de produção. Reinicie o Gunicorn pelo procedimento normal do servidor. Nenhuma nova dependência Python é necessária.
3. Configure um serviço de fila separado, com a mesma conta, diretório de trabalho, configuração do banco e armazenamento privado do serviço web. Em implantações com mais de um host, compartilhe o volume `private-theme-media/` entre o worker e todos os servidores web.
4. Use um timer systemd para executar uma geração por chamada. O timeout do serviço limita a execução completa, além do timeout de rede da aplicação. Substitua os caminhos de exemplo pelos do servidor.

   `~/.config/systemd/user/barbe-logomarcas.service`

   ```ini
   [Unit]
   Description=Processar fila de logomarcas do Tá Combinado

   [Service]
   Type=oneshot
   WorkingDirectory=/caminho/agenda
   ExecStart=/caminho/agenda/myenv/bin/python manage.py process_logo_generation --once
   TimeoutStartSec=240
   ```

   `~/.config/systemd/user/barbe-logomarcas.timer`

   ```ini
   [Unit]
   Description=Consultar a fila de logomarcas do Tá Combinado

   [Timer]
   OnBootSec=10s
   OnUnitInactiveSec=3s
   AccuracySec=1s

   [Install]
   WantedBy=timers.target
   ```

5. Como usuário do serviço, execute:

   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now barbe-logomarcas.timer
   systemctl --user list-timers barbe-logomarcas.timer
   ```

6. Ative o recurso no Django Admin e valide primeiro com um estabelecimento de teste. O ajuste de saldo aceita números positivos ou negativos. A configuração de créditos iniciais vale para novos cadastros. O saldo não é renovado automaticamente.

Para suspender novas gerações, desative a configuração global. Trabalhos que já chamaram a API podem terminar e cobrar o crédito se forem bem-sucedidos. Prévia, download e reaplicação do histórico permanecem disponíveis. Um trabalho interrompido é marcado como falho pela próxima varredura após cinco minutos, quando já não há um worker segurando sua trava.
