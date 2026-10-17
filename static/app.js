const providerNames = {claude: "Claude Code", codex: "Codex", opencode: "OpenCode", gemini: "Gemini", openrouter: "OpenRouter", coder: "Especialista em Código", cursor: "Cursor Agent", qwen: "Qwen Code", ollama: "Ollama local"};
const providerDetails = {openrouter: "Modelos grátis", coder: "Código · grátis", ollama: "Qwen 3.5 · 4B"};
const providerMarks = {claude: "C", codex: "O", opencode: "⌘", gemini: "G", openrouter: "R", coder: "{}", cursor: "↗", qwen: "Q", ollama: "◉"};
// Espelha o PAUSED_PROVIDERS do servidor: vazio = todos os detectados liberados.
const pausedProviderIds = new Set();
// Ordem da barra lateral: primeiro a mesa principal do usuário, depois o resto.
const mesaPrincipalIds = ["codex", "opencode", "gemini", "openrouter", "coder", "ollama", "claude"];
// Perguntas curtas não ganham nada com a rodada de revisão cruzada: até este
// tamanho a Mesa escolhe o modo Rápido sozinha (o seletor mostra a escolha).
const MODO_RAPIDO_ATE = 120;
let modePinned = false;
const state = {
  providers: [],
  selected: new Set(),
  history: [],
  turns: [],
  conversationId: null,
  conversations: [],
  historyTotal: 0,
  search: "",
  health: {id: null, status: "idle", providers: [], results: {}, error: "", open: false},
  busy: false,
  providersRendered: false,
};

let searchTimer = 0;
let exportMenuId = null;
// Opção A1: como as contribuições aparecem quando abertas — "side" (lado a lado,
// o padrão) ou "stacked" (uma após a outra). A escolha vale para toda a sessão.
let contributionsView = "side";
let contributionSeq = 0;

const providerList = document.querySelector("#providerList");
const synthesizer = document.querySelector("#synthesizer");
const selectionCount = document.querySelector("#selectionCount");
const conversation = document.querySelector("#conversation");
const welcome = document.querySelector("#welcome");
const messages = document.querySelector("#messages");
const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const sendButton = document.querySelector("#sendButton");
const modeSelect = document.querySelector("#mode");
const modeNote = document.querySelector("#modeNote");
const heroRosterText = document.querySelector("#heroRosterText");
const historyBox = document.querySelector("#historyBox");
const historyList = document.querySelector("#historyList");
const historyCount = document.querySelector("#historyCount");
const historySearch = document.querySelector("#historySearch");
const historySearchClear = document.querySelector("#historySearchClear");
const healthPanel = document.querySelector("#healthPanel");
const healthRun = document.querySelector("#healthRun");
const healthRunTitle = document.querySelector("#healthRunTitle");
const healthRunNote = document.querySelector("#healthRunNote");
function providerStateKind(provider) {
  if (/pausad/i.test(provider.state || "")) return "paused";
  if (!provider.installed) return "missing";
  // "Instalado" não quer dizer "funcionando": se a última rodada falhou por
  // falta de login ou de saldo, a linha mostra isso e sai da seleção padrão.
  return provider.last_error ? "failed" : "ready";
}

function buildProviderRow(provider, index, animate) {
  const kind = providerStateKind(provider);
  const row = document.createElement("label");
  row.className = `provider-option is-${kind}`;
  if (animate) {
    // A entrada escalonada roda só na primeira pintura da lista.
    row.classList.add("row-enter");
    row.style.setProperty("--row-index", index);
  }
  row.dataset.id = provider.id;
  if (provider.installed && state.selected.has(provider.id)) row.classList.add("is-selected");

  const check = document.createElement("input");
  check.type = "checkbox";
  check.value = provider.id;
  check.checked = state.selected.has(provider.id);
  check.disabled = !provider.installed;
  check.addEventListener("change", () => {
    if (check.checked) state.selected.add(provider.id);
    else state.selected.delete(provider.id);
    // Uma IA já basta para conversar (é o caso de marcar só o Especialista em
    // Código). Se nada ficar marcado, a hora de enviar avisa.
    renderProviders();
  });

  const mark = document.createElement("span");
  mark.className = "provider-icon";
  mark.textContent = providerMarks[provider.id] || "AI";

  const copy = document.createElement("span");
  copy.className = "provider-copy";
  const name = document.createElement("span");
  name.className = "provider-name";
  name.textContent = providerNames[provider.id] || provider.label;
  const meta = document.createElement("span");
  meta.className = "provider-meta";
  // O servidor manda o "detail" quando o modelo pode ser trocado por variável de
  // ambiente (hoje, o Especialista em Código): assim a barra lateral nunca mente
  // sobre qual modelo está respondendo.
  const detailText = provider.detail || providerDetails[provider.id];
  if (detailText) {
    const detail = document.createElement("small");
    detail.className = "provider-detail";
    detail.textContent = detailText;
    // A barra lateral é estreita e corta o texto com reticências: o nome completo
    // do modelo fica no tooltip (e o tooltip não atrapalha quem só passa o olho).
    detail.title = detailText;
    meta.append(detail);
  }
  const status = document.createElement("span");
  status.className = "provider-status";
  const dot = document.createElement("i");
  dot.className = "provider-dot";
  const stateText = document.createElement("span");
  stateText.className = "provider-state";
  stateText.textContent = provider.state || (provider.installed ? "disponível" : "não detectada");
  status.append(dot, stateText);
  meta.append(status);
  copy.append(name, meta);

  row.title = provider.reason || "";
  row.append(check, mark, copy);
  return row;
}

function buildProviderGroup(group, members, startIndex, animate) {
  const section = document.createElement("section");
  section.className = "provider-group";
  section.dataset.group = group.id;
  const head = document.createElement("div");
  head.className = "provider-group-head";
  const title = document.createElement("span");
  title.className = "provider-group-title";
  title.textContent = group.title;
  head.append(title);
  if (group.hint) {
    const hint = document.createElement("span");
    hint.className = "provider-group-hint";
    hint.textContent = group.hint;
    head.append(hint);
  }
  const items = document.createElement("div");
  items.className = "provider-group-items";
  members.forEach((provider, offset) => items.append(buildProviderRow(provider, startIndex + offset, animate)));
  section.append(head, items);
  return section;
}

