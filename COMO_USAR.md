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
6. Em **Modelo**, deixe **Padrão** para usar NitroGen ou selecione **MaleCNS v1.0 (Experimental)** para usar o connectoma da mosca em um processo separado.
7. Deixe o modo de captura em **Precisão** ou escolha **Tempo real**.
8. Deixe a saída de depuração desligada para **Simples** ou ative para **Detalhado**, gravando PNG, vídeos e logs detalhados.
9. Deixe o modo de jogo em **Padrão**, ou escolha **Jogo de luta** para Street Fighter 6.
10. Deixe **Modo de jogador** em **Automático**, ou escolha **Player 2** quando quiser que a IA tente entrar como segundo jogador.
11. Deixe **Supervisor multimodal** em **Desativado**, ou escolha **Ativado** para usar Qwen3.5 4B como orientador visual opcional.
12. Deixe **Recuperação inteligente** em **Temporário**, escolha **Persistente** para salvar lugares e resultados por jogo ou **Padrão** para remover essas camadas.
13. Ative **Horizonte reduzido** se quiser reavaliar o cenário após apenas 6 ações de cada bloco previsto.
14. Ative **Calibração automática** para aprender passivamente a resposta dos movimentos durante a sessão.
15. Deixe **Permitir acesso de menus** desativado ou ative se quiser liberar ações `START`, `BACK` e `GUIDE`.
16. Clique em **Iniciar**.
17. Para parar, clique em **Parar** no mesmo botão.

Padrões atuais:

- Modelo: `Padrão` (NitroGen).
- Porta do servidor: `5555`.
- Permitir acesso de menus: desligado por padrão.
- Captura: `dxcam` primeiro, `pyautogui` como fallback conservador.
- Modo de captura padrão: `Precisão`.
- Saída de depuração padrão: `Simples`.
- Modo de jogo padrão: `Padrão`.
- Modo de jogador padrão: `Automático`.
- Supervisor multimodal padrão: `Desativado`.
- Recuperação inteligente: `Temporário`.
- Horizonte reduzido: desligado.
- Calibração automática: desligada.
- Macro especial automática para `isaac-ng.exe` e `Cuphead.exe`.

No **Jogo de luta**, o NeveLudens incentiva mais movimento lateral, pulos e golpes ritmados, sem tentar substituir a IA base com estratégia própria. Para Street Fighter 6, prefira controles Modernos e use **Modo de jogador: Player 2** se você quiser jogar contra a IA.

Quando **Modo de jogador** está em **Player 2**, o NeveLudens também tenta mover para a direita e confirmar com `SOUTH`/A após acordar o controle virtual.

Quando **Supervisor multimodal** está em **Ativado**, o NeveLudens usa apenas **Qwen3.5 4B** como camada opcional. Ele carrega o modelo em `bitsandbytes` 4-bit, roda em segundo plano e só aplica orientações curtas quando recebe JSON válido. A VLM é conservadora: se não enxergar alvo visual claro, ela deve retornar `none` e não interfere na IA principal. Na primeira ativação, o modelo pode ser baixado para `.cache\huggingface` dentro do projeto.

Quando **MaleCNS v1.0 (Experimental)** está selecionado, o NitroGen não é carregado. O connectoma é executado por CPU em um worker separado, e a projeção 2D de sua atividade aparece na aba **Início**. Essa opção é experimental: ela reage a movimento, aproximação, ameaça e saliência visual, mas não possui conhecimento prévio dos jogos.

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
- `out\<modelo>\*_ACTIONS.json`: ações enviadas ao jogo, salvo apenas com a saída detalhada.
- `out\<modelo>\*_SUPERVISOR.json`: decisões do supervisor, salvo apenas com a saída detalhada.
- `out\<modelo>\*_DEBUG.mp4`: vídeo de debug, salvo apenas com a saída detalhada.
- `out\<modelo>\*_CLEAN.mp4`: vídeo limpo, salvo apenas com a saída detalhada.

## Observações

- O NitroGen exige GPU NVIDIA com CUDA. O MaleCNS v1.0 funciona localmente em CPU.
- O jogo precisa aceitar controle.
- O modelo é generalista; ele pode jogar mal em jogos que exigem planejamento, leitura precisa de UI ou conhecimento específico.
- O supervisor melhora estabilidade, mas não transforma automaticamente o modelo em especialista de cada jogo.
