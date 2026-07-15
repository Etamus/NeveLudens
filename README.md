# NeveLudens

NeveLudens é uma adaptação local para executar um agente visual de jogos no Windows. O projeto carrega um checkpoint em `models/ng.pt`, captura a janela de um jogo, envia os frames para um servidor de inferência local e aplica as ações previstas por meio de um controle virtual.

O foco deste estado do projeto é facilitar o uso: abrir um jogo, rodar `iniciar.bat`, escolher o processo `.exe` e deixar o launcher preparar o servidor e o player.

## Estado Atual

- Execução principal por `iniciar.bat`.
- Ambiente Python isolado em `.venv`, dentro do próprio projeto.
- Dependências e caches direcionados para pastas locais do projeto.
- Checkpoint esperado em `models/ng.pt`.
- Servidor de inferência na porta padrão `5555`.
- Captura em modo automático: tenta `dxcam` primeiro e cai para `pyautogui` se a captura ficar preta ou praticamente congelada por vários frames.
- Bloqueio opcional de ações de menu (`START`, `BACK`, `GUIDE`) para evitar que o agente fique preso em menus.
- Macro especial de inicialização ativada automaticamente para `isaac-ng.exe` e `Cuphead.exe`.
- Lógica de destravamento: se a imagem quase não muda por vários passos, o player força brevemente os analógicos em direções alternadas.
- Gravação de vídeos, ações e frames de depuração em `out` e `debug`.

## Requisitos

- Windows.
- Python 3.10 ou superior.
- GPU NVIDIA com CUDA funcional no PyTorch.
- O jogo precisa estar instalado e aberto no Windows.
- O jogo precisa aceitar controle virtual.

O projeto não inclui jogos. Você deve usar suas próprias cópias.

## Uso Rápido

1. Abra o jogo.
2. Deixe a janela do jogo visível.
3. Execute:

```bat
D:\NeveLudens\iniciar.bat
```

4. Escolha o processo do jogo pela lista ou digite o nome exato do `.exe`.
5. Normalmente responda `N` para permitir ações de menu.
6. Aguarde o servidor carregar o modelo.
7. Para parar, volte para a janela do NeveLudens e pressione `Ctrl+C`.

## Diagnóstico de Captura

Se o agente parecer cego, parado, vendo tela preta ou reagindo a algo errado, rode:

```bat
D:\NeveLudens\diagnosticar_captura.bat
```

O diagnóstico salva imagens em `debug` usando os backends de captura disponíveis. A imagem correta deve mostrar exatamente a janela do jogo.

## Estrutura

- `neveludens/`: pacote Python principal.
- `scripts/serve.py`: servidor local de inferência.
- `scripts/play.py`: player que captura o jogo e executa ações.
- `scripts/launcher.py`: menu usado por `iniciar.bat`.
- `models/ng.pt`: checkpoint do modelo.
- `debug/`: frames e capturas de diagnóstico.
- `out/`: vídeos e arquivos de ações.
- `logs/`: logs do servidor.
- `.venv/`: ambiente Python local.
- `.cache/`: caches locais de dependências e modelos auxiliares.

## Limitações

NeveLudens é um agente visual reativo. Ele prevê ações a partir da imagem observada, mas não possui planejamento longo, objetivo explícito, memória estratégica ou treinamento específico para cada jogo. Em jogos complexos, ele pode andar sem rumo, repetir padrões ou falhar em entender menus, fases e objetivos.

As camadas de captura automática, bloqueio de menu e destravamento melhoram a usabilidade, mas não substituem treinamento específico nem transformam o agente em um jogador confiável para qualquer jogo.

## Comandos Manuais

Iniciar servidor:

```bat
.venv\Scripts\python.exe scripts\serve.py models\ng.pt --port 5555
```

Rodar o player:

```bat
.venv\Scripts\python.exe scripts\play.py --process nome_do_jogo.exe --port 5555 --screenshot-backend auto
```

Na prática, prefira `iniciar.bat`, pois ele prepara o ambiente e usa os padrões atuais do projeto.
