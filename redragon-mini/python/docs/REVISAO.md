# Revisão da versão Python 0.2

O objetivo é configurar o próprio mouse uma vez: botão 4 colar, botão 5 copiar, botão 6 captura e botão 7 alternar duas configurações, sem remapeador aberto no computador. O configurador roda no Windows; a execução dos atalhos após a gravação deve vir da memória do mouse.

## Correções verificáveis

| Questão da implementação anterior | Implementação atual |
|---|---|
| Botão 4 ficava dependente da programação anterior | Botões 4, 5 e 6 recebem explicitamente os atalhos de cada sistema |
| Preservar os DPIs manteria 3500 no banco macOS capturado | Todos os estágios habilitados recebem a codificação confirmada de 2000 DPI |
| A interface genérica oferecia quatro perfis | A quantidade e a ordem vêm de um ciclo medido com o botão físico |
| A existência de `ProfileSwitch` no aplicativo era tratada como opção de gravação | Primeiro há um teste limitado do botão 7, com a conexão de configuração fechada entre cliques |
| Um checksum de botão parcialmente gravado poderia impedir a restauração | A recuperação lê o estado bruto e repara com uma cópia original validada |
| Uma consulta posterior poderia deixar um status de verificação antigo | O estado de verificação é invalidado antes de uma nova conferência |
| Encerrar a janela durante o teste poderia deixar uma programação temporária | O registro durável interrompido é reconhecido antes de outra configuração |
| Opção de execução dependia de um EXE próprio que o Windows recusou abrir | A distribuição usa scripts Python legíveis e o Python instalado pelo usuário |

A causa do bloqueio do EXE 0.1 no computador do usuário não foi determinada. A revisão estática daquele arquivo não mostrou defeito estrutural. A versão Python atende à nova preferência de execução; não deve ser apresentada como diagnóstico de uma política do Windows.

## Evidência de protocolo

As capturas e a análise estática do aplicativo fornecido estabelecem:

- VID `3554`, PID cabeado `F55E` e receptor `F5D5`; interface `MI_01`, coleção `COL05`.
- Identificação do modelo: CID `0x17`, MID `0x29`, tipo `2` no cabo e `0` no receptor.
- Relatório **Output** ID `08`, com **17 bytes incluindo o identificador**; respostas na interrupção IN `82`. Não é um Feature Report de 18 bytes.
- O código original envia os relatórios por `WriteFile` e prepara `ReadFile` sobreposto. O Python usa o mesmo caminho, com prazo compartilhado e cancelamento seguro dos buffers nativos.
- Checksum de relatório: soma dos 17 bytes módulo 256 igual a `0x55`. Escritas têm ACK idêntico ao comando; a versão atual também faz releitura e confere o banco ativo em cada bloco.
- Perfil ativo por `0E`, seleção pelo computador por `0F`. As capturas comprovam bancos 0 e 1 selecionáveis, mas não a troca pelo botão físico.
- A ação genérica `SetChangeConfigKey` produz o registro `09 00 00 4C`. Seu funcionamento neste firmware precisa do teste real.
- A operação `12` informa versão; `04 01` é **v4.01**, não uma contagem de quatro bancos.

## Endereços e DPI

| Botão | Registro da função | Registro do atalho |
|---|---|---|
| 4 | `0x0070` | `0x0180` |
| 5 | `0x006C` | `0x0160` |
| 6 | `0x0084` | `0x0220` |
| 7 | `0x0088` | `0x0240` |

A quantidade de etapas DPI fica no byte `0x02`, com checksum em `0x03`; o índice ativo é zero-based em `0x04`, com checksum em `0x05`. Cada etapa ocupa quatro bytes a partir de `0x0C + 4*i`. O cabeçalho do sensor 8960 e as capturas confirmam **2000 DPI = `14 14 00 2D`**. As cores dos estágios ficam separadamente em `0x2C + 4*i`.

A implementação verifica os metadados das etapas, conserva quantidade e índice ativo, grava 2000 em cada etapa habilitada e preserva as cores. Bytes sem interpretação estabelecida em `0x54–0x5F` e `0xBB–0xBF` são mantidos no banco de destino.

## Compatibilidade e limites reais

A foto mostra **M719RGB-PRO / Invader Pro / versão V2**, com Bluetooth, 2,4 GHz e cabo. A configuração do pacote original diz M719-WL e usa `XIn1=2`, mas esse parâmetro seleciona controles da interface; não demonstra, sozinho, incompatibilidade nem ausência de Bluetooth. A decisão de gravar usa identificação USB e resposta real do dispositivo, sem ampliar a lista autorizada a partir de um nome comercial.

O instalador foi extraído estaticamente e não trouxe firmware `.bin`/`.hex`, configuração V2 alternativa ou outro aplicativo. O payload 8051 dos utilitários chamados Reset e atualização não teve correspondência comprovada com a revisão capturada. Nenhum firmware é gravado por esta ferramenta.

Permanecem dependentes do mouse físico: suporte à ação interna, sequência de bancos, retenção ao desligar e compartilhamento dos perfis com receptor/Bluetooth. O assistente testa os pontos acessíveis pelo cabo e solicita testes de teclas em cada sistema e conexão. Não há software em segundo plano para substituir uma função ausente no firmware.

O backup cobre as regiões modificáveis `0x0000–0x00BF` e `0x0100–0x02FF`; não é imagem completa da memória. Macros longas não são copiadas por aproximação. O programa recusa a duplicação quando ela exigiria replicar uma dessas macros.

Uma transferência USB não é atômica. O usuário precisa evitar cliques durante leituras/gravações e guardar o backup original. Após uma falha de conexão, a restauração pode precisar ser repetida pelo cabo.

## Validação de software

Os testes de codec, transporte simulado, serviço e assistente usam a biblioteca padrão Python e não abrem dispositivos. São verificados pacotes reais, codificação dos atalhos, 2000 DPI, ciclos 2/4, rejeição de ciclo ímpar ou sem mudança, ausência de handle durante o clique solicitado, backup antes de cada primeira alteração, falhas de confirmação, troca inesperada de banco, corrupção parcial, recuperação, reconexão observada e preservação de erros.

O número final e os comandos de teste estão em `VALIDACAO.txt`. Os testes de simulação não substituem a execução no Windows e a validação física.
