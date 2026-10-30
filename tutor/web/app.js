// persona-tutor — front end
//  warm-up: recap last session's key expressions, then listen → shadow → compare
//  lesson: phrases, a grammar point, a model dialogue for the topic (optional; shadow the phrases)
//  conversation: the tutor leads a scenario (practising the lesson); each turn = transcript + reply + feedback
//  ask: a text chat with the tutor at any time, which can look up past mistakes
//  after the session: review + review videos; past sessions; the learner's memory (editable)
// UI text comes from i18n.js (t()).
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const S = {
  mode: "idle",                 // idle | warmup | convo | ended
  warmup: [], i: 0,             // recap items (kind "recap") then warm-up sentences (kind "shadow")
  recall: false,                // recap item: still trying to recall (answer hidden)
  session: null, started: 0, minutes: 5, timer: null,
  lesson: null,                 // {id, scenario, lesson} from /api/lesson, practised by the next conversation
  hints: [], hintLevel: 0, line: "",
  audioQueue: [], playing: null, lastAudio: [],
  recorder: null, chunks: [], busy: false,
  cfg: {}, trLabel: "show_translation",
};

function setStatus(key, ok = false) {
  $("status").textContent = t(key);
  $("status").className = "pill " + (ok ? "ok" : "muted");
}
function show(id, on = true) { $(id).classList.toggle("hidden", !on); }
function enable(ids, on = true) { ids.forEach((id) => ($(id).disabled = !on)); }
function label(id, key, vars) { $(id).textContent = t(key, vars); }

// ---------- NDJSON streaming ----------
async function stream(url, init, onEvent) {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(tMsg((await res.json().catch(() => ({}))).detail || res.statusText));
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const ln = buf.slice(0, nl); buf = buf.slice(nl + 1);
      if (ln.trim()) onEvent(JSON.parse(ln));
    }
  }
}
const postJSON = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// ---------- audio playback queue ----------
function enqueue(url) { S.audioQueue.push(url); if (!S.playing) playNext(); }
function playNext() {
  const url = S.audioQueue.shift();
  if (!url) { S.playing = null; return; }
  S.playing = new Audio(url);
  S.playing.onended = playNext;
  S.playing.onerror = playNext;
  S.playing.play().catch(playNext);
}
function stopAudio() { S.audioQueue = []; if (S.playing) { S.playing.pause(); S.playing = null; } }
function replay() { stopAudio(); S.lastAudio.forEach(enqueue); }

function ttsInfo(ev) {
  const mark = ev.verified ? "✓" : t("tts_unverified");
  const extra = ev.cached ? t("tts_cached") : ev.rephrased_from ? t("tts_rephrased") : ev.attempts > 1 ? t("tts_attempts", { n: ev.attempts }) : "";
  return `${ev.emotion} · ${ev.ref} · ${mark}${extra}`;
}

// ---------- the tutor's line ----------
function renderLine({ text, reading, tokens, translation, note, emotion, trLabel = "show_translation" }) {
  S.line = text;
  $("line").innerHTML = tokens
    ? tokens.map((x) => (x.click ? `<span class="w" data-w="${esc(x.surface)}" data-b="${esc(x.base)}">${esc(x.surface)}</span>` : esc(x.surface))).join("")
    : esc(text);
  $("reading").textContent = reading || "";
  $("translation").textContent = translation || "";
  show("translation", false);
  S.trLabel = trLabel;
  label("show-tr", trLabel);
  enable(["show-tr"], !!translation);
  $("note").textContent = note ? "💡 " + note : "";
  show("note", !!note);
  $("ttsinfo").textContent = emotion ? `${emotion} · ${t("synthesizing")}` : "";
}
function toggleTranslation() {
  const hidden = $("translation").classList.contains("hidden");
  show("translation", hidden);
  label("show-tr", hidden ? "hide" : S.trLabel);
}

// ---------- word explanation popover ----------
async function explainWord(el) {
  const pop = $("pop");
  const r = el.getBoundingClientRect();
  pop.style.left = `${Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - 376)}px`;
  pop.style.top = `${window.scrollY + r.bottom + 6}px`;
  pop.innerHTML = `<span class="w">${esc(el.dataset.w)}</span><span class="r">${esc(t("looking_up"))}</span>`;
  show("pop");
  try {
    const res = await fetch("/api/explain", postJSON({ word: el.dataset.w, base: el.dataset.b, sentence: S.line, session_id: S.session }));
    if (!res.ok) throw new Error((await res.json()).detail);
    const x = await res.json();
    pop.innerHTML = `<span class="w">${esc(el.dataset.w)}</span><span class="r">${esc(x.reading)}</span>` +
      `<div>${esc(x.meaning)}</div><div class="ex">${esc(x.usage)}</div><div class="ex">${esc(t("example", { text: x.example }))}</div>`;
  } catch (e) { pop.innerHTML += `<div class="ex">${esc(t("lookup_failed", { msg: e.message }))}</div>`; }
}
document.addEventListener("click", (e) => {
  const w = e.target.closest("#line .w");
  if (w) { explainWord(w); return; }
  if (!e.target.closest("#pop")) show("pop", false);
});

