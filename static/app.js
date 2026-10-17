const providerNames = {claude: "Claude Code", codex: "Codex", opencode: "OpenCode", gemini: "Gemini", openrouter: "OpenRouter", cursor: "Cursor Agent", qwen: "Qwen Code", ollama: "Ollama local"};
const providerDetails = {openrouter: "Modelos grátis", ollama: "Qwen 3.5 · 4B"};
const providerMarks = {claude: "C", codex: "O", opencode: "⌘", gemini: "G", openrouter: "R", cursor: "↗", qwen: "Q", ollama: "◉"};
// Espelha o PAUSED_PROVIDERS do servidor: vazio = todos os detectados liberados.
const pausedProviderIds = new Set();
// Ordem da barra lateral: primeiro a mesa principal do usuário, depois o resto.
const mesaPrincipalIds = ["codex", "opencode", "gemini", "openrouter", "ollama", "claude"];
const state = {providers: [], selected: new Set(), history: [], busy: false, providersRendered: false};

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

function providerStateKind(provider) {
  if (provider.installed) return "ready";
  return /pausad/i.test(provider.state || "") ? "paused" : "missing";
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
  if (kind === "ready" && state.selected.has(provider.id)) row.classList.add("is-selected");

  const check = document.createElement("input");
  check.type = "checkbox";
  check.value = provider.id;
  check.checked = state.selected.has(provider.id);
  check.disabled = !provider.installed;
  check.addEventListener("change", () => {
    if (check.checked) state.selected.add(provider.id);
    else state.selected.delete(provider.id);
    if (state.selected.size < 2 && check.checked) {
      const fallback = state.providers.find(p => p.installed && p.id !== provider.id);
      if (fallback) state.selected.add(fallback.id);
    }
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
  if (providerDetails[provider.id]) {
    const detail = document.createElement("small");
    detail.className = "provider-detail";
    detail.textContent = providerDetails[provider.id];
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
      : "Conecte pelo menos duas IAs para começar";
  }
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

function addAnswer(text, provider, notes = []) {
  document.querySelector("#activeStatus")?.remove();
  const card = document.createElement("article");
  card.className = "message answer-card";
  const heading = document.createElement("div");
  heading.className = "answer-heading";
  const mark = document.createElement("span");
  mark.className = "brand-mark";
  mark.textContent = "✳";
  const label = document.createElement("span");
  label.textContent = `RESPOSTA CONSOLIDADA · ${providerNames[provider] || provider}`;
  heading.append(mark, label);
  const body = document.createElement("div");
  body.className = "answer-text";
  renderMarkdown(body, text);
  card.append(heading, body);
  if (notes.length) {
    const details = document.createElement("details");
    details.className = "contribution-details";
    const summary = document.createElement("summary");
    summary.textContent = `Ver contribuições das ${notes.length} IAs`;
    details.append(summary);
    const list = document.createElement("div");
    list.className = "contribution-list";
    for (const note of notes) {
      const contribution = document.createElement("section");
      contribution.className = "contribution-item";
      const name = document.createElement("h3");
      name.textContent = note.provider || "IA participante";
      const content = document.createElement("div");
      content.className = "answer-text";
      renderMarkdown(content, note.summary || "");
      contribution.append(name, content);
      list.append(contribution);
    }
    details.append(list);
    card.append(details);
  }
  messages.append(card);
  conversation.scrollTop = conversation.scrollHeight;
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
  if (providers.length < 2) {
    addError("Selecione pelo menos duas IAs instaladas na barra lateral.");
    return;
  }
  state.busy = true;
  welcome.hidden = true;
  input.value = "";
  input.style.height = "auto";
  sendButton.disabled = true;
  addUserMessage(text);
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
    addAnswer(job.final, job.final_provider, job.notes || []);
    if (job.unavailable && Object.keys(job.unavailable).length) {
      const missed = Object.entries(job.unavailable).map(([name, reason]) => `${name}: ${reason}`).join("\n");
      addError(`Algumas IAs não responderam nesta rodada:\n${missed}`);
    }
    state.history.push({role: "user", content: text}, {role: "assistant", content: job.final});
    state.history = state.history.slice(-12);
  } catch (error) {
    addError(error.message || "Erro inesperado");
  } finally {
    state.busy = false;
    sendButton.disabled = false;
    input.focus();
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
});
modeSelect.addEventListener("change", () => {
  modeNote.textContent = modeSelect.value === "fast"
    ? "Rápida pula a revisão cruzada. Os modelos continuam iguais; há menos uma rodada de comparação."
    : "Completa inclui revisão cruzada. Cada provedor usa a autenticação e os limites da sua conta.";
});
input.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

document.querySelector("#newChat").addEventListener("click", () => {
  state.history = [];
  messages.innerHTML = "";
  welcome.hidden = false;
  input.focus();
});
document.querySelectorAll("[data-prompt]").forEach(button => {
  button.addEventListener("click", () => {
    input.value = button.dataset.prompt;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  });
});

async function initialize() {
  try {
    const response = await fetch("/api/providers", {cache: "no-store"});
    const data = await response.json();
    state.providers = data.providers.map(provider => pausedProviderIds.has(provider.id)
      ? {...provider, installed: false, state: "Pausado por enquanto", reason: "Desativado temporariamente na Mesa. O programa continua instalado no computador."}
      : provider);
    const installed = state.providers.filter(provider => provider.installed).map(provider => provider.id);
    state.selected = new Set(installed);
    renderProviders();
  } catch {
    providerList.textContent = "Não foi possível conectar ao servidor local.";
  }
}
initialize();
