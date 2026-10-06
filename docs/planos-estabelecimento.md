# Planos por estabelecimento

A página `/painel/mensalidade/` permite ao administrador escolher o plano do seu próprio estabelecimento:

No topo esquerdo do painel, o nome do estabelecimento aparece acompanhado de “Individual” ou “Profissional”, conforme o plano atual. Uma cobrança pendente não altera essa identificação.

| Identificador | Nome exibido | Valor / 30 dias | Profissionais ativos |
| --- | --- | --- | --- |
| `INDIVIDUAL` | Plano Individual | R$ 30,00 | Até 1 |
| `PROFISSIONAL` | Plano Profissional | R$ 50,00 | Sem limite |

Ambos incluem agendamentos online, WhatsApp, histórico de clientes, loja online e QR Code. O plano fica no campo `Tenant.plano`, representado por `TextChoices`. O preço é calculado no servidor a partir do identificador; valores ou IDs de estabelecimento enviados pelo navegador não alteram essa regra.

## Troca de plano

A seleção inicia a cobrança e preserva o plano atual até a confirmação do pagamento. Os dois botões “Escolher este plano” criam a preferência com o valor do plano escolhido e abrem o checkout. A abertura do checkout não acrescenta dias: a renovação depende de pagamento avulso confirmado, sem cobrança automática. O checkout Individual pode abrir com vários profissionais ativos; a aplicação do downgrade é validada após a aprovação.

Para trocar para o Individual com vários profissionais ativos, abra `/painel/profissionais/`, escolha quem continuará ativo e desative os demais. A troca será recusada enquanto houver mais de um ativo. Nenhum cadastro, agenda ou histórico é excluído. Profissionais inativos podem continuar cadastrados; o limite se aplica à criação de profissionais ativos e à ativação de cadastros existentes.

O checkout guarda o identificador do plano e o valor da compra. Uma prévia de checkout de outro plano não é reutilizada depois da troca. A confirmação validada de cada pagamento aplica o plano registrado no checkout e acrescenta os dias comprados, uma única vez. Pagamentos pendentes ou recusados não mudam o plano. O limite de profissionais é verificado novamente na confirmação; se surgirem profissionais extras durante um checkout Individual, a aplicação fica pendente até a desativação deles e uma nova confirmação. `PLATFORM_ACCESS_PRICE` não define mais o preço de renovação dos tenants.

## Proteção no backend

Os modelos validam a criação/ativação de profissionais e o downgrade. As gravações pelos modelos bloqueiam a linha do tenant durante a transação, serializando operações concorrentes. Triggers PostgreSQL também protegem `bulk_create`, `QuerySet.update` e gravações que contornem `save()`. Constraints limitam o plano aos dois identificadores permitidos.

Consultas, contagens e alterações usam o tenant autenticado. Só administradores do próprio estabelecimento podem selecionar planos. O painel mantém os controles existentes de pagamento, expiração e comprovantes.

## Migração dos estabelecimentos existentes

A migração original atribui `ILIMITADO` (posteriormente renomeado para `PROFISSIONAL`) aos estabelecimentos que já possuem mais de um profissional ativo. Os demais recebem `INDIVIDUAL`. Não altera a validade nem desativa profissionais. Checkouts históricos recebem `INDIVIDUAL` como identificação legada, sem mudar seus valores ou os pagamentos anteriores.

## Publicação

Depois de enviar o código pelo Git, no servidor:

```bash
cd /var/www/html/combinado
git pull --ff-only
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart combinado
```

Aplicar as migrations antes de reiniciar é necessário para evitar erro de coluna inexistente. Faça o backup habitual do banco antes da publicação. Esta funcionalidade não precisa de cron ou timer.

## Verificação

```bash
TENANT_BASE_DOMAIN=localhost DJANGO_DEBUG=true myenv/bin/python manage.py test tenants.test_plans tenants.tests painel.test_mensalidade pagamentos painel.tests agenda.tests whatsapp.test_returns --noinput
```

Os testes de planos cobrem criação/ativação, requisições diretas, isolamento, upgrade após pagamento, downgrade sem exclusão, preços e prévias de checkout, gravações em lote e concorrência.

## Arquivos da implementação

- `tenants/models.py`, `tenants/admin.py`: identificação, valor e validação do plano.
- `tenants/migrations/0012_tenant_plano_tenant_tenant_plano_valido.py`: campo e preservação de equipes existentes.
- `tenants/migrations/0013_proteger_limite_profissionais.py`: proteção PostgreSQL contra gravações que contornem os modelos.
- `profissionais/models.py`, `painel/views.py`: validação de profissionais ativos e mensagens de erro.
- `painel/mensalidade_views.py`: formulário e seleção por tenant, incluindo invalidação da prévia de pagamento.
- `painel/templates/painel/mensalidade.html`, `painel/static/painel/mensalidade.css`: cards e plano atual.
- `pagamentos/models.py`, `pagamentos/services.py`, `pagamentos/migrations/0003_checkoutacesso_plano.py`: plano na cobrança, preços e reutilização segura de checkout.
- `tenants/test_plans.py`: testes dos planos, concorrência e migração.
- `painel/test_mensalidade.py`, `pagamentos/tests.py`: testes do painel e pagamento adaptados aos planos e à autenticação atual.
- `painel/tests.py`, `agenda/test_booking.py`, `agenda/tests.py`, `whatsapp/test_returns.py`: fixtures com várias agendas identificam explicitamente o plano Ilimitado.
- `README.md`, `docs/planos-estabelecimento.md`: documentação.

### Resultado da validação

Passaram 115 testes das áreas afetadas e mais 3 testes de migração e confirmação de pagamentos (118 no total). A verificação ampliada encontrou 9 falhas em testes antigos de login de clientes, agendamento e limite diário. As mesmas 9 falhas foram reproduzidas em uma cópia do commit anterior à implementação; não foram introduzidas pelos planos.

A implementação atual de callbacks e comprovantes está em [pagamentos-mensalidade.md](pagamentos-mensalidade.md).
