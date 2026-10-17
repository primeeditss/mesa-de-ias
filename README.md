# Mesa de IAs

Aplicativo local de conversa multiprovedor. Você envia uma pergunta, as IAs selecionadas respondem em paralelo, leem as contribuições umas das outras e fazem uma revisão; por fim, uma IA escolhida produz a resposta única. Os provedores ficam numa barra lateral dividida entre **Sua mesa** e **Outros detectados**, com o **Histórico** das conversas logo abaixo.

## Abrir

No PowerShell, execute `.\start.ps1` dentro desta pasta. O navegador abre em `http://127.0.0.1:8765`. Para fechar, pressione `Ctrl+C` no PowerShell.

O servidor escuta somente em `127.0.0.1`, não na rede. Ele usa a autenticação que cada CLI já tem no computador e as chaves de API do `.env` (para os provedores chamados por HTTP). As conversas ficam salvas em `historico.json`, nesta mesma pasta, e podem ser reabertas na seção **Histórico** da barra lateral: o arquivo é lido e gravado só neste computador e nada é enviado para fora. Apague `historico.json` — ou use o `×` de cada conversa — para limpar tudo.

## Conectores

O app reconhece Claude Code (`claude`), Codex (`codex`), OpenCode (`opencode`), Gemini (API HTTP), OpenRouter (API HTTP), Cursor Agent (`cursor-agent`), Qwen Code (`qwen`) e Ollama (API HTTP local). No Windows, também reconhece scripts `.ps1`, `.cmd` e `.bat` instalados no PATH. `cursor` abre o editor e não substitui `cursor-agent`.

