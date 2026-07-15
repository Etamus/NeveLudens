# NeveLudens

NeveLudens e um agente visual local para jogos no Windows. Ele carrega um checkpoint em `models/ng.pt`, captura a janela do jogo, executa inferencia em um servidor local e envia acoes por um controle virtual.

O projeto agora deixou de ser apenas um player reativo. Ele ganhou uma camada de agente em volta do modelo: percepcao, memoria temporal, supervisor de objetivos, biblioteca de skills e perfis por jogo.

## Estado Atual

- Execucao principal por `iniciar.bat`.
- Ambiente Python isolado em `.venv`, dentro do proprio projeto.
- Dependencias e caches direcionados para pastas locais.
- Checkpoint esperado em `models/ng.pt`.
- Servidor de inferencia na porta padrao `5555`.
- Captura automatica: tenta `dxcam` primeiro e cai para `pyautogui` se a captura ficar preta ou congelada por varios frames.
- Supervisor de objetivos entre o modelo e o jogo.
- Memoria temporal curta para detectar loops, tela parada, loading e repeticao de acoes.
- Biblioteca de skills com `wait_loading`, `unstuck` e `break_repetition`.
- Perfis para `isaac-ng.exe`, `Cuphead.exe`, `celeste.exe`, `granblue_fantasy_relink.exe` e perfil generico.
- Log do supervisor em `out/<modelo>/*_SUPERVISOR.json`.
- Videos, acoes e frames de debug em `out` e `debug`.

## Arquitetura

O fluxo atual e:

```text
Frame limpo do jogo
  -> modelo visual gera acoes
  -> percepcao analisa o frame em paralelo
  -> memoria resume o que vem acontecendo
  -> perfil do jogo ajusta regras
  -> supervisor decide se aceita, filtra ou substitui a acao
  -> skill library pode executar uma rotina de recuperacao
  -> controle virtual envia a acao final
```

O modelo continua recebendo o frame limpo. As analises do supervisor nao sao desenhadas por cima da imagem, entao elas nao confundem a inferencia.

## Modulos Principais

- `neveludens/perception.py`: extrai sinais visuais leves, como brilho, contraste, movimento, tela escura, loading provavel e tela estatica.
- `neveludens/memory.py`: guarda memoria temporal curta, repeticao de acoes, streaks visuais e eventos.
- `neveludens/profiles.py`: define comportamento por jogo ou genero.
- `neveludens/skills.py`: contem rotinas reutilizaveis de recuperacao.
- `neveludens/supervisor.py`: coordena percepcao, memoria, perfil, skills e acoes do modelo.
- `scripts/play.py`: loop principal de jogo.
- `scripts/serve.py`: servidor local de inferencia.
- `scripts/launcher.py`: menu usado por `iniciar.bat`.

## Requisitos

- Windows.
- Python 3.10 ou superior.
- GPU NVIDIA com CUDA funcional no PyTorch.
- Jogo instalado e aberto no Windows.
- Jogo com suporte a controle virtual.

O projeto nao inclui jogos. Voce deve usar suas proprias copias.

## Uso Rapido

1. Abra o jogo.
2. Deixe a janela do jogo visivel.
3. Execute:

```bat
D:\NeveLudens\iniciar.bat
```

4. Escolha o processo do jogo pela lista ou digite o nome exato do `.exe`.
5. Normalmente responda `N` para permitir acoes de menu.
6. Aguarde o servidor carregar o modelo.
7. Para parar, volte para a janela do NeveLudens e pressione `Ctrl+C`.

## Diagnostico de Captura

Se o agente parecer cego, parado, vendo tela preta ou reagindo a algo errado, rode:

```bat
D:\NeveLudens\diagnosticar_captura.bat
```

As imagens sao salvas em `debug`. A captura correta deve mostrar exatamente a janela do jogo.

## Saidas Geradas

- `debug/`: frames e capturas de diagnostico.
- `out/<modelo>/*_DEBUG.mp4`: video com visualizacao de debug.
- `out/<modelo>/*_CLEAN.mp4`: video limpo da captura.
- `out/<modelo>/*_ACTIONS.json`: acoes finais enviadas ao jogo.
- `out/<modelo>/*_SUPERVISOR.json`: decisoes do supervisor, percepcao e memoria.
- `logs/`: logs do servidor.

## Limitacoes

NeveLudens ainda depende de um modelo visual reativo. O supervisor melhora estabilidade, evita alguns loops e aplica regras por jogo, mas nao substitui treinamento especifico, planejamento longo ou conhecimento profundo de cada jogo.

O projeto esta mais preparado para evoluir para um agente completo, mas ainda nao garante jogar qualquer jogo do inicio ao fim.

## Comandos Manuais

Iniciar servidor:

```bat
.venv\Scripts\python.exe scripts\serve.py models\ng.pt --port 5555
```

Rodar o player:

```bat
.venv\Scripts\python.exe scripts\play.py --process nome_do_jogo.exe --port 5555 --screenshot-backend auto
```

Na pratica, prefira `iniciar.bat`, pois ele prepara o ambiente e usa os padroes atuais.
