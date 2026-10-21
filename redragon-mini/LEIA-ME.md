# Redragon Mini — M719-WL

Versão experimental 0.1 para Windows 10/11, com .NET Framework 4.8. É portátil: extraia a pasta e abra `RedragonMini.exe`. Não precisa instalar o aplicativo original, Python, drivers ou serviços. O executável foi compilado e o protocolo foi testado com simulação e pacotes das capturas; ainda não foi executado no seu Windows ou validado no mouse físico.

## O que esta versão configura

| Ajuste | macOS | Windows |
|---|---|---|
| Perfil de base | 1 | 2 |
| Botão 6 | Command + 1 | Print Screen |
| Botão 5 | Manter atual ou escolher uma função/atalho | Manter atual ou escolher uma função/atalho |
| DPI e iluminação | Mantidos do perfil 1 | Mantidos do perfil 2 |

Como você já usa 2000 DPI e as cores desejadas, deixe esses valores prontos nos perfis 1 e 2 do aplicativo original. O Mini preserva os valores existentes, inclusive os outros botões, ao preparar as duas configurações. Command+1 corresponde ao seu atalho personalizado no macOS; o Mini não configura esse atalho no sistema.

## Primeiro uso e teste do botão 7

1. Extraia o ZIP em uma pasta sua. Conecte o M719-WL pelo **cabo USB** e feche o aplicativo original, inclusive a bandeja. O receptor também é reconhecido; as evidências de gravação fornecidas são principalmente do modo com cabo.
2. Abra `RedragonMini.exe`. A interface de configuração deve aparecer na lista. Se necessário, clique em **Procurar mouse**.
3. Escolha a função do botão 5 para cada sistema. **Manter configuração atual** conserva a programação existente no respectivo perfil. Para outro atalho, escolha **Atalho personalizado…**.
4. Para o objetivo de alternar pelo mouse, marque **Testar troca interna pelo botão 7 (experimental)**. O app informa que também substituirá as posições 3 e 4. Clique em **Gravar configurações**. O backup é salvo automaticamente antes da primeira gravação; não pressione o botão 7 nem desconecte o mouse durante a operação.
5. Depois da conclusão, feche o Mini, desligue/religue o mouse e teste o botão 7. O botão 6 deve alternar entre Command+1 e Print Screen. Repita por vários cliques para verificar todo o ciclo.
6. Teste no Mac pelo seu modo habitual de conexão, com o aplicativo Windows fechado. Só esse teste confirma que a troca e as configurações persistem sem software e após desligar.

**Limite importante:** o aplicativo original contém uma função interna de troca de perfil, mas não a oferece no menu deste modelo. As capturas não mostram essa função sendo acionada pelo botão. Portanto, gravar e reler seu código com sucesso **não prova** que o firmware executa a troca. Se o botão 7 não alternar os atalhos após fechar o app, use **Restaurar backup…**. Esta versão não inventa nem instala firmware para acrescentar uma função ausente.

## Por que usar quatro posições para duas configurações?

O software original trabalha com quatro posições, e não encontrei um comando comprovado para limitar seu ciclo a duas. O teste organiza as configurações como:

**1 macOS → 2 Windows → 3 macOS → 4 Windows → 1 macOS**

Assim, se a função interna percorrer quatro posições em ordem, cada clique alternará entre as duas configurações desejadas. Os ajustes dos perfis 1 e 2 são copiados para 3 e 4; bytes reservados sem interpretação são mantidos no destino. Isso substitui as configurações anteriores de 3 e 4, que ficam no backup.

Se o firmware não aceitar selecionar as quatro posições, o teste para antes de gravar. O teste também bloqueia a duplicação de perfis que referenciam macros longas: esta versão copia atalhos de teclado, mas ainda não copia os bancos dessas macros. Essa restrição não impede o modo normal de dois perfis, que mantém essas referências existentes.

Com a opção experimental desmarcada, o Mini grava somente os atalhos nos perfis 1 e 2, preserva o botão 7 e permite selecioná-los pelos botões **Ativar macOS agora** e **Ativar Windows agora**. Esse modo sozinho não resolve a troca física sem software.

## Backup e recuperação

O backup JSON inclui as regiões de configuração e atalhos que o Mini pode alterar: `0x0000–0x00BF` e `0x0100–0x02FF` de cada perfil incluído. Não é uma imagem de firmware ou de toda a memória. Macros longas fora dessas regiões não são alteradas.

Os arquivos ficam em `backups` ao lado do executável. Se a pasta não permitir escrita, ficam em `%LOCALAPPDATA%\RedragonMini\backups`. O botão **Abrir backups** abre o local usado. Guarde o primeiro backup: os seguintes representam o estado existente no momento de cada nova operação.

Para voltar ao estado anterior, conecte pelo mesmo tipo de conexão usado no backup e escolha **Restaurar backup…**. Antes de restaurar, o Mini salva outro backup. Ele confere cada bloco por releitura. Se houver desconexão durante uma gravação, tenta restaurar todos os perfis que foram incluídos; se isso falhar, reconecte e reaplique o arquivo salvo. Uma operação USB não é atômica: desligar o dispositivo ou pressionar o botão de perfil durante a gravação pode interrompê-la.

## Evidências e limitações

- Identificação encontrada: VID `3554`, PID `F55E` no cabo e `F5D5` no receptor; interface `MI_01`, coleção `COL05`; confirmação de modelo CID `23`, MID `41`.
- A seleção de perfil pelo computador e os formatos de gravação/releitura estão nas capturas fornecidas. Os atalhos foram conferidos também no código do aplicativo original.
- O código de troca de perfil do botão 7 vem da função `SetChangeConfigKey` do aplicativo, e seu funcionamento no firmware atual permanece experimental.
- Não há processo em segundo plano para interceptar o botão. O objetivo do teste é verificar a função autônoma do próprio mouse.
- Os arquivos chamados de Reset e atualização enviados são byte a byte idênticos. O firmware recuperado deles não teve correspondência comprovada com a revisão capturada; não foi utilizado no app.
- Nenhum executável ou DLL proprietário enviado foi executado ou incluído nesta distribuição. O Mini usa as APIs HID do Windows.
- O executável não possui assinatura digital. Código-fonte e instruções de compilação estão incluídos para inspeção.

## Compilar a partir do fonte

No Windows com .NET Framework 4.8, execute `build.cmd` na pasta do projeto. Ele usa o compilador do próprio Framework e gera `dist\RedragonMini.exe`. Não requer pacotes externos. Também há um projeto SDK `src\RedragonMini.csproj` para quem já usa o SDK .NET; esse caminho restaura apenas as referências de compilação do Framework.

Os testes podem ser executados com Python 3 e SDK .NET 8 por `python scripts/validate.py`. Eles simulam o dispositivo; não fazem gravações USB. Os relatórios de engenharia reversa estão em `docs`.