// ---------- recording (push-to-talk) ----------
async function initMic() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
  S.recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  S.recorder.ondataavailable = (e) => e.data.size && S.chunks.push(e.data);
  S.recorder.onstop = onRecorded;
}
function startRec() {
  if (!S.recorder || S.recorder.state === "recording" || $("rec").disabled) return;
  stopAudio();
  S.chunks = [];
  S.recorder.start();
  $("rec").classList.add("recording");
  label("rec", "recording");
}
function stopRec() {
  if (!S.recorder || S.recorder.state !== "recording") return;
  S.recorder.stop();
  $("rec").classList.remove("recording");
  label("rec", "rec");
}
async function onRecorded() {
  const blob = new Blob(S.chunks, { type: S.recorder.mimeType });
  if (blob.size < 2000) { label("feedback", "too_short"); return; }
  const name = "rec" + (S.recorder.mimeType.includes("mp4") ? ".m4a" : ".webm");
  if (S.mode === "warmup") return shadowTurn(blob, name);
  if (S.mode === "convo") return convoTurn(blob, name);
}

function showMine(text, reading, lang) {
  $("mine").innerHTML = text ? esc(text) + (lang === "native" ? `<span class="tag">${esc(t("native_question"))}</span>` : "")
    : esc(t("no_speech_mine"));
  $("mine").dataset.text = text || "";
  $("mine").classList.toggle("muted", !text);
  $("minereading").textContent = reading || "";
}
function clearMine() { showMine("", ""); $("mine").textContent = "—"; $("mine").dataset.text = ""; }
const triedThisItem = () => $("mine").textContent !== "—";

// ---------- warm-up ----------
async function shadowTurn(blob, name) {
  const s = S.warmup[S.i];
  const fd = new FormData();
  fd.append("audio", blob, name);
  fd.append("target", s.kind === "recap" ? s.better : s.text);
  setStatus("transcribing");
  enable(["rec"], false);
  try {
    const r = await (await fetch("/api/transcribe", { method: "POST", body: fd })).json();
    showMine(r.text, r.reading);
    if (r.compare) showCompare(r.compare, s.kind === "recap" && S.recall);
    if (S.recall) { markRecap(s, r.compare?.score ?? null); return revealRecap(); }
  } catch (e) { label("feedback", "transcribe_failed", { msg: e }); }
  enable(["rec", "retry", "next"]);
  setStatus("ready", true);
}

function showCompare(c, recall = false) {
  const diff = c.ops.map((o) => {
    if (o.op === "equal") return `<span class="equal">${esc(o.ref)}</span>`;
    if (o.op === "missing") return `<span class="missing" title="${esc(t("missing"))}">${esc(o.ref)}</span>`;
    if (o.op === "extra") return `<span class="extra" title="${esc(t("extra"))}">${esc(o.hyp)}</span>`;
    return `<span class="wrong" title="${esc(t("said_as", { hyp: o.hyp }))}">${esc(o.ref)}</span>`;
  }).join("");
  const verdict = recall
    ? t(c.score >= 90 ? "recall_good" : "recall_compare")
    : t(c.score >= 95 ? "verdict_great" : c.score >= 80 ? "verdict_ok" : "verdict_low");
  $("feedback").innerHTML =
    `<div><span class="score">${c.score}</span>${esc(verdict)}</div><div class="diff">${diff}</div>` +
    `<div class="legend"><span style="color:var(--ok)">${esc(t("legend_ok"))}</span><span style="color:var(--miss)">${esc(t("legend_miss"))}</span>` +
    `<span style="color:var(--extra)">${esc(t("legend_extra"))}</span></div><div class="legend">${esc(t("legend_note"))}</div>`;
  $("feedback").classList.remove("muted");
}

async function startWarmup() {
  if (!(await ensureMic())) return;
  S.mode = "warmup";
  const [recap, shadow] = await Promise.all([fetch("/api/recap").then((r) => r.json()), fetch("/api/warmup").then((r) => r.json())]);
  const items = recap ? recap.items.map((x, index) => ({ ...x, kind: "recap", index, dir: recap.dir, date: recap.date, scenario: recap.scenario })) : [];
  S.warmup = [...items, ...shadow.map((x) => ({ ...x, kind: "shadow" }))];
  S.i = 0;
  show("start", false); show("scenario", false); show("lesson", false); show("convo", false);
  show("retry"); show("next"); show("end", false); show("hint", false);
  showSentence();
}

// ---------- views (left menu) ----------
function showView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== "view-" + name));
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  if (name === "lessons") loadLessons().catch(() => {});
  if (name === "history") loadHistory().catch(() => {});
  if (name === "memory") loadMemory().catch(() => {});
}

