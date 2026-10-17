# HANDOFF — Mesa de IAs

## O que é este projeto

Uma "Mesa de IAs" — interface web onde várias IAs (Codex, Claude Code, OpenCode, Gemini,
OpenRouter, Ollama) respondem em paralelo a uma mesma pergunta, e uma IA "juíza" sintetiza a
resposta final.

## Stack

- Backend: Python (`server.py`) — servidor HTTP local, **apenas biblioteca padrão** (sem
  dependências externas: não usa `requests` nem `httpx`)
- Frontend: HTML/CSS/JS em `static/`
- Porta: `http://127.0.0.1:8765`

## Estado atual

- ✅ Interface visual aconchegante (arte vetorial original)
- ✅ Provedores numa barra lateral organizada: "Sua mesa" e "Outros detectados"
- ✅ Gemini chamado pela API HTTP do Google AI Studio — não passa mais pelo terminal
- ✅ Ollama chamado por HTTP em `http://127.0.0.1:11434` — não passa mais pelo terminal
- ✅ Animações suaves (só `transform`/`opacity`, respeitam `prefers-reduced-motion`)
- ✅ Claude Code e OpenCode reativados na interface
- ✅ Memória de falhas por provedor (etiqueta "sem login"/"sem saldo" e fora da seleção padrão)
- ✅ Síntese entregue a uma IA que já respondeu, sem chamada perdida
- ✅ Modo Rápido automático em perguntas curtas (até 120 caracteres)
- ✅ Histórico de conversas em `historico.json`, com seção própria na barra lateral
- ✅ Busca no histórico (ignora acento e maiúscula) e exportação da conversa em `.md` ou `.html`
- ✅ Painel de confiança: "Testar minhas IAs" (tempo e motivo de cada uma) e cronômetro por IA na rodada
- ✅ Respostas completas de cada IA, "lado a lado" (Opção A1) — sem o corte de 1.400 caracteres
- ✅ Especialista em Código (provedor `coder`, via OpenRouter com modelo fixo e prompt próprio)
- ✅ Mesa aceita uma IA só — sem revisão nem síntese inúteis, cartão "RESPOSTA DIRETA"

## O que precisa ser feito

1. ✅ Colocar os provedores numa barra lateral organizada
2. ✅ Chamar Gemini e Ollama por API HTTP, não por terminal (lentidão resolvida)
3. ✅ Adicionar animações suaves sem causar lag
4. ✅ Manter o visual aconchegante
5. ✅ Reativar Claude Code e OpenCode

Todos os itens originais estão concluídos. As pendências restantes estão no fim do arquivo.

## Segunda rodada — rapidez e histórico

1. ✅ **Opção 1 — síntese por quem respondeu**: se a IA escolhida para a resposta final não
   respondeu na rodada inicial, `orchestrate()` troca o sintetizador por uma IA que respondeu
   (`synthesizer not in first` → primeiro de `selected` presente em `first`).
2. ✅ **Opção 2 — não marcar quem falhou**: `run_parallel()` registra o último erro de cada
   provedor em `provider_last_error` (`server.py`); `provider_status()` expõe `last_error` e,
   quando o CLI só "parece instalado", troca o estado pelo motivo curto
   (`short_failure_reason()`). No `app.js`, `providerStateKind()` devolve `failed`, a linha
   fica âmbar e `defaultSelection()` deixa esse provedor desmarcado — mas só se sobrarem duas
   IAs com que conversar. Depois de cada rodada, `refreshProviders()` atualiza a barra.
3. ✅ **Opção 3 — Rápida automática**: `previewMode()` no `app.js` troca o modo para Rápida
   enquanto a pergunta tem até `MODO_RAPIDO_ATE` (120) caracteres. Se o usuário mexer no
   seletor (`modePinned`), a Mesa não mexe mais nele.
