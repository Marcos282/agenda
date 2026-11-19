from . import guide

CATEGORY = dict(id='servicos', title='Serviços', icon='✂️', description='Organize o catálogo, os preços e o tempo de atendimento.', tutorials=[
    guide('cadastrar-servico', 'Cadastrar e editar serviços',
          'O cadastro do serviço guarda o nome do atendimento e se ele está ativo. Valor e duração são definidos no vínculo com o profissional.',
          ['Abra Serviços no menu e escolha Novo serviço.', 'Informe o nome do atendimento e marque Ativo. Salve o cadastro.',
           'Para alterar o nome ou a situação, abra Editar na lista de serviços.',
           'Depois vincule o serviço aos profissionais que o realizam. Desativar o serviço retira sua disponibilidade para novas reservas.'],
          'Desativar preserva o histórico. Evite criar outro serviço só para mudar seu preço: edite o vínculo com o profissional.',
          [('Nome', 'Atendimento de exemplo'), ('Ativo', 'Disponível no catálogo'), ('Próximo passo', 'Vincular ao profissional')],
          ('vincular-servico',), 'cadastro editar serviço catálogo disponibilidade'),
    guide('vincular-servico', 'Vincular serviços, configurar preço e duração',
          'O mesmo serviço pode ter valores e durações diferentes para cada profissional.',
          ['Abra Profissionais e entre em Serviços do profissional desejado.', 'Clique em + Adicionar serviço e selecione um serviço ativo ainda não vinculado.',
           'Preencha Valor (R$) e Duração (minutos). Mantenha Ativo marcado e salve.',
           'Para mudar preço ou duração, edite o vínculo existente. Se ele já estiver na lista, não é necessário cadastrá-lo novamente.',
           'Para parar de oferecer só esse atendimento com essa pessoa, use Deixar de oferecer. Para reativar, use Voltar a oferecer, com o serviço e o profissional ativos.'],
          'Serviço, profissional e vínculo precisam estar ativos. A duração também precisa caber dentro de um período aberto da agenda.',
          [('Serviço', 'Atendimento de exemplo'), ('Valor (R$)', '40,00'), ('Duração (minutos)', '40'), ('Ativo', 'Vínculo disponível')],
          ('cadastrar-profissional', 'cadastrar-servico', 'abrir-agenda'), 'valor preço minutos duração associar vincular serviço profissional'),
])