// ---------- lesson ----------
async function startLesson() {
  enable(["lesson", "convo", "start"], false);
  setStatus("lesson_preparing");
  showView("lesson");
  $("lessonbody").innerHTML = `<p class="muted">${esc(t("lesson_preparing"))}</p>`;
  try {
    const res = await fetch("/api/lesson", postJSON({ scenario: $("scenario").value || null }));
    if (!res.ok) throw new Error(tMsg((await res.json().catch(() => ({}))).detail || res.statusText));
    S.lesson = await res.json();
    $("topic").textContent = S.lesson.scenario.title;
    $("topic-native").textContent = uiTitle(S.lesson.scenario) !== S.lesson.scenario.title ? uiTitle(S.lesson.scenario) : "";
    label("cost", "cost", { cost: S.lesson.cost.toFixed(3) });
    renderLesson($("lessonbody"), S.lesson.lesson, S.lesson.scenario, true);
    renderKeyPoints(S.lesson.lesson);
    show("scenario", false); show("lesson", false); show("start", false);
    label("convo", "start_convo_lesson");
  } catch (e) { $("lessonbody").innerHTML = `<p class="muted">${esc(t("lesson_failed", { msg: e.message }))}</p>`; }
  enable(["lesson", "convo", "start"]);
  setStatus("ready", true);
}

// one line of target-language text with a play button (texts[i] is what the button says)
function sayable(texts, x, cls = "") {
  texts.push(x.text);
  return `<div class="ls-line ${cls}"><button class="play" data-i="${texts.length - 1}" title="${esc(t("replay"))}">▶</button>` +
    `<div><div class="ls-t">${esc(x.text)}</div><div class="reading">${esc(x.reading || "")}</div>` +
    `<div class="rv-note">${esc(x.translation || "")}${x.note ? " — " + esc(x.note) : ""}</div></div></div>`;
}

// key points first (what to use in the conversation), then the dialogue, the grammar explanation and the note
function renderLesson(box, l, scenario, current) {
  const texts = [];
  const who = (d) => (d.speaker === "tutor" ? S.cfg.tutor_name : S.cfg.learner_name);
  const sub = uiTitle(scenario) !== scenario.title ? ` <span class="muted">(${esc(uiTitle(scenario))})</span>` : "";
  const phrases = l.phrases.map((p) => sayable(texts, p)).join("");
  const examples = l.grammar.examples.map((e) => sayable(texts, e)).join("");
  const first = texts.length;
  const dialogue = l.dialogue.map((d) => `<div class="ls-who">${esc(who(d))}</div>` + sayable(texts, d, d.speaker)).join("");
  box.innerHTML =
    `<h2 class="ls-title">${esc(scenario.title)}${sub}</h2>` +
    `<section class="card keypoints"><div class="kp-head">${esc(t("key_points"))}</div>` +
    `<div class="rv-sec">${esc(t("lesson_phrases"))}</div>${phrases}` +
    `<div class="rv-sec">${esc(t("lesson_grammar"))}</div><div class="kp-grammar">${esc(l.grammar.point)}</div>` +
    `<div class="ls-expl">${esc(l.grammar.explanation)}</div>${examples}</section>` +
    (current ? `<div class="row"><button class="ls-shadow">${esc(t("lesson_shadow"))}</button>` +
      `<button class="ls-convo primary">${esc(t("start_convo_lesson"))}</button></div>` : "") +
    `<section class="card"><h2>${esc(t("lesson_dialogue"))} <button class="playall small">${esc(t("play_dialogue"))}</button></h2>${dialogue}</section>` +
    (l.culture ? `<section class="card"><h2>${esc(t("lesson_culture"))}</h2><div class="ls-expl">${esc(l.culture)}</div></section>` : "");
  box.querySelectorAll(".play").forEach((b) => (b.onclick = () => synthAndPlay(texts[b.dataset.i], "neutral")));
  box.querySelector(".playall").onclick = () => playAll(texts.slice(first));
  if (current) {
    box.querySelector(".ls-shadow").onclick = () => shadowLesson(l);
    box.querySelector(".ls-convo").onclick = () => { showView("practice"); startConvo(); };
  }
}

// the practice view keeps the key points in sight during the conversation
function renderKeyPoints(l) {
  $("kp-body").innerHTML = l.phrases.map((p) => `<span class="kp-chip" title="${esc(p.translation)}">${esc(p.text)}</span>`).join("") +
    `<div class="kp-grammar">${esc(t("lesson_grammar"))}: ${esc(l.grammar.point)}</div>` +
    `<div class="ls-expl">${esc(l.grammar.explanation)}</div>`;
  show("keypoints");
}

// past lessons: read again (and listen)
async function loadLessons() {
  const list = await (await fetch("/api/lessons")).json();
  $("lessons").innerHTML = list.length ? "" : `<li class="muted">${esc(t("no_lessons"))}</li>`;
  for (const x of list) {
    const li = document.createElement("li");
    const sub = uiTitle(x.scenario) !== x.scenario.title ? ` <span class="muted">(${esc(uiTitle(x.scenario))})</span>` : "";
    li.innerHTML = `<a href="#" class="ls-link"><b>${esc(x.date.slice(0, 16))}</b> ${esc(x.scenario.title)}</a>${sub}`;
    li.querySelector("a").onclick = (e) => {
      e.preventDefault();
      renderLesson($("pastlesson"), x.lesson, x.scenario, false);
      $("pastlesson").scrollIntoView({ behavior: "smooth" });
    };
    $("lessons").appendChild(li);
  }
}