4. ✅ **Histórico de conversas**: `server.py` guarda até 50 conversas em `historico.json`
   (gravação atômica: `.tmp` + `replace`), com as rotas `GET /api/historico`,
   `GET /api/historico/<id>`, `POST /api/historico` e `DELETE /api/historico/<id>`.
   O `app.js` mantém `state.turns`/`state.conversationId`, salva ao fim de cada conversa e
   reconstrói a tela ao clicar numa entrada. O arquivo é ignorado pelo Git.

Medido com "Responda apenas: OK" (Gemini + OpenRouter): ~7 s, contra ~50 s antes.

## Terceira rodada — layout e rolagem

1. ✅ **Corrente de alturas**: `body` era `height:100vh` com `overflow:hidden` e o `.layout`
   (grid) deixava a linha crescer com o conteúdo (`min-height:auto`). Resultado: `.main`
   esticava junto com a resposta, `.conversation` nunca tinha o que rolar e o resto da tela
   ficava cortado. Corrigido com `grid-template-rows:minmax(0,1fr)` no `.layout` e
   `min-height:0` em `.main`, `.sidebar` e `.conversation` (esta com `overflow-y:auto`).
2. ✅ **Controle de rolagem do chat**: pílula flutuante (`.scroll-control`) com setas, trilha e
   polegar. Funciona arrastando o polegar, clicando na trilha, pelas setas e pelo teclado
   (setas, PageUp/PageDown, Home/End), com `aria-valuenow` acompanhando. Só aparece quando há
   mais de 24 px fora da tela (`atualizarControleDeScroll()`, atualizado por `ResizeObserver`).
   `comportamentoSuave()` troca `smooth` por `instant` quando o sistema pede menos movimento.
   A barra nativa fica escondida **apenas na conversa** (`scrollbar-width:none`) para não
   duplicar o controle.

Medido numa janela de 656 px de altura: `.main` fica com 656 px (antes esticava para 4102 px)
e a conversa, com 8446 px de conteúdo, rola até o fim (0 → 400 → 8446).

## Quarta rodada — guardar e achar (Opção C: buscar + exportar)

1. ✅ **Buscar no histórico**: `GET /api/historico?busca=...` filtra as conversas pelo texto
   inteiro — título, mensagens e contribuições — e devolve um `match` com o trecho onde a
   palavra apareceu. `fold_text()` compara em minúsculas e sem acento **sem mudar o tamanho do
   texto** (decompõe cada caractere e tira só o acento), então "orcamento" acha "orçamento" e o
   trecho cai exatamente no ponto encontrado. Sem `busca`, a rota responde como antes.
2. ✅ **Exportar a conversa**: `GET /api/historico/<id>/exportar?formato=md|html` monta o
   arquivo no servidor e entrega como download (`Content-Disposition`), com nome vindo do
   título e sem acentos nem cedilha (`title_slug()`). O Markdown é a versão canônica (título,
   data, cada pergunta, cada resposta e as contribuições). O HTML é um documento único, com o
   CSS embutido em tom claro de papel e `@media print` — pensado para imprimir ou enviar —
   e o Markdown das respostas é convertido por `markdown_to_html()` (títulos, listas, negrito,
   itálico, código, citação e links), com `html.escape` em tudo que vem dos modelos.
3. ✅ **Na tela**: caixa de busca no topo do Histórico (contador "3 de 12", trecho do encontro
   em itálico, aviso de "nada encontrado" e limpar pelo `×` ou Esc) e o botão `⤓` em cada
   conversa, que abre as duas opções de arquivo. As opções são **links de verdade**
   (`<a download>`): quem baixa é o navegador, com o nome que o servidor mandou.

Testado com 40 verificações automáticas no `server.py` (busca com e sem acento, os dois
formatos, 404 de id inexistente, 400 de formato desconhecido, HTML sem `script` injetado e a
lista sem busca inalterada) e no navegador (busca, limpar, abrir o menu e baixar os dois
arquivos: `.md` de 658 bytes e `.html` de 4047 bytes, com os nomes certos).

