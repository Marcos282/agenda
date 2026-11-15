# Mensalidade: Mercado Pago, confirmação e comprovantes

## Fluxo

`/painel/mensalidade/` oferece somente o Plano Profissional, com profissionais ilimitados e todas as funcionalidades. `PLATFORM_MONTHLY_PRICE=30.00` define o preço de R$ 30,00/mês. O botão **Renovar por 30 dias** cria/reutiliza uma preferência e abre o Checkout Pro. Somente uma aprovação verificada no backend aplica a renovação. O pagamento continua avulso, sem débito automático.

Reutilizamos `Tenant`, `CheckoutAcesso`, `PagamentoAcesso`, o serviço de envio de preferências e a validação de webhook já existentes. Não há um segundo sistema de cobrança. O UUID do checkout é a `external_reference` e também a chave de idempotência na criação da preferência. Preços de novas compras vêm de `PLATFORM_MONTHLY_PRICE`, nunca de valores enviados no navegador. A confirmação usa o valor persistido da cobrança, inclusive em pagamentos antigos.

## Credenciais e configuração

Credenciais permanecem no `.env` do servidor, carregadas pelas configurações Django existentes. Não são incluídas em templates, JavaScript ou corpos de requisição exibidos no frontend.

Para produção, configure o domínio público central:

```dotenv
MERCADO_PAGO_PUBLIC_URL=https://tacombinado.net
TENANT_BASE_DOMAIN=tacombinado.net
DJANGO_DEBUG=false
MERCADO_PAGO_LIVE_MODE=true
PLATFORM_MONTHLY_PRICE=30.00
```

Mantenha `MERCADO_PAGO_ACCESS_TOKEN` e `MERCADO_PAGO_WEBHOOK_SECRET` com os valores privados já configurados. Não publique o `.env`. No painel do Mercado Pago habilite o evento **Pagamentos** e configure o webhook HTTPS com a mesma chave secreta do servidor.

A preferência inclui:

- `notification_url`: `https://tacombinado.net/pagamentos/mercadopago/webhook/`
- `back_urls.success`: `https://tacombinado.net/pagamentos/mercadopago/sucesso/`
- `back_urls.pending`: `https://tacombinado.net/pagamentos/mercadopago/pendente/`
- `back_urls.failure`: `https://tacombinado.net/pagamentos/mercadopago/falha/`
- `auto_return`: `approved`

A antiga URL `/integracoes/mercado-pago/webhook/` permanece válida para cobranças anteriores.

## Confirmação e segurança

O webhook valida `x-signature`, `x-request-id` e o ID do evento com o SDK oficial. O ID no corpo precisa corresponder ao ID assinado na URL. Depois consulta o pagamento pela API do Mercado Pago e verifica ID, referência interna, valor exato, moeda BRL, recebedor, ambiente e preferência da ordem. Não confia em `status=approved` enviado pelo navegador.

Os retornos centrais apenas localizam a cobrança interna e redirecionam para o subdomínio correto, sem conceder acesso. O painel exige autenticação do administrador daquele estabelecimento e pode consultar a API para complementar a confirmação. A autenticação em um estabelecimento não dá acesso ao comprovante de outro.

A confirmação bloqueia a linha do tenant dentro de uma transação. O `payment_id` é chave primária e `creditado_em` registra a concessão. Repetir o webhook ou receber webhook e retorno simultaneamente não duplica os dias nem reaplica o plano.

A nova validade é `data efetiva de aprovação no fuso configurado no Django + 30 dias`, substituindo a validade anterior mesmo no pagamento antecipado. Exemplo: recebimento em 15/01/2027 resulta em validade até 14/02/2027. O backend exige `date_approved` válido com fuso horário retornado pela API autenticada; cobrança pendente/recusada ou aprovação sem data válida não concede dias. O ID único do pagamento e o bloqueio transacional por estabelecimento impedem renovação duplicada.

