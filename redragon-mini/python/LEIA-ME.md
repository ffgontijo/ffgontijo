# Redragon Mini Python 0.4

Configurador para rodar uma vez no **Windows**, usando **Python 3.10 ou superior**. Depois da gravação e dos testes, o objetivo é usar os atalhos armazenados no próprio mouse, sem este programa aberto no Windows ou no Mac.

Não precisa instalar pacotes com `pip`, drivers ou serviços. Não contém um executável próprio: usa o Python e as APIs HID do Windows.

## Adicionar as cores aos perfis que já funcionam

A versão 0.2 foi **testada por você no mouse real**, com os botões 4, 5, 6 e 7 funcionando por cabo, receptor 2,4 GHz e Bluetooth. A versão 0.3 gravou e releu as cores, mas a luz permaneceu vermelha e apagava ao mover no modo sem fio. A versão 0.4 amplia o ajuste para os dois grupos de iluminação e desativa esse apagamento. Use **5 — Ajustar SOMENTE ILUMINAÇÃO**:

| Perfil identificado pelos atalhos atuais | Faixa RGB e indicador de DPI, fixos |
|---|---|
| macOS | Rosa/magenta — R:255 G:0 B:255 (`#FF00FF`) |
| Windows | Vermelha — R:255 G:0 B:0 (`#FF0000`) |

1. Extraia este ZIP em uma pasta nova e abra **Iniciar.cmd**. Use o mesmo Python já instalado.
2. Conecte o mouse pelo **cabo USB de dados** e feche o aplicativo original da Redragon.
3. Escolha **5**. Pressione o botão 7 **uma vez por etapa**, somente quando solicitado, depois Enter. O programa reconhece cada perfil pelos atalhos existentes; não presume o sistema pelo número do banco.
4. Ele salva um backup novo e configura **a faixa RGB e todas as cores do indicador de DPI**, com efeito fixo e brilho máximo, além de desativar **Lights off when moving** em todos os bancos. Os valores de DPI não são alterados. Não é necessário copiar backups antigos para esta pasta.
5. Siga a etapa de desconectar, desligar por cinco segundos e reconectar. O programa relê todos os bancos e pede novos cliques do botão 7. Depois de cada clique, confere o perfil selecionado fisicamente, sem selecioná-lo primeiro pelo computador, e mostra as duas cores e a opção de movimento lidas.
6. Com a conexão do configurador fechada, pressione o botão 7 e confira visualmente **macOS rosa ↔ Windows vermelho**. Responda `s` se alternou ou `n` se não alternou. Os dados lidos e a confirmação visual são registrados separadamente: memória correta não comprova, sozinha, que o firmware exibiu as cores. Teste também pelo receptor e Bluetooth.

**A opção 5 não regrava botões, atalhos ou valores de DPI.** Conserva macros, quantidade e índice das etapas DPI e tempo de repouso. A cor do indicador, seu efeito e seu brilho fazem parte desta atualização; a preferência de apagar ao mover é explicitamente desativada. O perfil que estava ativo no início da operação é selecionado novamente ao final. A verificação após reconexão também devolve a seleção que encontrou. O efeito é fixo, sem respiração ou animação; o desligamento por repouso continua seguindo o tempo existente do mouse.

Os testes de software cobrem a nova gravação e a recuperação. As capturas originais tinham o indicador da primeira etapa DPI vermelho nos dois perfis; a versão 0.3 conservava essa tabela e a opção de apagar ao mover. A versão 0.4 configura esses registros também, mas a exibição física precisa da sua conferência. Se os bytes estiverem corretos e a luz ainda não alternar, responda `n` e guarde o log dos bancos mostrado pelo programa; isso aponta para uma diferença na ativação da iluminação pelo firmware, não para uma confirmação visual bem-sucedida.

## Os dois perfis

| Botão da imagem | Perfil macOS | Perfil Windows |
|---|---|---|
| 4 | Command+V — colar | Ctrl+V — colar |
| 5 | Command+C — copiar | Ctrl+C — copiar |
| 6 | Command+1 — captura definida por você | Print Screen |
| 7 | Alternar a configuração interna | Alternar a configuração interna |

