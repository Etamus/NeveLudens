# NeveLudens - uso local

## Caminho principal

Execute:

```bat
D:\NeveLudens\iniciar.bat
```

Tudo fica dentro do próprio projeto:

- Ambiente Python: `D:\NeveLudens\.venv`
- Cache do pip: `D:\NeveLudens\.cache\pip`
- Cache Hugging Face/Transformers: `D:\NeveLudens\.cache\huggingface`
- Cache Torch: `D:\NeveLudens\.cache\torch`
- Checkpoint do modelo: `D:\NeveLudens\models\ng.pt`
- Logs do servidor: `D:\NeveLudens\logs`
- Vídeos e ações gravadas: `D:\NeveLudens\out`

## Como rodar

1. Abra o jogo no Windows antes de iniciar o NeveLudens.
2. Rode `D:\NeveLudens\iniciar.bat`.
3. Escolha o processo do jogo pela lista ou digite o nome exato do `.exe`.
4. Deixe `Permitir ações de menu START/BACK/GUIDE?` como `N`, especialmente em jogos que abrem pause/options com facilidade.
5. A captura usa `dxcam` primeiro e troca para `pyautogui` se ficar preta ou congelada por vários frames.
6. Para `isaac-ng.exe` e `Cuphead.exe`, a macro especial de inicialização roda automaticamente.
7. A porta do servidor é `5555` por padrão; se estiver ocupada por outro programa, o launcher escolhe outra livre sem perguntar.
8. Aguarde o servidor carregar o modelo.
9. Mantenha a janela do jogo visível e ativa.
10. Para parar, volte para a janela do NeveLudens e pressione `Ctrl+C`.

## Diagnóstico de captura

Execute:

```bat
D:\NeveLudens\diagnosticar_captura.bat
```

As imagens serão salvas em `D:\NeveLudens\debug`. A captura correta deve mostrar exatamente a janela do jogo.

## Observações

- O projeto exige CUDA no código atual; CPU não é um caminho prático.
- O projeto não inclui jogos.
- O modelo é reativo e não garante jogar qualquer jogo do início ao fim.
- Se o jogo não for encontrado, confira o nome exato do processo no Gerenciador de Tarefas.
- Se algo falhar ao carregar o modelo, veja o log mais recente em `D:\NeveLudens\logs`.
- Se a imagem quase não mudar por vários passos, o player força brevemente os analógicos em direções alternadas para tentar destravar.