## Quinta rodada — painel de confiança (Opção B: testar as IAs + cronômetros)

1. ✅ **Botão "Testar minhas IAs"** (barra lateral, logo abaixo da lista de provedores):
   `POST /api/testar` cria o teste e chama `run_provider()` de cada IA detectada **ao mesmo
   tempo**, com uma pergunta mínima ("Responda apenas: OK"). O frontend acompanha por
   `GET /api/testar/<id>` e as linhas vão aparecendo conforme cada IA responde. O teste nunca
   roda sozinho: cada chamada consome cota/limite, então quem decide é a pessoa, no botão.
2. ✅ **O resultado é um cartão na conversa**: cada IA aparece com ✓ ou ✕, o tempo em segundos e
   o motivo (`limite atingido`, `sem saldo`, `sem login`, `sem conexão` ou `demorou demais`),
   mais o começo da resposta de quem foi bem. O cartão tem "Testar de novo" e um `×` para
   fechar; fechado, o botão vira "Ver resultado do teste" e reabre a lista **sem gastar cota**.
3. ✅ **O teste alimenta a memória de falhas**: quem falha fica etiquetado na lista de IAs e sai
   da seleção (desde que sobrem duas); quem volta a responder sai da etiqueta.
   `short_failure_reason()` ganhou `limite atingido` (cota, `429`, "usage limit") e manteve
   `sem saldo` (saldo, crédito) — a ordem da checagem importa, porque o erro de cota do Gemini
   também cita "billing".
4. ✅ **Cronômetros**: `run_parallel()` mede o tempo de cada IA e publica `provider_seconds`; a
   síntese é cronometrada em `synth_seconds`. Durante a rodada, o cartão de progresso mostra
   "Concluída em 3,4 s" / "Não respondeu em 12,2 s" em cada linha; na resposta final, o título
   ganha o tempo da síntese ("RESPOSTA CONSOLIDADA · Gemini · 2,1 s") e o rodapé "Painel de
   confiança desta rodada" lista cada IA com o seu tempo — ou com o motivo da falha.
5. ✅ **Erro cru, mas limpo**: `strip_ansi()` tira os códigos de cor que os CLIs jogam no meio do
   erro e `clean_detail()` corta em 300 caracteres. É o texto que a pessoa copia para pedir
   ajuda, e é o que aparece embaixo de quem falhou.

Testado com 51 verificações automáticas no `server.py` (as IAs são **substituídas por respostas
falsas**: nenhuma cota é gasta; cobre as etiquetas, o teste completo, lista explícita, 400, 404,
a IA que passa do prazo e os cronômetros da rodada) e no navegador (botão, linhas aparecendo uma
a uma, tempos, etiquetas na lista de IAs, abrir/fechar sem chamada nova e o rodapé da resposta
com uma IA falhando e outra demorando 9 s).

## Sexta rodada — respostas completas, lado a lado (Opção A1)

1. ✅ **Fim do corte de 1.400 caracteres**: o texto de cada IA ia para a tela e para o histórico
   cortado em 1.400. Agora vai inteiro, no campo `text`, com um teto único de segurança —
   `MAX_NOTE_CHARS = 20.000` (≈10 páginas) — usado **nos dois lugares**, para a conversa
   reaberta mostrar exatamente o que apareceu na tela. Uma resposta fora do normal para no teto
   em vez de travar o desenho ou engordar o arquivo.
2. ✅ **Campo renomeado com respeito ao que já existe**: `summary` virou `text` (o nome antigo
   mentia: não era resumo nenhum). As conversas gravadas antes desta rodada continuam abrindo:
   `note_text()` lê `text` e, quando não há, cai no `summary`. Testado de propósito com uma
   conversa no formato antigo (busca, abrir e exportar).