// the dialogue line by line, in order (each line's audio queued as soon as it is ready)
async function playAll(texts) {
  S.lastAudio = []; stopAudio();
  for (const text of texts) {
    try {
      await stream("/api/say", postJSON({ text, emotion: "neutral" }), (ev) => {
        if (ev.type === "segment") { S.lastAudio.push(ev.audio); enqueue(ev.audio); }
      });
    } catch (e) { $("ttsinfo").textContent = t("error", { msg: e.message }); return; }
  }
}

// shadow the lesson's phrases with the warm-up flow (listen → say → compare)
async function shadowLesson(l) {
  if (!(await ensureMic())) return;
  showView("practice");
  S.mode = "warmup";
  S.warmup = l.phrases.map((p) => ({ ...p, kind: "shadow", emotion: "neutral" }));
  S.i = 0;
  show("start", false); show("scenario", false); show("lesson", false); show("convo", false);
  show("retry"); show("next"); show("end", false); show("hint", false);
  showSentence();
}

async function synthAndPlay(text, emotion) {
  S.lastAudio = []; stopAudio();
  try {
    await stream("/api/say", postJSON({ text, emotion }), (ev) => {
      if (ev.type === "segment") { S.lastAudio.push(ev.audio); enqueue(ev.audio); $("ttsinfo").textContent = ttsInfo(ev); }
    });
  } catch (e) { $("ttsinfo").textContent = t("error", { msg: e.message }); }
}

async function showSentence() {
  const s = S.warmup[S.i];
  $("progress").textContent = `${S.i + 1} / ${S.warmup.length}`;
  label("retry", "retry");
  if (s.kind === "recap") return showRecall(s);
  label("topic", "topic_warmup"); $("topic-native").textContent = "";
  renderLine({ text: s.text, reading: s.reading, translation: s.translation, emotion: s.emotion });
  clearMine();
  label("feedback", "listen_then_repeat"); $("feedback").classList.add("muted");
  enable(["rec", "retry", "next", "replay"], false);
  setStatus("synthesizing");
  await synthAndPlay(s.text, s.emotion);
  setStatus("ready", true);
  enable(["rec", "replay", "next"]);
  label("next", S.i + 1 < S.warmup.length ? "next" : "finish_warmup");
}

// ---------- recap: recall last session's key expressions ----------
function showRecall(s) {
  S.recall = true;
  label("topic", "topic_recap");
  $("topic-native").textContent = `${s.date.slice(5, 10)} · ${s.scenario}`;
  renderLine({ text: s.said, reading: s.said_reading, translation: s.reason, trLabel: "show_reason", note: t("recap_note") });
  clearMine();
  label("feedback", "recap_hint"); $("feedback").classList.add("muted");
  stopAudio(); S.lastAudio = [];
  label("retry", "show_answer");
  label("next", "next");
  enable(["rec", "retry", "next"]); enable(["replay"], false);
  setStatus("ready", true);
}

async function revealRecap() {
  const s = S.warmup[S.i];
  if (S.recall && !triedThisItem()) markRecap(s, null);  // gave up without trying
  S.recall = false;
  renderLine({ text: s.better, reading: s.reading, note: s.reason, emotion: "neutral" });
  label("retry", "retry");
  enable(["rec", "retry", "next", "replay"], false);
  setStatus("synthesizing");
  await synthAndPlay(s.better, "neutral");
  if (!triedThisItem()) label("feedback", "listen_then_repeat");
  setStatus("ready", true);
  enable(["rec", "retry", "next", "replay"]);
  label("next", S.i + 1 < S.warmup.length ? "next" : "finish_warmup");
}

function markRecap(s, score) {
  fetch("/api/recap/mark", postJSON({ dir: s.dir, index: s.index, score })).catch(() => {});
}

function nextWarmup() {
  if (S.i + 1 < S.warmup.length) { S.i++; showSentence(); return; }
  S.mode = "idle"; S.recall = false;
  label("topic", "warmup_done"); $("progress").textContent = "";
  renderLine({ text: t("warmup_done_line") });
  show("retry", false); show("next", false);
  enable(["rec"], false);
  if (S.lesson) { label("topic", "topic_lesson"); show("convo"); label("convo", "start_convo_lesson"); return; }
  show("scenario"); show("lesson"); show("convo");
  label("start", "warmup_again"); show("start");
}

// ---------- conversation ----------
async function ensureMic() {
  if (S.recorder) return true;
  try { await initMic(); return true; } catch (e) { label("feedback", "mic_failed", { msg: e }); return false; }
}

function tick() {
  const sec = Math.floor((Date.now() - S.started) / 1000);
  const mm = String(Math.floor(sec / 60)).padStart(2, "0"), ss = String(sec % 60).padStart(2, "0");
  $("timer").textContent = `${mm}:${ss} / ${S.minutes}:00`;
}

