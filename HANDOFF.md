\# HANDOFF — Mesa de IAs



\## O que é este projeto

Uma "Mesa de IAs" — interface web onde várias IAs (Codex, OpenCode, Gemini, OpenRouter, Ollama) respondem em paralelo a uma mesma pergunta, e uma IA "juíza" sintetiza a resposta final.



\## Stack

\- Backend: Python (`server.py`) — servidor HTTP local

\- Frontend: HTML/CSS/JS em `static/`

\- Porta: `http://127.0.0.1:8765`



\## Estado atual

\- ✅ Interface visual aconchegante (arte vetorial original)

\- ✅ Provedores rodando via CLI (lento)

\- ⚠️ Gemini e Ollama chamados via terminal — causa lentidão

\- ⚠️ Claude Code e OpenCode foram desativados na interface (sem créditos)

\- ⚠️ Refatoração em andamento para chamar Gemini e Ollama via API HTTP direta



\## O que precisa ser feito

1\. Colocar os provedores numa \*\*barra lateral organizada\*\*

2\. Fazer o \*\*Gemini\*\* e o \*\*Ollama\*\* serem chamados diretamente por \*\*API HTTP\*\*, não por terminal (resolver lentidão)

3\. Adicionar \*\*animações suaves\*\* sem causar lag

4\. Manter o visual aconchegante

5\. Reativar Claude Code e OpenCode quando possível



\## Decisões técnicas já tomadas

\- O Gemini deve usar a API do Google AI Studio com modelo `gemini-2.5-flash`

\- O Ollama deve usar HTTP em `http://127.0.0.1:11434` com modelo `qwen3.5:4b`

\- A variável de ambiente do Gemini é `GEMINI\_API\_KEY` no `.env`

\- Respeitar `prefers-reduced-motion` (acessibilidade)



\## Arquivos importantes

\- `server.py` — lógica do servidor e orquestração das IAs

\- `static/app.js` — interface e requisições do frontend

\- `static/index.html` — estrutura da página

\- `static/style.css` — estilos e animações

\- `README.md` — documentação



\## Próximos passos sugeridos

1\. Ler `server.py` e identificar onde Gemini/Ollama são chamados via CLI

2\. Trocar essas chamadas para HTTP (usar `requests` ou `httpx`)

3\. Reestruturar `index.html` para incluir sidebar

4\. Atualizar `app.js` e `style.css` conforme novo layout

5\. Testar em `http://127.0.0.1:8765`

