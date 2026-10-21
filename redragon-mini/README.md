# Redragon Mini — M719-WL

Aplicativo portátil experimental para Windows 10/11, com .NET Framework 4.8.

## Download direto

[**Baixar RedragonMini-portatil-v0.1.zip**](https://github.com/ffgontijo/ffgontijo/raw/refs/heads/codex/redragon-mini-v0.1/redragon-mini/RedragonMini-portatil-v0.1.zip)

Extraia o ZIP e abra `RedragonMini.exe`. Não é necessário compilar, instalar o aplicativo original, Python ou um driver adicional.

## Configuração

- Perfil 1 (macOS): botão 6 = Command+1.
- Perfil 2 (Windows): botão 6 = Print Screen.
- Botão 5 configurável, com opção de preservar a programação atual.
- Mantém o DPI e a iluminação existentes nos perfis de base.
- Salva backup antes de alterar configurações e verifica os dados por releitura.

**A troca pelo botão 7 é experimental.** A função foi encontrada no software original, mas seu funcionamento neste firmware ainda precisa de teste físico. Quando habilitada, o Mini prepara quatro posições como macOS → Windows → macOS → Windows, para alternar entre duas configurações caso o firmware ofereça essa função. Isso substitui as posições 3 e 4; o backup permite restaurá-las.

O executável foi compilado e 109 verificações automáticas de protocolo, planejamento e backup passaram. Ainda não houve teste no Windows nem no mouse físico. A gravação verificada não comprova persistência após desligar ou suporte à ação interna de troca.

Consulte o [guia completo](LEIA-ME.md) antes do primeiro teste. Relatórios de engenharia reversa e limites estão em [docs](docs/VALIDACAO.md).

## Código e compilação

O código está em `src`; `build.cmd` usa o compilador do .NET Framework do Windows e gera `dist/RedragonMini.exe`. O ZIP contém o programa compilado e o código-fonte. As DLLs, instaladores e firmware proprietários usados como material de análise não fazem parte desta distribuição.

A cópia foi publicada em uma branch separada deste repositório. A branch principal e a página do perfil permanecem inalteradas.