function renderProviders() {
  const previousSynth = synthesizer.value;
  providerList.innerHTML = "";
  synthesizer.innerHTML = "";
  const byId = new Map(state.providers.map(provider => [provider.id, provider]));
  const main = mesaPrincipalIds.map(id => byId.get(id)).filter(Boolean);
  const placed = new Set(main.map(provider => provider.id));
  const others = state.providers.filter(provider => !placed.has(provider.id));
  // A entrada escalonada só acontece na primeira pintura; depois disso a lista
  // atualiza sem re-animar (evita a sensação de lag ao marcar/desmarcar).
  const animate = !state.providersRendered;
  state.providersRendered = true;
  if (main.length) {
    const ready = main.filter(provider => provider.installed).length;
    providerList.append(buildProviderGroup(
      {id: "mesa", title: "Sua mesa", hint: `${ready}/${main.length} prontas`},
      main,
      0,
      animate,
    ));
  }
  if (others.length) {
    providerList.append(buildProviderGroup(
      {id: "others", title: "Outros detectados", hint: others.length === 1 ? "1 provedor" : `${others.length} provedores`},
      others,
      main.length,
      animate,
    ));
  }
  for (const provider of state.providers) {
    if (!provider.installed) continue;
    const option = document.createElement("option");
    option.value = provider.id;
    option.textContent = providerNames[provider.id] || provider.label;
    synthesizer.append(option);
  }
  const selectedAvailable = [...state.selected].filter(id => state.providers.some(p => p.id === id && p.installed));
  selectionCount.textContent = `${selectedAvailable.length} ${selectedAvailable.length === 1 ? "IA selecionada" : "IAs selecionadas"}`;
  const detectedCount = state.providers.filter(provider => provider.installed).length;
  if (heroRosterText) {
    heroRosterText.textContent = detectedCount
      ? `${selectedAvailable.length} de ${detectedCount} IAs na mesa`
      : "Conecte pelo menos uma IA para começar";
  }
  updateModeNote();
  if (previousSynth && selectedAvailable.includes(previousSynth)) synthesizer.value = previousSynth;
  else if (selectedAvailable.includes("codex")) synthesizer.value = "codex";
  else if (selectedAvailable.length) synthesizer.value = selectedAvailable[0];
}

function addUserMessage(text) {
  const bubble = document.createElement("div");
  bubble.className = "message user-message";
  bubble.textContent = text;
  messages.append(bubble);
}

function addStatus(text, detail = "", progress = {}, output = {}, started = Date.now() / 1000, mode = "complete") {
  const card = document.createElement("div");
  card.className = "message status-card";
  card.id = "activeStatus";
  const spinner = document.createElement("span");
  spinner.className = "status-orbit";
  spinner.textContent = "✳";
  const copy = document.createElement("div");
  copy.className = "status-copy";
  const header = document.createElement("div");
  header.className = "status-header";
  const heading = document.createElement("div");
  heading.className = "status-heading";
  const title = document.createElement("span");
  title.className = "status-title";
  title.textContent = text;
  title.dataset.role = "title";
  heading.append(title);
  const sub = document.createElement("small");
  sub.className = "status-detail";
  sub.dataset.role = "detail";
  heading.append(sub);
  const elapsed = document.createElement("span");
  elapsed.className = "status-elapsed";
  elapsed.dataset.role = "elapsed";
  header.append(heading, elapsed);
  copy.append(header);
  const steps = document.createElement("div");
  steps.className = "status-steps";
  steps.dataset.role = "steps";
  copy.append(steps);
  const agents = document.createElement("div");
  agents.className = "status-agents";
  agents.dataset.role = "agents";
  copy.append(agents);
  card.append(spinner, copy);
  messages.append(card);
  updateStatusCard(card, text, detail, progress, output, started, mode);
  conversation.scrollTop = conversation.scrollHeight;
}

