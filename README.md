<img width="1400" height="350" alt="Neveludens (1)" src="https://github.com/user-attachments/assets/0d91ec71-2ad6-487c-b881-c7572b73bb98" />

---

NeveLudens é uma plataforma local de agente visual para jogos. Ele observa a janela do jogo, interpreta frames com um modelo visual, transforma decisões em comandos de controle virtual e aplica uma camada de supervisão para tornar a execução mais estável.

A proposta é abrir um jogo, escolher o processo na interface e iniciar um agente capaz jogar usando apenas imagem e controle. O projeto não depende de leitura de memória do jogo, scripts por fase ou integração específica com a engine.

---

## Visão de Produto

NeveLudens funciona como um piloto visual local para jogos. Ele combina um modelo generalista com uma camada operacional feita para tornar a execução mais prática: captura confiável, memória temporal, supervisor de objetivos, biblioteca de skills e perfis por jogo.

O produto atual entrega:

- Interface gráfica WPF para iniciar o agente sem usar terminal.
- Instalador CMD para preparar dependências dentro da pasta do projeto.
- Pipeline local de captura, inferência, supervisão e controle virtual.
- Diagnóstico de captura para investigar tela preta, congelada ou janela incorreta.
- Logs, vídeos e histórico de ações para análise posterior.

Na prática, o NeveLudens é indicado para pesquisa, experimentação, prototipagem e demonstrações de agentes visuais em jogos. Ele ainda não deve ser tratado como uma IA capaz de zerar qualquer jogo sozinha, mas já oferece uma base muito mais usável do que um player bruto de modelo.

## O Que Ele Faz

1. Detecta janelas visíveis no Windows e permite escolher o processo do jogo.
2. Captura a janela com `dxcam` por padrão e usa `pyautogui` como fallback conservador quando a captura fica preta ou congelada por vários frames.
3. Envia frames limpos para um servidor local de inferência.
4. Recebe sequências de comandos analógicos e botões de controle.
5. Analisa o estado visual em paralelo, sem alterar a imagem enviada ao modelo.
6. Usa memória temporal para detectar tela parada, loading provável e repetição de ações.
7. Aplica perfis por jogo e skills de recuperação quando necessário.
8. Envia a ação final para o jogo por um controle virtual.
9. Salva logs, vídeos e decisões do supervisor para diagnóstico.

## Execução e Instalação

### `iniciar.bat`

Abre a interface principal em WPF. Por ela você pode:

- Selecionar uma janela de jogo detectada.
- Digitar manualmente o nome do `.exe`.
- Escolher a captura: `auto`, `dxcam` ou `pyautogui`.
- Escolher o modo de captura: `Precisão` ou `Tempo real`.
- Escolher a saída de depuração: `Normal` ou `Debug`.
- Escolher o modo de jogo: `Padrão` ou `Jogo de luta`.
- Escolher o jogador do agente: `Automático` ou `Player 2`.
- Escolher o supervisor multimodal: `Desativado` ou `Ativado`.
- Ligar ou desligar a recuperação inteligente.
- Ativar ou desativar **Permitir acesso de menus**, que controla `START`, `BACK` e `GUIDE`.
- Iniciar e parar o agente.
- Rodar diagnóstico de captura.
- Acompanhar o log de execução na própria janela.

Padrões atuais:

- Porta do servidor: `5555`.
- Permitir acesso de menus: ligado por padrão.
- Captura recomendada: `auto`.
- Modo de captura padrão: `Precisão`.
- Saída de depuração padrão: `Normal`.
- Modo de jogo padrão: `Padrão`, sem filtro extra sobre a IA.
- Jogador do agente padrão: `Automático`, mantendo o comportamento atual.
- Supervisor multimodal padrão: `Desativado`, mantendo o comportamento atual.
- Recuperação inteligente: ligada por padrão.
- Macro especial automática para `isaac-ng.exe` e `Cuphead.exe`.

Modos de captura:

- `Precisão`: comportamento original. Usa execução em passos com `xspeedhack`.
- `Tempo real`: não usa `xspeedhack`; apenas captura a tela e envia controle virtual.

Saída de depuração:

- `Normal`: não salva PNG por frame, vídeo debug, vídeo limpo, ações JSON ou log detalhado do supervisor.
- `Debug`: salva os mesmos artefatos de depuração usados anteriormente.

Modo de jogo:

- `Padrão`: não adiciona nenhuma camada específica de gênero.
- `Jogo de luta`: ativa uma camada opcional simples que incentiva mais movimento lateral, pulos e golpes ritmados. Ela não tenta entender o lado do personagem nem substituir a IA base.

Jogador do agente:

- `Automático`: comportamento atual. O jogo decide a posição do controle virtual conforme a ordem de dispositivos.
- `Player 2`: tenta fazer a IA entrar como segundo jogador. Primeiro aguarda o jogador humano assumir o Player 1; se nenhum controle XInput existir, cria um controle virtual parado para reservar o primeiro slot e depois cria o controle ativo da IA. Após acordar o controle, move para a direita e confirma com `SOUTH`/A para ajudar em telas de escolha de lado.