3. ✅ **Botão "Ver as N respostas lado a lado"**: em cada resposta final, o antigo "Ver
   contribuições" deu lugar a um botão que abre um painel com as respostas completas de cada IA
   em **colunas** (`grid` com `auto-fit`, mínimo de 320 px por coluna). Quando não cabe lado a
   lado — janela estreita ou muitas IAs — as colunas se empilham sozinhas, sem virar texto
   ilegível. Com 3 IAs e a largura normal da conversa (800 px) são 2 colunas de ~372 px.
4. ✅ **Dois jeitos de ler, e a escolha é lembrada**: dentro do painel, `▥ Lado a lado` (padrão)
   e `☰ Uma após a outra`; a preferência vale para a sessão inteira. O `×` fecha e devolve o
   foco ao botão. Abrir, fechar e trocar de modo **não gastam cota**: o texto já veio junto com
   a resposta final (confirmado no navegador: um único `POST /api/chat` na rodada inteira).
5. ✅ **A busca agora mostra onde achou**: quando a palavra estava dentro de uma contribuição, a
   conversa aparecia na lista **sem o trecho** (`match_excerpt()` só olhava a resposta final).
   Agora o trecho também vem das contribuições — defeito antigo da Opção C, achado pelo teste
   desta rodada.

Testado com 42 verificações automáticas no `server.py` (as IAs são **substituídas por respostas
falsas**, com um marcador no fim de cada texto: nenhuma cota gasta; cobre o texto inteiro na
rodada, no histórico, na busca e nas duas exportações, o teto de 20.000, a compatibilidade com o
formato antigo e os arquivos da tela) e no navegador (resposta de 3.163 caracteres chegando
inteira, botão com a contagem certa, painel abrindo, 3 contribuições, colunas medidas em
3 × 361 px numa largura de 1.180 px, modo empilhado, fechar devolvendo o foco, reabrir sem
chamada nova, conversa reaberta do histórico com o texto inteiro e console sem erro).

## Sétima rodada — Especialista em Código (provedor `coder`)

Pedido do usuário: uma IA dedicada a programação, porque o Gemini vinha cometendo erros de
lógica em CSS; escolhida só ela quando for programar.

1. ✅ **DeepSeek gratuito não existe mais.** Antes de escrever código, a lista pública de
   modelos do OpenRouter foi consultada: dos 471 modelos, 19 são gratuitos e **nenhum é
   DeepSeek** (`deepseek/deepseek-coder` e `deepseek/deepseek-r1:free`, sugeridos pelo usuário,
   não existem mais). Os DeepSeek atuais (`deepseek/deepseek-v4.1-flash`, `...chat-v3.1`,
   `...r1`) são pagos.
2. ✅ **Modelo escolhido por teste, não por folheto.** Três perguntas de lógica de CSS, com
   resposta verificável, foram enviadas aos candidatos gratuitos. A pergunta decisiva: um
   ancestral com `transform` vira referência de `position: fixed`? Resultado:
   `poolside/laguna-s-2.1`, `cohere/north-mini-code`, `nvidia/nemotron-3.5-lightning` e
   `nvidia/nemotron-3-nano-omni` **erraram** (responderam "colado na janela", com confiança);
   `nvidia/nemotron-3-super-120b-a12b:free` **acertou** em 27 s e
   `xingchen-agi/xing4.0-29b-a4b` acertou, mas levou **266 s** (estouraria o tempo limite de
   240 s da Mesa). `google/gemma-4-31b-it:free` respondeu HTTP 429 e
   `thinkingmachines/inkling:free` respondeu HTTP 403 (só para "agentic harnesses").
   **Decisão**: padrão `nvidia/nemotron-3-super-120b-a12b:free`.
3. ✅ **Provedor `coder`** em `server.py`: entra em `PROVIDERS` ("Especialista em Código") e em
   `DIRECT_API_PROVIDERS`; `provider_status()` o reporta como pronto quando existe
   `OPENROUTER_API_KEY` (mesma chave do OpenRouter) e devolve `detail` com o nome curto do
   modelo. `run_openrouter()` ganhou o parâmetro `model` (o roteador `openrouter/free` continua
   igual); `run_provider("coder")` chama o modelo fixo.