function updateStatusCard(card, text, detail, progress, output = {}, started = Date.now() / 1000, mode = "complete") {
  card.querySelector('[data-role="title"]').textContent = text;
  card.querySelector('[data-role="detail"]').textContent = detail;
  const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - Number(started || Date.now() / 1000)));
  card.querySelector('[data-role="elapsed"]').textContent = elapsed < 60
    ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${String(elapsed % 60).padStart(2, "0")}s`;
  const stage = /revisão/i.test(text) ? 1 : /preparando|síntese/i.test(text) ? 2 : 0;
  const stepList = mode === "fast"
    ? ["Respostas independentes", "Síntese final"]
    : ["Respostas independentes", "Revisão cruzada", "Síntese final"];
  const activeStep = mode === "fast" && stage === 2 ? 1 : Math.min(stage, stepList.length - 1);
  const steps = card.querySelector('[data-role="steps"]');
  const stepKey = `${mode}:${activeStep}`;
  if (steps.dataset.stepKey !== stepKey) {
    steps.dataset.stepKey = stepKey;
    steps.replaceChildren();
    stepList.forEach((label, index) => {
      const step = document.createElement("span");
      step.className = `status-step${index < activeStep ? " is-complete" : index === activeStep ? " is-active" : ""}`;
      const marker = document.createElement("i");
      marker.textContent = index < activeStep ? "✓" : String(index + 1).padStart(2, "0");
      const name = document.createElement("b");
      name.textContent = label;
      step.append(marker, name);
      steps.append(step);
    });
  }
  const agents = card.querySelector('[data-role="agents"]');
  const entries = Object.entries(progress || {});
  const key = `${JSON.stringify(entries)}:${JSON.stringify(output || {})}`;
  if (agents.dataset.progressKey === key) return;
  agents.dataset.progressKey = key;
  agents.replaceChildren();
  for (const [id, value] of entries) {
    const row = document.createElement("div");
    row.className = "status-agent";
    const name = document.createElement("span");
    name.className = "status-agent-name";
    name.textContent = providerNames[id] || id;
    const status = document.createElement("span");
    status.className = "status-agent-state";
    status.textContent = value;
    if (/concluída|pronta|pronto/i.test(value)) row.classList.add("is-done");
    if (/não respondeu|falhou/i.test(value)) row.classList.add("is-error");
    const top = document.createElement("div");
    top.className = "status-agent-top";
    top.append(name, status);
    const preview = document.createElement("div");
    preview.className = "status-agent-preview";
    const previewLabel = document.createElement("span");
    previewLabel.className = "status-agent-preview-label";
    previewLabel.textContent = "PRÉVIA DA RESPOSTA";
    const previewText = document.createElement("span");
    previewText.className = "status-agent-preview-text";
    const content = String(output?.[id] || "").trim();
    previewText.textContent = content
      ? (content.length > 420 ? `…${content.slice(-420)}` : content)
      : "Aguardando a primeira parte da resposta…";
    if (content) preview.classList.add("has-output");
    preview.append(previewLabel, previewText);
    row.append(top, preview);
    agents.append(row);
  }
}

function setStatus(text, detail = "", progress = {}, output = {}, started = Date.now() / 1000, mode = "complete") {
  let card = document.querySelector("#activeStatus");
  if (!card) {
    addStatus(text, detail, progress, output, started, mode);
    return;
  }
  const followOutput = conversation.scrollHeight - conversation.scrollTop - conversation.clientHeight < 110;
  updateStatusCard(card, text, detail, progress, output, started, mode);
  if (followOutput) conversation.scrollTop = conversation.scrollHeight;
}

function addAnswer(text, provider, notes = [], trust = null) {
  document.querySelector("#activeStatus")?.remove();
  const card = document.createElement("article");
  card.className = "message answer-card";
  const heading = document.createElement("div");
  heading.className = "answer-heading";
  const mark = document.createElement("span");
  mark.className = "brand-mark";
  mark.textContent = "✳";
  const label = document.createElement("span");
  // Sem rodada de síntese (rodada com uma IA só) o cartão não é "consolidado":
  // é a resposta dela, entregue direto. O rótulo não promete mais do que a Mesa fez.
  const direta = Boolean(trust) && !trust.synthSeconds;
  const synthesisTime = trust && trust.synthSeconds ? ` · ${formatSeconds(trust.synthSeconds)}` : "";
  label.textContent = `${direta ? "RESPOSTA DIRETA" : "RESPOSTA CONSOLIDADA"} · ${providerNames[provider] || provider}${synthesisTime}`;
  heading.append(mark, label);
  const body = document.createElement("div");
  body.className = "answer-text";
  renderMarkdown(body, text);
  card.append(heading, body);
  if (notes.length) addContributions(card, notes);
  renderTrust(card, trust);
  messages.append(card);
  conversation.scrollTop = conversation.scrollHeight;
}

// Opção A1 · As respostas completas de cada IA, para comparar.
// O botão abre um painel com as contribuições lado a lado (padrão) ou uma após a
// outra. Abrir e fechar não gasta cota: o texto já veio junto com a resposta final.
function addContributions(card, notes) {
  const many = notes.length > 1;
  const panelId = `contributions-${++contributionSeq}`;

  const box = document.createElement("section");
  box.className = "contributions";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "contributions-toggle";
  toggle.setAttribute("aria-expanded", "false");
  toggle.setAttribute("aria-controls", panelId);

  const panel = document.createElement("div");
  panel.className = "contributions-panel";
  panel.id = panelId;
  panel.hidden = true;

  const head = document.createElement("div");
  head.className = "contributions-head";
  const title = document.createElement("span");
  title.className = "contributions-title";
  title.textContent = many ? `Respostas completas das ${notes.length} IAs` : "Resposta completa da IA";
  head.append(title);

  const modeButtons = [];
  if (many) {
    const views = document.createElement("div");
    views.className = "contributions-views";
    views.setAttribute("role", "group");
    views.setAttribute("aria-label", "Como mostrar as respostas");
    for (const [modo, texto] of [["side", "▥ Lado a lado"], ["stacked", "☰ Uma após a outra"]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "contributions-view";
      button.dataset.view = modo;
      button.textContent = texto;
      button.addEventListener("click", () => { contributionsView = modo; applyView(); });
      modeButtons.push(button);
      views.append(button);
    }
    head.append(views);
  }

  const close = document.createElement("button");
  close.type = "button";
  close.className = "contributions-close";
  close.setAttribute("aria-label", "Fechar as respostas");
  close.textContent = "×";
  close.addEventListener("click", () => {
    panel.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
    toggle.focus();
  });
  head.append(close);

  const list = document.createElement("div");
  list.className = "contribution-list";
  for (const note of notes) {
    const contribution = document.createElement("section");
    contribution.className = "contribution-item";
    const name = document.createElement("h3");
    name.textContent = note.provider || "IA participante";
    const content = document.createElement("div");
    content.className = "answer-text";
    // "text" é o nome atual; "summary" era o nome antigo (e vinha cortado em 1.400).
    renderMarkdown(content, note.text || note.summary || "");
    contribution.append(name, content);
    list.append(contribution);
  }

  function applyView() {
    if (!many) {
      list.dataset.view = "stacked";
      toggle.textContent = "▥ Ver a resposta completa desta IA";
      return;
    }
    list.dataset.view = contributionsView;
    for (const button of modeButtons) {
      button.setAttribute("aria-pressed", String(button.dataset.view === contributionsView));
    }
    toggle.textContent = contributionsView === "side"
      ? `▥ Ver as ${notes.length} respostas lado a lado`
      : `☰ Ver as ${notes.length} respostas de cada IA`;
  }

  toggle.addEventListener("click", () => {
    const abrindo = panel.hidden;
    panel.hidden = !abrindo;
    toggle.setAttribute("aria-expanded", String(abrindo));
    if (!abrindo) return;
    // Se o painel nasceu abaixo da área visível, sobe até ele (sem arrastar quem
    // está lendo uma conversa antiga lá em cima).
    const area = conversation.getBoundingClientRect();
    const topo = panel.getBoundingClientRect().top;
    if (topo > area.bottom - 60) conversation.scrollTop += topo - area.top - 14;
  });

  applyView();
  panel.append(head, list);
  box.append(toggle, panel);
  card.append(box);
}

// Render the models' Markdown with DOM nodes so their output can never inject HTML.
function renderMarkdown(target, source) {
  const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
  let paragraph = [];
  let list = null;
  const closeList = () => { list = null; };
  const flushParagraph = () => {
    if (!paragraph.length) return;
    const p = document.createElement("p");
    appendInline(p, paragraph.join(" "));
    target.append(p);
    paragraph = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      flushParagraph(); closeList();
      const codeLines = [];
      while (++i < lines.length && !lines[i].trim().startsWith("```")) codeLines.push(lines[i]);
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = codeLines.join("\n");
      pre.append(code); target.append(pre);
      continue;
    }
    const heading = line.match(/^\s{0,3}(#{1,3})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      flushParagraph(); closeList();
      const h = document.createElement(`h${heading[1].length + 1}`);
      appendInline(h, heading[2]); target.append(h); continue;
    }
    const item = line.match(/^\s*(?:[-*+]\s+|(\d+)[.)]\s+)(.*)$/);
    if (item) {
      flushParagraph();
      const type = item[1] ? "ol" : "ul";
      if (!list || list.tagName.toLowerCase() !== type) {
        closeList(); list = document.createElement(type); target.append(list);
      }
      const li = document.createElement("li"); appendInline(li, item[2]); list.append(li); continue;
    }
    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      flushParagraph(); closeList();
      const blockquote = document.createElement("blockquote"); appendInline(blockquote, quote[1]); target.append(blockquote); continue;
    }
    if (!line.trim()) { flushParagraph(); closeList(); continue; }
    closeList(); paragraph.push(line.trim());
  }
  flushParagraph();
}