function logTurn(html) { const li = document.createElement("li"); li.innerHTML = html; $("log").appendChild(li); return li; }
const tutorSays = (text) => `<span class="m">${esc(S.cfg.tutor_name)}: </span>${esc(text)}`;

// One reply stream (session start / turn / end). Handles reply, segments, feedback.
async function runReply(url, init, { onTranscript } = {}) {
  S.busy = true;
  enable(["rec", "hint", "end"], false);
  setStatus("thinking");
  S.lastAudio = []; stopAudio();
  let logLi = null, closing = false, lastSeg = null;
  try {
    await stream(url, init, (ev) => {
      if (ev.type === "session") {
        S.session = ev.id;
        $("topic").textContent = ev.scenario.title;
        $("topic-native").textContent = uiTitle(ev.scenario) !== ev.scenario.title ? uiTitle(ev.scenario) : "";
      } else if (ev.type === "transcript") {
        showMine(ev.text, ev.reading, ev.lang);
        if (ev.text) onTranscript?.(ev);
        $("feedback").innerHTML = `<span class="muted">${esc(t(ev.lang === "target" ? "checking" : "not_graded"))}</span>`;
      } else if (ev.type === "feedback") {
        showFeedback(ev);
        if (S.lastUserLi && !ev.natural) S.lastUserLi.innerHTML += `<div class="fbx">${ev.verdict === "misheard" ? "?" : "→"} ${esc(ev.natural_rewrite)}</div>`;
      } else if (ev.type === "feedback_error") {
        $("feedback").innerHTML = `<span class="muted">${esc(t("feedback_unavailable", { msg: ev.message }))}</span>`;
      } else if (ev.type === "reply_text") {
        // streaming: show the line as it is written; the final "reply" makes words clickable
        if (!logLi) { renderLine({ text: ev.text, emotion: ev.emotion }); show("hintbox", false); logLi = logTurn(""); }
        $("line").textContent = ev.text;
        logLi.innerHTML = tutorSays(ev.text);
      } else if (ev.type === "reply") {
        renderLine(ev);
        $("ttsinfo").textContent = lastSeg ? ttsInfo(lastSeg) : "";
        S.hints = ev.hints || []; S.hintLevel = 0; show("hintbox", false);
        closing = ev.closing;
        if (ev.cost != null) label("cost", "cost", { cost: ev.cost.toFixed(3) });
        if (!logLi) logLi = logTurn("");
        logLi.innerHTML = tutorSays(ev.text);
      } else if (ev.type === "segment") {
        lastSeg = ev;
        S.lastAudio.push(ev.audio); enqueue(ev.audio);
        $("ttsinfo").textContent = ttsInfo(ev);
        enable(["replay"]);
      } else if (ev.type === "error") {
        $("feedback").innerHTML = `<span class="muted">${esc(ev.key ? tMsg(ev.key) : ev.message)}</span>`;
      }
    });
  } catch (e) {
    label("feedback", "error", { msg: e.message });
  }
  S.busy = false;
  if (closing) return endConvoUI();
  setStatus("ready", true);
  enable(["rec", "end"]);
  enable(["hint"], S.hints.length > 0);
}

function showFeedback(fb) {
  if (fb.natural) { $("feedback").innerHTML = `<span class="fb-ok">${esc(t("natural"))}</span>`; return; }
  const said = `<div class="fbrow"><span class="k">${esc(t("fb_said"))}</span><span class="fb-said">${esc($("mine").dataset.text)}</span></div>`;
  const why = `<div class="fbrow"><span class="k">${esc(t("fb_why"))}</span>${esc(fb.feedback)}</div>`;
  const better = (key) => `<div class="fbrow"><span class="k">${esc(t(key))}</span><span class="fb-better">${esc(fb.natural_rewrite)}</span></div>`;
  $("feedback").innerHTML =
    fb.verdict === "misheard" ? `<div class="fb-soft">${esc(t("fb_misheard"))}</div>${better("fb_meant")}` :
    fb.verdict === "suggestion" ? `<div class="fb-soft">${esc(t("fb_suggestion"))}</div>${better("fb_better")}${why}` :
    `${said}${better("fb_better")}${why}<div class="row"><button id="fb-dismiss" class="small">${esc(t("fb_dismiss"))}</button></div>`;
  $("feedback").classList.remove("muted");
  const dismiss = $("fb-dismiss");
  if (dismiss) dismiss.onclick = async () => {
    dismiss.disabled = true;
    const res = await fetch("/api/feedback/dismiss", postJSON({ session_id: S.session, turn: fb.turn }));
    dismiss.textContent = res.ok ? t("fb_dismissed") : t("error", { msg: res.statusText });
  };
}