4. ✅ **Prompt de especialista**: `build_prompt()` acrescenta um bloco só para o `coder` — ler o
   código pela lógica (ordem de aplicação, especificidade, precedência, fluxo, estado em
   execução), mostrar o trecho exato e o efeito real, entregar a correção pronta e não inventar
   problema. Quando ele participou, a síntese recebe o aviso para tratar os trechos de código
   dele como a referência de código.
5. ✅ **Nome honesto na barra lateral**: o texto de detalhe vem do **servidor**
   (`provider.detail`, com o `app.js` aceitando-o antes do mapa fixo), então trocar o modelo por
   `MESA_CODE_MODEL` muda o que aparece na tela — e modelo pago aparece como `· pago`.
6. ✅ **Uma IA só (o que o usuário pediu: "marcar só ele")**: a Mesa exigia duas IAs. Agora
   `len(selected) < 1` é o único bloqueio, e a rodada com **um contribuinte** pula revisão e
   síntese — a resposta já é a final. Isso economiza duas chamadas por rodada (importante no
   limite de 50/dia do OpenRouter) e o cartão diz **RESPOSTA DIRETA** em vez de
   "RESPOSTA CONSOLIDADA". Com duas ou mais, nada mudou.
7. ✅ **Limites honestos**: `MAX_NOTE_CHARS`, histórico e exportação valem igual para o novo
   provedor; o item divide a chave e o limite diário do OpenRouter.

Testado com 52 verificações automáticas (`teste_especialista.py`, IAs falsas, porta 8897,
nenhuma cota gasta) — barra lateral, modelo configurado e trocável, roteamento para o modelo
certo, prompt de especialista (e ausência dele nos outros), rodada com uma IA só (uma única
chamada, sem síntese, cartão com a resposta integral), rodadas com duas IAs sem regressão e os
arquivos da tela — mais o navegador (item na barra lateral com símbolo `{}` e detalhe do modelo,
só ele marcado → "RESPOSTA DIRETA · Especialista em Código" com o texto inteiro e o cronômetro,
depois com Gemini → "RESPOSTA CONSOLIDADA" e "Ver as 2 respostas lado a lado", console sem erro).

## Decisões técnicas

- **Gemini**: API do Google AI Studio, chave `GEMINI_API_KEY` no `.env`.
  O modelo `gemini-2.5-flash` previsto no plano original foi **recusado pela própria API**
  ("no longer available to new users"). O padrão passou a ser `gemini-3.8-flash`, trocável
  pela variável `MESA_GEMINI_MODEL`.
- **Ollama**: HTTP em `http://127.0.0.1:11434` (variável `MESA_OLLAMA_BASE`), modelo
  `qwen3.5:4b` (variável `MESA_OLLAMA_MODEL`). Envia `think: false` e `keep_alive: 30m`, e o
  modelo é pré-carregado no arranque (`warm_ollama`) para evitar a partida fria.
- **Pausar um provedor**: adicionar o id em `PAUSED_PROVIDERS` (`server.py`) **e** em
  `pausedProviderIds` (`static/app.js`). Hoje as duas listas estão vazias.
- **Ordem da barra lateral**: `mesaPrincipalIds` em `static/app.js` define quem entra em
  "Sua mesa"; todo o resto vai para "Outros detectados".
- **Acessibilidade**: `prefers-reduced-motion` desliga as animações de entrada.
- **Animação sem lag**: apenas `transform`/`opacity`, `animation-fill-mode: backwards` (para
  não sequestrar o `:hover`) e a entrada escalonada roda só na primeira pintura.
- **Memória de falhas**: vive só na memória do servidor (`provider_last_error`), some ao
  reiniciar. É de propósito: não grava credenciais nem histórico de erros em disco.
