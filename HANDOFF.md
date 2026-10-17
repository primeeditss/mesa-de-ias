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

## Progresso (git)

- `59f4cab` — itens 1 e 2 (barra lateral organizada + Gemini/Ollama por HTTP)
- `ce377ca` — item 3 (animações suaves)
- itens 4 e 5 (visual aconchegante + provedores reativados) — `git log --oneline` mostra o hash
- rodada 2 (rapidez + histórico) — `git log --oneline` mostra o hash

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