function appendInline(target, source) {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;
  let cursor = 0;
  for (const match of source.matchAll(pattern)) {
    target.append(document.createTextNode(source.slice(cursor, match.index)));
    const token = match[0];
    if (token.startsWith("`")) {
      const code = document.createElement("code"); code.textContent = token.slice(1, -1); target.append(code);
    } else if (token.startsWith("**")) {
      const strong = document.createElement("strong"); strong.textContent = token.slice(2, -2); target.append(strong);
    } else if (token.startsWith("*")) {
      const em = document.createElement("em"); em.textContent = token.slice(1, -1); target.append(em);
    } else {
      const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      let safeUrl = null;
      try { const parsed = new URL(link[2], window.location.href); if (parsed.protocol === "https:") safeUrl = parsed.href; } catch {}
      if (safeUrl) {
        const anchor = document.createElement("a"); anchor.href = safeUrl; anchor.target = "_blank"; anchor.rel = "noopener noreferrer";
        anchor.textContent = link[1]; target.append(anchor);
      } else target.append(document.createTextNode(link[1]));
    }
    cursor = match.index + token.length;
  }
  target.append(document.createTextNode(source.slice(cursor)));
}

function addError(text) {
  document.querySelector("#activeStatus")?.remove();
  const card = document.createElement("div");
  card.className = "message status-card error-card";
  card.textContent = text;
  messages.append(card);
  conversation.scrollTop = conversation.scrollHeight;
}

async function waitForJob(id) {
  while (true) {
    const response = await fetch(`/api/jobs/${encodeURIComponent(id)}`, {cache: "no-store"});
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || "Não consegui acompanhar esta conversa");
    if (job.status === "error") throw new Error(job.error || "A conversa não pôde ser concluída");
    if (job.status === "done") return job;
    setStatus(
      job.phase || "As IAs estão conversando",
      job.activity || "A Mesa está acompanhando as etapas desta conversa.",
      job.provider_progress || {},
      job.provider_output || {},
      job.started,
      job.mode || modeSelect.value,
    );
    await new Promise(resolve => setTimeout(resolve, 1200));
  }
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text || state.busy) return;
  const providers = [...state.selected].filter(id => state.providers.some(p => p.id === id && p.installed));
  if (providers.length < 1) {
    addError("Selecione pelo menos uma IA instalada na barra lateral.");
    return;
  }
  previewMode();
  state.busy = true;
  welcome.hidden = true;
  input.value = "";
  input.style.height = "auto";
  sendButton.disabled = true;
  addUserMessage(text);
  state.turns.push({role: "user", text});
  addStatus("Enviando a pergunta", `${providers.map(id => providerNames[id]).join(" · ")}`);
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        message: text,
        providers,
        synthesizer: synthesizer.value || providers[0],
        mode: modeSelect.value,
        history: state.history,
      }),
    });
    const created = await response.json();
    if (!response.ok) throw new Error(created.error || "Não foi possível iniciar a conversa");
    setStatus(
      "Respostas independentes",
      "Cada IA prepara sua própria resposta.",
      Object.fromEntries(providers.map(id => [id, "Na fila"])),
      {},
      Date.now() / 1000,
      modeSelect.value,
    );
    const job = await waitForJob(created.id);
    addAnswer(job.final, job.final_provider, job.notes || [], {
      seconds: job.provider_seconds || {},
      failures: job.provider_failures || {},
      synthSeconds: job.synth_seconds || 0,
    });
    state.turns.push({role: "assistant", text: job.final, provider: job.final_provider, notes: job.notes || []});
    if (job.unavailable && Object.keys(job.unavailable).length) {
      const missed = Object.entries(job.unavailable).map(([name, reason]) => `${name}: ${reason}`).join("\n");
      addError(`Algumas IAs não responderam nesta rodada:\n${missed}`);
    }
    state.history.push({role: "user", content: text}, {role: "assistant", content: job.final});
    state.history = state.history.slice(-12);
    await saveConversation();
  } catch (error) {
    addError(error.message || "Erro inesperado");
  } finally {
    state.busy = false;
    sendButton.disabled = false;
    input.focus();
    // A Mesa aprende com a rodada: quem falhou sai da seleção e ganha uma
    // etiqueta própria ("sem login", "sem saldo") na barra lateral.
    await refreshProviders();
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  previewMode();
});

