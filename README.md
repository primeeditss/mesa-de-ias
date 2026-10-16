# Mesa de IAs

Aplicativo local de conversa multiprovedor. Você envia uma pergunta, os CLIs selecionados respondem em paralelo, leem as contribuições uns dos outros e fazem uma revisão; por fim, uma IA escolhida produz a resposta única.

## Abrir

No PowerShell, execute `.\start.ps1` dentro desta pasta. O navegador abre em `http://127.0.0.1:8765`. Para fechar, pressione `Ctrl+C` no PowerShell.

O servidor escuta somente em `127.0.0.1`, não na rede. Ele usa a autenticação que cada CLI já tem no computador e não grava as respostas em disco. O histórico da conversa permanece no navegador enquanto a página estiver aberta.

## Conectores

O app reconhece Claude Code (`claude`), Codex (`codex`), OpenCode (`opencode`), Gemini CLI (`gemini`), OpenRouter, Cursor Agent (`cursor-agent`), Qwen Code (`qwen`) e Ollama (`ollama`). No Windows, também reconhece scripts `.ps1`, `.cmd` e `.bat` instalados no PATH. `cursor` abre o editor e não substitui `cursor-agent`.

Para o Gemini CLI nesta Mesa, use uma chave do Google AI Studio. O servidor procura `GEMINI_API_KEY` no ambiente e, se não encontrar, lê somente essa variável de `C:\Users\<seu usuário>\MEUS PROJETOS\.env`. Para outro local, defina `MESA_ENV_FILE` antes de iniciar o servidor. Exemplo de linha no `.env`: `GEMINI_API_KEY=sua_chave_aqui`. Não compartilhe a chave; a Mesa a passa apenas ao processo do Gemini. No primeiro uso, abra `gemini` dentro da pasta `MEUS PROJETOS` e selecione **Use Gemini API Key** para configurar o CLI.

A autenticação pessoal por Google no Gemini CLI deixou de funcionar para contas individuais; a chave da API é o caminho apropriado para integrar o Gemini a esta Mesa. O uso gratuito do Google AI Studio tem limites de taxa e disponibilidade por modelo/conta, então não é ilimitado. No modo Completo, cada pergunta pode chamar o Gemini na resposta inicial, na revisão e também na síntese final. Consulte os [limites e preços atuais da API Gemini](https://ai.google.dev/gemini-api/docs/pricing). Para configurar o Qwen Code, execute `qwen`, use `/auth` e escolha um provedor; a Mesa só o habilita depois que essa autenticação estiver selecionada. A antiga opção OAuth gratuita do Qwen foi descontinuada. O Ollama é local e usa por padrão `qwen3.5:4b`; baixe o modelo uma vez com `ollama run qwen3.5:4b`. O painel só marca Ollama como disponível quando encontra esse modelo. Para escolher outro modelo local, defina `MESA_OLLAMA_MODEL` antes de iniciar o servidor. O modelo recomendado ocupa cerca de 3,3 GB; o download depende do espaço em disco e do hardware disponíveis.

OpenRouter também está disponível com modelos sem custo. Crie uma conta e uma chave em [openrouter.ai/keys](https://openrouter.ai/keys) e acrescente `OPENROUTER_API_KEY=sua_chave_aqui` ao mesmo arquivo `.env`. A Mesa usa o roteador `openrouter/free`, que escolhe entre modelos gratuitos disponíveis; a qualidade e a disponibilidade variam. O plano gratuito publica limite de 50 chamadas por dia e 20 por minuto. Uma rodada completa pode usar até três chamadas para cada IA participante.

Cursor Agent só aparece como disponível quando o comando `cursor-agent` está acessível no PATH. A documentação atual do Cursor orienta a instalação da CLI no Windows via WSL.

Claude Code e OpenCode estão temporariamente pausados na Mesa para reduzir esperas. Continuam instalados; para reativá-los, remova seus IDs de `PAUSED_PROVIDERS` em `server.py` e reinicie o servidor. O modo Completo faz respostas paralelas, uma rodada de revisão e uma síntese final. O modo Rápido pula a revisão cruzada e faz a síntese com as respostas iniciais, reduzindo uma rodada de chamadas sem trocar os modelos selecionados. Ambos respeitam a autenticação, os limites e a cobrança de cada serviço. Durante a conversa, a tela acompanha as etapas e mostra prévias do texto que chega de cada IA; ao final, exibe a resposta consolidada e deixa as contribuições individuais disponíveis para consulta. A Mesa mostra respostas e progresso, não o raciocínio privado dos modelos.

## Requisitos

- Python 3.10 ou superior.
- Pelo menos dois CLIs instalados e autenticados.
- Sem dependências Python externas.

Os CLIs são executados a partir de uma pasta temporária vazia, para que a conversa não use arquivos do projeto nem altere seu código.
