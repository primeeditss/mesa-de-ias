# Mesa de IAs

Aplicativo local de conversa multiprovedor. Você envia uma pergunta, as IAs selecionadas respondem em paralelo, leem as contribuições umas das outras e fazem uma revisão; por fim, uma IA escolhida produz a resposta única. Os provedores ficam numa barra lateral dividida entre **Sua mesa** e **Outros detectados**, com o **Painel de confiança** (o botão **Testar minhas IAs**) e o **Histórico** das conversas logo abaixo.

## Abrir

No PowerShell, execute `.\start.ps1` dentro desta pasta. O navegador abre em `http://127.0.0.1:8765`. Para fechar, pressione `Ctrl+C` no PowerShell.

O servidor escuta somente em `127.0.0.1`, não na rede. Ele usa a autenticação que cada CLI já tem no computador e as chaves de API do `.env` (para os provedores chamados por HTTP). As conversas ficam salvas em `historico.json`, nesta mesma pasta, e podem ser reabertas na seção **Histórico** da barra lateral: o arquivo é lido e gravado só neste computador e nada é enviado para fora. Apague `historico.json` — ou use o `×` de cada conversa — para limpar tudo.

## Conectores

O app reconhece Claude Code (`claude`), Codex (`codex`), OpenCode (`opencode`), Gemini (API HTTP), OpenRouter (API HTTP), Cursor Agent (`cursor-agent`), Qwen Code (`qwen`) e Ollama (API HTTP local). No Windows, também reconhece scripts `.ps1`, `.cmd` e `.bat` instalados no PATH. `cursor` abre o editor e não substitui `cursor-agent`.

