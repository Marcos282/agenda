# Mensalidade: Mercado Pago, confirmação e comprovantes

## Fluxo

`/painel/mensalidade/` oferece `INDIVIDUAL` (R$ 30 / 30 dias, até um profissional ativo) e `PROFISSIONAL` (R$ 50 / 30 dias, profissionais ilimitados). Cada botão cria/reutiliza uma preferência e abre o Checkout Pro. A seleção não muda o plano: somente uma aprovação verificada no backend aplica o plano comprado e a renovação.

Reutilizamos `Tenant`, `CheckoutAcesso`, `PagamentoAcesso`, o serviço de envio de preferências e a validação de webhook já existentes. Não há um segundo sistema de cobrança. O UUID do checkout é a `external_reference` e também a chave de idempotência na criação da preferência. Preços são calculados pelo identificador do plano, nunca por valores enviados no navegador.

## Credenciais e configuração

Credenciais permanecem no `.env` do servidor, carregadas pelas configurações Django existentes. Não são incluídas em templates, JavaScript ou corpos de requisição exibidos no frontend.

Para produção, configure o domínio público central:

```dotenv
MERCADO_PAGO_PUBLIC_URL=https://tacombinado.net
TENANT_BASE_DOMAIN=tacombinado.net
DJANGO_DEBUG=false
MERCADO_PAGO_LIVE_MODE=true
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

A nova validade é `max(data atual no timezone do tenant, validade atual) + 30 dias`. Exemplo: validade em 05/11/2026 e pagamento antes disso resulta em 05/12/2026. Uma cobrança pendente/recusada não concede dias.

## Downgrade

O Individual exige até um profissional ativo. O checkout pode ser aberto mesmo com vários profissionais ativos. A validação ocorre ao confirmar o pagamento; a aplicação do plano fica pendente até o estabelecimento escolher quem permanecerá ativo. Não depende de quais usuários estão logados. O estabelecimento deve escolher quem continuará ativo e desativar os demais; nenhum cadastro ou histórico é excluído.

Se profissionais extras surgirem entre checkout e aprovação, a confirmação não altera plano nem validade; o webhook retorna 503 para permitir reenvio. Após desativar os extras, uma nova confirmação processa a cobrança uma única vez. O retorno do painel também pode reconsultar o pagamento. A regra de continuar com múltiplos profissionais até deslogar não está implementada.

## Registro e comprovantes

`CheckoutAcesso` mantém tenant, plano, valor, UUID/reference, criação, preferência e período comprado. `PagamentoAcesso` mantém ID Mercado Pago, status, aprovação, concessão, quantidade de dias efetivamente concedidos, validade anterior e nova validade. `NotificacaoMercadoPago` mantém a auditoria das notificações e do processamento.

O histórico mostra também pagamentos pendentes, recusados ou reembolsados, sem botão de comprovante aprovado. A mensalidade exibe o botão azul **Comprovante de pagamento** somente para pagamentos `approved` com concessão registrada. A página interna `/painel/mensalidade/comprovantes/<payment_id>/` utiliza exclusivamente os dados persistidos e mostra estabelecimento, plano, valor, data, ID, status e as duas validades. Não aceita valores ou datas da query string como conteúdo do comprovante.

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

Os testes usam o SDK simulado; não geram cobranças reais. Cobrem assinatura, validação financeira, referências, retorno forjado, isolamento de comprovantes, histórico, aprovação, pendência, vencimento, upgrade/downgrade, migração e concorrência.

## Arquivos

- `pagamentos/models.py`, `pagamentos/services.py`, `pagamentos/views.py`: registro e integração reutilizados.
- `pagamentos/migrations/0004_remove_checkoutacesso_checkout_acesso_plano_valido_and_more.py`: campos de auditoria e migração do plano.
- `tenants/models.py`, `tenants/middleware.py`, `tenants/migrations/0014_remove_tenant_tenant_plano_valido_alter_tenant_plano_and_more.py`: plano e retornos centrais.
- `barbe/urls.py`, `painel/urls.py`: webhook, retornos e comprovante.
- `painel/mensalidade_views.py`, `painel/templates/painel/mensalidade.html`, `painel/templates/painel/comprovante_pagamento.html`, `painel/static/painel/mensalidade.css`: interface e consulta por tenant.
- `profissionais/models.py`: validação do plano Profissional.
- `pagamentos/tests.py`, `pagamentos/test_receipts.py`, `painel/test_mensalidade.py`, `tenants/test_plans.py`: testes adaptados e novos.
- Fixtures em `agenda/test_booking.py`, `agenda/tests.py`, `painel/tests.py`, `whatsapp/test_returns.py`: identificador renomeado.

## Referências oficiais

- [URLs de retorno](https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/configure-back-urls)
- [Notificações de pagamento](https://www.mercadopago.com.br/developers/en/docs/checkout-pro-preferences/payment-notifications)

### Resultado da validação local

Os 63 testes de pagamentos, mensalidade e planos passaram. Uma verificação adicional de login passou em 3 de 4 testes; o teste antigo da página inicial ainda espera o texto “Já sou cliente”, enquanto o template existente usa “Entrar”. Esse template não foi alterado nesta implementação.