- **Histórico**: um único `historico.json` na raiz do projeto, no formato
  `{"version": 1, "conversations": [...]}`, mais recente primeiro. O frontend é quem monta a
  conversa (o servidor não sabe o que é um "turno"); o servidor só valida, corta tamanhos
  (`_clean_history_entry()`) e grava. Apagar só acontece por ação explícita (`DELETE`).
- **Busca**: feita no servidor, não na tela, porque só o `historico.json` tem o texto inteiro
  das conversas (a lista da barra lateral guarda apenas títulos e contagens). A dobra de
  acentos é **caractere por caractere** de propósito: preserva os índices, o que permite
  recortar o trecho exato onde a palavra foi encontrada.
- **Exportação**: montada no servidor, e não no navegador, para o mesmo link servir de download
  sem a Mesa estar aberta. O Markdown é o formato canônico; o HTML sai em tom claro de papel,
  mesmo com o app escuro, porque é o que funciona ao imprimir e ao enviar. O CSS do HTML é uma
  versão reduzida do tema, embutida no próprio arquivo.
- **Teste das IAs**: roda como tarefa própria (`checks`, o mesmo desenho de "job" da conversa),
  com prazo de `TEST_TIMEOUT_SECONDS` (60 s) para o conjunto. Quem não voltar dentro do prazo
  aparece como "demorou demais" — e, se responder depois, o próprio worker corrige a linha do
  painel. O teste escreve na mesma `provider_last_error` da rodada: é o que faz a lista de IAs
  ficar com a etiqueta certa.
- **Onde o resultado do teste aparece**: num cartão da conversa, não na barra lateral. A barra
  tem três blocos (lista de IAs, painel, histórico) e, com a lista dentro dela, a lista de IAs
  ficava com menos de 120 px de altura. O resultado é temporário: não vai para o histórico.
- **Cronômetros**: `provider_seconds` guarda o tempo da **rodada inicial** (é o número que
  interessa para confiar numa IA) e `synth_seconds`, o da síntese. O tempo da revisão cruzada
  aparece no texto do cartão de progresso, mas não substitui o da resposta.
- **Um teto só para o texto**: `MAX_NOTE_CHARS` (20.000) vale para a contribuição na tela **e**
  no histórico. Teto diferente em cada lado faria a conversa reaberta mostrar menos do que foi
  visto ao vivo — o que qualquer pessoa leria como defeito.
- **`text` no lugar de `summary`**: o texto das contribuições sempre foi a resposta inteira da
  IA (nunca um resumo). `note_text()` centraliza a leitura e aceita o nome antigo, então nada
  precisa ser migrado no `historico.json`; a primeira gravação de cada conversa já sai no
  formato novo.
- **Lado a lado sem rolagem interna**: as colunas crescem junto com a página (sem `overflow`
  próprio) — quem rola é a conversa, que já tem o controle da rodada 3. Colunas com rolagem
  própria disputariam o gesto de rolar no trackpad.
- **A A1 não mexeu na síntese**: o `synth_prompt` continua pedindo uma resposta só, sem repetir
  as contribuições uma por uma. Quem quer comparar e ouvir cada voz usa o painel novo; a A2
  (síntese estruturada, com concordâncias, divergências e quem sustenta cada ponto) fica para
  depois, quando houver mais de duas IAs respondendo.
- **Especialista em Código = modelo fixo, não o roteador**: o `openrouter` continua usando
  `openrouter/free` (que sorteia um modelo gratuito a cada chamada). O `coder` aponta para um
  modelo escolhido (`MESA_CODE_MODEL`), porque um revisor de código precisa ser o **mesmo** toda
  vez — com o roteador, uma revisão boa e outra ruim não teriam de onde vir. Os dois dividem a
  mesma chave e o mesmo limite diário.
