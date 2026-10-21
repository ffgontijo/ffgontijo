# Revisão da versão Python 0.4

O objetivo é configurar o próprio mouse uma vez: botão 4 colar, botão 5 copiar, botão 6 captura e botão 7 alternar duas configurações, sem remapeador aberto no computador. O configurador roda no Windows; a execução dos atalhos após a gravação deve vir da memória do mouse.

## Correção após o teste físico da versão 0.3

O usuário forneceu o log completo da versão 0.3: os bancos foram classificados corretamente como macOS/Windows/macOS/Windows e os bytes persistiram após desligar/reconectar. Mesmo assim, a luz permaneceu vermelha; o botão 7 só causava um breve piscar. A mesma cor era momentaneamente alterada pelo aplicativo original e retornava ao vermelho. No receptor, a iluminação apagava ao mover.

Portanto, não há evidência de perda da gravação, nem de um aplicativo original aberto sobrescrevendo os dados. A versão 0.3 não configurava o indicador de DPI, cuja primeira etapa estava vermelha em ambos os perfis das capturas, nem alterava a preferência de apagar ao mover, que estava habilitada. Esses são dois pontos concretos corrigidos na versão 0.4. A hipótese de interferência entre grupos de iluminação é compatível com o relato, mas sua causalidade física ainda precisa de confirmação.

| Registros adicionais | Destino na versão 0.4 |
|---|---|
| `0x2C + 4*i`, oito estágios | R,G,B,checksum: macOS `FF 00 FF 57`, Windows `FF 00 00 56` |
| `0x4C–0x4D` | Indicador DPI fixo: `01 54` |
| `0x4E–0x4F` | Brilho máximo do indicador: `FF 56` |
| `0x52–0x53` | Indicador habilitado: `01 54` |
| `0xB3–0xB4` | Apagar ao mover desativado: `00 55` |

Os registros de valores DPI `0x0C–0x2B`, quantidade/índice das etapas e tempo de repouso `0xAD–0xAE` continuam intactos. A velocidade de respiração do indicador em `0x50–0x51` é conservada, pois não é utilizada em modo fixo. A estrutura DPILed, o parser/serializador nativo e os controles originais confirmam os campos. `ValueConvert.DPIIndexToBrightness(10)` retorna 255; essa escala é diferente do brilho 0–9 da faixa principal. As escritas respeitam registros RGB de quatro bytes e opções de dois bytes.

Depois da gravação de todos os bancos, há uma segunda conferência de todos eles para detectar sobrescrita de um banco pela gravação de outro. Após reconexão, cada clique físico do botão 7 é seguido por leitura do banco resultante sem selecioná-lo primeiro com o computador. O backup registra esses dados em `physical_lighting_reads`. A aparência é perguntada separadamente ao usuário, em `visual_color_confirmed`, e nunca é inferida da igualdade dos bytes.

O backup de iluminação recebe escopo enumerado `main_dpi_movement`; a restauração utiliza somente as regiões conhecidas desse escopo, sem aceitar endereços arbitrários vindos do JSON. A ausência do campo indica o escopo original da versão 0.3, somente `A0–A8`. A recuperação antes/depois de restauração também propaga o escopo, preservando botões e DPI mesmo com falhas parciais.

## Atualização RGB da versão 0.3, base da implementação

O usuário confirmou que a versão 0.2 funciona no mouse real por cabo, receptor 2,4 GHz e Bluetooth, incluindo os quatro botões solicitados. A opção 5 acrescenta **macOS magenta `FF00FF` e Windows vermelho `FF0000`**, sem repetir a programação dos atalhos ou dos valores de DPI.

A análise estática da biblioteca nativa fornecida e do aplicativo original identifica a iluminação principal como:

| Região | Conteúdo |
|---|---|
| `0xA0–0xA6` | Modo, R, G, B, velocidade, brilho, checksum |
| `0xA7–0xA8` | Habilitado, checksum |

O modo **3** permite RGB personalizado aceso continuamente. O controle original desabilita a velocidade nesse modo e mantém cor e brilho. O modo 2 é respiração; a tradução inglesa do XML não é suficiente para escolher o efeito. A velocidade existente é conservada e o brilho é **9**, máximo da faixa nativa 0–9. A habilitação é `01 54`. Cada registro soma `0x55` módulo 256, independentemente do checksum do relatório USB.

O serializador nativo escreve **7 bytes em A0 e 2 em A7**. A implementação usa essas unidades tanto na gravação quanto na recuperação, com ACK e releitura. Na versão 0.3, a atualização escrevia somente `A0–A8`; na versão 0.4 os registros adicionais são os indicados acima. O tempo de repouso continua conservado.

Antes de gravar, o assistente lê o ciclo existente com a conexão fechada entre cliques, sem alterar o botão 7. Reconhece cada sistema pelos registros de B4/B5/B6 e exige B7 como troca interna. Aceita somente um ciclo completo alternado de dois ou quatro bancos. Bytes não utilizados no restante de cada slot de atalho não fazem parte da assinatura e são preservados.

Os alvos partem dos dados atuais do mouse. Todos os originais e destinos ficam salvos em um novo backup durável antes da primeira escrita. Uma segunda leitura rejeita dados alterados durante o teste; a leitura integral posterior confere que as demais regiões permaneceram iguais. Em caso de falha, a recuperação de um backup `rgb_only` restaura somente os registros de iluminação, inclusive se outro programa alterou teclas ou DPI depois do backup. A opção de restauração manual respeita o mesmo escopo.

A seleção inicial é devolvida após a atualização e após a conferência RGB do ciclo, inclusive nas saídas por erro quando o dispositivo ainda responde. A persistência dos bytes da versão 0.3 foi confirmada pelo usuário; a aparência desejada não funcionou. A exibição física da correção 0.4 ainda precisa do teste no mouse.

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
- Perfil ativo por `0E`, seleção pelo computador por `0F`. As capturas comprovam bancos 0 e 1 selecionáveis; o usuário confirmou posteriormente a troca pelo botão físico usando a versão 0.2.
- A ação genérica `SetChangeConfigKey` produz o registro `09 00 00 4C`. Seu funcionamento foi confirmado pelo usuário nesta unidade; isso não autoriza presumir suporte em outras revisões.
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

O usuário confirmou a troca interna e os atalhos por cabo, receptor e Bluetooth na versão 0.2. O assistente continua medindo a sequência real de bancos e conferindo os dados após reconexão. A correção de iluminação da versão 0.4 ainda precisa de confirmação visual nessas conexões. Não há software em segundo plano para executar a troca.

O backup cobre as regiões modificáveis `0x0000–0x00BF` e `0x0100–0x02FF`; não é imagem completa da memória. Macros longas não são copiadas por aproximação. O programa recusa a duplicação quando ela exigiria replicar uma dessas macros.

Uma transferência USB não é atômica. O usuário precisa evitar cliques durante leituras/gravações e guardar o backup original. Após uma falha de conexão, a restauração pode precisar ser repetida pelo cabo.

## Validação de software

Os testes de codec, transporte simulado, serviço e assistente usam a biblioteca padrão Python e não abrem dispositivos. São verificados pacotes reais, codificação dos atalhos, 2000 DPI, ciclos 2/4, rejeição de ciclo ímpar ou sem mudança, ausência de handle durante o clique solicitado, backup antes de cada primeira alteração, falhas de confirmação, troca inesperada de banco, corrupção parcial, recuperação, reconexão observada e preservação de erros.

O número final e os comandos de teste estão em `VALIDACAO.txt`. Os testes de simulação não substituem a execução no Windows e a validação física.
