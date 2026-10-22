"use strict";

const $ = (id) => document.getElementById(id);
const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
};

const state = {
  curriculum: null,
  view: null,
  progress: store.get("w2a-progress", { problems: {}, concepts: {} }),
  explore: store.get("w2a-explore", false),
  radix: store.get("w2a-radix", "dec"),
  coachEnabled: false,
  coachModel: "",
  lastCode: "",
  lastWave: null,
  slug: null,
  problem: null,
  hintLevel: -1,       // highest hint opened since the last submission
  lastFeedback: null,
};

let editor = null;
const wideScreen = matchMedia("(min-width: 980px)");

// ------------------------------------------------------------------ helpers

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function inline(s) { return esc(s).replace(/`([^`]+)`/g, "<code>$1</code>"); }

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

function getCode() { return editor ? editor.getValue() : $("code").value; }
function setCode(text) { if (editor) editor.setValue(text); else $("code").value = text; }

function flagLine(line) {
  if (!editor || !line) return;
  editor.eachLine((h) => editor.removeLineClass(h, "background", "cm-flag"));
  editor.addLineClass(line - 1, "background", "cm-flag");
  editor.scrollIntoView({ line: line - 1, ch: 0 }, 80);
  editor.setCursor({ line: line - 1, ch: 0 });
  editor.focus();
}
function clearFlags() { if (editor) editor.eachLine((h) => editor.removeLineClass(h, "background", "cm-flag")); }

// ------------------------------------------------------------------ map

function allProblems() { return state.curriculum.stages.flatMap((s) => s.problems.map((p) => ({ ...p, stage: s.id }))); }

function renderMap() {
  const solved = (slug) => state.progress.problems?.[slug]?.solved;
  const unlocked = new Map(state.view.stages.map((s) => [s.id, s.unlocked]));
  $("map").innerHTML = state.curriculum.stages.map((s) => {
    const open = state.explore || unlocked.get(s.id);
    const chips = s.problems.map((p) => {
      const cls = ["chip", solved(p.slug) && "solved", p.slug === state.slug && "current",
        !p.available ? "soon" : !open && "locked"].filter(Boolean).join(" ");
      const title = !p.available ? "Being authored, not ready yet" : !open ? "Finish the previous stage first" : p.title;
      return `<button type="button" class="${cls}" data-slug="${p.slug}" title="${esc(title)}">${esc(p.slug)}</button>`;
    }).join("");
    return `<div class="stage${open ? "" : " locked"}">
      <div class="stage-head"><span class="n">${s.id}</span><span class="t">${esc(s.title)}</span>${open ? "" : '<span class="lock">locked</span>'}</div>
      <div class="chips">${chips}</div></div>`;
  }).join("");
  $("map").querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => {
    if (b.classList.contains("locked") || b.classList.contains("soon")) return;
    if (!wideScreen.matches) $("map-box").open = false;
    openProblem(b.dataset.slug);
  }));

  const total = allProblems().length;
  const done = allProblems().filter((p) => solved(p.slug)).length;
  const mastered = state.view.mastered.length;
  $("summary").textContent = `${done} of ${total} solved · ${mastered} concept${mastered === 1 ? "" : "s"} mastered`;
  $("map-summary").textContent = `Stages · ${done} of ${total} solved`;
}

async function refreshProgress(update) {
  const data = await api("/api/progress", { progress: state.progress, ...(update || {}) });
  state.progress = data.progress;
  state.view = data.view;
  store.set("w2a-progress", state.progress);
  renderMap();
}

// ------------------------------------------------------------------ problem

function renderSpec(text) {
  return text.split(/\n\s*\n/).map((para) => {
    const lines = para.split("\n");
    if (lines.every((l) => /^\s*-\s+/.test(l))) {
      return `<ul>${lines.map((l) => `<li>${inline(l.replace(/^\s*-\s+/, ""))}</li>`).join("")}</ul>`;
    }
    if (lines.some((l) => /^\s{2,}\S/.test(l) && !/^\s*-\s/.test(l))) return `<pre>${esc(para)}</pre>`;
    return `<p>${inline(lines.join(" "))}</p>`;
  }).join("");
}

async function openProblem(slug) {
  state.slug = slug;
  state.hintLevel = -1;
  $("coach-body").innerHTML = "";
  location.hash = slug;
  $("result").hidden = true;
  clearFlags();
  const p = await api(`/api/problem/${encodeURIComponent(slug)}`);
  state.problem = p;
  $("p-stage").textContent = `Stage ${p.stage.id} · ${p.stage.title}`;
  $("p-title").textContent = p.title;
  $("p-meta").innerHTML = `<span>${esc(p.source)}</span><a href="${esc(p.hdlbits_url)}" target="_blank" rel="noopener">Original problem on HDLBits ↗</a>`;
  if (!p.available) {
    $("p-spec").innerHTML = `<p class="empty">This problem is still being authored and verified. It will appear here once it passes review.</p>`;
    $("p-given").hidden = true;
    $("editor-block").hidden = true;
    renderMap();
    return;
  }
  $("editor-block").hidden = false;
  $("p-spec").innerHTML = renderSpec(p.spec);
  if (p.given.length) {
    $("p-given").hidden = false;
    $("p-given").innerHTML = `<span class="label">Provided module${p.given.length > 1 ? "s" : ""} (you can instantiate ${p.given.length > 1 ? "them" : "it"}):</span><pre>${esc(p.given.join("\n"))}</pre>`;
  } else {
    $("p-given").hidden = true;
  }
  setCode(store.get(`w2a-code-${slug}`, p.template));
  renderMap();
}

// ------------------------------------------------------------------ results

const STATUS = {
  pass: "Correct", mismatch: "Wrong output", compile_error: "Does not compile", error: "Does not compile",
  structure: "Missing submodules", timeout: "Did not finish", rejected: "Not run",
};

function renderCompile(c) {
  const box = $("r-compile");
  if (!c) { box.hidden = true; return; }
  box.hidden = false;
  const where = c.line ? `<button type="button" class="ghost" data-line="${c.line}">Line ${c.line}</button> <code>${esc(c.code || "")}</code>` : "";
  box.innerHTML = `${where ? `<div class="where">${where}</div>` : ""}<div>${inline(c.explanation)}</div>` +
    (c.compiler_message ? `<div class="raw">Compiler: ${esc(c.compiler_message)}</div>` : "");
  box.querySelectorAll("[data-line]").forEach((b) => b.addEventListener("click", () => flagLine(+b.dataset.line)));
  if (c.line) flagLine(c.line);
}

function num(value) {
  if (value == null) return "?";
  if (/[xz]/.test(value)) return "x";
  if (state.radix === "bin") return value;
  const n = BigInt("0b" + value);
  return state.radix === "hex" ? "0x" + n.toString(16) : n.toString();
}

function renderWave(history, mismatched) {
  const fig = $("r-wave");
  if (!history || !history.length) { fig.hidden = true; return; }
  fig.hidden = false;
  state.lastWave = [history, mismatched];
  document.querySelectorAll(".radix button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.radix === state.radix)));
  const cols = history.length;
  const wave = $("wave");
  const widest = Math.max(...Object.values({ ...history[0].inputs, ...history[0].outputs }).map((s) => s.width));
  const minCol = state.radix === "bin" ? Math.max(4.2, widest * 0.5 + 1) : state.radix === "hex" ? Math.max(4.2, widest / 4 * 0.5 + 2) : 4.2;
  wave.style.gridTemplateColumns = `max-content repeat(${cols}, minmax(${minCol}rem, 1fr))`;
  const cells = [`<div class="sig"></div>`];
  history.forEach((_, i) => cells.push(`<div class="tick${i === cols - 1 ? " first" : ""}">${i === cols - 1 ? "first wrong" : `#${i + 1}`}</div>`));
  const ins = Object.entries(history[0].inputs);
  for (const [name, meta] of ins) {
    cells.push(`<div class="sig">${esc(name)}</div>`);
    history.forEach((snap, i) => {
      const v = snap.inputs[name]?.value;
      if (meta.width === 1) {
        const prev = i > 0 ? history[i - 1].inputs[name]?.value : v;
        cells.push(`<div class="bit${v === "1" ? " hi" : ""}${i > 0 && prev !== v ? " edge" : ""}"></div>`);
      } else {
        cells.push(`<div class="bus${/[xz]/.test(v || "") ? " x" : ""}">${num(v)}</div>`);
      }
    });
  }
  cells.push(`<div class="gap"></div>`);
  for (const name of Object.keys(history[0].outputs)) {
    const bad = mismatched.includes(name);
    cells.push(`<div class="sig">${esc(name)} expected</div>`);
    history.forEach((snap) => cells.push(`<div class="bus">${num(snap.outputs[name]?.expected)}</div>`));
    cells.push(`<div class="sig you">${esc(name)} yours</div>`);
    history.forEach((snap) => {
      const o = snap.outputs[name] || {};
      const wrong = bad && o.expected !== o.got && !/[xz]/.test(o.expected || "");
      cells.push(`<div class="bus ${wrong ? "bad" : "ok"}">${num(o.got)}</div>`);
    });
  }
  wave.innerHTML = cells.join("");
}

const LEVELS = [
  { lv: 0, key: "L0", name: "Concept" },
  { lv: 1, key: "L1", name: "Counterexample" },
  { lv: 2, key: "L2", name: "Where to look" },
  { lv: 3, key: "L3", name: "Structure" },
];

function hintAvailable(h, key) {
  const v = h[key];
  return Array.isArray(v) ? v.length > 0 : Boolean(v);
}

function nextCoachLevel() { return Math.min(3, state.hintLevel + 1); }

function renderLadder() {
  const fb = state.lastFeedback;
  const h = fb.hints;
  const solved = fb.status === "pass";
  $("ladder").hidden = solved;
  if (solved) return;
  $("ask").hidden = !state.coachEnabled;
  $("ask-btn").textContent = `Ask the coach (L${Math.max(0, nextCoachLevel())})`;
  $("ladder-buttons").innerHTML = LEVELS.map(({ lv, key, name }) => {
    const ok = hintAvailable(h, key);
    const open = lv <= state.hintLevel;
    return `<button type="button" class="step${open ? " open" : ""}" data-lv="${lv}" ${ok ? "" : "disabled"}>
      <span class="lv">${key}</span>${name}</button>`;
  }).join("");
  $("ladder-buttons").querySelectorAll(".step").forEach((b) => b.addEventListener("click", () => {
    state.hintLevel = Math.max(state.hintLevel, +b.dataset.lv);
    renderLadder();
  }));
  const parts = [];
  for (const { lv, key, name } of LEVELS) {
    if (lv > state.hintLevel || !hintAvailable(h, key)) continue;
    let body = "";
    if (key === "L0") {
      body = h.L0.map((c) => `<p><b>${esc(c.title)}.</b> ${inline(c.note)}</p><pre>${esc(c.example)}</pre>`).join("");
    } else if (key === "L1") {
      body = `<p>${inline(h.L1.text)}</p>`;
    } else if (key === "L2") {
      body = `<ul class="lines">${h.L2.map((l) => `<li><button type="button" data-line="${l.line}"><span class="ln">line ${l.line}</span>${esc(l.code)}<span class="why">${esc(l.why)} ${esc(l.signal)}</span></button></li>`).join("")}</ul>`;
    } else if (key === "L3") {
      body = `<p>${inline(h.L3)}</p>`;
    }
    parts.push(`<div class="hint"><h3><span class="lv">${key}</span>${name}</h3>${body}</div>`);
  }
  $("hint-body").innerHTML = parts.join("") || `<p class="empty">Open a hint above when you are stuck.</p>`;
  $("hint-body").querySelectorAll("[data-line]").forEach((b) => b.addEventListener("click", () => flagLine(+b.dataset.line)));
}

const FALLBACK = {
  leak: "The coach's answer gave too much away, so here is the built-in hint instead.",
  error: "The coach did not answer in time, so here is the built-in hint instead.",
  daily_limit: "The coach has reached today's limit, so here is the built-in hint instead.",
};

async function askCoach() {
  const level = Math.max(0, nextCoachLevel());
  $("ask-btn").disabled = true;
  $("ask-btn").textContent = "Thinking…";
  try {
    const r = await api("/api/coach", { slug: state.slug, code: state.lastCode, level });
    state.hintLevel = Math.max(state.hintLevel, level);
    const meta = [r.model ? r.model.replace("nvidia/", "") : "built-in", `L${r.level}`,
      r.latency_s != null ? `${r.latency_s} s` : "", r.cached ? "cached" : "", r.model ? "leak-checked" : ""].filter(Boolean).join(" · ");
    const line = r.root_cause_line && r.level >= 2 ? `<p><button type="button" class="ghost" data-line="${r.root_cause_line}">Show line ${r.root_cause_line}</button></p>` : "";
    const fall = r.fallback && FALLBACK[r.fallback] ? `<p class="fallback">${esc(FALLBACK[r.fallback])}</p>` : "";
    const card = document.createElement("div");
    card.className = "hint coach";
    card.innerHTML = `<h3><span class="lv">AI</span>Coach<span class="badge">${esc(meta)}</span></h3>${fall}<p>${inline(r.hint)}</p>${line}`;
    card.querySelectorAll("[data-line]").forEach((b) => b.addEventListener("click", () => flagLine(+b.dataset.line)));
    $("coach-body").prepend(card);
  } catch (err) {
    const card = document.createElement("div");
    card.className = "hint coach";
    card.innerHTML = `<p class="fallback">${esc(err.message)}</p>`;
    $("coach-body").prepend(card);
  } finally {
    $("ask-btn").disabled = false;
    renderLadder();
  }
}

async function submit() {
  if (!state.problem?.available) return;
  const code = getCode();
  state.lastCode = code;
  $("coach-body").innerHTML = "";
  store.set(`w2a-code-${state.slug}`, code);
  $("submit").disabled = true;
  $("busy").hidden = false;
  clearFlags();
  const usedHint = state.hintLevel;
  try {
    const r = await api("/api/grade", { slug: state.slug, code });
    state.lastFeedback = r.feedback;
    $("result").hidden = false;
    $("r-pill").className = `pill ${r.status}`;
    $("r-pill").textContent = STATUS[r.status] || r.status;
    $("r-summary").innerHTML = inline(r.feedback.summary);
    renderCompile(r.feedback.compile);
    const ws = r.feedback.warnings || [];
    $("r-warnings").hidden = !ws.length;
    $("r-warnings").innerHTML = ws.map((w) => `<li>${inline(w)}</li>`).join("");
    renderWave(r.waveform, (r.outputs || []).filter((o) => o.mismatches).map((o) => o.name));
    renderLadder();
    await refreshProgress({ slug: state.slug, passed: r.status === "pass", hint_level: usedHint });
    $("result").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
  } catch (err) {
    $("result").hidden = false;
    $("r-pill").className = "pill error";
    $("r-pill").textContent = "Error";
    $("r-summary").textContent = err.message;
    ["r-compile", "r-warnings", "r-wave"].forEach((id) => { $(id).hidden = true; });
    $("ladder").hidden = true;
  } finally {
    $("submit").disabled = false;
    $("busy").hidden = true;
  }
}

// ------------------------------------------------------------------ boot

function firstOpenProblem() {
  const unlocked = new Map(state.view.stages.map((s) => [s.id, s.unlocked]));
  const list = allProblems().filter((p) => p.available && (state.explore || unlocked.get(p.stage)));
  return (list.find((p) => !state.progress.problems?.[p.slug]?.solved) || list[0])?.slug;
}

async function boot() {
  if (window.CodeMirror) {
    editor = CodeMirror.fromTextArea($("code"), {
      mode: "verilog", lineNumbers: true, indentUnit: 2, tabSize: 2, viewportMargin: Infinity,
      extraKeys: { "Ctrl-Enter": submit, "Cmd-Enter": submit },
    });
    editor.on("change", () => { if (state.slug) store.set(`w2a-code-${state.slug}`, editor.getValue()); });
  } else {
    $("code").addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") submit(); });
  }
  $("submit").addEventListener("click", submit);
  $("reset").addEventListener("click", () => { if (state.problem?.template) setCode(state.problem.template); });
  $("map-box").open = wideScreen.matches;
  wideScreen.addEventListener("change", (e) => { if (e.matches) $("map-box").open = true; });
  document.querySelectorAll(".radix button").forEach((b) => b.addEventListener("click", () => {
    state.radix = b.dataset.radix;
    store.set("w2a-radix", state.radix);
    if (state.lastWave) renderWave(...state.lastWave);
  }));
  $("ask-btn").addEventListener("click", askCoach);
  api("/api/coach/status").then((s) => {
    state.coachEnabled = s.enabled;
    state.coachModel = s.model;
    if (state.lastFeedback) renderLadder();  // results may already be on screen
  }).catch(() => {});
  $("explore").checked = state.explore;
  $("explore").addEventListener("change", (e) => { state.explore = e.target.checked; store.set("w2a-explore", state.explore); renderMap(); });

  state.curriculum = await api("/api/curriculum");
  await refreshProgress();
  const fromHash = decodeURIComponent(location.hash.slice(1));
  const known = allProblems().some((p) => p.slug === fromHash);
  await openProblem(known ? fromHash : firstOpenProblem());
}

boot().catch((err) => {
  $("p-title").textContent = "Could not load the course";
  $("p-spec").innerHTML = `<p class="empty">${esc(err.message)}</p>`;
});