async function startConvo() {
  if (!(await ensureMic())) return;
  S.mode = "convo";
  S.started = Date.now();
  clearInterval(S.timer); S.timer = setInterval(tick, 1000); tick();
  $("log").innerHTML = ""; $("logbox").open = false;
  show("start", false); show("scenario", false); show("lesson", false); show("convo", false);
  show("retry", false); show("next", false); show("hint"); show("end");
  $("progress").textContent = "";
  clearMine();
  label("feedback", "convo_intro"); $("feedback").classList.add("muted");
  if (!S.lesson) show("keypoints", false);
  await runReply("/api/session/start", postJSON({ scenario: $("scenario").value || null, lesson: S.lesson?.id || null }));
}

async function convoTurn(blob, name) {
  const fd = new FormData();
  fd.append("session_id", S.session);
  fd.append("audio", blob, name);
  label("mine", "transcribing");
  await runReply("/api/turn", { method: "POST", body: fd }, {
    onTranscript: (ev) => { S.lastUserLi = logTurn(`${esc(t("i_said"))}: ${esc(ev.text)}`); },
  });
}

async function endConvo() {
  if (S.busy) return;
  await runReply("/api/session/end", postJSON({ session_id: S.session }));
}

function endConvoUI() {
  S.mode = "ended";
  clearInterval(S.timer);
  setStatus("session_over", true);
  enable(["rec", "hint", "end"], false);
  show("end", false); show("hint", false);
  $("logbox").open = true;
  label("start", "warmup_again"); show("start");
  show("scenario"); show("lesson"); show("convo"); label("convo", "convo_again");
  S.lesson = null;
  loadReview();
}

async function loadReview() {
  show("reviewbox");
  $("review").innerHTML = `<span class="muted">${esc(t("review_loading"))}</span>`;
  try {
    const res = await fetch("/api/session/review", postJSON({ session_id: S.session }));
    if (!res.ok) throw new Error((await res.json()).detail);
    const r = await res.json();
    label("cost", "cost", { cost: r.cost.toFixed(3) });
    const exp = r.expressions.map((e) =>
      `<div class="rv-exp"><span class="fb-said">${esc(e.said)}</span> → <span class="fb-better">${esc(e.better)}</span><div class="rv-note">${esc(e.reason)}</div></div>`).join("");
    const turns = r.turns.map((x) => `<div class="rv-turn">
      <div class="rv-row"><span class="k">${esc(t("i_said"))}</span>${esc(x.said)}${x.lang === "native" ? `<span class="tag">${esc(t("own_language"))}</span>` : ""}</div>
      <div class="rv-row"><span class="k">${esc(t("corrected"))}</span>${x.corrected_reason ? `<b>${esc(x.corrected)}</b><div class="rv-note">${esc(x.corrected_reason)}</div>` : `<span class="fb-ok">${esc(t("fine_as_is"))}</span>`}</div>
      <div class="rv-row"><span class="k">${esc(t("model"))}</span><span class="rv-up">${esc(x.upgraded)}</span><div class="rv-note">${esc(x.translation)}</div><div class="rv-note">💡 ${esc(x.upgrade_note)}</div></div>
    </div>`).join("");
    const mark = (u) => (u.used ? (u.correct ? "used_ok" : "used_wrong") : "not_used");
    const lessonUse = r.lesson_use?.length
      ? `<div class="rv-sec">${esc(t("review_lesson"))}</div>` + r.lesson_use.map((u) =>
        `<div class="rv-row"><span class="lu ${mark(u)}">${esc(t(mark(u)))}</span> ${esc(u.item)}${u.note ? `<div class="rv-note">${esc(u.note)}</div>` : ""}</div>`).join("")
      : "";
    if (r.memory_updated) loadMemory();
    $("review").innerHTML = `${lessonUse}<div class="rv-sec">${esc(t("review_key"))}</div>${exp}<div class="rv-sec">${esc(t("review_lines"))}</div><div class="rv-note">${esc(t("explain_modes"))}</div>${turns}` +
      `<div class="rv-sec">${esc(t("review_video"))}</div><div id="rv-video"></div>` +
      `<div class="rv-note">${esc(t("saved_to", { dir: r.dir }))}</div>`;
    $("review").classList.remove("muted");
    videoBlock($("rv-video"), r.dir, r.videos);
    loadHistory().catch(() => {});
  } catch (e) { label("review", "review_failed", { msg: e.message }); }
}

// ---------- review videos ----------
function videoLabel(v) { return t("mode_" + v.mode) + (v.shadow ? t("shadowing") : ""); }

function videoBlock(box, dir, videos) {
  const players = (videos || []).map((v) =>
    `<div class="vid"><div class="k">${esc(videoLabel(v))} <span class="muted">— ${esc(t("explain_" + v.mode + "_video"))}</span></div><video controls preload="metadata" src="${esc(v.mp4)}"></video>` +
    `<a href="${esc(v.mp3)}" download>${esc(t("download_mp3"))}</a></div>`).join("");
  box.innerHTML = players +
    `<div class="row"><button class="mkvid">${esc(t(videos?.length ? "remake_video" : "make_video"))}</button>` +
    `<span class="muted small">${esc(t("video_note"))}</span></div><pre class="small vlog hidden"></pre>`;
  box.querySelector(".mkvid").onclick = () => makeVideo(box, dir);
}