Supervisor multimodal:

- `Desativado`: comportamento padrão. Nenhum modelo multimodal extra é carregado.
- `Ativado`: inicia uma camada opcional com **Qwen3.5 4B** em `safetensors` carregado com `bitsandbytes` 4-bit. Ela roda de forma assíncrona, analisa screenshots ocasionais e retorna apenas uma orientação curta em JSON. O agente principal continua jogando normalmente; se o supervisor demorar, falhar ou retornar JSON inválido, a resposta é ignorada.
- A VLM é conservadora por padrão: só aplica orientação quando identifica um alvo visual claro, como caminho, porta, prompt, inimigo, perigo ou menu real. Telas ambíguas, teto, chão, parede, escuridão ou frases genéricas são rejeitadas.
- As orientações não são aplicadas continuamente. Elas entram como poucos pulsos curtos e há um intervalo maior entre novas análises para evitar atropelar a IA principal.
- Na primeira ativação, o modelo pode ser baixado para `.cache\huggingface` dentro do projeto.

Recuperação inteligente:

- Une memória temporal e anti-loop em uma única opção.
- Quando ligada, guarda os últimos frames resumidos, ações e eventos para saber se a tela está parada ou se a IA repetiu o mesmo comando.
- Quando detecta travamento ou repetição forte, permite acionar skills de recuperação conforme o perfil interno do jogo.

### `instalar.bat`

Roda um instalador CMD normal. Ele prepara o projeto para uso local:

- Mostra um menu antes de iniciar.
- Permite verificar o ambiente atual.
- Pede confirmação antes de instalar ou atualizar.
- Oferece instalar Python 3.11/3.12 via `winget` quando nenhum Python compatível é encontrado.
- Cria ou reutiliza `.venv` dentro do projeto.
- Instala dependências Python dentro da `.venv`.
- Mantém caches em `.cache`.
- Ajusta PyTorch CUDA na `.venv`.
- Baixa `models/ng.pt` quando necessário.
- Valida importações, CUDA e controle virtual.

Nada é instalado globalmente pelo `pip`.

## Competência do Modelo

A tabela abaixo resume a competência observada por tipo de jogo e tipo de tarefa:

| Categoria | Combate | Navegação | Tarefa específica |
| --- | ---: | ---: | ---: |
| Jogos 3D | 61,2% | 55,0% | 56,3% |
| 2D com visão superior | 46,0% | 52,0% | 61,5% |
| 2D lateral | 44,8% | 37,9% | 54,0% |

Leitura prática:

- Em jogos 3D, o modelo tende a lidar melhor com combate e navegação básica.
- Em 2D com visão superior, tarefas específicas podem funcionar melhor que combate puro.
- Em 2D lateral, plataforma e navegação ainda são pontos mais frágeis.

## Precisão por Gênero de Jogo

| Gênero | Precisão |
| --- | ---: |
| Action RPG | 34,9% |
| Plataforma | 18,4% |
| Ação e aventura | 9,2% |
| Esportes | 5,8% |
| Metroidvania | 5,4% |
| Roguelike | 4,9% |
| RPG | 4,7% |
| Battle Royale | 4,0% |
| Corrida | 3,3% |
| Outros | 9,4% |

Esses números ajudam a definir expectativas. O modelo generalista não tem o mesmo nível de competência em todos os gêneros. Por isso o NeveLudens adiciona supervisor, memória, skills e perfis por jogo: essas camadas não ensinam o modelo do zero, mas tornam a execução mais estável e menos repetitiva.

## Camadas Inteligentes

### Percepção confiável

`neveludens/perception.py` analisa brilho, contraste, movimento, bordas, tela escura, loading provável e tela estática. Essa análise roda ao lado do modelo e não altera o frame principal.

### Recuperação inteligente

`neveludens/memory.py` guarda histórico curto de frames, ações e eventos. Esse histórico alimenta o anti-loop e as skills de recuperação. Na interface, memória temporal e anti-loop aparecem juntos como **Recuperação inteligente**.

### Supervisor de objetivos

`neveludens/supervisor.py` decide se a ação do modelo deve ser aceita, ajustada ou substituída por uma skill. Ele é a camada que transforma o modelo reativo em um agente mais coordenado.

### Skill library

`neveludens/skills.py` contém rotinas reutilizáveis:

- `wait_loading`: reduz comandos durante telas de loading provável.
- `unstuck`: força uma ação de destravamento quando a imagem muda pouco.
- `break_repetition`: quebra padrões de ação repetidos demais.

### Modo de luta

`neveludens/fighting.py` é uma camada opcional. Ela só roda quando **Modo de jogo** está em **Jogo de luta**.

