# NeveLudens - uso local

## Caminho principal

Execute:

```bat
D:\NeveLudens\iniciar.bat
```

Tudo fica dentro do proprio projeto:

- Ambiente Python: `D:\NeveLudens\.venv`
- Cache do pip: `D:\NeveLudens\.cache\pip`
- Cache Hugging Face/Transformers: `D:\NeveLudens\.cache\huggingface`
- Cache Torch: `D:\NeveLudens\.cache\torch`
- Checkpoint do modelo: `D:\NeveLudens\models\ng.pt`
- Logs do servidor: `D:\NeveLudens\logs`
- Videos, acoes e logs do supervisor: `D:\NeveLudens\out`

## Como rodar

1. Abra o jogo no Windows antes de iniciar o NeveLudens.
2. Rode `D:\NeveLudens\iniciar.bat`.
3. Escolha o processo do jogo pela lista ou digite o nome exato do `.exe`.
4. Deixe `Permitir acoes de menu START/BACK/GUIDE?` como `N`, especialmente em jogos que abrem pause/options com facilidade.
5. A captura usa `dxcam` primeiro e troca para `pyautogui` se ficar preta ou congelada por varios frames.
6. Para `isaac-ng.exe` e `Cuphead.exe`, a macro especial de inicializacao roda automaticamente.
7. A porta do servidor e `5555` por padrao; se estiver ocupada por outro programa, o launcher escolhe outra livre sem perguntar.
8. Aguarde o servidor carregar o modelo.
9. Mantenha a janela do jogo visivel e ativa.
10. Para parar, volte para a janela do NeveLudens e pressione `Ctrl+C`.

## O que o supervisor faz

- Analisa o frame em paralelo, sem alterar a imagem enviada ao modelo.
- Mantem memoria curta de movimento visual, tela escura, loading e repeticao de acoes.
- Carrega um perfil do jogo quando o processo e conhecido.
- Bloqueia botoes de menu quando voce nao permite menu.
- Converte tokens digitais de mira para analogico direito em perfis que precisam disso.
- Chama skills de espera, destravamento ou quebra de repeticao quando necessario.

## Diagnostico de captura

Execute:

```bat
D:\NeveLudens\diagnosticar_captura.bat
```

As imagens serao salvas em `D:\NeveLudens\debug`. A captura correta deve mostrar exatamente a janela do jogo.

## Logs importantes

- `out\<modelo>\*_ACTIONS.json`: acoes finais enviadas ao jogo.
- `out\<modelo>\*_SUPERVISOR.json`: percepcao, memoria, objetivo e skill usada.
- `logs\server_*.log`: inicializacao e inferencia do servidor.

## Observacoes

- O projeto exige CUDA no codigo atual; CPU nao e um caminho pratico.
- O projeto nao inclui jogos.
- O modelo ainda e reativo e nao garante jogar qualquer jogo do inicio ao fim.
- O supervisor melhora estabilidade, mas nao substitui treinamento especifico.
- Se o jogo nao for encontrado, confira o nome exato do processo no Gerenciador de Tarefas.