function progressText(ev) {
  const a = { ...ev.args };
  if (ev.key === "voice_retry") a.status = t(a.ok ? "p_ok" : "p_failed");
  return t("p_" + ev.key, a);
}

async function makeVideo(box, dir) {
  const btn = box.querySelector(".mkvid"), log = box.querySelector(".vlog");
  btn.disabled = true; log.classList.remove("hidden"); log.textContent = "";
  const lock = ["start", "convo"];
  enable(lock, false);
  setStatus("rendering_status");
  let videos = null;
  const add = (s) => { log.textContent += s + "\n"; log.scrollTop = log.scrollHeight; };
  try {
    await stream("/api/session/video", postJSON({ dir }), (ev) => {
      if (ev.type === "progress") add(progressText(ev));
      else if (ev.type === "videos") videos = ev.videos;
      else if (ev.type === "error") add(t("error", { msg: ev.message }));
    });
  } catch (e) { add(t("error", { msg: e.message })); }
  enable(lock);
  setStatus("ready", true);
  if (videos) { const text = log.textContent; videoBlock(box, dir, videos); box.querySelector(".vlog").textContent = text; }
  else btn.disabled = false;
}

// ---------- past sessions ----------
// scenario: {title (target language), titles: {code: title}, title_en}; show the UI-language title next to it
const uiTitle = (sc) => sc.titles?.[LANG] || sc.title_en || sc.title;

async function loadHistory() {
  const list = await (await fetch("/api/history")).json();
  $("history").innerHTML = list.length ? "" : `<li class="muted">${esc(t("no_history"))}</li>`;
  for (const h of list) {
    const li = document.createElement("li");
    const sub = uiTitle(h.scenario) !== h.scenario.title ? ` <span class="muted">(${esc(uiTitle(h.scenario))})</span>` : "";
    li.innerHTML = `<div><b>${esc(h.date.slice(0, 16))}</b> ${esc(h.scenario.title)}${sub}</div><div class="hv"></div>`;
    $("history").appendChild(li);
    videoBlock(li.querySelector(".hv"), h.dir, h.videos);
  }
}

// ---------- ask: a text chat, kept only on this page ----------
const askLog = [];   // {role, text}, sent whole with each question

async function sendAsk() {
  const q = $("ask-text").value.trim();
  if (!q || $("ask-send").disabled) return;
  enable(["ask-send"], false);
  $("ask-text").value = "";
  askLog.push({ role: "user", text: q });
  const log = $("ask-log");
  const add = (cls, text) => {
    const el = document.createElement("div");
    el.className = cls; el.textContent = text;
    log.append(el); el.scrollIntoView({ block: "nearest" });
    return el;
  };
  add("ask-msg me", q);
  const el = add("ask-msg", "…");
  try {
    await stream("/api/ask", postJSON({ messages: askLog }), (ev) => {
      if (ev.type === "delta") el.textContent = ev.text;
      else if (ev.type === "error") throw new Error(ev.message);
      else if (ev.type === "answer") {
        el.textContent = ev.text;
        askLog.push({ role: "assistant", text: ev.text });
        // say when it looked up past mistakes (and how many came back)
        ev.tool_calls.forEach((c) => el.before(Object.assign(document.createElement("div"), {
          className: "muted small", textContent: t("looked_up_mistakes", { kind: c.input?.category || t("all_kinds"), n: c.is_error ? "!" : c.count }),
        })));
      }
      el.scrollIntoView({ block: "nearest" });
    });
  } catch (e) {
    askLog.pop();              // the question stays in the box, ready to send again
    $("ask-text").value = q;
    el.textContent = t("error", { msg: e.message });
  }
  enable(["ask-send"]);
  $("ask-text").focus();
}

// ---------- memory: what the tutor remembers (data/learner.json), editable ----------
const MEM_FIELDS = ["level", "errors", "mastered", "topics", "about"];

async function loadMemory() {
  const m = await (await fetch("/api/memory")).json();
  $("memory").innerHTML = MEM_FIELDS.map((k) => {
    const v = k === "level" ? m.level : (m[k] || []).join("\n");
    const hint = k === "level" ? "" : ` <span class="muted small">(${esc(t("mem_one_per_line"))})</span>`;
    return `<label class="mem"><span class="k">${esc(t("mem_" + k))}</span>${hint}<textarea data-k="${k}" rows="${k === "level" ? 2 : 4}">${esc(v)}</textarea></label>`;
  }).join("");
  $("mem-status").textContent = m.updated ? t("mem_when", { when: m.updated.slice(0, 16) }) : t("mem_empty");
}