function updateModeNote(auto) {
  // Com uma IA só não existe revisão cruzada nem resposta consolidada por outra:
  // a IA responde direto, e a Mesa nem gasta as chamadas extras.
  if (state.selected.size === 1) {
    modeNote.textContent = "Com uma IA só, ela responde direto — sem revisão cruzada e sem síntese de outra IA.";
    return;
  }
  modeNote.textContent = modeSelect.value === "fast"
    ? "Rápida pula a revisão cruzada. Os modelos continuam iguais; há menos uma rodada de comparação."
    : "Completa inclui revisão cruzada. Cada provedor usa a autenticação e os limites da sua conta.";
  if (auto) modeNote.textContent += " Pergunta curta: apliquei o modo Rápido automaticamente.";
}

// Só age enquanto o usuário não fixou o modo no seletor.
function previewMode() {
  if (modePinned) return;
  const wanted = input.value.trim().length <= MODO_RAPIDO_ATE ? "fast" : "complete";
  if (modeSelect.value === wanted) return;
  modeSelect.value = wanted;
  updateModeNote(wanted === "fast");
}

modeSelect.addEventListener("change", () => {
  // Escolha explícita: a partir daqui a Mesa não mexe mais no seletor.
  modePinned = true;
  updateModeNote(false);
});
input.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

document.querySelector("#newChat").addEventListener("click", () => {
  state.history = [];
  state.turns = [];
  state.conversationId = null;
  messages.replaceChildren();
  welcome.hidden = false;
  renderHistory();
  input.focus();
});
document.querySelectorAll("[data-prompt]").forEach(button => {
  button.addEventListener("click", () => {
    input.value = button.dataset.prompt;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  });
});

// --------------------------- Rolagem do chat ---------------------------
// O polegar só muda de altura e de transform (nada de reflow por pixel) e o
// controle é uma barra de verdade: arrastar, clicar na trilha, setas, teclado.

const scrollControl = document.querySelector("#scrollControl");
const scrollTrack = document.querySelector("#scrollTrack");
const scrollThumb = document.querySelector("#scrollThumb");
const scrollTopButton = document.querySelector("#scrollTopButton");
const scrollBottomButton = document.querySelector("#scrollBottomButton");

// "auto" em scrollTo significa "use o scroll-behavior do CSS" — que aqui é
// smooth. Para pular de verdade (arrastar o polegar, menos movimento) é
// preciso pedir "instant".
function comportamentoSuave() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth";
}

function limiteDeScroll() {
  return Math.max(0, conversation.scrollHeight - conversation.clientHeight);
}

function moverConversa(top, instantaneo = false) {
  conversation.scrollTo({
    top: Math.max(0, Math.min(top, limiteDeScroll())),
    behavior: instantaneo ? "instant" : comportamentoSuave(),
  });
}

function atualizarControleDeScroll() {
  if (!scrollControl) return;
  const limite = limiteDeScroll();
  // Sem o que rolar (tela de boas-vindas, resposta curta), o controle sai de cena.
  if (limite < 24) {
    scrollControl.hidden = true;
    return;
  }
  scrollControl.hidden = false;
  const trilha = scrollTrack.clientHeight || 96;
  const alturaPolegar = Math.max(26, Math.round(trilha * (conversation.clientHeight / conversation.scrollHeight)));
  const curso = Math.max(0, trilha - alturaPolegar);
  const progresso = Math.min(1, Math.max(0, conversation.scrollTop / limite));
  scrollThumb.style.height = `${alturaPolegar}px`;
  scrollThumb.style.transform = `translateY(${Math.round(curso * progresso)}px)`;
  scrollTrack.setAttribute("aria-valuenow", String(Math.round(progresso * 100)));
  scrollTopButton.classList.toggle("is-spent", progresso <= 0.001);
  scrollBottomButton.classList.toggle("is-spent", progresso >= 0.999);
}

function polegarPara(event, instantaneo) {
  const caixa = scrollTrack.getBoundingClientRect();
  const curso = Math.max(1, caixa.height - (scrollThumb.offsetHeight || 26));
  const topo = event.clientY - caixa.top - (scrollThumb.offsetHeight || 26) / 2;
  const progresso = Math.min(1, Math.max(0, topo / curso));
  moverConversa(progresso * limiteDeScroll(), instantaneo);
}

function iniciarControleDeScroll() {
  if (!scrollControl) return;
  atualizarControleDeScroll();

  // Um quadro por vez: durante a rolagem o polegar não recalcula à toa.
  let quadro = 0;
  conversation.addEventListener("scroll", () => {
    if (quadro) return;
    quadro = requestAnimationFrame(() => {
      quadro = 0;
      atualizarControleDeScroll();
    });
  }, {passive: true});

  scrollTopButton.addEventListener("click", () => moverConversa(0));
  scrollBottomButton.addEventListener("click", () => moverConversa(limiteDeScroll()));

  let arrastando = false;
  scrollTrack.addEventListener("pointerdown", event => {
    event.preventDefault();
    arrastando = true;
    scrollControl.classList.add("is-dragging");
    polegarPara(event, true);
  });
  window.addEventListener("pointermove", event => {
    if (arrastando) polegarPara(event, true);
  });
  for (const fim of ["pointerup", "pointercancel"]) {
    window.addEventListener(fim, () => {
      arrastando = false;
      scrollControl.classList.remove("is-dragging");
    });
  }

  scrollTrack.addEventListener("keydown", event => {
    const pagina = conversation.clientHeight * 0.9;
    const saltos = {ArrowUp: -70, ArrowDown: 70, PageUp: -pagina, PageDown: pagina};
    if (event.key === "Home") moverConversa(0);
    else if (event.key === "End") moverConversa(limiteDeScroll());
    else if (saltos[event.key] !== undefined) moverConversa(conversation.scrollTop + saltos[event.key]);
    else return;
    event.preventDefault();
  });

  if (window.ResizeObserver) {
    const observador = new ResizeObserver(() => atualizarControleDeScroll());
    observador.observe(conversation);
    observador.observe(messages);
  }
  window.addEventListener("resize", atualizarControleDeScroll);
}

// ------------------------------- Histórico -------------------------------
// As conversas ficam em `historico.json`, na pasta do projeto. A Mesa só lê e
// grava esse arquivo local; nada é enviado para fora do computador.

