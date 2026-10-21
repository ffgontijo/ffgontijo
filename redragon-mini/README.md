# Redragon Mini — Python 0.2

Configurador de uso único para Windows. Os atalhos são gravados no mouse; não é instalado um remapeador ou serviço em segundo plano.

## Download

[**Baixar RedragonMini-Python-v0.2.zip**](https://github.com/ffgontijo/ffgontijo/raw/refs/heads/codex/redragon-mini-v0.1/redragon-mini/RedragonMini-Python-v0.2.zip)

Instale Python 3.10 ou superior para Windows, extraia o ZIP inteiro e abra **Iniciar.cmd**. Não precisa de `pip`, EXE próprio, driver adicional ou administrador. Escolha **1 — Configurar os dois perfis** e siga os cliques do teste do botão 7.

| Botão | macOS | Windows |
|---|---|---|
| 4 — colar | Command+V | Ctrl+V |
| 5 — copiar | Command+C | Ctrl+C |
| 6 — captura | Command+1 | Print Screen |
| 7 | Alternar a configuração interna | Alternar a configuração interna |

DPI: **2000 em todas as etapas habilitadas**; cores preservadas.

## Procedimento

O assistente confirma a identificação USB, salva backup antes de alterar qualquer banco e testa a troca física com a conexão de configuração fechada entre cliques. Só grava os atalhos finais depois de medir e repetir um ciclo válido.

Se o mouse percorrer quatro bancos, o assistente os organiza como macOS/Windows/macOS/Windows na ordem observada. Se a ação de troca não funcionar, ele para e tenta restaurar os originais. O código genérico do aplicativo original não é tratado como comprovação de suporte no firmware.

A gravação é feita pelo cabo. Ao final, o assistente observa a desconexão/reconexão e verifica novamente memória e ciclo. O desligamento efetivo e os testes de teclas no Mac, no Windows e pelos modos receptor/Bluetooth ainda precisam do procedimento no hardware. Nenhuma gravação ou teste físico foi feito no ambiente de desenvolvimento.

## Guia, revisão e código

- [Guia completo](python/LEIA-ME.md)
- [Revisão do código e das evidências](python/docs/REVISAO.md)
- [Código Python e testes](python)

A lista de modelos autorizados é baseada nas capturas fornecidas: 3554:F55E, CID17/MID29 no cabo. A foto M719RGB-PRO V2 não substitui a identificação real; outros IDs são mostrados somente para diagnóstico e não recebem comandos de gravação.

Os arquivos do aplicativo C# 0.1 permanecem no histórico desta branch. O download recomendado acima contém somente a versão Python. A branch principal e a página do perfil não são alteradas.