Na configuração inicial pela **opção 1**, o configurador grava **2000 DPI em todas as etapas habilitadas** dos dois perfis. A iluminação e as demais funções partem dos perfis 1 e 2 existentes; as cores são preservadas nessa opção. Depois, a opção 5 acrescenta rosa/vermelho. Isso corrige uma diferença das capturas: nelas o perfil macOS estava com 3500 DPI. O programa não configura o atalho Command+1 no macOS; esse atalho precisa continuar cadastrado no sistema.

## Configuração inicial completa — opção 1

Se os atalhos já funcionam, use somente a opção 5 descrita acima.

1. Instale o **Python 3.10 ou superior para Windows**, se ainda não tiver. Use o instalador oficial de <https://www.python.org/downloads/windows/>. O iniciador reconhece `py` ou `python`.
2. Extraia o ZIP inteiro em uma pasta sua. Não abra os arquivos de dentro do ZIP.
3. Conecte o **cabo USB de dados diretamente ao mouse e ao PC**. O receptor USB e o Bluetooth não são usados para gravar nesta versão.
4. Feche o aplicativo original da Redragon, inclusive o ícone da bandeja.
5. Abra **Iniciar.cmd** e escolha **1 — Configurar os dois perfis**. Não é necessário executar como administrador.
6. Durante o teste solicitado, pressione **uma única vez o botão 7**, e depois Enter no teclado. Não pressione botões enquanto o programa estiver lendo ou gravando.
7. Ao terminar a gravação, o programa pede para desconectar o cabo, colocar a chave inferior em **OFF**, aguardar pelo menos cinco segundos e reconectar. Ele observa a desconexão USB e confere os dados novamente. Siga o procedimento de desligamento: observar o USB desaparecer não mede se a bateria foi desligada.
8. Conclua os cliques de conferência do botão 7. Feche o configurador e teste os atalhos reais no Windows e no Mac, inclusive pelo receptor e Bluetooth se pretende usar esses modos.

Se preferir o terminal, rode `py -3 configure.py`. Para consultar a identificação sem gravar configurações, use `py -3 configure.py --inspect` ou a opção 2 do menu.

## O que o assistente realmente verifica

A presença de uma função no software genérico não comprova suporte no firmware do seu mouse. Esta versão primeiro faz um teste físico limitado:

- Confirma a identificação de modelo pelo USB e lê os perfis de base.
- Salva um backup local durável **antes da primeira alteração**.
- Grava temporariamente apenas a função do botão 7 no banco em teste.
- Fecha a conexão e o modo de configuração do programa antes de cada clique solicitado.
- Lê o banco ativo depois do clique. Se aparecer outro banco, faz seu backup antes de alterar seu botão 7.
- Só aceita um ciclo repetível de dois ou quatro bancos. Um ciclo sem mudança, irregular ou ímpar interrompe o processo e tenta restaurar os dados originais.
- Depois prepara os atalhos dos botões 4, 5 e 6 e verifica cada gravação por releitura.

Se o firmware percorrer **dois bancos**, são as duas configurações pedidas. Se ele percorrer **quatro bancos**, a ordem real observada recebe macOS → Windows → macOS → Windows, para cada clique alternar entre duas configurações lógicas. Nesse caso os bancos extras também serão substituídos, com os originais no backup. Os números físicos podem aparecer no relatório; o programa não presume que todos os modelos tenham quatro posições.

**Se o botão 7 não trocar o banco com o configurador desconectado, esta versão para.** Ela não instala um remapeador, não simula a troca no computador e não acrescenta ao firmware uma função que ele não tenha. Não há firmware novo compatível comprovado nos anexos enviados.

## Compatibilidade com o M719RGB-PRO V2 da foto

A etiqueta identifica um M719RGB-PRO, versão V2, com cabo, 2,4 GHz e Bluetooth. As capturas fornecidas identificam o protocolo USB `3554:F55E` no cabo, com CID `0x17`, MID `0x29`, tipo `2`; o receptor é `3554:F5D5`, tipo `0`. O configurador confirma esses identificadores e a interface exata antes de gravar.