Essa camada não usa detector visual, não tenta descobrir quem está de qual lado e não cria estratégia própria. Ela apenas incentiva o agente a se movimentar mais para direita/esquerda, pular com mais frequência e atacar em pulsos curtos quando o modelo fica passivo.

Para `StreetFighter6.exe`/`SF6.exe`, o ritmo de movimento, pulo e ataque é mais agressivo. O modo **Padrão** não usa essa camada.

### Perfis por jogo

`neveludens/profiles.py` define ajustes por processo ou gênero. Perfis atuais:

- `isaac-ng.exe`: perfil top-down, com mira pelo analógico direito.
- `Cuphead.exe`: perfil plataforma.
- `celeste.exe`: perfil plataforma.
- `granblue_fantasy_relink.exe`: perfil action RPG.
- Perfil genérico para qualquer outro `.exe`.

## Arquitetura

```text
Janela do jogo
  -> captura dxcam/pyautogui
  -> frame limpo para o modelo
  -> inferência local
  -> ações previstas
  -> percepção + memória + perfil
  -> supervisor de objetivos
  -> skill library quando necessário
  -> controle virtual
  -> jogo
```

O servidor local é iniciado na porta `5555` por padrão. Se essa porta estiver ocupada por outro programa, o launcher escolhe uma porta livre automaticamente para aquela execução.

## Requisitos

- Windows.
- Python 3.10 ou superior.
- GPU NVIDIA com CUDA funcional no PyTorch.
- Jogo aberto em janela visível.
- Suporte a controle virtual no Windows.

Observação importante: o pacote Python `vgamepad` é instalado na `.venv`, mas o driver de controle virtual precisa estar disponível no Windows. O instalador valida isso e avisa se o controle virtual não puder ser criado.

## Instalação

Para uma cópia nova do projeto:

```bat
instalar.bat
```

O CMD mostra cada etapa da instalação e pausa no final para você conferir o resultado.

Pastas usadas:

- `.venv`: ambiente Python local.
- `.cache`: caches locais de pip, Hugging Face, Transformers e Torch.
- `models/ng.pt`: checkpoint do modelo.
- `logs`: logs de servidor, interface e instalação.
- `out`: vídeos, ações e logs do supervisor.
- `debug`: capturas de diagnóstico e frames.

## Uso Rápido

1. Abra o jogo no Windows.
2. Execute `iniciar.bat`.
3. Clique em **Atualizar** se o jogo não aparecer.
4. Selecione o jogo ou digite o nome do `.exe`.
5. Deixe a captura em `auto`.
6. Deixe o modo de captura em **Precisão** ou escolha **Tempo real**.
7. Deixe a saída de depuração em **Normal** ou escolha **Debug** para gravar PNG/vídeos/logs detalhados.
8. Deixe o modo de jogo em **Padrão**, ou escolha **Jogo de luta** para Street Fighter 6.
9. Deixe o jogador do agente em **Automático**, ou escolha **Player 2** quando quiser que a IA tente entrar como segundo jogador.
10. Deixe **Recuperação inteligente** ligada para usar memória temporal e anti-loop juntos.
11. Clique em **Iniciar**.
12. Para parar, clique em **Parar** no mesmo botão.

Se o agente parecer cego, vendo tela preta ou reagindo a uma imagem congelada, use **Diagnosticar** na própria interface.

## Saídas Geradas

- `out/<modelo>/*_DEBUG.mp4`: vídeo com visualização de debug, salvo apenas no modo `Debug`.
- `out/<modelo>/*_CLEAN.mp4`: vídeo limpo da captura, salvo apenas no modo `Debug`.
- `out/<modelo>/*_ACTIONS.json`: ações finais enviadas ao jogo, salvo apenas no modo `Debug`.
- `out/<modelo>/*_SUPERVISOR.json`: percepção, memória, objetivo e skill usada, salvo apenas no modo `Debug`.
- `logs/server_*.log`: carregamento do modelo e servidor.
- `logs/gui_run_*.log`: log espelho da interface de início.

## Limitações Importantes

NeveLudens não garante jogar bem qualquer jogo automaticamente. O modelo base é generalista, reativo e pode falhar em jogos que exigem planejamento longo, leitura precisa de UI, memória de mapa, estratégia por fase ou conhecimento de objetivos.

As camadas adicionadas melhoram a robustez operacional, mas não substituem treinamento específico. O caminho natural para evoluir o projeto é combinar este agente com:

- perfis por jogo mais ricos;
- reconhecimento de UI e objetivos;
- memória de longo prazo;
- uma IA multimodal supervisora;
- skills nomeadas por contexto;
- avaliação automática de progresso.

## Comandos Manuais

Normalmente você não precisa deles, mas continuam disponíveis:

```bat
.venv\Scripts\python.exe scripts\serve.py models\ng.pt --port 5555
```

```bat
.venv\Scripts\python.exe scripts\play.py --process nome_do_jogo.exe --port 5555 --screenshot-backend auto --agent-slot auto
```

Para uso comum, prefira `instalar.bat` e `iniciar.bat`.
