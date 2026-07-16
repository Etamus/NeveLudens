# NeveLudens - guia rápido

## Primeira instalação

Execute:

```bat
instalar.bat
```

No menu, escolha **Instalar ou atualizar o NeveLudens** e confirme. Se não houver Python 3.11/3.12, o instalador oferece instalar uma dessas versões via `winget`.

O CMD executa a instalação etapa por etapa. O instalador cria e usa apenas pastas locais do projeto:

- `.venv`
- `.cache`
- `models`
- `logs`
- `out`
- `debug`

O `pip` não instala pacotes globalmente.

## Rodar o agente

1. Abra o jogo no Windows.
2. Deixe a janela do jogo visível.
3. Execute:

```bat
iniciar.bat
```

4. Selecione o processo do jogo na lista ou digite o nome exato do `.exe`.
5. Deixe a captura em `Automática`, a menos que queira testar manualmente `dxcam` ou `pyautogui`.
6. Deixe o modo de captura em **Precisão** ou escolha **Tempo real**.
7. Deixe a saída de depuração em **Normal** ou escolha **Debug** para gravar PNG, vídeos e logs detalhados.
8. Deixe o modo de jogo em **Padrão**, ou escolha **Jogo de luta** para Street Fighter 6.
9. Deixe **Jogador do agente** em **Automático**, ou escolha **Player 2** quando quiser que a IA tente entrar como segundo jogador.
10. Deixe **Recuperação inteligente** ligada para usar memória temporal e anti-loop juntos.
11. Deixe **Permitir acesso de menus** ativado ou desative se quiser bloquear ações `START`, `BACK` e `GUIDE`.
12. Clique em **Iniciar**.
13. Para parar, clique em **Parar** no mesmo botão.

Padrões atuais:

- Porta do servidor: `5555`.
- Permitir acesso de menus: ligado por padrão.
- Captura: `dxcam` primeiro, `pyautogui` como fallback conservador.
- Modo de captura padrão: `Precisão`.
- Saída de depuração padrão: `Normal`.
- Modo de jogo padrão: `Padrão`.
- Jogador do agente padrão: `Automático`.
- Recuperação inteligente: ligada.
- Macro especial automática para `isaac-ng.exe` e `Cuphead.exe`.

No **Jogo de luta**, o NeveLudens incentiva mais movimento lateral, pulos e golpes ritmados, sem tentar substituir a IA base com estratégia própria. Para Street Fighter 6, prefira controles Modernos e use **Jogador do agente: Player 2** se você quiser jogar contra a IA.

Quando **Jogador do agente** está em **Player 2**, o NeveLudens também tenta mover para a direita e confirmar com `SOUTH`/A após acordar o controle virtual.

## Diagnóstico de captura

Na interface do `iniciar.bat`, selecione o jogo e clique em **Diagnosticar**.

As imagens são salvas em:

```bat
D:\NeveLudens\debug
```

A captura correta deve mostrar exatamente a janela do jogo. Se a imagem estiver preta, congelada ou mostrando outra janela, esse é o primeiro ponto a corrigir.

## Logs importantes

- `logs\gui_run_*.log`: log espelho do iniciar.
- `logs\server_*.log`: log do servidor local.
- `out\<modelo>\*_ACTIONS.json`: ações enviadas ao jogo, salvo apenas no modo `Debug`.
- `out\<modelo>\*_SUPERVISOR.json`: decisões do supervisor, salvo apenas no modo `Debug`.
- `out\<modelo>\*_DEBUG.mp4`: vídeo de debug, salvo apenas no modo `Debug`.
- `out\<modelo>\*_CLEAN.mp4`: vídeo limpo, salvo apenas no modo `Debug`.

## Observações

- O projeto exige GPU NVIDIA com CUDA no estado atual.
- O jogo precisa aceitar controle.
- O modelo é generalista; ele pode jogar mal em jogos que exigem planejamento, leitura precisa de UI ou conhecimento específico.
- O supervisor melhora estabilidade, mas não transforma automaticamente o modelo em especialista de cada jogo.