O Gemini é chamado pela **API HTTP** do Google AI Studio, sem passar pelo terminal — é isso que tirou a lentidão do CLI. Crie uma chave gratuita em [aistudio.google.com/apikey](https://aistudio.google.com/apikey) e coloque no `.env`. O servidor procura `GEMINI_API_KEY` no ambiente e, se não encontrar, lê somente essa variável de `C:\Users\<seu usuário>\MEUS PROJETOS\.env`. Para outro local, defina `MESA_ENV_FILE` antes de iniciar o servidor. Exemplo de linha no `.env`: `GEMINI_API_KEY=sua_chave_aqui`. Não compartilhe a chave; a Mesa a usa apenas nas chamadas ao serviço do Google. O modelo padrão é `gemini-3.8-flash` — o `gemini-2.5-flash` foi descontinuado pela própria API — e pode ser trocado com `MESA_GEMINI_MODEL`. Não é preciso instalar nem autenticar o Gemini CLI neste computador.

A autenticação pessoal por Google no Gemini CLI deixou de funcionar para contas individuais — por isso a Mesa usa a chave da API, e não o CLI. O uso gratuito do Google AI Studio tem limites de taxa e disponibilidade por modelo/conta, então não é ilimitado. No modo Completo, cada pergunta pode chamar o Gemini na resposta inicial, na revisão e também na síntese final. Consulte os [limites e preços atuais da API Gemini](https://ai.google.dev/gemini-api/docs/pricing). Para configurar o Qwen Code, execute `qwen`, use `/auth` e escolha um provedor; a Mesa só o habilita depois que essa autenticação estiver selecionada. A antiga opção OAuth gratuita do Qwen foi descontinuada. O Ollama também é chamado por **API HTTP**, em `http://127.0.0.1:11434` (ou no endereço indicado por `OLLAMA_HOST` / `MESA_OLLAMA_BASE`), e usa por padrão `qwen3.5:4b`; baixe o modelo uma vez com `ollama pull qwen3.5:4b`. O painel mostra **Ollama fechado** quando o aplicativo não está aberto e **modelo ausente** quando ele responde mas falta o modelo. A Mesa envia `keep_alive` de 30 minutos e pré-carrega o modelo no arranque, para a primeira resposta não pegar partida fria. Para escolher outro modelo local, defina `MESA_OLLAMA_MODEL` antes de iniciar o servidor. O modelo recomendado ocupa cerca de 3,3 GB; o download depende do espaço em disco e do hardware disponíveis.

OpenRouter também está disponível com modelos sem custo. Crie uma conta e uma chave em [openrouter.ai/keys](https://openrouter.ai/keys) e acrescente `OPENROUTER_API_KEY=sua_chave_aqui` ao mesmo arquivo `.env`. A Mesa usa o roteador `openrouter/free`, que escolhe entre modelos gratuitos disponíveis; a qualidade e a disponibilidade variam. O plano gratuito publica limite de 50 chamadas por dia e 20 por minuto. Uma rodada completa pode usar até três chamadas para cada IA participante.

Cursor Agent só aparece como disponível quando o comando `cursor-agent` está acessível no PATH. A documentação atual do Cursor orienta a instalação da CLI no Windows via WSL.

Claude Code e OpenCode voltaram a ficar disponíveis. Para pausar algum provedor (por exemplo, um CLI lento), coloque o ID dele em `PAUSED_PROVIDERS` no `server.py` **e** em `pausedProviderIds` no `static/app.js`, e reinicie o servidor. A divisão da barra lateral também é configurável: `mesaPrincipalIds` no `static/app.js` decide quem entra em **Sua mesa**; o resto vai para **Outros detectados**. O modo Completo faz respostas paralelas, uma rodada de revisão e uma síntese final. O modo Rápido pula a revisão cruzada e faz a síntese com as respostas iniciais, reduzindo uma rodada de chamadas sem trocar os modelos selecionados. Ambos respeitam a autenticação, os limites e a cobrança de cada serviço. Durante a conversa, a tela acompanha as etapas e mostra o tempo de cada IA e prévias do texto que chega; ao final, exibe a resposta consolidada com o cronômetro de cada participante e o botão **Ver as N respostas lado a lado**, que abre o texto completo de cada IA para comparação. A Mesa mostra respostas e progresso, não o raciocínio privado dos modelos.

## Velocidade

A Mesa evita o trabalho que não vira resposta:

- **Memória de falhas.** Um provedor que falha numa rodada (sem login, sem saldo, sem cota) ganha etiqueta âmbar com o motivo no lugar do "instalado" e sai da seleção padrão. Cada rodada atualiza essa memória; reiniciar o servidor começa de novo.
- **Síntese por quem respondeu.** Se a IA escolhida para a resposta final não respondeu na rodada inicial, a síntese passa para outra que respondeu — em vez de gastar uma chamada fadada a falhar (um CLI leva ~20 s só para recusar).
- **Modo Rápido automático.** Perguntas curtas pulam a revisão cruzada sozinhas, e o seletor mostra a escolha. Assim que você troca o modo à mão, a Mesa para de mexer nele. O limite de tamanho está em `MODO_RAPIDO_ATE` no `static/app.js`.

Com isso, uma pergunta simples respondida por Gemini e OpenRouter cai de ~50 s para ~7 s. Os CLIs (Claude Code, Codex, OpenCode, Cursor) levam de 16 a 22 s por chamada só para iniciar, então rendem mais em perguntas que realmente precisam deles.

## Painel de confiança

O botão **Testar minhas IAs**, na barra lateral logo abaixo da lista de provedores, faz uma pergunta mínima ("Responda apenas: OK") para cada IA detectada, todas ao mesmo tempo, e mostra quem respondeu, em quanto tempo e por que falhou — sem precisar abrir uma conversa inteira para descobrir.

O resultado abre num cartão na conversa: ✓ com o tempo de quem respondeu, ✕ com o motivo de quem não respondeu — **sem login**, **sem saldo**, **limite atingido**, **sem conexão** ou **demorou demais** — e o começo da resposta de quem foi bem. O botão **Testar de novo** repete a checagem. O `×` fecha o cartão, e o botão da barra lateral passa a dizer **Ver resultado do teste**: ele reabre a lista sem gastar cota de novo.

O teste **nunca roda sozinho** — cada chamada consome cota ou limite do serviço, então quem decide é você. Ele também atualiza a mesma memória de falhas usada pelas rodadas: quem falha ganha a etiqueta na lista e sai da seleção (desde que sobrem duas IAs), e quem voltou a responder perde a etiqueta. O motivo vem do erro real do provedor, já sem os códigos de cor que os CLIs misturam na saída, para você poder copiar e pedir ajuda se precisar.

Cada teste tem um prazo (60 s no total): quem não responder dentro dele aparece como "demorou demais" — e, se responder depois, o painel se corrige sozinho.

### Cronômetro de cada IA

Durante a rodada, o cartão de progresso mostra o tempo de cada IA ("Concluída em 3,4 s" ou "Não respondeu em 12,2 s"). Na resposta final, o título traz o tempo da síntese ("RESPOSTA CONSOLIDADA · Gemini · 2,1 s") e o rodapé **Painel de confiança desta rodada** lista cada participante com o seu tempo — ou com o motivo de ter ficado de fora.

Os tempos valem para a rodada que acabou de acontecer: não são gravados no histórico, então reabrir uma conversa antiga não mostra o rodapé.

## Respostas completas, lado a lado

Cada resposta final traz o botão **Ver as N respostas lado a lado**. Ele abre um painel com o texto **inteiro** que cada IA enviou — sem corte — para você comparar as vozes e conferir de onde veio cada ponto da resposta consolidada.

As respostas aparecem em colunas quando há espaço (duas na largura normal da conversa) e se empilham sozinhas em janelas estreitas ou quando há muitas IAs, para nunca virar texto apertado. Dentro do painel, dois botões escolhem o jeito de ler: **Lado a lado** (padrão) ou **Uma após a outra** — e a sua escolha vale para o resto da sessão. O `×` fecha e devolve o foco ao botão.

Abrir, fechar ou trocar de modo **não faz chamada nenhuma e não gasta cota**: o texto já veio junto com a resposta final, e continua guardado no histórico. O único limite é de tamanho: até 20.000 caracteres por IA (cerca de dez páginas), uma trava de segurança para uma resposta fora do normal não pesar o arquivo nem travar a tela.

## Histórico de conversas

Cada conversa concluída é gravada em `historico.json`, na pasta do projeto, com as 50 mais recentes primeiro. A seção **Histórico** da barra lateral mostra o título, quantas mensagens tem e quando foi a última vez; clicar reabre a conversa no meio da tela e permite continuar de onde parou, com o contexto das mensagens anteriores. O `×` apaga uma conversa, com confirmação.

A **busca** logo acima da lista procura no texto inteiro das conversas — título, perguntas, respostas e contribuições — e ignora maiúsculas e acentos: digitar `orcamento` encontra "orçamento". Os resultados mostram em itálico o trecho onde a palavra apareceu e o contador passa a dizer quantas de quantas conversas combinam ("3 de 12"). O `×` da caixa, ou a tecla Esc, limpam a busca.

O botão `⤓` de cada conversa **salva uma cópia** na pasta de downloads do navegador, com o nome `mesa-<assunto da conversa>`, em dois formatos:

- **Documento de texto (`.md`)** — título, data, cada pergunta, cada resposta e as contribuições. Abre em qualquer editor, no VS Code ou no GitHub, e serve para colar em outro lugar.
- **Página pronta (`.html`)** — um arquivo único, com o estilo embutido e fundo claro, que abre no navegador sem precisar da Mesa. É o formato bom para **imprimir** ou enviar a alguém.

Nos dois casos nada sai do computador: o arquivo é montado pelo próprio servidor local.

O arquivo é gravado de forma atômica (escreve num temporário e troca), então fechar o servidor no meio da gravação não corrompe o JSON — e ele fica fora do Git pelo `.gitignore`. Só texto é salvo: o raciocínio privado dos modelos não entra no arquivo, como também não aparece na tela.

## Requisitos

- Python 3.10 ou superior.
- Pelo menos duas IAs disponíveis: CLIs instalados e autenticados, ou as chaves de API e o Ollama configurados.
- Sem dependências Python externas.

Os CLIs são executados a partir de uma pasta temporária vazia, para que a conversa não use arquivos do projeto nem altere seu código. Gemini, OpenRouter e Ollama não iniciam processo nenhum: a conversa acontece por HTTP. As animações da interface usam apenas `transform` e `opacity` e são desligadas quando o sistema pede menos movimento (`prefers-reduced-motion`). O mesmo vale para a rolagem: cada área (a conversa e a lista de provedores) rola por conta própria em qualquer tamanho de janela, e a conversa tem um controle próprio — setas para o topo e para o fim, trilha que aceita clique e arrasto do polegar, e teclado (setas, PageUp/PageDown, Home/End). Ele só aparece quando há conteúdo fora da tela.
