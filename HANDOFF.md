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

## O que precisa ser feito

1. ✅ Colocar os provedores numa barra lateral organizada
2. ✅ Chamar Gemini e Ollama por API HTTP, não por terminal (lentidão resolvida)
3. ✅ Adicionar animações suaves sem causar lag
4. ✅ Manter o visual aconchegante
5. ✅ Reativar Claude Code e OpenCode

Todos os itens originais estão concluídos. As pendências restantes estão no fim do arquivo.

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

## Progresso (git)

- `59f4cab` — itens 1 e 2 (barra lateral organizada + Gemini/Ollama por HTTP)
- `ce377ca` — item 3 (animações suaves)
- itens 4 e 5 (visual aconchegante + provedores reativados) — `git log --oneline` mostra o hash

Repositório: `C:\Users\aceli\OneDrive\Documentos\Projeto Padrão`.
A pasta de trabalho (`...\re\outputs\mesa-ias`) é uma cópia idêntica, sem Git próprio.

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
- Para o item 5 valer, o servidor Python precisa ser reiniciado (mudanças em `server.py`).
  Alterações em `static/` aparecem só recarregando a página.
