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
6. Clique em **Iniciar**.
7. Para parar, clique em **Parar** no mesmo botão.

Padrões atuais:

- Porta do servidor: `5555`.
- `START`, `BACK` e `GUIDE`: sempre liberados.
- Captura: `dxcam` primeiro, `pyautogui` como fallback conservador.
- Macro especial automática para `isaac-ng.exe` e `Cuphead.exe`.

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
- `out\<modelo>\*_ACTIONS.json`: ações enviadas ao jogo.
- `out\<modelo>\*_SUPERVISOR.json`: decisões do supervisor.
- `out\<modelo>\*_DEBUG.mp4`: vídeo de debug.
- `out\<modelo>\*_CLEAN.mp4`: vídeo limpo.

## Observações

- O projeto exige GPU NVIDIA com CUDA no estado atual.
- O jogo precisa aceitar controle.
- O modelo é generalista; ele pode jogar mal em jogos que exigem planejamento, leitura precisa de UI ou conhecimento específico.
- O supervisor melhora estabilidade, mas não transforma automaticamente o modelo em especialista de cada jogo.