## Plano único e pagamentos legados

A migração para o Profissional preserva vencimentos, profissionais, checkouts e pagamentos, sem chamadas ao Mercado Pago ou cobranças adicionais. Não há downgrade nem limite de profissionais por plano. Contratações diretas de `INDIVIDUAL` ou `SIMPLES` são recusadas no backend.

Checkouts legados mantêm seu plano e valor originais nos comprovantes. Pagamentos antigos confirmados após a migração concedem os 30 dias uma única vez, mantendo o estabelecimento no Profissional. Não exigem desativar profissionais nem pagar diferença. Veja [planos-estabelecimento.md](planos-estabelecimento.md) para a operação de migração.

## Registro e comprovantes

`CheckoutAcesso` mantém tenant, plano, valor, UUID/reference, criação, preferência e período comprado. `PagamentoAcesso` mantém ID Mercado Pago, status, aprovação, concessão, quantidade de dias efetivamente concedidos, validade anterior e nova validade. `NotificacaoMercadoPago` mantém a auditoria das notificações e do processamento.

O histórico mostra também pagamentos pendentes, recusados ou reembolsados, sem botão de comprovante aprovado. Os comprovantes aprovados são escolhidos em um combobox, identificado por data, plano, valor e ID. Ao selecionar, o botão abre a página interna correspondente. A mensalidade exibe o botão azul **Comprovante de pagamento** somente para pagamentos `approved` com concessão registrada. A página interna `/painel/mensalidade/comprovantes/<payment_id>/` utiliza exclusivamente os dados persistidos e mostra estabelecimento, plano, valor, data, ID, status e as duas validades. Não aceita valores ou datas da query string como conteúdo do comprovante.

Pagamentos antigos mantêm seu histórico e seus valores. Quando não havia registros das validades anterior/nova, mostramos que a informação não foi registrada; não reconstruímos datas a partir da validade atual. Os identificadores anteriores `ILIMITADO` são migrados para `PROFISSIONAL`, sem alterar equipes ou pagamentos.

## Publicação

Depois de enviar os commits pela máquina local, no servidor:

```bash
cd /var/www/html/combinado
git pull --ff-only origin main
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart combinado
```

As migrations precisam ser aplicadas antes de reiniciar o processo com o novo código. Garanta que o domínio base, além dos subdomínios, esteja servido pelo mesmo Django e que as quatro URLs centrais sejam acessíveis por HTTPS. Configure o webhook na conta/aplicação Mercado Pago. Não é necessário cron para confirmação de pagamento.

## Testes

```bash
TENANT_BASE_DOMAIN=localhost DJANGO_DEBUG=true myenv/bin/python manage.py test pagamentos painel.test_mensalidade tenants.test_plans --noinput
```

Os testes usam o SDK simulado; não geram cobranças reais. Cobrem assinatura de webhooks, validação financeira, referências, retorno forjado, isolamento de comprovantes, histórico, aprovação, pendência, vencimento, plano único, migração sem cobranças e concorrência.

## Arquivos

- `pagamentos/models.py`, `pagamentos/services.py`, `pagamentos/views.py`: registro e integração reutilizados.
- `pagamentos/migrations/0004_remove_checkoutacesso_checkout_acesso_plano_valido_and_more.py`: campos de auditoria e migração do plano.
- `tenants/models.py`, `tenants/middleware.py`, `tenants/migrations/0014_remove_tenant_tenant_plano_valido_alter_tenant_plano_and_more.py`: plano e retornos centrais.
- `barbe/urls.py`, `painel/urls.py`: webhook, retornos e comprovante.
- `painel/mensalidade_views.py`, `painel/templates/painel/mensalidade.html`, `painel/templates/painel/comprovante_pagamento.html`, `painel/static/painel/mensalidade.css`: interface e consulta por tenant.
- `profissionais/models.py`: profissionais sem restrição de quantidade por plano.
- `pagamentos/tests.py`, `pagamentos/test_receipts.py`, `painel/test_mensalidade.py`, `tenants/test_plans.py`: testes adaptados e novos.
- Fixtures em `agenda/test_booking.py`, `agenda/tests.py`, `painel/tests.py`, `whatsapp/test_returns.py`: identificador renomeado.

