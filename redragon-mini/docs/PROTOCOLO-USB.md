# M719-WL: protocolo observado nas capturas

Análise estática dos dois PCAPs enviados pelo usuário. Nenhum executável foi executado; nenhum mouse foi acessado. `parse_pcap.py` interpreta o PCAP clássico little endian, DLT_USBPCAP=249. `extract_evidence.py` gera `evidence.json` com hashes SHA-256, índices dos pacotes, gravações relevantes e ACKs correspondentes.

## Identificação USB

* Mouse cabeado: VID `3554`, PID `F55E`, bcdDevice `0401`; interface HID 1, subclass/protocol 0/0, endpoint IN `82`, máximo 17 bytes. Configuração USB tem três interfaces: teclado 0, interface de configuração/mídia 1, mouse 2.
* Receptor observado em Redragon_DPI.pcap: VID `3554`, PID `F5D5`, bcdDevice `0110`; interface HID 1 subclass/protocol 1/2, IN `82`, máximo 17 bytes. Interface de teclado 0.
* Nas duas capturas o mouse é o dispositivo endereço 12 (Profile) ou 7 (DPI), barramento USBPcap2. Endereços são transitórios, não fazem parte do critério de seleção.
* As capturas não incluem descritores HID report. Portanto o usage page da coleção que contém report 08 não foi determinado pelo PCAP.

## Transporte de comandos

SET_REPORT HID **output**, não feature. Setup USB capturado: `21 09 08 02 01 00 11 00` = interface 1, report output 08, 17 bytes. Respostas chegam por interrupção IN `82`, também com 17 bytes. Em Win32 o equivalente é `HidD_SetOutputReport`, seguido de leitura do handle HID apropriado.

Formato (offsets em decimal):

| Offset | Conteúdo |
| --- | --- |
| 0 | `08`, report ID |
| 1 | operação |
| 2 | `00` nas capturas |
| 3..4 | endereço big endian nas operações de memória |
| 5 | tamanho do conteúdo significativo, máximo 10 |
| 6..15 | dados, preenchimento com zero nos pedidos |
| 16 | checksum: soma de todos os 17 bytes módulo 256 = `55` |

Operações observadas:

| Operação | Pedido/resposta |
| --- | --- |
| `01` | identificação cifrada: pedido tamanho 8, primeiros 4 bytes aleatórios, últimos 4 zero; usado por `ConfirmIdentity` para conferir CID/MID/tipo do modelo |
| `02` | status do aplicativo: tamanho1, dado1 ao conectar e dado0 ao desconectar; ACK idêntico |
| `03` | consulta conexão; pedido sem dados, resposta tamanho1, dado0/1, bytes adicionais de identificação mesmo fora do tamanho |
| `04` | consulta bateria/status; não necessário para escrever configuração |
| `07` | gravar memória, tamanho1..10, ACK exatamente igual ao pedido |
| `08` | ler memória, tamanho1..10; resposta repete operação/endereço/tamanho e fornece dados |
| `0A` | notificação espontânea após troca de perfil; não é ACK ao comando `0F` |
| `0E` | ler índice do perfil atual; pedido sem dados; resposta tamanho1/dado índice |
| `0F` | selecionar índice do perfil; tamanho1/dado índice, ACK igual ao pedido |
| `12` | versão de firmware; resposta `04 01` significa v4.01 segundo engenharia reversa do aplicativo; **não** informa quantidade de perfis |

ACKs para gravar e selecionar perfil levam aproximadamente 80ms nas capturas. Leituras comuns levam aproximadamente 1ms. O programa usa limite de 2000ms e não repete automaticamente comandos de gravação que expirarem.

## Evidência de perfis internos

Em Redragon_Profile.pcap:

1. Perfil inicial lido por `0E` é índice1.
2. Pacote14359 em t=38.384117s envia `08 0f 00 00 00 01 00 00 00 00 00 00 00 00 00 00 3d`, recebe ACK pacote14364. Depois uma série de leituras `08` retorna outros valores sem gravar uma nova configuração: DPI em endereço `0C` muda de `14 14 00 2D` para `23 23 00 0F`; atalhos em `0160` e `0180` passam de modificador Ctrl (`01`) para GUI/Command (`08`).
3. Pacote24397 em t=59.993115s envia seleção índice1 terminada em checksum `3C`; as leituras voltam aos valores originais.