- **Modelo por variável de ambiente, nome na tela**: `code_model_detail()` deriva o nome curto do
  próprio id do modelo (`MODEL_SHORT_NAMES` cobre os conhecidos) e marca `· grátis` ou `· pago`.
  O `app.js` prefere `provider.detail` ao mapa fixo, então trocar `MESA_CODE_MODEL` muda o que
  aparece na barra lateral — sem editar a interface, sem prometer o que não é.
- **Uma contribuição não se sintetiza**: com um único contribuinte, revisão cruzada e síntese
  seriam chamadas pagas para reescrever o mesmo texto. `orchestrate()` entrega a resposta como
  ela veio (`publish_end()`, o mesmo desfecho da síntese) e o rótulo do cartão passa a
  **RESPOSTA DIRETA**. Isso também vale quando várias IAs são marcadas e só uma responde — quem
  falhou continua listado no rodapé, e a pessoa sai com a resposta em vez de um erro.
- **Especialista é prompt, não só modelo**: o bloco de `build_prompt()` para o `coder` vale para
  qualquer modelo configurado em `MESA_CODE_MODEL`, para a especialidade não depender da sorte de
  qual modelo está na moda naquele mês.

## Progresso (git)

- `59f4cab` — itens 1 e 2 (barra lateral organizada + Gemini/Ollama por HTTP)
- `ce377ca` — item 3 (animações suaves)
- itens 4 e 5 (visual aconchegante + provedores reativados) — `git log --oneline` mostra o hash
- rodada 2 (rapidez + histórico) — `git log --oneline` mostra o hash
- rodada 3 (rolagem) — `4df6333` no projeto e `dd9e27b` no espelho
- rodada 4 (busca no histórico + exportar em `.md`/`.html`) — `git log --oneline` mostra o hash
- rodada 5 (testar as IAs + cronômetros) — `git log --oneline` mostra o hash
- rodada 6 (respostas completas lado a lado) — `git log --oneline` mostra o hash
- rodada 7 (Especialista em Código + rodada com uma IA só) — `git log --oneline` mostra o hash

Cada pasta tem o próprio repositório Git: a pasta de trabalho (esta) e o espelho em
`C:\Users\aceli\OneDrive\Documentos\Projeto Padrão`. As duas ficam com o mesmo conteúdo.

## Arquivos importantes

- `server.py` — lógica do servidor e orquestração das IAs
- `static/app.js` — interface e requisições do frontend
- `static/index.html` — estrutura da página
- `static/style.css` — estilos e animações
- `README.md` — documentação

## Pendências pequenas

- Qwen Code precisa de login: abra o Qwen Code e rode `/auth`.
- O Ollama precisa do aplicativo aberto; com ele fechado a Mesa mostra "Ollama fechado"
  (e, com ele aberto mas sem o modelo, "modelo ausente").
- **Reiniciar o servidor Python** para valer o que mudou em `server.py` (memória de falhas e
  rotas do histórico). Alterações em `static/` aparecem só recarregando a página (Ctrl+F5).
- A memória de falhas começa vazia a cada arranque: a primeira pergunta depois de reiniciar
  ainda pode chamar um CLI quebrado (e então ele fica etiquetado e fora da seleção).
- Os arquivos exportados caem na pasta de downloads do navegador, com o nome
  `mesa-<assunto>.<md|html>`; nenhum arquivo é criado na pasta do projeto.
- O tempo de cada IA **não** vai para o histórico: abrir uma conversa antiga não mostra o
  rodapé de confiança (os cronômetros valem para a rodada que acabou de acontecer).
- O resultado do teste também é temporário: fecha com `×`, "Nova conversa" ou recarregando a
  página. Quem guarda a informação para valer são as etiquetas na lista de IAs.
- As respostas completas viajam inteiras até 20.000 caracteres por IA (`MAX_NOTE_CHARS`). Acima
  disso — o que não é uma resposta normal — o fim é cortado, para o arquivo e a tela não
  sofrerem. O número está num lugar só, então mudar o teto é mexer numa linha.
