# Análise estática dos dois utilitários de firmware

Nenhum dos executáveis foi iniciado. Nenhuma atualização ou gravação em hardware
foi realizada. As conclusões abaixo vêm dos bytes dos arquivos anexados.

## Os arquivos “Reset” e “upgrade” são idênticos

Os dois anexos têm 749.802 bytes e SHA-256:

`3257d10c706e893935f059eb0a0fade95579a43481db2946f9661af94401a200`

Assim, os nomes não identificam duas operações diferentes neste conjunto de
anexos. Ambos contêm o mesmo programa nativo PE32 x86 e o mesmo payload.

O cabeçalho PE registra `2021-03-12 03:48:30 UTC`. O caminho PDB termina em
`SH25F273_MP_TOOL.pdb`. Isso identifica o projeto do utilitário, mas não prova
que o hardware conectado usa o mesmo controlador.

## Extração reproduzível do payload

O utilitário possui quatro seções PE. O último byte das seções fica no offset
`0xB0000`; dali em diante há um overlay de `0x70EA` bytes.

Cabeçalho do overlay:

```
5A A5 53 49 4E 4F 25 8A 00 51 70 00
      S  I  N  O  VID   PID   tamanho
```

O parser do próprio utilitário, em `0x4060AA–0x4061BC`, procura a assinatura
`5A A5 SINO`, lê VID/PID/tamanho como inteiros de 16 bits big endian e então lê
o payload. O tamanho é `0x7000` (28 KiB).

As rotinas em `0x403230` e `0x4032D0` implementam uma variante de TEA:

- blocos de 8 bytes, duas palavras de 32 bits em big endian;
- 32 rodadas;
- delta `0x9E3769B9` (diferente do TEA padrão);
- soma inicial da decodificação `0xC6ED3720`;
- cada um dos quatro bytes da chave é usado como uma palavra da chave;
- a chave deste arquivo, armazenada após o payload, é `93 BD 50 13`.

`extract_firmware.py` traduz esse algoritmo sem carregar ou executar código do
anexo. A recodificação do resultado reproduz todos os bytes do payload cifrado.
O resultado está em `decrypted.bin`, SHA-256:

`15028ba044175d75b669d2fcdbd0046fb3176780f4524944690078baa6a5ecf3`

O código decodificado é compatível com a arquitetura 8051. O vetor de reset é
`02 35 1D` (`LJMP 0x351D`). Há dados iniciais nas regiões `0x5800`, `0x5900`,
`0x5A00` e `0x5B00`, incluindo tabelas de ações e luzes. A existência de duas
tabelas semelhantes, sozinha, não demonstra dois perfis alternáveis por botão.

## Correspondência com o mouse das capturas não estabelecida

O descritor USB dentro do firmware, em `0x0B7C`, é:

```
12 01 10 01 00 00 00 08 8A 25 51 00 00 01 01 02 00 01
```

Ele declara VID `258A`, PID `0051`. Os relatórios HID declarados incluem um
Feature Report ID `05`, com 5 bytes de dados (6 com o identificador).

O `Config.ini` anexado, usado pelo aplicativo atual, declara VID `3554` e PIDs
`F55E` / `F5D5`; os valores decodificados de MM, DM e Sensor são `CX52850E`,
`BK2481` e `8960`. As capturas usam SET_REPORT do tipo **output**, ID `08`,
com 17 bytes incluindo o identificador. A resposta chega por interrupção IN.

Essas diferenças impedem usar este payload como prova de que a revisão
capturada implementa uma ação específica ou permite limitar a troca a dois
perfis. Pode ser outra revisão, uma imagem de fábrica ou um modo especial;
não foi estabelecida a relação. Também não foi estabelecida compatibilidade
para gravar este firmware no mouse do usuário.

O caminho de configuração do programa portátil deve usar o protocolo
comprovado pelo aplicativo e pelas capturas. Não é necessário carregar este
payload para configurar atalhos. Não há evidência aqui suficiente para propor
uma modificação de firmware que acrescente o comportamento solicitado.