O Gemini é chamado pela **API HTTP** do Google AI Studio, sem passar pelo terminal — é isso que tirou a lentidão do CLI. Crie uma chave gratuita em [aistudio.google.com/apikey](https://aistudio.google.com/apikey) e coloque no `.env`. O servidor procura `GEMINI_API_KEY` no ambiente e, se não encontrar, lê somente essa variável de `C:\Users\<seu usuário>\MEUS PROJETOS\.env`. Para outro local, defina `MESA_ENV_FILE` antes de iniciar o servidor. Exemplo de linha no `.env`: `GEMINI_API_KEY=sua_chave_aqui`. Não compartilhe a chave; a Mesa a usa apenas nas chamadas ao serviço do Google. O modelo padrão é `gemini-3.8-flash` — o `gemini-2.5-flash` foi descontinuado pela própria API — e pode ser trocado com `MESA_GEMINI_MODEL`. Não é preciso instalar nem autenticar o Gemini CLI neste computador.

A autenticação pessoal por Google no Gemini CLI deixou de funcionar para contas individuais — por isso a Mesa usa a chave da API, e não o CLI. O uso gratuito do Google AI Studio tem limites de taxa e disponibilidade por modelo/conta, então não é ilimitado. No modo Completo, cada pergunta pode chamar o Gemini na resposta inicial, na revisão e também na síntese final. Consulte os [limites e preços atuais da API Gemini](https://ai.google.dev/gemini-api/docs/pricing). Para configurar o Qwen Code, execute `qwen`, use `/auth` e escolha um provedor; a Mesa só o habilita depois que essa autenticação estiver selecionada. A antiga opção OAuth gratuita do Qwen foi descontinuada. O Ollama também é chamado por **API HTTP**, em `http://127.0.0.1:11434` (ou no endereço indicado por `OLLAMA_HOST` / `MESA_OLLAMA_BASE`), e usa por padrão `qwen3.5:4b`; baixe o modelo uma vez com `ollama pull qwen3.5:4b`. O painel mostra **Ollama fechado** quando o aplicativo não está aberto e **modelo ausente** quando ele responde mas falta o modelo. A Mesa envia `keep_alive` de 30 minutos e pré-carrega o modelo no arranque, para a primeira resposta não pegar partida fria. Para escolher outro modelo local, defina `MESA_OLLAMA_MODEL` antes de iniciar o servidor. O modelo recomendado ocupa cerca de 3,3 GB; o download depende do espaço em disco e do hardware disponíveis.

OpenRouter também está disponível com modelos sem custo. Crie uma conta e uma chave em [openrouter.ai/keys](https://openrouter.ai/keys) e acrescente `OPENROUTER_API_KEY=sua_chave_aqui` ao mesmo arquivo `.env`. A Mesa usa o roteador `openrouter/free`, que escolhe entre modelos gratuitos disponíveis; a qualidade e a disponibilidade variam. O plano gratuito publica limite de 50 chamadas por dia e 20 por minuto. Uma rodada completa pode usar até três chamadas para cada IA participante.

Cursor Agent só aparece como disponível quando o comando `cursor-agent` está acessível no PATH. A documentação atual do Cursor orienta a instalação da CLI no Windows via WSL.

Claude Code e OpenCode voltaram a ficar disponíveis. Para pausar algum provedor (por exemplo, um CLI lento), coloque o ID dele em `PAUSED_PROVIDERS` no `server.py` **e** em `pausedProviderIds` no `static/app.js`, e reinicie o servidor. A divisão da barra lateral também é configurável: `mesaPrincipalIds` no `static/app.js` decide quem entra em **Sua mesa**; o resto vai para **Outros detectados**. O modo Completo faz respostas paralelas, uma rodada de revisão e uma síntese final. O modo Rápido pula a revisão cruzada e faz a síntese com as respostas iniciais, reduzindo uma rodada de chamadas sem trocar os modelos selecionados. Ambos respeitam a autenticação, os limites e a cobrança de cada serviço. Durante a conversa, a tela acompanha as etapas e mostra prévias do texto que chega de cada IA; ao final, exibe a resposta consolidada e deixa as contribuições individuais disponíveis para consulta. A Mesa mostra respostas e progresso, não o raciocínio privado dos modelos.

## Velocidade

A Mesa evita o trabalho que não vira resposta:

- **Memória de falhas.** Um provedor que falha numa rodada (sem login, sem saldo, sem cota) ganha etiqueta âmbar com o motivo no lugar do "instalado" e sai da seleção padrão. Cada rodada atualiza essa memória; reiniciar o servidor começa de novo.
- **Síntese por quem respondeu.** Se a IA escolhida para a resposta final não respondeu na rodada inicial, a síntese passa para outra que respondeu — em vez de gastar uma chamada fadada a falhar (um CLI leva ~20 s só para recusar).
- **Modo Rápido automático.** Perguntas curtas pulam a revisão cruzada sozinhas, e o seletor mostra a escolha. Assim que você troca o modo à mão, a Mesa para de mexer nele. O limite de tamanho está em `MODO_RAPIDO_ATE` no `static/app.js`.

Com isso, uma pergunta simples respondida por Gemini e OpenRouter cai de ~50 s para ~7 s. Os CLIs (Claude Code, Codex, OpenCode, Cursor) levam de 16 a 22 s por chamada só para iniciar, então rendem mais em perguntas que realmente precisam deles.

## Histórico de conversas

Cada conversa concluída é gravada em `historico.json`, na pasta do projeto, com as 50 mais recentes primeiro. A seção **Histórico** da barra lateral mostra o título, quantas mensagens tem e quando foi a última vez; clicar reabre a conversa no meio da tela e permite continuar de onde parou, com o contexto das mensagens anteriores. O `×` apaga uma conversa, com confirmação.

O arquivo é gravado de forma atômica (escreve num temporário e troca), então fechar o servidor no meio da gravação não corrompe o JSON — e ele fica fora do Git pelo `.gitignore`. Só texto é salvo: o raciocínio privado dos modelos não entra no arquivo, como também não aparece na tela.

## Requisitos

- Python 3.10 ou superior.
- Pelo menos duas IAs disponíveis: CLIs instalados e autenticados, ou as chaves de API e o Ollama configurados.
- Sem dependências Python externas.

Os CLIs são executados a partir de uma pasta temporária vazia, para que a conversa não use arquivos do projeto nem altere seu código. Gemini, OpenRouter e Ollama não iniciam processo nenhum: a conversa acontece por HTTP. As animações da interface usam apenas `transform` e `opacity` e são desligadas quando o sistema pede menos movimento (`prefers-reduced-motion`). O mesmo vale para a rolagem: cada área (a conversa e a lista de provedores) rola por conta própria em qualquer tamanho de janela, e a conversa tem um controle próprio — setas para o topo e para o fim, trilha que aceita clique e arrasto do polegar, e teclado (setas, PageUp/PageDown, Home/End). Ele só aparece quando há conteúdo fora da tela.
