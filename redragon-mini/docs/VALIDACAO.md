# Validação da versão 0.1

Aplicação compilada para Windows, AnyCPU, .NET Framework 4.8. Código também compilado com a sintaxe C# 5 aceita pelo compilador do .NET Framework usado por `build.cmd`.

Testes executados no ambiente de desenvolvimento Linux, usando o código de protocolo, planejamento de alterações e backup:

- **48 verificações de protocolo:** pacotes reais das capturas, checksums, endereços, identidade do cabo/receptor, codificação dos atalhos, perfis distintos, rejeição de plano obsoleto, releitura após escrita, interrupção após troca inesperada de perfil e preservação de erros durante recuperação.
- **61 verificações de planejamento e backup:** macOS/Windows/macOS/Windows, preservação de DPI/RGB e bytes reservados do destino, manutenção do botão 7 no modo normal, isolamento dos buffers, macros longas, ordem de gravação, seleção da interface HID e validação/reabertura de arquivos de backup.
- **109 verificações passaram no total.** Nenhum teste abre um dispositivo USB real.
- Na análise dos PCAPs, 519 relatórios de saída e 512 respostas de 17 bytes tiveram seus checksums conferidos sem divergências.

Revisão estática independente conferiu as estruturas Win32, seleção `MI_01&COL05`, ciclo de vida de leituras sobrepostas, endereços e encodings contra o software original.

## Ainda não validado

- Abertura da interface gráfica no Windows e enumeração real do HID no computador do usuário.
- Execução da função escondida tipo 9 pelo firmware do mouse, ordem/número de posições percorridas e funcionamento do botão 7 sem software.
- Retenção após desligar e uso de perfis gravados pelo cabo quando conectado ao Mac pelo receptor.

A releitura implementada confirma o conteúdo retornado pelo dispositivo durante a sessão. Persistência e comportamento dos botões precisam do teste físico descrito no LEIA-ME.

Não foram instalados drivers, executados os programas proprietários anexados ou gravados dispositivos durante o desenvolvimento. Nenhum firmware proprietário foi incorporado ao app.
