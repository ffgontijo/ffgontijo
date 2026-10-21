# Redragon Mini — Python 0.5

Configurador de uso único para Windows. Os atalhos são gravados no mouse; não é instalado um remapeador ou serviço em segundo plano.

## Download

[**Baixar RedragonMini-Python-v0.5.zip**](https://github.com/ffgontijo/ffgontijo/raw/refs/heads/codex/redragon-mini-v0.1/redragon-mini/RedragonMini-Python-v0.5.zip)

Instale Python 3.10 ou superior para Windows, extraia o ZIP inteiro e abra **Iniciar.cmd**. Não precisa de `pip`, EXE próprio, driver adicional ou administrador.

**Se os atalhos já funcionam, escolha 5 — Ajustar DPI e indicador.** Extraia em uma pasta nova, conecte pelo cabo, feche o app original e siga os cliques solicitados no botão 7. A opção conserva todos os botões, atalhos e macros e aplica:

| Perfil | DPI | Somente o indicador DPI | Iluminação principal |
|---|---|---|---|
| Windows | **2100** | **Azul** `#0000FF`, fixo | **Desligada** |
| macOS / MacBook | **2000** | **Vermelho** `#FF0000`, fixo | **Desligada** |

**Lights off when moving fica desativado** nos quatro bancos. O indicador usa modo fixo, sem respiração ou animação; o tempo de repouso permanece como estava. Quantidade e índice das etapas DPI e valores numéricos das etapas desabilitadas são conservados. As etapas habilitadas recebem o DPI do perfil.

O assistente salva um backup novo, lê o ciclo existente sem regravar o botão 7 e confere os registros gravados. A restauração desse backup também se limita aos campos de DPI/iluminação da operação, sem restaurar teclas. Não precisa copiar backups antigos para a nova pasta. Siga a verificação após desligar/reconectar e confira visualmente, com o programa desconectado: faixa apagada e somente o indicador azul/Windows ou vermelho/Mac. Responda `s` se ficou correto ou `n` se não ficou. Memória e aparência são registradas separadamente.

Para configurar os atalhos pela primeira vez, escolha **1 — Configurar os dois perfis**. Depois use 5 para aplicar o DPI/indicador atuais.

| Botão | macOS | Windows |
|---|---|---|
| 4 — colar | Command+V | Ctrl+V |
| 5 — copiar | Command+C | Ctrl+C |
| 6 — captura | Command+1 | Print Screen |
| 7 | Alternar a configuração interna | Alternar a configuração interna |

DPI na configuração inicial da opção 1: **2000 nos dois sistemas**. A opção 5 aplica a configuração atual: **2100 no Windows e 2000 no Mac**. Se os botões já funcionam, use somente 5.

## Procedimento

O assistente confirma a identificação USB, salva backup antes de alterar qualquer banco e testa a troca física com a conexão de configuração fechada entre cliques. Só grava os atalhos finais depois de medir e repetir um ciclo válido.

Se o mouse percorrer quatro bancos, o assistente os organiza como macOS/Windows/macOS/Windows na ordem observada. Se a ação de troca não funcionar, ele para e tenta restaurar os originais. O código genérico do aplicativo original não é tratado como comprovação de suporte no firmware.

A gravação é feita pelo cabo. Depois, o uso é pela memória do mouse, sem programa residente. **O usuário confirmou os botões e a troca interna por cabo, receptor 2,4 GHz e Bluetooth** na versão 0.2. As versões 0.3/0.4 persistiram os bytes de iluminação, mas não produziram a alternância visual desejada. A configuração 0.5 usa DPI diferentes e somente o indicador aceso; a atualização ainda precisa do teste físico nas três conexões. Nenhuma gravação física é feita no ambiente de desenvolvimento.

## Guia, revisão e código

- [Guia completo](python/LEIA-ME.md)
- [Revisão do código e das evidências](python/docs/REVISAO.md)
- [Código Python e testes](python)

A lista de modelos autorizados é baseada nas capturas fornecidas: 3554:F55E, CID17/MID29 no cabo. A foto M719RGB-PRO V2 não substitui a identificação real; outros IDs são mostrados somente para diagnóstico e não recebem comandos de gravação.

Os arquivos do aplicativo C# 0.1 permanecem no histórico desta branch. O download recomendado acima contém somente a versão Python. A branch principal e a página do perfil não são alteradas.
