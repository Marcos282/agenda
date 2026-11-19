from . import guide

CATEGORY = dict(id='profissionais', title='Profissionais', icon='👥', description='Monte a equipe que aparece no seu site.', tutorials=[
    guide('cadastrar-profissional', 'Cadastrar e editar um profissional',
          'Cada profissional tem seus próprios serviços e períodos de atendimento.',
          ['No menu Profissionais, escolha Novo profissional.', 'Preencha Nome e os contatos que desejar informar. Confira o campo Ativo.',
           'Salve. Para corrigir dados depois, volte à lista e escolha Editar profissional no cartão desejado.',
           'Para suspender novos atendimentos dessa pessoa, desmarque Ativo e salve. Reative o mesmo cadastro quando ela voltar.'],
          'Profissionais inativos deixam de participar das ofertas disponíveis para novas reservas. O histórico dos agendamentos é preservado.',
          [('Nome', 'Profissional de exemplo'), ('Telefone / E-mail', 'Contatos do profissional'), ('Ativo', 'Marcado: disponível para novas reservas')],
          ('fotos-profissional', 'vincular-servico'), 'cadastrar profissional equipe editar ativar desativar'),
    guide('fotos-profissional', 'Adicionar foto e imagem de fundo',
          'A foto identifica o profissional. A imagem de fundo aparece na página de agendamento desse profissional.',
          ['Em Profissionais, abra Editar no cadastro desejado.', 'No campo Foto, selecione uma imagem do seu dispositivo.',
           'No campo de imagem de fundo, selecione a arte desejada. Salve e confira a página pública do profissional.',
           'Para trocar, envie outra imagem e salve. Use os controles de remoção do formulário se quiser retirar a imagem atual.'],
          'Envie arquivos de até 5 MB e até 4096 × 4096 pixels. Use imagens próprias ou autorizadas, sem dados de clientes.',
          [('Foto', 'Retrato do profissional'), ('Imagem de fundo', 'Arte da página de agendamento'), ('Após salvar', 'Confira o resultado no site')],
          ('cadastrar-profissional', 'personalizar-site'), 'foto imagem fundo banner profissional'),
])
