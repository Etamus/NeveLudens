<img width="1400" height="350" alt="Neveludens (1)" src="https://github.com/user-attachments/assets/0d91ec71-2ad6-487c-b881-c7572b73bb98" />

---

NeveLudens é um agente visual local para jogos que opera diretamente sobre a interface visual do jogo. Ela captura frames, executa inferência visual para selecionar ações e envia comandos por meio de um controle virtual, usando memória temporal e supervisão para reduzir repetição, travamentos e decisões inconsistentes. O agente não depende de leitura de memória do jogo, instrumentação da engine ou scripts específicos por fase, mantendo uma operação plug-and-play.

---

<img width="966" height="626" alt="{5B2DF142-D76F-43EC-85D7-B5425D095F47}" src="https://github.com/user-attachments/assets/3e14aa6a-5cc2-48f5-94bd-3cb52af50e17" />
<img width="976" height="634" alt="image" src="https://github.com/user-attachments/assets/16d3c614-fef3-4c74-aba9-83b3861a6daf" />
<img width="966" height="624" alt="{706FA098-61AC-44CD-BFEC-E37877F25FAC}" src="https://github.com/user-attachments/assets/3e05f318-af24-4b21-b4cb-540dfcdb208d" />

---

## Produto

NeveLudens funciona como um piloto visual local para jogos. Ele combina um modelo generalista com uma camada operacional feita para tornar a execução mais prática: captura confiável, memória temporal, supervisor de objetivos, biblioteca de skills e perfis por jogo.

O produto atual entrega:

- Interface gráfica WPF local para iniciar o agente sem usar terminal.
- Instalador CMD para preparar dependências dentro da pasta do projeto.
- Pipeline local de captura, inferência, supervisão e controle virtual.
- Diagnóstico de captura para investigar tela preta, congelada ou janela incorreta.
- Logs, vídeos e histórico de ações para análise posterior.

Na prática, o NeveLudens é indicado para pesquisa, experimentação, prototipagem e demonstrações de agentes visuais em jogos. Ele ainda não deve ser tratado como uma IA capaz de zerar qualquer jogo sozinha, mas já oferece uma base muito mais usável do que um player bruto de modelo.

## Funcionamento

1. Detecta janelas visíveis no Windows e permite escolher o processo do jogo.
2. Captura a janela com `dxcam` por padrão e usa `pyautogui` como fallback conservador quando a captura fica preta ou congelada por vários frames.
3. Envia frames limpos para um servidor local de inferência.
4. Recebe sequências de comandos analógicos e botões de controle.
5. Analisa o estado visual em paralelo, sem alterar a imagem enviada ao modelo.
6. Usa memória temporal para detectar tela parada, loading provável e repetição de ações.
7. Aplica perfis por jogo e skills de recuperação quando necessário.
8. Envia a ação final para o jogo por um controle virtual.
9. Salva logs, vídeos e decisões do supervisor para diagnóstico.

## Instalação

### `iniciar.bat`

Abre a interface principal em WPF. O `iniciar.bat` chama a GUI local por PowerShell; por ela você pode:

- Selecionar uma janela de jogo detectada.
- Digitar manualmente o nome do `.exe`.
- Escolher a captura: `auto`, `dxcam` ou `pyautogui`.
- Escolher o modo de captura: `Precisão` ou `Tempo real`.
- Ativar ou desativar a saída de depuração detalhada.
- Escolher o modo de jogo: `Padrão`, `Jogo de luta` ou `Tela dividida`.
- Escolher o modo de jogador: `Automático`, `Player 2` ou `Jogador 2 (Co-op)`.
- Escolher o supervisor multimodal: `Desativado` ou `Ativado`.
- Escolher o nível da Recuperação inteligente: `Desativado`, `Temporário` ou `Persistente`.
- Ativar ou desativar **Permitir acesso de menus**, que controla `START`, `BACK` e `GUIDE`.
- Iniciar e parar o agente.
- Rodar diagnóstico de captura.
- Acompanhar o log de execução na própria janela.