- **Modelos gratuitos são instáveis**: na escolha do Especialista em Código, dois candidatos
  responderam HTTP 429 e um respondeu HTTP 403. Quando ele falhar, a etiqueta âmbar aparece na
  lista com o motivo ("limite atingido") e ele sai da seleção padrão da rodada seguinte — tentar
  de novo mais tarde costuma bastar. Se incomodar, trocar `MESA_CODE_MODEL` é uma linha.
- **DeepSeek hoje é pago no OpenRouter** (as versões gratuitas não existem mais). Para usar
  DeepSeek de verdade: colocar créditos na conta do OpenRouter e definir
  `MESA_CODE_MODEL=deepseek/deepseek-v4.1-flash` (a barra lateral passa a mostrar `· pago`).

## Retomar as IAs (3 passos, quando você quiser)

1. **Logins dos CLIs**: no terminal, `claude` → `/login` e `cursor-agent login`.
2. **Ollama**: abrir o aplicativo (ele responde por HTTP em `http://127.0.0.1:11434`).
3. **Conferir**: clicar em "Testar minhas IAs" e ler o cartão. O Codex está com limite até
   **11/11/2026 16:56** (não adianta tentar antes disso) e o Qwen Code pede `/auth` dentro dele.

Enquanto isso, a Mesa conversa com três nomes — **Gemini**, **OpenRouter** e **Especialista em
Código** (os dois últimos dividem a chave e o limite diário do OpenRouter). O app funciona de
ponta a ponta; a "sala de debate" (Opção A2) passa a valer de verdade com três ou mais vozes
independentes respondendo.

## Fecho da sessão (17/10/2026)

**Pronto e testado**: itens 1–5 do HANDOFF e as rodadas 2 a 7 — barra lateral organizada,
Gemini/Ollama por HTTP, animações, visual aconchegante, provedores reativados, rapidez +
histórico, rolagem, buscar/exportar (Opção C), testar as IAs + cronômetros (Opção B), as
respostas completas lado a lado (Opção A1), o **Especialista em Código** e a rodada com uma IA
só. A Mesa é usável de ponta a ponta hoje.

**O que falta, em ordem de valor:**

1. **Recuperar as IAs** (hoje respondem Gemini, OpenRouter e o Especialista em Código — mas os
   dois últimos dividem a mesma chave): os 3 passos da seção acima.
2. **Decidir sobre o modelo do Especialista em Código**: ele hoje usa um gratuito
   (`nvidia/nemotron-3-super-120b-a12b:free`), sujeito a instabilidade e ao limite diário da
   chave do OpenRouter. Se o DeepSeek de verdade for desejado (pago, fração de centavo por
   resposta), basta definir `MESA_CODE_MODEL`.
3. **Opção A2 — sala de debate de verdade**: com 3+ IAs respondendo, a resposta final ganha
   blocos fixos — onde concordam, onde divergem, o que só uma trouxe e quem sustenta cada ponto.
   Depende de o modelo obedecer ao formato, por isso ficou para depois de usar o app alguns dias.
4. **Opção D — provedor compatível com OpenAI**: o `.env` tem 5 chaves que nenhuma linha do
   projeto lê (`OMNIROUTE_API_KEY`, `ZEN_API_KEY`, `ZEN_BASE_URL`, `ZEN_MODEL=deep.free`,
   `PLANNER_PROVIDER`). Uma opção é dar à Mesa um provedor genérico "compatível com OpenAI"
   (`base_url` + chave + modelo), o que destravaria qualquer serviço novo sem mexer no código.

**Como retomar**: comece a conversa entregando este arquivo. Ele conta o estado, as decisões e as
armadilhas conhecidas — em especial: `server.py` só vale depois de **reiniciar o servidor**;
`static/` aparece com **Ctrl+F5**; conversas no formato antigo continuam abrindo; e as duas
pastas (esta e o espelho) andam juntas, sempre com o mesmo conteúdo.