Isso demonstra pelo menos dois conjuntos selecionáveis pelo firmware, independentes dos arquivos de perfil no PC. **Não demonstra** que a ação de botão9 funciona neste firmware, quantos perfis físicos a ação percorre, nem persistência depois de desligar. O app gerenciado oferece quatro índices, mas só os índices0 e1 aparecem nos PCAPs fornecidos.

## Mapa de memória usado

Configuração básica: `0000..00BF`, preservada integralmente nos snapshots. Não foi atribuído significado a todos os campos.

DPI ativo observado em `000C..000F`: 2000 DPI `14 14 00 2D`, 2500 DPI `19 19 00 23`. Não precisa ser alterado quando já está em2000.

Tabela de teclas: `0060 + índiceHardware *4`. Cada registro é `tipo,param1,param2,checksum`, soma dos4bytes=`55` módulo256. Índices da configuração fornecida:

| Botão no desenho | Índice hardware | Endereço da tecla | Slot do atalho |
| --- | --- | --- | --- |
| 1 | 0 | `0060` | `0100` |
| 2 | 1 | `0064` | `0120` |
| 3 | 2 | `0068` | `0140` |
| 4 | 4 | `0070` | `0180` |
| 5 | 3 | `006C` | `0160` |
| 6 | 9 | `0084` | `0220` |
| 7 | 10 | `0088` | `0240` |
| 8 | 5 | `0074` | `01A0` |

Atalho simples ou mídia é tipo5, registro `05 00 00 50`. O slot é `0100 + índiceHardware*20hex`, cada slot tem32bytes. O snapshot preserva `0100..02FF` (16slots). Macros gerais a partir de `0300` não fazem parte desse backup e não são alteradas por este módulo.

Formato do atalho: quantidade de eventos; para cada evento3bytes (estado/tipo, código low, código high); checksum de todo o atalho=soma`55`. Teclado usa down`81` e up`41`. Modificadores usam down`80` e up`40`, código é máscara HID (`01`=Ctrl esquerdo, `08`=GUI esquerdo/Command). Mídia usa down`82` e up`42`.

Exemplos:

* Ctrl+C observado: `04 80 01 00 81 06 00 41 06 00 40 01 00 C1`.
* GUI+V observado: `04 80 08 00 81 19 00 41 19 00 40 08 00 8D`.
* Command+1 derivado desse formato, validado pela engenharia reversa do app: `04 80 08 00 81 1E 00 41 1E 00 40 08 00 83`.
* PrintScreen, uso HID46: `02 81 46 00 41 46 00 05`.
* A ação oculta `SetChangeConfigKey` no app gera tipo9,param1=0,param2=0, portanto registro `09 00 00 4C`. **Esse registro não aparece gravado no PCAP**; o suporte efetivo do firmware precisa de validação física.

## Limites de implementação

`src/Protocol.cs` valida checksum, operação/endereço/tamanho, ACK exato de escrita e leitura posterior. Antes de aplicar patches confere todos os bytes originais; isso impede aplicar plano de backup obsoleto. Lê perfis com seleção verificada e restaura o perfil originalmente ativo ao encerrar o backup, inclusive se uma leitura falhar. Só escreve regiões explicitamente presentes no plano; rollback e persistência de backup cabem ao serviço da aplicação.


## Identificação específica do receptor e do mouse

A correspondência entre descritor USB, endereço de dispositivo e resposta da operação01 é direta em `Redragon_DPI.pcap`:

| Dispositivo | Descritor | Respostas01 | Byte12 da resposta |
| --- | --- | --- | --- |
| Mouse cabeado VID3554/PIDF55E, endereço7 | Pacote2 | Pacotes14525,14537,17381 | `02` |
| Receptor VID3554/PIDF5D5, endereço6 | Pacote8 | Pacotes14549,14557,17391 | `00` |

Nos dois casos byte10=`17` (CID23 decimal) e byte11=`29` (MID41 decimal), como extraído por `CS_GetDeviceInfo` do aplicativo original. Exemplo completo de receptor: `08 01 00 00 00 08 F6 18 30 EB 17 29 00 00 00 00 DB`. `ConfirmIdentity(expectedDeviceType)` permite os tipos0 e2 e pode exigir o tipo correspondente ao PID selecionado. Trata-se de confirmação de identidade do modelo, não autenticação criptográfica; o aplicativo original também recebe os identificadores sem cifra nesses offsets.

A suíte final de protocolo passou 48 verificações: inclui identidade válida/inválida, interrupção de gravações após troca inesperada de perfil e preservação do erro original quando a recuperação também falha.