async function saveMemory() {
  const body = {};
  $("memory").querySelectorAll("textarea").forEach((el) => {
    body[el.dataset.k] = el.dataset.k === "level" ? el.value : el.value.split("\n");
  });
  try {
    const res = await fetch("/api/memory", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(res.statusText);
    await loadMemory();
    $("mem-status").textContent = t("mem_saved");
  } catch (e) { $("mem-status").textContent = t("error", { msg: e.message }); }
}

// ---------- hints: 1st = keywords, 2nd = model answer (with audio) ----------
async function hint() {
  if (!S.hints.length) return;
  S.hintLevel++;
  const box = $("hintbox");
  show("hintbox");
  if (S.hintLevel === 1) {
    box.innerHTML = `<span class="k">${esc(t("keywords"))}</span>${esc(S.hints[0])}`;
    label("hint", "hint_more");
    return;
  }
  box.innerHTML = `<div><span class="k">${esc(t("keywords"))}</span>${esc(S.hints[0])}</div>` +
    `<div><span class="k">${esc(t("model_answer"))}</span>${esc(S.hints[1] || "")}</div>`;
  enable(["hint"], false);
  label("hint", "hint");
  if (S.hints[1]) await synthAndPlay(S.hints[1], "neutral");
}

// ---------- TTS test tool ----------
async function ttsTest() {
  enable(["t-say"], false);
  $("t-log").textContent = "";
  const t0 = performance.now();
  S.lastAudio = []; stopAudio();
  try {
    await stream("/api/say", postJSON({ text: $("t-text").value, emotion: $("t-emo").value, fresh: true }), (ev) => {
      if (ev.type !== "segment") return;
      S.lastAudio.push(ev.audio); enqueue(ev.audio);
      const sec = ((performance.now() - t0) / 1000).toFixed(1);
      $("t-log").textContent += `[${sec}s] ${ev.text}\n  ${ttsInfo(ev)} · ASR: ${ev.asr} (CER ${ev.cer})\n`;
    });
  } catch (e) { $("t-log").textContent += t("error", { msg: e.message }); }
  enable(["t-say", "replay"]);
}

// ---------- wiring ----------
$("start").onclick = startWarmup;
$("next").onclick = nextWarmup;
$("retry").onclick = () => {
  if (S.recall) return revealRecap();
  label("feedback", "listen_again"); replay();
};
$("replay").onclick = replay;
$("show-tr").onclick = toggleTranslation;
$("convo").onclick = startConvo;
$("lesson").onclick = startLesson;
$("mem-save").onclick = saveMemory;
$("ask-send").onclick = sendAsk;
$("ask-text").addEventListener("keydown", (e) => {   // not while an IME is composing: Enter confirms the kana/kanji there
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendAsk(); }
});
$("hint").onclick = hint;
$("end").onclick = endConvo;
$("t-say").onclick = ttsTest;
document.querySelectorAll("#nav button").forEach((b) => (b.onclick = () => showView(b.dataset.view)));
$("kp-open").onclick = () => showView("lesson");
const rec = $("rec");
rec.addEventListener("pointerdown", (e) => { e.preventDefault(); startRec(); });
rec.addEventListener("pointerup", stopRec);
rec.addEventListener("pointerleave", stopRec);
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !e.repeat && !["TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) { e.preventDefault(); startRec(); }
});
document.addEventListener("keyup", (e) => { if (e.code === "Space") { e.preventDefault(); stopRec(); } });

// config first: it decides the UI language, then everything else renders in it
fetch("/api/config").then((r) => r.json()).then((c) => {
  S.cfg = c;
  // ?lang=en / ?lang=zh-TW overrides config.yaml ui_language for this page
  setLanguage(new URLSearchParams(location.search).get("lang") || c.ui_language, { tutor: c.tutor_name });
  setLanguage(LANG, { target: t("lang_" + c.target) });   // language name in the UI language
  $("apptitle").textContent = t("title");
  $("avatar").textContent = [...c.tutor_name][0] || "?";
  if (c.avatar) {
    $("avatar").textContent = "";
    Object.assign($("avatar").style, { backgroundImage: "url(/api/avatar)", backgroundSize: "cover", backgroundPosition: "center" });
  }
  $("level").textContent = t("lang_" + c.target);
  $("level").title = c.level;
  S.minutes = c.session_minutes;
  if (c.llm_error) { setStatus("llm_missing"); label("feedback", "llm_missing_detail", { msg: c.llm_error }); }
  else setStatus("ready", true);
  fetch("/api/recap").then((r) => r.json()).then((r) => {
    if (r?.items?.length) label("start", "start_warmup_recap", { n: r.items.length });
  }).catch(() => {});
  fetch("/api/scenarios").then((r) => r.json()).then((list) => {
    $("scenario").innerHTML = `<option value="">${esc(t("topic_random"))}</option>` +
      list.map((s) => `<option value="${esc(s.id)}">${esc(s.title)}${uiTitle(s) !== s.title ? ` (${esc(uiTitle(s))})` : ""}</option>`).join("");
    show("scenario"); show("lesson"); show("convo");
  });
  fetch("/api/warmup").then((r) => r.json()).then((w) => { if (w[0]) $("t-text").value = w[0].text; }).catch(() => {});
  loadHistory().catch(() => {});
  loadMemory().catch(() => {});
}).catch(() => setStatus("offline"));
