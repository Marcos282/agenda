from . import guide

CATEGORY = dict(id='personalizacao', title='Personalização', icon='🎨', description='Deixe o site com a cara do seu estabelecimento.', tutorials=[
    guide('personalizar-site', 'Escolher tema, cores e logomarca',
          'Personalização reúne a aparência e as opções visuais atualmente disponíveis para seu site.',
          ['Abra Personalização no menu.', 'Escolha um tema e ajuste a cor principal. Use a prévia para conferir o resultado antes de salvar.',
           'Na área de conteúdo, selecione a logomarca. Prefira PNG ou WebP com fundo transparente; a recomendação é 600 × 200 ou 300 × 300 pixels.',
           'Use as opções Ativar imagem, Desativar sem remover ou Remover imagem do site para controlar a logomarca.',
           'Confira também o ícone decorativo e a opção Hero sem cor. Salve as alterações da seção e abra o site para verificar.'],
          'As imagens Foto e Imagem de fundo dos profissionais são editadas em Profissionais. Campos de banner e textos antigos do tema não são opções de edição na tela atual.',
          [('Aparência', 'Tema + cor principal'), ('Conteúdo', 'Ícone + logomarca + Hero sem cor'), ('Conferência', 'Prévia → salvar → conferir site')],
          ('fotos-profissional', 'restaurar-visual'), 'personalização personalizar tema cores logo logotipo logomarca imagem prévia'),
    guide('restaurar-visual', 'Visualizar e restaurar o tema',
          'A prévia permite conferir o visual. Restaurar é uma ação separada, que volta a configuração de aparência ao padrão.',
          ['Na Personalização, use a opção de visualizar a prévia para conferir o site.',
           'Se quiser começar novamente, localize a ação de restaurar o padrão e leia a confirmação.',
           'A restauração volta o tema e a cor ao original e remove a exibição das imagens e demais opções do tema. Os arquivos são preservados, mas não há recuperação automática da aparência anterior. Confirme somente se deseja isso; depois confira o site.'],
          'Restaurar não é um histórico de versões nem um botão para desfazer qualquer alteração. Confira as imagens e opções que serão restauradas na tela.',
          [('Visualizar', 'Confira sem receber reservas na prévia'), ('Restaurar', 'Leia e confirme a volta ao padrão'), ('Depois', 'Revise o site público')],
          ('personalizar-site',), 'restaurar padrão visualizar prévia tema'),
])