Padrões atuais:

- Porta do servidor: `5555`.
- Permitir acesso de menus: desligado por padrão.
- Captura recomendada: `auto`.
- Modo de captura padrão: `Precisão`.
- Saída de depuração padrão: `Simples`.
- Modo de jogo padrão: `Padrão`, sem filtro extra sobre a IA.
- Modo de jogador padrão: `Automático`, mantendo o comportamento atual.
- Supervisor multimodal padrão: `Desativado`, mantendo o comportamento atual.
- Recuperação inteligente: `Temporário` por padrão.
- Horizonte reduzido: desligado por padrão; quando ligado, executa até 6 das 18 ações previstas antes de observar novamente.
- Calibração automática: desligada por padrão; aprende passivamente a resposta dos movimentos durante a sessão.
- Macro especial automática para `isaac-ng.exe` e `Cuphead.exe`.

Modos de captura:

- `Precisão`: comportamento original. Usa execução em passos com `xspeedhack`.
- `Tempo real`: não usa `xspeedhack`; apenas captura a tela e envia controle virtual.

Saída de depuração:

- `Simples`: não salva PNG por frame, vídeo debug, vídeo limpo, ações JSON ou log detalhado do supervisor.
- `Detalhado`: salva os mesmos artefatos de depuração usados anteriormente.

Modo de jogo:

- `Padrão`: não adiciona nenhuma camada específica de gênero.
- `Jogo de luta`: ativa uma camada opcional simples que incentiva mais movimento lateral, pulos e golpes ritmados. Ela não tenta entender o lado do personagem nem substituir a IA base.
- `Tela dividida`: envia ao modelo e ao Supervisor multimodal somente a metade esquerda da tela. Não adiciona lógica de perseguição, rota ou alvo; apenas mantém inputs de movimento mais contínuos e aplica um escape curto quando a tela parece travada. Botões de ação, ataque, interação e menu continuam livres.

Modelo:

- `Padrão`: usa `models/ng.pt`, o mesmo checkpoint atual do NeveLudens.
- `MaleCNS v1.0 (Experimental)`: usa uma simulação local do connectoma completo da mosca, com 166.700 neurônios e 25.582.938 conexões. Esse motor é separado do NitroGen, recebe a imagem real do jogo e converte a atividade de neurônios descendentes em comandos de controle.
- O MaleCNS não é um checkpoint treinado e não conhece jogos previamente. Um codificador visual estimula retina, movimento, aproximação, ameaça e perseguição; um decodificador motor interpreta circuitos associados a direção, avanço, recuo, fuga e ações.
- Ao selecionar MaleCNS, o NitroGen não é carregado. Ao selecionar Padrão, o MaleCNS não é importado nem executado.
- A aba Início mostra uma projeção 2D em tempo real dos disparos do MaleCNS enquanto esse motor estiver ativo.

Modo de jogador:

- `Automático`: comportamento atual. O jogo decide a posição do controle virtual conforme a ordem de dispositivos.
- `Player 2`: tenta fazer a IA entrar como segundo jogador. Primeiro aguarda o jogador humano assumir o Player 1; se nenhum controle XInput existir, cria um controle virtual parado para reservar o primeiro slot e depois cria o controle ativo da IA. Após acordar o controle, move para a direita e confirma com `SOUTH`/A para ajudar em telas de escolha de lado.
- `Jogador 2 (Co-op)`: usa a mesma reserva de slot do `Player 2`, mas a macro inicial confirma primeiro, espera 5 segundos, move para a esquerda, confirma de novo e espera mais 5 segundos. É uma variação para telas de entrada co-op.

Supervisor multimodal:

