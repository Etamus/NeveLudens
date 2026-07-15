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
- Escolher o modo de captura: `auto`, `dxcam` ou `pyautogui`.
- Iniciar e parar o agente.
- Rodar diagnóstico de captura.
- Acompanhar o log de execução na própria janela.

Padrões atuais:

- Porta do servidor: `5555`.
- Ações `START`, `BACK` e `GUIDE`: sempre liberadas.
- Captura recomendada: `auto`.
- Macro especial automática para `isaac-ng.exe` e `Cuphead.exe`.

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

### Memória temporal

`neveludens/memory.py` guarda histórico curto de frames, ações e eventos. Ela identifica repetição de comando, pouca mudança visual e sequências de possível travamento.

### Supervisor de objetivos

`neveludens/supervisor.py` decide se a ação do modelo deve ser aceita, ajustada ou substituída por uma skill. Ele é a camada que transforma o modelo reativo em um agente mais coordenado.

### Skill library

`neveludens/skills.py` contém rotinas reutilizáveis:

- `wait_loading`: reduz comandos durante telas de loading provável.
- `unstuck`: força uma ação de destravamento quando a imagem muda pouco.
- `break_repetition`: quebra padrões de ação repetidos demais.

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
6. Clique em **Iniciar**.
7. Para parar, clique em **Parar** no mesmo botão.

Se o agente parecer cego, vendo tela preta ou reagindo a uma imagem congelada, use **Diagnosticar** na própria interface.

## Saídas Geradas

- `out/<modelo>/*_DEBUG.mp4`: vídeo com visualização de debug.
- `out/<modelo>/*_CLEAN.mp4`: vídeo limpo da captura.
- `out/<modelo>/*_ACTIONS.json`: ações finais enviadas ao jogo.
- `out/<modelo>/*_SUPERVISOR.json`: percepção, memória, objetivo e skill usada.
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
.venv\Scripts\python.exe scripts\play.py --process nome_do_jogo.exe --port 5555 --screenshot-backend auto
```

Para uso comum, prefira `instalar.bat` e `iniciar.bat`.
