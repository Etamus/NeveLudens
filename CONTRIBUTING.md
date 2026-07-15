# Contribuindo para o NeveLudens

Obrigado pelo interesse em contribuir com o NeveLudens.

O NeveLudens é um agente visual local para jogos no Windows. Ele captura a janela do jogo, roda inferência local, aplica supervisor, memória temporal, perfis por jogo e skills de recuperação, e envia comandos por controle virtual.

Contribuições são bem-vindas em código, documentação, testes de jogos, diagnóstico de captura, perfis, melhorias de instalação e relatos claros de comportamento.

## Como Contribuir

Você pode ajudar em áreas como:

- Corrigir bugs de captura, execução, instalação ou controle virtual.
- Melhorar o `iniciar.bat` e a interface WPF em `scripts/Start-NeveLudensGui.ps1`.
- Melhorar o `instalar.bat` sem instalar dependências Python globalmente.
- Criar ou ajustar perfis em `neveludens/profiles.py`.
- Adicionar skills de recuperação em `neveludens/skills.py`.
- Melhorar percepção, memória e supervisor em `neveludens/perception.py`, `neveludens/memory.py` e `neveludens/supervisor.py`.
- Testar jogos e registrar resultados por gênero, câmera, controle e tipo de captura.
- Melhorar README, guia de uso e solução de problemas.

## Antes de Abrir uma Issue

Inclua o máximo possível:

- Nome exato do jogo e do processo `.exe`.
- Sistema operacional.
- Versão do Python usada na `.venv`.
- GPU e versão do driver NVIDIA, quando relevante.
- Backend de captura usado: `auto`, `dxcam` ou `pyautogui`.
- Se a captura ficou preta, congelada, deslocada ou correta.
- Últimos logs de `logs/gui_run_*.log` e `logs/server_*.log`.
- Arquivos de `debug` gerados pelo diagnóstico de captura, quando úteis.
- Trechos de `out/<modelo>/*_SUPERVISOR.json` quando o problema envolver repetição, travamento ou ações ruins.

Remova informações privadas de logs e prints antes de publicar.

## Ambiente de Desenvolvimento

O caminho principal no Windows é:

```bat
instalar.bat
```

O instalador cria ou reutiliza:

- `.venv`
- `.cache`
- `models`
- `logs`
- `out`
- `debug`

Depois, para iniciar o agente:

```bat
iniciar.bat
```

Para comandos manuais:

```bat
.venv\Scripts\python.exe scripts\launcher.py --process nome_do_jogo.exe --screenshot-backend auto --port 5555 --non-interactive
```

```bat
.venv\Scripts\python.exe scripts\capture_check.py --process nome_do_jogo.exe --backend all
```

## Padrões Técnicos

- Mantenha mudanças pequenas e focadas.
- Preserve instalação local dentro do projeto.
- Não adicione dependências globais obrigatórias sem uma justificativa forte.
- Evite confundir o frame enviado ao modelo com overlays visuais ou marcações de debug.
- Prefira lógica conservadora para fallback de captura: um frame ruim isolado não deve trocar backend sozinho.
- Perfis por jogo devem ser específicos, reversíveis e documentados no README quando mudarem comportamento do usuário.
- Skills devem ser curtas, reutilizáveis e seguras para jogos diferentes.
- Mudanças no supervisor devem salvar motivos claros no log para facilitar depuração.

## Testes Recomendados

Antes de enviar uma pull request, rode pelo menos o que fizer sentido para sua alteração:

```bat
.venv\Scripts\python.exe -m pip install -e .
```

```bat
.venv\Scripts\python.exe scripts\capture_check.py --process nome_do_jogo.exe --backend all
```

```bat
.venv\Scripts\python.exe -c "import torch, torchvision, neveludens, cv2, dxcam, vgamepad, xspeedhack, zmq; print('OK')"
```

Se mexer no `iniciar.bat` ou na interface WPF, abra a interface e confira:

- botão de minimizar;
- botão de fechar;
- diagnóstico de captura;
- botão único `Iniciar`/`Parar`;
- log sem barra horizontal;
- seleção de processo com texto longo.

Se mexer no instalador, confira:

- menu inicial;
- confirmação antes de instalar;
- criação ou reutilização da `.venv`;
- falha clara quando Python, CUDA, Hugging Face ou controle virtual não estiverem disponíveis;
- ausência de mensagem de sucesso antes da validação final.

## O Que Não Fazer Commit

Não inclua arquivos locais, pesados ou gerados:

```text
.venv/
.cache/
models/
logs/
out/
debug/
neveludens_local_config.json
*.pyc
__pycache__/
```

Também evite incluir vídeos, checkpoints, capturas privadas, logs com dados pessoais ou arquivos temporários criados durante testes.

## Pull Requests

Ao abrir uma pull request:

1. Explique o problema ou objetivo.
2. Descreva a solução.
3. Liste os jogos/processos testados, se houver.
4. Informe se a mudança afeta instalação, captura, modelo, supervisor, perfis ou interface.
5. Atualize documentação quando o comportamento mudar.
6. Inclua logs ou prints apenas quando ajudarem a revisão.

Exemplos de nomes de branch:

```text
fix-dxcam-window-region
ui-start-window-minimize
profile-hollow-knight
skill-break-stuck-loop
docs-installation-flow
```

## Direção do Projeto

O NeveLudens não pretende ser apenas um script que aperta botões. A direção do projeto é construir uma base local para agentes visuais jogarem com mais confiabilidade:

- percepção confiável;
- memória temporal;
- supervisor de objetivos;
- biblioteca de skills;
- perfis por jogo;
- diagnóstico claro de captura e decisões.

Contribuições que tornem o agente mais observável, estável, fácil de usar e mais competente em jogos reais são especialmente valiosas.