function formatWhen(timestamp) {
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - Number(timestamp || 0)));
  if (seconds < 60) return "agora";
  if (seconds < 3600) return `há ${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `há ${Math.floor(seconds / 3600)} h`;
  if (seconds < 172800) return "ontem";
  return new Date(timestamp * 1000).toLocaleDateString("pt-BR", {day: "2-digit", month: "2-digit"});
}

function renderHistory() {
  if (!historyBox || !historyList) return;
  const items = state.conversations || [];
  const searching = Boolean(state.search);
  historyList.replaceChildren();
  // Procurando, a caixa continua visível mesmo sem resultado — é lá que a
  // pessoa desfaz a busca.
  historyBox.hidden = items.length === 0 && !searching;
  if (historyCount) {
    if (searching) {
      historyCount.textContent = items.length ? `${items.length} de ${state.historyTotal || items.length}` : "nenhuma";
    } else {
      historyCount.textContent = items.length ? `${items.length} ${items.length === 1 ? "conversa" : "conversas"}` : "";
    }
  }
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "history-item";
    if (item.id === state.conversationId) row.classList.add("is-active");

    const open = document.createElement("button");
    open.type = "button";
    open.className = "history-open";
    const title = document.createElement("span");
    title.className = "history-item-title";
    title.textContent = item.title || "Conversa sem título";
    const meta = document.createElement("small");
    meta.className = "history-item-meta";
    const count = Number(item.count || 0);
    meta.textContent = `${count} ${count === 1 ? "mensagem" : "mensagens"} · ${formatWhen(item.updated)}`;
    open.append(title, meta);
    if (item.match) {
      // O trecho vem do servidor: é o pedaço do texto onde a busca bateu.
      const match = document.createElement("small");
      match.className = "history-item-match";
      match.textContent = item.match;
      open.append(match);
    }
    open.addEventListener("click", () => openConversation(item.id));

    const save = document.createElement("button");
    save.type = "button";
    save.className = "history-save";
    save.title = "Salvar uma cópia desta conversa";
    save.setAttribute("aria-label", `Salvar uma cópia de ${item.title || "conversa"}`);
    save.setAttribute("aria-expanded", String(exportMenuId === item.id));
    save.textContent = "⤓";
    save.addEventListener("click", () => {
      exportMenuId = exportMenuId === item.id ? null : item.id;
      renderHistory();
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "history-remove";
    remove.title = "Apagar esta conversa";
    remove.textContent = "×";
    remove.addEventListener("click", () => removeConversation(item, remove));

    row.append(open, save, remove);
    historyList.append(row);
    if (exportMenuId === item.id) historyList.append(buildExportMenu(item));
  }
  if (!items.length && searching) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = `Nada encontrado para “${state.search}”. Tente outra palavra.`;
    historyList.append(empty);
  }
}

// Menu do botão "salvar cópia": dois formatos, cada um explicado numa linha.
// São links de verdade (não chamadas de script): o navegador cuida do download
// com o nome que o servidor já mandou pronto.
function buildExportMenu(item) {
  const options = [
    {format: "md", mark: "#", title: "Documento de texto", note: "arquivo .md para editar ou colar em qualquer lugar"},
    {format: "html", mark: "◫", title: "Página pronta", note: "arquivo .html que abre no navegador, bom para imprimir ou enviar"},
  ];
  const menu = document.createElement("div");
  menu.className = "history-export-menu";
  for (const option of options) {
    const link = document.createElement("a");
    link.className = "history-export-option";
    link.href = `/api/historico/${encodeURIComponent(item.id)}/exportar?formato=${option.format}`;
    link.download = "";
    const mark = document.createElement("span");
    mark.className = "history-export-mark";
    mark.textContent = option.mark;
    const copy = document.createElement("span");
    copy.className = "history-export-copy";
    const strong = document.createElement("b");
    strong.textContent = option.title;
    const small = document.createElement("small");
    small.textContent = option.note;
    copy.append(strong, small);
    link.append(mark, copy);
    // Fecha o menu depois que o download começou (daí o atraso de um quadro).
    link.addEventListener("click", () => window.setTimeout(() => {
      exportMenuId = null;
      renderHistory();
    }, 0));
    menu.append(link);
  }
  return menu;
}

// Fecha o menu de exportação ao clicar em qualquer outro lugar.
document.addEventListener("click", event => {
  if (!exportMenuId) return;
  const target = event.target;
  if (target instanceof Element && (target.closest(".history-export-menu") || target.closest(".history-save"))) return;
  exportMenuId = null;
  renderHistory();
});

async function loadHistory(term = state.search) {
  state.search = String(term || "").trim();
  const url = state.search ? `/api/historico?busca=${encodeURIComponent(state.search)}` : "/api/historico";
  try {
    const response = await fetch(url, {cache: "no-store"});
    const data = await response.json();
    if (response.ok && Array.isArray(data.conversations)) {
      state.conversations = data.conversations;
      state.historyTotal = Number(data.total || data.conversations.length);
    }
  } catch {
    // O histórico é um extra: se ele falhar, a conversa em tela continua.
  }
  renderHistory();
}

function setHistorySearch(term) {
  if (historySearch) historySearch.value = term;
  if (historySearchClear) historySearchClear.hidden = !term;
  loadHistory(term);
}

async function openConversation(id) {
  if (state.busy || !id) return;
  try {
    const response = await fetch(`/api/historico/${encodeURIComponent(id)}`, {cache: "no-store"});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não consegui abrir esta conversa");
    messages.replaceChildren();
    state.turns = [];
    state.history = [];
    for (const entry of data.messages || []) {
      const text = String(entry.text || "");
      if (entry.role === "user") {
        addUserMessage(text);
        state.turns.push({role: "user", text});
        state.history.push({role: "user", content: text});
      } else {
        const notes = Array.isArray(entry.notes) ? entry.notes : [];
        const provider = entry.provider || "";
        addAnswer(text, provider, notes);
        state.turns.push({role: "assistant", text, provider, notes});
        state.history.push({role: "assistant", content: text});
      }
    }
    state.history = state.history.slice(-12);
    state.conversationId = data.id || id;
    welcome.hidden = state.turns.length > 0;
    conversation.scrollTop = 0;
    renderHistory();
    input.focus();
  } catch (error) {
    addError(error.message || "Não consegui abrir esta conversa");
  }
}

async function removeConversation(item, button) {
  const title = item.title || "esta conversa";
  if (!window.confirm(`Apagar "${title}"? Não há como desfazer.`)) return;
  button.disabled = true;
  try {
    const response = await fetch(`/api/historico/${encodeURIComponent(item.id)}`, {method: "DELETE"});
    if (!response.ok) throw new Error("falhou");
    if (state.conversationId === item.id) state.conversationId = null;
  } catch {
    button.disabled = false;
  }
  await loadHistory();
}

async function saveConversation() {
  if (!state.turns.length) return;
  try {
    const response = await fetch("/api/historico", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        id: state.conversationId,
        title: state.turns[0].text,
        messages: state.turns,
      }),
    });
    if (!response.ok) return;
    const saved = await response.json();
    if (saved && saved.id) state.conversationId = saved.id;
  } catch {
    // Sem histórico: a conversa em tela continua intacta.
  }
  await loadHistory();
}

function defaultSelection() {
  const installed = state.providers.filter(provider => provider.installed);
  const healthy = installed.filter(provider => !provider.last_error).map(provider => provider.id);
  // Só deixa de marcar quem falhou se ainda sobrarem duas IAs para conversar.
  return healthy.length >= 2 ? healthy : installed.map(provider => provider.id);
}

function applyProviders(payload) {
  state.providers = payload.map(provider => pausedProviderIds.has(provider.id)
    ? {...provider, installed: false, state: "Pausado por enquanto", reason: "Desativado temporariamente na Mesa. O programa continua instalado no computador."}
    : provider);
}

async function refreshProviders(options = {}) {
  try {
    const response = await fetch("/api/providers", {cache: "no-store"});
    const data = await response.json();
    applyProviders(data.providers || []);
    if (options.keepSelection === false) {
      state.selected = new Set(defaultSelection());
    } else {
      // Quem acabou de falhar sai da seleção — desde que sobrem duas IAs.
      const failed = state.providers.filter(p => p.last_error && state.selected.has(p.id)).map(p => p.id);
      const remaining = [...state.selected].filter(id => !failed.includes(id));
      if (failed.length && remaining.length >= 2) state.selected = new Set(remaining);
    }
    renderProviders();
    return true;
  } catch {
    return false;
  }
}

// ------------------- Painel de confiança (testar as minhas IAs) -------------------
// O teste faz uma pergunta mínima a cada IA detectada, todas ao mesmo tempo, e
// mostra quem respondeu, em quanto tempo e por que falhou. Nunca roda sozinho:
// cada teste gasta cota, então quem decide é a pessoa, no botão.
const HEALTH_POLL_MS = 700;
const HEALTH_LIMIT_MS = 120000;

function formatSeconds(value) {
  const seconds = Math.max(0, Number(value) || 0);
  return `${seconds.toFixed(1).replace(".", ",")} s`;
}

// Mesma ordem da barra lateral, para o painel não parecer outra lista qualquer.
function healthOrder(ids) {
  const main = mesaPrincipalIds.filter(id => ids.includes(id));
  return [...main, ...ids.filter(id => !main.includes(id))];
}

function healthHasResults() {
  return Object.keys(state.health.results).length > 0 || Boolean(state.health.error);
}

function healthRow(id, result) {
  const row = document.createElement("div");
  row.className = "health-item" + (result ? (result.ok ? " is-ok" : " is-off") : " is-waiting");
  const dot = document.createElement("i");
  dot.className = "health-dot";
  dot.setAttribute("aria-hidden", "true");
  dot.textContent = result ? (result.ok ? "✓" : "✕") : "○";
  const copy = document.createElement("div");
  copy.className = "health-copy";
  const top = document.createElement("div");
  top.className = "health-item-top";
  const name = document.createElement("span");
  name.className = "health-name";
  name.textContent = providerNames[id] || id;
  const time = document.createElement("span");
  time.className = "health-time";
  time.textContent = result ? formatSeconds(result.seconds) : "…";
  top.append(name, time);
  const note = document.createElement("small");
  note.className = "health-note";
  if (!result) {
    note.textContent = "Aguardando resposta…";
  } else if (result.ok) {
    note.textContent = result.sample ? `Respondeu: ${result.sample}` : "Respondeu normalmente";
  } else {
    note.textContent = `${result.reason} · ${String(result.detail || "").slice(0, 170)}`;
  }
  copy.append(top, note);
  row.append(dot, copy);
  return row;
}

// O resultado vira um cartão na área da conversa: ali cabe a lista inteira sem
// espremer a barra lateral (que segue mostrando a etiqueta de cada IA).
function renderHealthCard() {
  const existente = document.querySelector("#healthCard");
  if (!state.health.open || !healthHasResults()) {
    if (existente) existente.remove();
    return;
  }
  const {status, providers, results, error} = state.health;
  const ids = healthOrder(providers);
  const respondendo = Object.values(results).filter(item => item.ok).length;
  let card = existente;
  if (!card) {
    card = document.createElement("article");
    card.className = "message health-card";
    card.id = "healthCard";
    messages.append(card);
  }
  const head = document.createElement("div");
  head.className = "health-card-head";
  const title = document.createElement("span");
  title.className = "health-card-title";
  title.textContent = status === "running" ? "Testando as minhas IAs" : "Teste das minhas IAs";
  const hint = document.createElement("span");
  hint.className = "health-card-hint";
  hint.textContent = status === "running"
    ? (ids.length ? `${Object.keys(results).length} de ${ids.length}` : "Chamando cada IA")
    : `${respondendo} de ${ids.length} respondendo`;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "health-card-close";
  close.setAttribute("aria-label", "Fechar o resultado do teste");
  close.textContent = "×";
  close.addEventListener("click", () => {
    state.health.open = false;
    renderHealth();
  });
  head.append(title, hint, close);
  const list = document.createElement("div");
  list.className = "health-card-list";
  if (error) {
    const alerta = document.createElement("p");
    alerta.className = "health-alert";
    alerta.textContent = error;
    list.append(alerta);
  }
  for (const id of ids) list.append(healthRow(id, results[id]));
  const foot = document.createElement("div");
  foot.className = "health-card-foot";
  const again = document.createElement("button");
  again.type = "button";
  again.className = "health-card-again";
  again.textContent = status === "running" ? "Testando…" : "Testar de novo";
  again.disabled = status === "running";
  again.addEventListener("click", runHealthCheck);
  const explica = document.createElement("small");
  explica.textContent = "Quem falha aqui também fica etiquetado na sua lista de IAs.";
  foot.append(again, explica);
  card.replaceChildren(head, list, foot);
  if (!existente) {
    // Ao abrir o cartão, mostre o começo dele (título e primeiras IAs) em vez do
    // fim: durante o teste as linhas seguintes aparecem sozinhas embaixo.
    const topo = card.getBoundingClientRect().top - conversation.getBoundingClientRect().top + conversation.scrollTop;
    moverConversa(topo - 16);
  }
}

function renderHealth() {
  if (!healthPanel || !healthRun) return;
  const {status, providers, results} = state.health;
  const respondendo = Object.values(results).filter(item => item.ok).length;
  const tem = healthHasResults();
  const total = providers.length;
  healthPanel.dataset.status = status;
  healthRun.disabled = status === "running";
  if (status === "running") {
    healthRunTitle.textContent = "Testando…";
    healthRunNote.textContent = total
      ? `${Object.keys(results).length} de ${total} responderam · o resultado abre na conversa`
      : "Chamando cada IA detectada";
  } else if (tem) {
    const contagem = total ? `${respondendo} de ${total} respondendo` : "Nenhuma IA respondeu";
    healthRunTitle.textContent = state.health.open ? "Testar de novo" : "Ver resultado do teste";
    healthRunNote.textContent = state.health.open ? contagem : `${contagem} · a lista está na conversa`;
  } else {
    healthRunTitle.textContent = "Testar minhas IAs";
    healthRunNote.textContent = "Uma pergunta mínima para cada IA detectada";
  }
  renderHealthCard();
}

async function followHealthCheck(id) {
  const started = Date.now();
  while (Date.now() - started < HEALTH_LIMIT_MS) {
    const response = await fetch(`/api/testar/${encodeURIComponent(id)}`, {cache: "no-store"});
    const check = await lerJson(response);
    if (!response.ok) throw new Error(check.error || "O teste se perdeu no caminho");
    state.health.providers = check.providers || state.health.providers;
    state.health.results = check.results || {};
    state.health.status = check.status === "done" ? "done" : "running";
    renderHealth();
    if (state.health.status === "done") return;
    await new Promise(resolve => window.setTimeout(resolve, HEALTH_POLL_MS));
  }
  state.health.status = "done";
  renderHealth();
}

// O servidor pode estar aberto desde antes desta atualização: nesse caso a rota
// do teste ainda não existe e a resposta não é JSON. Sem isso, a pessoa veria
// um erro de programação em vez de "reinicie o servidor".
async function lerJson(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

async function runHealthCheck() {
  if (state.health.status === "running") return;
  state.health = {id: null, status: "running", providers: [], results: {}, error: "", open: true};
  renderHealth();
  try {
    const response = await fetch("/api/testar", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: "{}",
    });
    const started = await lerJson(response);
    if (!response.ok) {
      throw new Error(started.error || "Não consegui iniciar o teste. Se o servidor já estava aberto antes desta atualização, reinicie-o.");
    }
    state.health.id = started.id;
    state.health.providers = started.providers || [];
    renderHealth();
  } catch (error) {
    state.health.status = "error";
    state.health.error = error.message || "Não consegui testar as IAs agora";
    renderHealth();
    return;
  }
  try {
    await followHealthCheck(state.health.id);
  } catch (error) {
    state.health.status = "error";
    state.health.error = error.message || "O teste não pôde terminar";
    renderHealth();
  }
  // O teste alimenta a mesma memória de falhas da rodada: a barra lateral passa
  // a mostrar a etiqueta certa (sem login, sem saldo, limite atingido).
  await refreshProviders();
}

// Rodapé de confiança da resposta final: quem respondeu, em quanto tempo, e quem
// ficou de fora. É o cronômetro que fica salvo na conversa desta tela.
function renderTrust(card, trust) {
  const seconds = (trust && trust.seconds) || {};
  const failures = (trust && trust.failures) || {};
  const ids = healthOrder(Object.keys(seconds));
  if (!ids.length) return;
  const box = document.createElement("div");
  box.className = "answer-trust";
  const title = document.createElement("span");
  title.className = "answer-trust-title";
  title.textContent = "Painel de confiança desta rodada";
  const list = document.createElement("div");
  list.className = "answer-trust-list";
  for (const id of ids) {
    const item = document.createElement("span");
    const failed = failures[id];
    item.className = "answer-trust-item" + (failed ? " is-off" : " is-ok");
    const name = document.createElement("b");
    name.textContent = providerNames[id] || id;
    const value = document.createElement("span");
    value.textContent = failed ? `falhou · ${failed}` : formatSeconds(seconds[id]);
    item.append(name, value);
    list.append(item);
  }
  box.append(title, list);
  card.append(box);
}

async function initialize() {
  if (!await refreshProviders({keepSelection: false})) {
    providerList.textContent = "Não foi possível conectar ao servidor local.";
  }
  loadHistory();
  iniciarControleDeScroll();
}

if (healthRun) {
  // Se o resultado já existe, o botão só reabre a lista (sem gastar cota de
  // novo). Testar outra vez é uma decisão explícita, dentro do cartão.
  healthRun.addEventListener("click", () => {
    if (healthHasResults() && !state.health.open) {
      state.health.open = true;
      renderHealth();
      return;
    }
    runHealthCheck();
  });
}

// Busca no histórico: espera a pessoa parar de digitar antes de perguntar ao
// servidor, e o Esc limpa tudo de uma vez.
if (historySearch) {
  historySearch.addEventListener("input", () => {
    if (historySearchClear) historySearchClear.hidden = !historySearch.value;
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => loadHistory(historySearch.value), 220);
  });
  historySearch.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    setHistorySearch("");
  });
}
if (historySearchClear) {
  historySearchClear.addEventListener("click", () => {
    setHistorySearch("");
    if (historySearch) historySearch.focus();
  });
}
initialize();
