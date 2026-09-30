"use strict";

const el = (tag, props, ...kids) => {
  const n = document.createElement(tag);
  Object.assign(n, props || {});
  for (const k of kids) n.append(k);
  return n;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function fmt(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Panel": "1" } });
  let data = {};
  try { data = await res.json(); } catch (e) { /* non-JSON error body */ }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

/* ---------- info tags ---------- */

function tagChip(tag) {
  const kids = [
    el("span", { className: "ico", innerHTML: iconSvg(tag.kind === "local" ? "local" : "network") }),
    el("b", { textContent: tag.kind === "local" ? "Local" : "Network" }),
    el("span", { textContent: `${tag.label} · ${tag.detail}` }),
  ];
  if (tag.paid) kids.push(el("b", { className: "dollar", textContent: "$", title: "This part costs money" }));
  return el("span", { className: `tag ${tag.kind}${tag.paid ? " paid" : ""}` }, ...kids);
}


// One icon per feature (drawn in icons.js), shown next to the feature button and that feature's history items.
const toolIcon = (id) => (iconSvg(id) ? el("span", { className: `ico ico-${id}`, innerHTML: iconSvg(id, 18), title: id === "youtube" ? "YouTube" : id }) : null);
const withIcon = (id, ...kids) => [toolIcon(id), ...kids].filter(Boolean);

/* ---------- free pill + shared progress bar ---------- */
const state = { tools: [], models: [], prices: {}, selectedId: null, view: "home", key: { saved: false, last4: null, provider: null } };
const PROVIDER_NAME = { anthropic: "Anthropic", openrouter: "OpenRouter" };
const pill = (kind) => el("span", { className: kind === "free" ? "pill free" : "pill paid", textContent: kind === "free" ? "Free" : "$" });
// Left panel: only two tags. "Local" = it can run on this Mac; "API" = it can use a cloud API.
const railTag = (text, kind) => el("span", { className: kind === "local" ? "pill free" : "pill paid", textContent: text });
const railTags = (t) => [t.has_free ? railTag("Local", "local") : null, t.has_paid ? railTag("API", "api") : null].filter(Boolean);
const toolPills = (t) => [t.has_free ? pill("free") : null, t.has_paid ? pill("paid") : null].filter(Boolean);

function progressPanel() {
  const fill = el("div", { className: "bar-fill" });
  const bar = el("div", { className: "bar", role: "progressbar" }, fill);
  bar.setAttribute("aria-valuemin", "0");
  bar.setAttribute("aria-valuemax", "100");
  const text = el("p", { className: "stage-text" });
  const pct = el("span", { className: "stage-pct" });
  const root = el("div", { className: "progress", hidden: true }, el("div", { className: "progress-row" }, text, pct), bar);
  return {
    root,
    update(job) {
      root.hidden = false;
      fill.style.width = `${job.percent}%`;
      bar.setAttribute("aria-valuenow", String(job.percent));
      text.textContent = `Step ${job.stage} of ${job.stage_count} · ${job.label}` + (job.detail ? ` · ${job.detail}` : "");
      pct.textContent = `${job.percent}%`;
    },
    hide() { root.hidden = true; },
  };
}

/* ---------- result view ---------- */
const ytLink = (rec, t) => `https://youtu.be/${encodeURIComponent(rec.video_id)}` + (t ? `?t=${t}` : "");
const fmtNum = (n) => Number(n || 0).toLocaleString("en-US");
const fmtUsd = (n) => `$${n < 0.01 ? n.toFixed(4) : n.toFixed(3)}`;
function costLine(rec) {
  if (rec.provider === "cloud") {
    const via = rec.route === "openrouter" ? " via OpenRouter" : "";
    const money = rec.cost_usd != null ? `≈ ${fmtUsd(rec.cost_usd)}` : "$";
    return `cost: ${money} · ${rec.model_name || rec.model}${via} · ${fmtNum(rec.tokens_in)} in / ${fmtNum(rec.tokens_out)} out tokens · ${rec.seconds}s`;
  }
  return `cost: free · local · ${rec.effort ? rec.effort + " · " : ""}${rec.model} · ${rec.seconds}s`;
}

function toMarkdown(rec) {
  const s = rec.summary;
  let md = `# ${rec.title}\n\n> ${s.tldr}\n\n`;
  for (const sec of s.sections) {
    md += `## ${sec.title} ([${fmt(sec.start)}](${ytLink(rec, sec.start)}))\n`;
    md += sec.bullets.map((b) => `- ${b}`).join("\n") + "\n\n";
  }
  if (s.takeaways.length) md += `## Key takeaways\n` + s.takeaways.map((t) => `- ${t}`).join("\n") + "\n";
  return md + `\nSource: ${ytLink(rec, 0)}\n`;
}

async function copyText(text, btn) {
  let ok = true;
  try { await navigator.clipboard.writeText(text); } catch (e) {
    const ta = el("textarea", { value: text });
    document.body.append(ta); ta.select();
    try { ok = document.execCommand("copy"); } catch (e2) { ok = false; }
    ta.remove();
  }
  const old = btn.textContent;
  btn.textContent = ok ? "Copied" : "Copy failed";
  setTimeout(() => (btn.textContent = old), 2000);
}

function renderResult(box, rec) {
  const s = rec.summary;
  const copy = el("button", { id: "copy-md", textContent: "Copy as Markdown" });
  copy.onclick = () => copyText(toMarkdown(rec), copy);
  const nodes = [
    el("h2", { className: "section-label", textContent: "Summary" }),
    el("p", { className: "cost", textContent: costLine(rec) }),
    el("h1", { textContent: rec.title }),
    el("p", { className: "source" }, el("a", { href: ytLink(rec, 0), target: "_blank", rel: "noopener", textContent: "Watch on YouTube" })),
    el("p", { className: "tldr", textContent: s.tldr }),
    el("div", { className: "toolbar" }, copy),
  ];
  s.sections.forEach((sec, i) => {
    const ts = el("a", { className: "ts", href: ytLink(rec, sec.start), target: "_blank", rel: "noopener", textContent: fmt(sec.start), title: "Open the video at this moment" });
    ts.onclick = (e) => e.stopPropagation();
    const ul = el("ul");
    sec.bullets.forEach((b) => ul.append(el("li", { textContent: b })));
    nodes.push(el("details", { open: i === 0 },
      el("summary", null, ts, el("span", { textContent: sec.title })),
      el("div", { className: "body" }, ul)));
  });
  if (s.takeaways.length) {
    const ul = el("ul");
    s.takeaways.forEach((t) => ul.append(el("li", { textContent: t })));
    nodes.push(el("h2", { textContent: "Key takeaways", style: "margin-top:16px" }), ul);
  }
  box.replaceChildren(...nodes);
}

/* ---------- YouTube tool ---------- */
let youtubeUI = null; // built once so a running job survives navigating away

function optionRow(o) {
  const local = o.provider === "local";
  const ready = local ? state.models.includes(o.model) : state.key.saved;
  const load = local ? `${o.load} load` : "no load on your Mac";
  const mark = local ? "" : " $";
  const why = ready ? "" : (local ? " · not installed" : " · add API key on Home");
  const price = state.prices[o.id] ? ` · $${state.prices[o.id].in} in / $${state.prices[o.id].out} out per 1M tokens` : "";
  return { ready, text: `${o.effort} · ${o.name}${mark}${price} · ${load}${why}` };
}

function buildYoutubeUI(meta) {
  const url = el("input", { id: "yt-url", type: "url", placeholder: "Paste a YouTube link", autocomplete: "off" });
  const option = el("select", { id: "yt-option", title: "Effort and model" });
  const go = el("button", { id: "yt-go", className: "primary", textContent: "Summarize" });
  const abortBtn = el("button", { id: "yt-abort", className: "abort", textContent: "Abort", hidden: true, title: "Stop now and discard everything" });
  const tagsBox = el("div", { className: "tags" });
  const head = el("div", { className: "tool-head" });
  const status = el("p", { className: "status", role: "status" });
  const progress = progressPanel();
  const out = el("div", { id: "yt-result" });
  let running = false;
  let currentJob = null;

  function present(rec) { // show a summary in the middle and select its history item
    renderResult(out, rec);
    state.selectedId = rec.id || null;
    remember(); markSelected();
  }
  function clearShown() {
    out.replaceChildren(); out.dataset.job = "";
    state.selectedId = null;
    remember(); markSelected();
  }

  const selected = () => meta.options.find((o) => o.id === option.value) || meta.options.find((o) => o.id === meta.default_option);
  const setStatus = (text, isError) => { status.className = isError ? "status error" : "status"; status.textContent = text; };

  function drawTags() {
    const opt = selected();
    const via = opt.provider === "cloud" && state.key.provider === "openrouter" ? " via OpenRouter" : "";
    const tags = meta.tags.map((t) => (t.label === "Summarizer" ? { ...opt.tag, detail: opt.tag.detail + via } : t));
    tagsBox.replaceChildren(...tags.map(tagChip));
    const free = !tags.some((t) => t.paid);
    head.replaceChildren(el("h2", { textContent: meta.name }), ...(free ? [pill("free")] : []));
  }

  function refreshOptions() { // rebuild the grouped dropdown from installed models + key state
    const keep = option.value || meta.default_option;
    const groups = [["local", "On this Mac (free)"], ["cloud", "Cloud ($) · Claude API"]];
    option.replaceChildren(...groups.map(([prov, title]) => {
      const g = el("optgroup", { label: title });
      meta.options.filter((o) => o.provider === prov).forEach((o) => {
        const row = optionRow(o);
        g.append(el("option", { value: o.id, disabled: !row.ready, textContent: row.text }));
      });
      return g;
    }));
    const wanted = [...option.options].find((o) => o.value === keep && !o.disabled)
      || [...option.options].find((o) => !o.disabled);
    if (wanted) option.value = wanted.value;
    drawTags();
  }
  option.onchange = drawTags;

  async function loadModels() {
    try {
      const data = await api("/api/models");
      state.models = data.models;
      if (data.error) setStatus(data.error, true);
    } catch (e) { setStatus(e.message, true); }
    try { state.prices = await api("/api/prices"); } catch (e) { state.prices = {}; } // prices are a nice-to-have
    refreshOptions();
  }

  // Poll one job until it ends. `out.dataset.job` says which job may render into the result area.
  async function follow(jobId) {
    running = true; currentJob = jobId;
    go.disabled = true; abortBtn.hidden = true; abortBtn.disabled = false; setStatus(""); // shown only when the job can be stopped
    try {
      for (;;) {
        const job = await api(`/api/jobs/${jobId}`);
        if (job.status === "error") throw new Error(job.error);
        if (job.status === "aborted") { clearShown(); progress.hide(); setStatus("Aborted. Nothing was saved."); break; }
        if (job.status === "done") {
          progress.hide();
          if (out.dataset.job === jobId) { present(job.result); setStatus(""); }
          else setStatus(`Finished: ${job.result.title}. Open it from History.`);
          refreshHistory();
          break;
        }
        abortBtn.hidden = !job.can_abort; // local runs only; a cloud request cannot be cancelled once sent
        progress.update(job);
        await sleep(1000);
      }
    } catch (e) { progress.hide(); setStatus(e.message, true); } finally {
      running = false; currentJob = null; go.disabled = false; abortBtn.hidden = true;
    }
  }

  async function run() {
    if (running) return; // Enter key or double click while a job is running
    const link = url.value.trim();
    if (!link) return setStatus("Paste a YouTube link first.", true);
    if (!option.value) return setStatus("No option available. Start Ollama, or add an API key on Home.", true);
    running = true; go.disabled = true; setStatus("");
    clearShown(); // the old summary is no longer on screen
    let jobId;
    try {
      ({ job_id: jobId } = await api("/api/youtube/summarize", { method: "POST", body: JSON.stringify({ url: link, option: option.value }) }));
    } catch (e) { running = false; go.disabled = false; return setStatus(e.message, true); }
    out.dataset.job = jobId;
    follow(jobId);
  }

  abortBtn.onclick = async () => {
    if (!currentJob) return;
    abortBtn.disabled = true;
    try { await api(`/api/jobs/${currentJob}/abort`, { method: "POST", body: "{}" }); } catch (e) {
      abortBtn.disabled = false;
      return setStatus(e.message, true);
    }
    clearShown(); progress.hide(); setStatus("Aborted. Nothing was saved.");
  };
  go.onclick = run;
  url.onkeydown = (e) => { if (e.key === "Enter") run(); };

  refreshOptions();
  loadModels();
  return {
    root: el("div", null,
      el("section", { className: "input-card", ariaLabel: "Summarize a video" }, head,
        el("div", { className: "form" }, url, option, go, abortBtn),
        el("p", { className: "hint", textContent: "Easy = fastest and cheapest · Hard = best quality, slowest, most load or cost. Cloud runs send the transcript to the provider and can't be aborted once sent." }),
        tagsBox, progress.root, status),
      out),
    show(rec) { out.dataset.job = ""; present(rec); },
    clear: clearShown,
    attach(job) { out.dataset.job = job.id; follow(job.id); },
    refreshOptions,
  };
}

function youtubeView(stage, meta, record) {
  if (!youtubeUI) youtubeUI = buildYoutubeUI(meta);
  stage.replaceChildren(youtubeUI.root);
  if (record) youtubeUI.show(record);
}

/* ---------- Home: tool cards + API key card ---------- */
const KEY_MASK = "\u2022".repeat(24); // a fixed mask: it is not derived from the key, so there is nothing to copy

function keyCard() {
  const input = el("input", { id: "key-input", type: "password", placeholder: "sk-or-… or sk-ant-…", autocomplete: "new-password", spellcheck: false });
  const save = el("button", { id: "key-save", className: "primary" });
  const status = el("p", { id: "key-status", className: "status", role: "status" });
  const say = (text, isError) => { status.className = isError ? "status error" : "status"; status.textContent = text; };
  const draw = () => {
    input.value = state.key.saved ? KEY_MASK : "";
    save.textContent = state.key.saved ? "Update" : "Test & save";
    if (state.key.error) say(`${state.key.error} Cloud options stay disabled until this is fixed.`, true);
    else say(state.key.saved ? `${PROVIDER_NAME[state.key.provider] || "API"} key saved in macOS Keychain (ends in ${state.key.last4}).` : "No key saved. Cloud options stay disabled.");
  };
  input.onfocus = () => { if (input.value === KEY_MASK) input.value = ""; }; // an empty field, ready for the new key
  input.onblur = () => { if (!input.value && state.key.saved) input.value = KEY_MASK; };
  input.onkeydown = (e) => { if (e.key === "Enter") save.click(); };
  save.onclick = async () => {
    const value = input.value.split("\u2022").join("").trim(); // never let mask dots ride along with a pasted key
    if (!value || input.value === KEY_MASK) {
      return say(state.key.saved ? "To change the key: clear the field, paste the new key, then press Update." : "Paste your API key first.", true);
    }
    save.disabled = true; say("Checking the key with Anthropic…");
    try {
      state.key = await api("/api/settings/key", { method: "POST", body: JSON.stringify({ key: value }) });
      if (youtubeUI) youtubeUI.refreshOptions();
      draw();
    } catch (e) {
      input.value = ""; // the key never stays in the page
      say(e.message + (state.key.saved ? " Your previous key is still saved." : ""), true);
    } finally { save.disabled = false; }
  };
  draw();
  return el("section", { className: "key-card" },
    el("h3", { textContent: "API key" }),
    el("p", { className: "hint", textContent: "Needed only for cloud options ($). Paste an OpenRouter key (sk-or-…, reaches Claude) or an Anthropic key (sk-ant-…). One key at a time; it is kept in your macOS Keychain and sent only to that provider. Use a dedicated key with a spend limit." }),
    el("div", { className: "form" }, input, save),
    status);
}

function homeView(stage) {
  const cards = state.tools.map((t) => {
    const card = el("button", { className: "card" }, el("span", { className: "card-title" }, ...withIcon(t.icon || t.id, el("span", { textContent: t.name }))), el("span", { className: "card-marks" }, ...railTags(t)));
    card.onclick = () => openTool(t.id);
    return card;
  });
  stage.replaceChildren(el("h2", { textContent: "Home" }), el("div", { className: "cards" }, ...cards), keyCard());
}

/* ---------- shell: rail, history ---------- */
const VIEWS = { youtube: youtubeView };

function openTool(id, record) {
  document.querySelectorAll(".tool-btn").forEach((b) => b.classList.toggle("active", b.dataset.id === id));
  state.view = id;
  if (id === "home") { homeView(document.getElementById("stage")); remember(); markSelected(); return; }
  const meta = state.tools.find((t) => t.id === id);
  if (!meta || !VIEWS[id]) return;
  VIEWS[id](document.getElementById("stage"), meta, record);
  remember(); markSelected();
}

// A history item is highlighted exactly while its summary is showing in the middle.
const LAST_KEY = "learning-panel:last-summary"; // per-viewer convenience only; the page works without it
function remember() {
  try {
    if (state.selectedId && state.view === "youtube") localStorage.setItem(LAST_KEY, state.selectedId);
    else localStorage.removeItem(LAST_KEY);
  } catch (e) { /* storage blocked: nothing to remember */ }
}
function recalled() {
  try { return localStorage.getItem(LAST_KEY); } catch (e) { return null; }
}
function markSelected() {
  const visible = state.view === "youtube" ? state.selectedId : null;
  document.querySelectorAll("#history-list .hist-item").forEach((li) => {
    const on = li.dataset.id === visible;
    li.classList.toggle("selected", on);
    li.querySelector(".hist-open").setAttribute("aria-current", on ? "true" : "false");
  });
}

async function refreshHistory() {
  const list = document.getElementById("history-list");
  try {
    const items = await api("/api/history");
    if (!items.length) return list.replaceChildren(el("li", { className: "empty", textContent: "Summaries you make will appear here." }));
    list.replaceChildren(...items.map((it) => {
      const open = el("button", { className: "hist-open" },
        el("span", { className: "hist-title" }, ...withIcon(it.tool || "youtube", el("span", { className: "hist-text", textContent: it.title || it.video_id }))),
        el("small", { textContent: `${new Date(it.created).toLocaleString()} · ${it.effort ? it.effort + " · " : ""}${it.model_name || it.model}${it.provider === "cloud" ? " $" : ""}` }));
      open.onclick = async () => {
        try {
          openTool("youtube", await api(`/api/history/${it.id}`));
        } catch (e) { list.prepend(el("li", { className: "empty", textContent: e.message })); }
      };
      const del = el("button", { className: "hist-del", innerHTML: iconSvg("trash", 15), title: "Delete this summary", ariaLabel: `Delete ${it.title}` });
      del.onclick = async () => {
        try { await api(`/api/history/${it.id}`, { method: "DELETE" }); } catch (e) { /* already gone */ }
        if (state.selectedId === it.id && youtubeUI) youtubeUI.clear(); // nothing stale left on screen
        refreshHistory();
      };
      const row = el("li", { className: "hist-item" }, open, del);
      row.dataset.id = it.id;
      return row;
    }));
    markSelected();
  } catch (e) { list.replaceChildren(el("li", { className: "empty", textContent: e.message })); }
}

async function init() {
  const rail = document.getElementById("rail");
  try {
    state.tools = await api("/api/tools");
  } catch (e) {
    return document.getElementById("stage").replaceChildren(el("p", { className: "status error", textContent: e.message }));
  }
  try { // a locked Keychain must not break the free local features
    state.key = await api("/api/settings/key");
  } catch (e) { state.key = { saved: false, last4: null, error: e.message }; }
  const home = el("button", { className: "tool-btn" }, el("span", { textContent: "Home" }));
  home.dataset.id = "home";
  home.onclick = () => openTool("home");
  rail.replaceChildren(home, ...state.tools.map((t) => {
    const b = el("button", { className: "tool-btn" }, el("span", { className: "tool-name" }, ...withIcon(t.icon || t.id, el("span", { textContent: t.name }))), el("span", { className: "card-marks" }, ...railTags(t)));
    b.dataset.id = t.id;
    b.onclick = () => openTool(t.id);
    return b;
  }));
  let job = null;
  try { ({ job } = await api("/api/jobs/active")); } catch (e) { /* no running job to show */ }
  if (job) { // a job may still be running from before a reload or a closed tab
    openTool("youtube");
    youtubeUI.attach(job);
  } else {
    const lastId = recalled();
    let rec = null;
    if (lastId) { try { rec = await api(`/api/history/${lastId}`); } catch (e) { /* it was deleted */ } }
    if (rec) openTool("youtube", rec); else openTool("home");
  }
  refreshHistory();
}
init();