O nome comercial não basta para assumir que revisões diferentes usam o mesmo protocolo. Se seu mouse atual apresentar outros identificadores, a opção 2 mostra os candidatos em modo de leitura, e a gravação é recusada. Não são tentados comandos de outros modelos por aproximação.

As capturas comprovam gravações no modo com cabo. Depois de usar a versão 0.2, você confirmou o funcionamento real dos botões e da troca de perfis por cabo, receptor e Bluetooth. Na versão 0.3, você confirmou a persistência dos bytes das cores após reconexão, mas relatou ausência da alternância visual. A iluminação da versão 0.4 ainda requer conferência nesses modos.

## Backup, cancelamento e restauração

Os backups ficam na pasta `backups` ao lado dos scripts. Se ela não permitir escrita, o programa usa `%LOCALAPPDATA%\RedragonMiniPython\backups` e informa o caminho.

Cada arquivo JSON guarda os bytes originais, checksums, bancos observados e estado do procedimento. Guarde o primeiro backup de uma configuração. As regiões incluídas são `0x0000–0x00BF` e `0x0100–0x02FF`; não é uma cópia do firmware ou da memória inteira.

Um backup criado pela opção 5 recebe `operation: "rgb_only"` e `lighting_scope: "main_dpi_movement"`. Tanto a recuperação automática quanto **4 — Restaurar backup**, ao usar esse arquivo, restauram somente os registros de iluminação modificados: faixa RGB, cores e efeito/brilho do indicador, e opção de apagar ao mover. Outras configurações alteradas posteriormente não são substituídas. Backups RGB da versão 0.3, sem esse campo de escopo, continuam restaurando somente a faixa principal. Backups antigos da configuração completa continuam restaurando a configuração completa.

**Ctrl+C durante a configuração** tenta restaurar os dados originais. Uma desconexão pode impedir a restauração automática; reconecte pelo cabo e escolha **4 — Restaurar backup**. A restauração consegue reparar registros de botão deixados com checksum inválido por uma gravação interrompida, usando um backup válido.

Se o programa for encerrado à força durante uma gravação, o próximo assistente detecta o registro interrompido e solicita restaurá-lo antes de uma nova configuração. Assim, um botão 7 temporariamente alterado não vira, silenciosamente, o novo estado original.

Antes de restaurar, o programa registra o estado atual. Registros já corrompidos são guardados como diagnóstico, não como destinos válidos de restauração. Se a conexão cair durante uma reparação, reaplique o backup original. Nenhuma operação USB é atômica; não pressione o botão de perfil durante transferências.

**Ctrl+C somente no teste de reconexão** deixa a configuração gravada, com a verificação pendente. Use **3 — Verificar configuração** posteriormente.

Esta versão copia atalhos simples, mas não os bancos de macros longas fora das regiões salvas. Se duplicar um banco exigiria copiar uma macro longa usada por outro botão, ela para e restaura em vez de criar uma referência incorreta.

## O que mudou desde o aplicativo 0.1

- Os botões 4, 5 e 6 agora são todos configurados explicitamente.
- A troca interna pelo botão 7 é testada antes da gravação final.
- A quantidade e a ordem dos bancos vêm do comportamento observado, não de um número fixo da interface original.
- A conexão do configurador é fechada entre os cliques do teste físico.
- Backup, restauração e leitura após reconexão fazem parte do mesmo assistente.
- O transporte usa `WriteFile` do Windows como a biblioteca original, com leitura sobreposta e limite de espera.
- A versão de firmware `04 01` deve ser interpretada como **4.01**; a documentação antiga invertia os bytes na exibição.

## Testes e código

Os módulos estão em arquivos `.py` legíveis. Execute os testes de simulação com:

```text
py -3 -m unittest discover -s tests -v
```

Os testes não abrem dispositivos nem gravam USB. Eles verificam pacotes capturados, atalhos, proteção de identidade/banco, backups, falhas e restauração. Não substituem a execução no Windows e o teste físico do mouse.