## Referências oficiais

- [URLs de retorno](https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/configure-back-urls)
- [Notificações de pagamento](https://www.mercadopago.com.br/developers/en/docs/checkout-pro-preferences/payment-notifications)

### Resultado da validação local

Os 63 testes de pagamentos, mensalidade e planos passaram. Uma verificação adicional de login passou em 3 de 4 testes; o teste antigo da página inicial ainda espera o texto “Já sou cliente”, enquanto o template existente usa “Entrar”. Esse template não foi alterado nesta implementação.


## Validade inicial, tolerância e suspensão de reservas

Novos estabelecimentos recebem 60 dias corridos no cadastro: os primeiros 30 são a gratuidade comercial, seguidos de 30 dias de validade inicial. Não há classificação de inadimplência nesse intervalo. `data_expiracao` continua sendo a propriedade do modelo `Tenant` que lê o campo persistido `expira_em`. Registros existentes mantêm suas datas; o fallback legado para registros sem data continua usando cadastro + 30 dias. Não há atualização em massa de validades.

`tenants/subscriptions.py` centraliza os estados usando America/Sao_Paulo. O dia do vencimento continua válido. Os três dias seguintes são integralmente liberados: vencimento em 31/12 permite reservas até 03/01 às 23:59:59 e bloqueia em 04/01 às 00:00. O cálculo não depende de cron.

A validação ocorre no middleware nas rotas de agendamento e no serviço `reservar`, após reler e bloquear o tenant no banco. A criação pelo `save()` do modelo também é protegida. Os fluxos público, visitante, painel e WhatsApp convergem no serviço existente. Operações administrativas de banco como `bulk_create` não são API de reservas e não devem ser usadas para novas reservas.

O site, catálogo, fotos, tema e equipe permanecem visíveis. A área de horários apresenta somente a mensagem pública de indisponibilidade, sem expor o vencimento. Login, painel, clientes, consulta e atualização de reservas existentes e renovação continuam disponíveis. Não há cancelamento automático nem alteração do campo `ativo`.

O botão existente Renovação mantém posição e destino. As cores são verde (>7 dias), azul (4–7), amarelo (0–3), laranja (tolerância) e vermelho (bloqueio). Um único banner na base do painel mostra aviso, ação e horas restantes na tolerância, recalculados a cada requisição. Após pagamento, a próxima requisição reflete a validade confirmada.

## Avisos ao proprietário por WhatsApp

A rotina reutiliza o provider Evolution existente e envia ao `Tenant.telefone`, nunca aos clientes. Requer telefone válido, API configurada e instância do estabelecimento conectada. O envio ocorre três dias antes, no dia de vencimento e após bloqueio, com linguagem de renovação sem classificar a validade inicial como inadimplência.

`AvisoAssinatura` registra uma tentativa por estabelecimento, data de expiração e etapa. Envios incertos não são repetidos automaticamente; verificar a conversa antes de qualquer intervenção manual. Alterações da validade iniciam um novo ciclo de avisos. Não houve modificação das mensagens de agendamentos existentes.

Executar diariamente, preferencialmente às 09:00 de São Paulo, pelo agendador já usado na instalação:

```bash
python manage.py notificar_assinaturas
```

Nenhuma tarefa foi instalada automaticamente. Sem essa execução os avisos de WhatsApp não são enviados, mas o bloqueio e os banners continuam funcionando normalmente.

## Implantação desta alteração

Migrações: `tenants.0024` altera somente a descrição do campo, sem recalcular dados; `whatsapp.0007` cria o registro de deduplicação dos avisos. Nenhuma migração altera pagamentos ou vencimentos históricos.

Depois de revisar e transferir o código, no ambiente de destino, com o virtualenv apropriado:

```bash
python manage.py migrate
python manage.py check
python manage.py collectstatic --noinput
```

Reiniciar o serviço Django conforme a instalação e adicionar `notificar_assinaturas` ao agendador caso os avisos sejam desejados. Não foi executado deploy ou comando de migração no banco configurado do projeto.


## Validação e arquivos desta entrega

Foram aprovados **107 testes** nas suítes `tenants.test_subscriptions`, `tenants.tests`, `pagamentos.tests`, `painel.test_mensalidade`, `agenda.test_booking`, `agenda.test_guest_booking` e `usuarios.test_home`, em PostgreSQL 16 temporário, sem usar o banco configurado do projeto. O processo de teste desativou CAPTCHA e Evolution e usou hash de senha rápido. Pagamentos, relógio dos casos novos e transporte de notificações foram simulados. Os testes cobrem cadastro, preservação de datas, gratuidade, cores e avisos, tolerância, viradas de mês/ano, bloqueio GET/POST e direto no serviço/modelo, painel acessível, histórico, aprovação antecipada/tardia, data de aprovação, webhook repetido, reativação e isolamento.

A suíte adicional `painel.test_agendamento` tem 11 testes, com 7 falhas também reproduzidas no código original HEAD em cópia isolada. Estão relacionadas às expectativas de login de clientes/consulta de histórico e ao tipo de data no formulário; não foram alteradas nesta entrega. A primeira rodada sem isolar o CAPTCHA também apresentou falhas de configuração; a rodada final acima usa isolamento explícito. Não houve envio real de WhatsApp nem cobrança real.

`manage.py check`, `makemigrations --check --dry-run` e `git diff --check` passaram. Para reproduzir as suítes em um banco local de teste, com as dependências instaladas:

```bash
TENANT_BASE_DOMAIN=localhost DEV_PUBLIC_HOST='' DEV_TENANT_SUBDOMAIN='' \
TURNSTILE_ENABLED=false EVOLUTION_API_URL='' EVOLUTION_API_KEY='' \
python manage.py test tenants.test_subscriptions tenants.tests pagamentos.tests \
  painel.test_mensalidade agenda.test_booking agenda.test_guest_booking usuarios.test_home --noinput
```

Arquivos alterados/criados:

- `tenants/models.py`, `tenants/subscriptions.py`, `tenants/middleware.py`: cadastro, estados e bloqueio das rotas de reserva.
- `agenda/booking.py`, `agenda/models.py`: proteção transacional da criação de reservas.
- `pagamentos/services.py`: renovação pela aprovação efetiva, mantendo validações e idempotência existentes.
- `painel/templates/painel/base.html`, `painel/templates/painel/aviso_assinatura.html`: menu completo, cores e banner.
- `usuarios/templates/usuarios/base.html`: navegação da conta preservada após vencimento.
- `usuarios/templates/usuarios/home.html`, `usuarios/templates/usuarios/loja.html`, `usuarios/templates/usuarios/agendamentos_indisponiveis.html`, `usuarios/templates/usuarios/booking_unavailable.html`: catálogo preservado e mensagem pública.
- `whatsapp/models.py`, `whatsapp/subscriptions.py`, `whatsapp/management/commands/notificar_assinaturas.py`: registro e envio deduplicado ao proprietário.
- `tenants/migrations/0024_alter_tenant_expira_em.py`, `whatsapp/migrations/0007_avisoassinatura.py`: descrição do campo e tabela de avisos.
- `tenants/test_subscriptions.py`, `pagamentos/tests.py`, `painel/test_mensalidade.py`: cobertura nova e atualização das expectativas comerciais.
- `docs/pagamentos-mensalidade.md`: regras, validação e comandos operacionais.