- `Desativado`: comportamento padrão. Nenhum modelo multimodal extra é carregado.
- `Ativado`: inicia uma camada opcional com **Qwen3.5 4B** em `safetensors` carregado com `bitsandbytes` 4-bit. Ela roda de forma assíncrona, analisa screenshots ocasionais e retorna apenas uma orientação curta em JSON. O agente principal continua jogando normalmente; se o supervisor demorar, falhar ou retornar JSON inválido, a resposta é ignorada.
- A VLM é conservadora por padrão: só aplica orientação quando identifica um alvo visual claro, como caminho, porta, prompt, inimigo, perigo ou menu real. Telas ambíguas, teto, chão, parede, escuridão ou frases genéricas são rejeitadas.
- As orientações não são aplicadas continuamente. Elas entram como poucos pulsos curtos e há um intervalo maior entre novas análises para evitar atropelar a IA principal.
- Na primeira ativação, o modelo pode ser baixado para `.cache\huggingface` dentro do projeto.

Recuperação inteligente:

- `Desativado`: não mantém memória temporal, não executa anti-loop e não cria memória persistente.
- `Temporário`: reproduz exatamente o anti-loop anterior à reformulação. Observa baixa movimentação visual e repetição de ações durante a sessão e usa a sequência fixa de escapes original.
- `Persistente`: usa a recuperação reformulada baseada no resultado visual e acrescenta memória de lugares, resultados por jogo, arquivo em `memories/` e resumo para a VLM. Ele não acumula o anti-loop legado do modo Temporário.
- Ficar parado, atacar ou esperar não é suficiente para acionar recuperação; são exigidas várias tentativas reais de movimento sem resultado.
- A recuperação altera somente o movimento necessário, preservando câmera e botões previstos pelo modelo.

Horizonte reduzido:

- É uma opção isolada e desligada por padrão.
- Quando ligada, usa as primeiras 6 ações de cada bloco de 18 e então solicita uma nova observação.
- Aumenta a frequência de reavaliação do cenário, com o custo de fazer mais inferências durante a sessão.

Calibração automática:

- É passiva: não executa testes próprios nem toma o controle durante a inicialização.
- Aprende quais direções produzem resposta visual e ajuda a recuperação a evitar a direção que acabou de falhar.
- Só reforça movimentos analógicos fracos depois de observar repetidamente que comandos fortes funcionam e comandos fracos não.

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
- Baixa a cópia processada e verificada do MaleCNS para `.cache\malecns` quando necessário.
- Valida importações, CUDA para o NitroGen, MaleCNS e controle virtual.

Nada é instalado globalmente pelo `pip`. O MaleCNS usa Numba/CPU por padrão e não exige Docker, WSL, Node, Conda ou compilador C++.

## Benchmark

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

## Precisão por Gênero

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

## Camadas

### Percepção confiável

`neveludens/perception.py` analisa brilho, contraste, movimento, bordas, tela escura, loading provável e tela estática. Essa análise roda ao lado do modelo e não altera o frame principal.

### Recuperação inteligente

No nível `Temporário`, `neveludens/legacy_anti_loop.py` preserva o comportamento original: guarda somente o estado curto necessário, detecta baixa movimentação e assinaturas repetidas e executa as mesmas direções fixas de escape usadas antes da reformulação.

No nível `Persistente`, a recuperação atual compara o movimento enviado com a resposta visual. `neveludens/advanced_memory.py` também reconhece imagens parecidas por hash visual, agrupa lugares visitados, registra quais padrões de ação deram progresso ou não e salva um arquivo por jogo em `memories/`.

Quando ligada junto do Supervisor multimodal, ela envia um resumo curto para a VLM com sinais como "mesmo lugar há muitos passos", "última ação não mudou a cena" e "área vista recentemente". Isso ajuda a VLM orientar uma rota diferente sem receber uma lista enorme de prints antigos.

### Supervisor de objetivos

`neveludens/supervisor.py` decide se a ação do modelo deve ser aceita, ajustada ou substituída por uma skill. Ele é a camada que transforma o modelo reativo em um agente mais coordenado.

### Skill library

`neveludens/skills.py` contém rotinas reutilizáveis:

- `wait_loading`: reduz comandos durante telas de loading provável.
- `unstuck`: tenta uma direção alternativa após várias ações de movimento sem resultado visual.
- `break_repetition`: quebra somente padrões repetidos de movimento que também não produziram progresso.

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
- GPU NVIDIA com CUDA funcional no PyTorch para o motor NitroGen. O MaleCNS pode executar em CPU.
- Jogo aberto em janela visível.
- Suporte a controle virtual no Windows.

Observação importante: o pacote Python `vgamepad` é instalado na `.venv`, mas o controle virtual também exige o driver ViGEmBus no Windows. O `instalar.bat` detecta sua ausência, pede autorização e instala ou repara o driver usando o MSI que já acompanha o pacote local. Essa é a única dependência que precisa ser registrada no Windows, pois um driver não pode operar somente dentro da pasta do projeto.

## Uso

1. Abra o jogo no Windows.
2. Execute `iniciar.bat`.
3. Clique em **Atualizar** se o jogo não aparecer.
4. Selecione o jogo ou digite o nome do `.exe`.
5. Deixe a captura em `auto`.
6. Deixe o modo de captura em **Precisão** ou escolha **Tempo real**.
7. Deixe a saída de depuração desligada para **Simples** ou ative para **Detalhado**, gravando PNG, vídeos e logs detalhados.
8. Deixe o modo de jogo em **Padrão**, escolha **Jogo de luta** para Street Fighter 6 ou **Tela dividida** para jogos co-op/split-screen em que a IA deve enxergar apenas a metade esquerda da tela.
9. Deixe o modo de jogador em **Automático**, escolha **Player 2** para entrada lateral padrão ou **Jogador 2 (Co-op)** para a macro de confirmação/esquerda/confirmação.
10. Deixe **Recuperação inteligente** em **Temporário**, escolha **Persistente** para salvar lugares e resultados por jogo ou **Padrão** para não usar essas camadas.
11. Clique em **Iniciar**.
12. Para parar, clique em **Parar** no mesmo botão.

Se o agente parecer cego, vendo tela preta ou reagindo a uma imagem congelada, use **Diagnosticar** na própria interface.

## Saídas

- `out/<modelo>/*_DEBUG.mp4`: vídeo com visualização de debug, salvo apenas com a saída detalhada.
- `out/<modelo>/*_CLEAN.mp4`: vídeo limpo da captura, salvo apenas com a saída detalhada.
- `out/<modelo>/*_ACTIONS.json`: ações finais enviadas ao jogo, salvo apenas com a saída detalhada.
- `out/<modelo>/*_SUPERVISOR.json`: percepção, memória, objetivo e skill usada, salvo apenas com a saída detalhada.
- `memories/<jogo>.json`: memória persistente por processo, criada apenas quando **Recuperação inteligente** está em `Persistente`.
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
.venv\Scripts\python.exe scripts\flybrain_serve.py --port 5555 --data .cache\malecns
```

```bat
.venv\Scripts\python.exe scripts\play.py --process nome_do_jogo.exe --port 5555 --screenshot-backend auto --agent-slot auto
```

Para uso comum, prefira `instalar.bat` e `iniciar.bat`.

## Informações Legais

Copyright (c) 2026 Mateus Lopes. Todos os direitos reservados.

Qualquer cópia, redistribuição ou modificação deve preservar a atribuição ao autor original conforme LICENSE.txt.

O backend experimental usa o pacote `flybrain` sob licença MIT e dados MaleCNS v1.0 sob CC BY 4.0. O connectoma é resultado da colaboração FlyEM/HHMI Janelia, University of Cambridge, MRC Laboratory of Molecular Biology e Google Research. Consulte `THIRD_PARTY_NOTICES.md`.
