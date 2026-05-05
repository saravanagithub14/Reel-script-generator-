/* ════════════════════════════════════════════
   ViralCraft AI — Frontend App Logic v2
   Multi-provider: Groq · Ollama · Anthropic
═══════════════════════════════════════════ */

const API = "http://127.0.0.1:8000";

// ── State ──────────────────────────────────────────────────
let currentMode     = "topic";     // "topic" | "paragraph"
let currentProvider = "groq";      // "groq" | "ollama" | "anthropic"
let activeJobId     = null;
let jobPollTimer    = null;
let loadingTimer    = null;

// ── Boot ───────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  checkHealth();
  loadStyleMemory();
});

// ── Health Check & Provider Sync ───────────────────────────
async function checkHealth() {
  const dot   = document.getElementById("statusDot");
  const label = document.getElementById("statusLabel");
  const pstat = document.getElementById("providerStatus");

  try {
    const res  = await fetch(`${API}/api/health`);
    const data = await res.json();

    // Sync active provider from server .env
    const serverProvider = data.active_provider || "groq";
    selectProvider(serverProvider, /* fromServer */ true);

    dot.classList.add("online");
    label.textContent = `Ready · ${data.style_transcripts} style reels`;

    // Show provider readiness hint
    if (!data.provider_ready) {
      const hints = {
        groq:      "Add GROQ_API_KEY to backend/.env — free at console.groq.com",
        anthropic: "Add ANTHROPIC_API_KEY to backend/.env",
        ollama:    "Start Ollama: ollama serve",
      };
      const msg = hints[serverProvider] || "Check backend/.env";
      showToast(`⚠ ${msg}`, "error", 7000);
      pstat.textContent = "⚠ Not configured";
      pstat.className   = "provider-status warn";
    } else {
      pstat.textContent = `✓ ${data.active_provider} · ${data.whisper_model} whisper`;
      pstat.className   = "provider-status ok";
    }
  } catch {
    dot.classList.add("offline");
    label.textContent       = "Backend offline — run start.bat";
    pstat.textContent       = "× Backend not running";
    pstat.className         = "provider-status error";
    showToast("Backend not running. Double-click start.bat to start.", "error", 8000);
  }
}

// ── Provider Picker ────────────────────────────────────────
function selectProvider(provider, fromServer = false) {
  currentProvider = provider;

  // Update pill active state
  ["groq", "ollama", "anthropic"].forEach(p => {
    const pill = document.getElementById(`pill-${p}`);
    if (pill) pill.classList.toggle("active", p === provider);
  });

  // Show/hide model selector (only for Groq)
  const modelWrap = document.getElementById("modelSelectWrap");
  if (modelWrap) modelWrap.style.display = provider === "groq" ? "" : "none";

  // Update generate button label
  const providerNames = { groq: "Groq", ollama: "Ollama", anthropic: "Claude" };
  const generateBtn = document.getElementById("generateBtn");
  if (generateBtn) {
    generateBtn.innerHTML = `<span class="btn-icon">✨</span> Generate via ${providerNames[provider] || provider}`;
  }

  if (!fromServer) {
    // Brief visual feedback
    const pstat = document.getElementById("providerStatus");
    if (pstat) {
      const hints = {
        groq:      "Using Groq (free) — Llama 3 / Mixtral",
        ollama:    "Using Ollama (local) — no internet needed",
        anthropic: "Using Anthropic Claude (paid)",
      };
      pstat.textContent = hints[provider] || "";
      pstat.className   = "provider-status ok";
    }
  }
}

// ── Mode Toggle ─────────────────────────────────────────────
function setMode(mode) {
  currentMode = mode;
  const topicBtn      = document.getElementById("modeTopicBtn");
  const paraBtn       = document.getElementById("modeParagraphBtn");
  const topicWrap     = document.getElementById("topicInputWrapper");
  const paraWrap      = document.getElementById("paragraphInputWrapper");
  const title         = document.getElementById("inputTitle");
  const subtitle      = document.getElementById("inputSubtitle");

  if (mode === "topic") {
    topicBtn.classList.add("active");    topicBtn.setAttribute("aria-selected", "true");
    paraBtn.classList.remove("active");  paraBtn.setAttribute("aria-selected", "false");
    topicWrap.classList.remove("hidden");
    paraWrap.classList.add("hidden");
    title.textContent    = "Enter Your Topic";
    subtitle.textContent = "Type a tech topic or keyword in English or Malayalam";
  } else {
    paraBtn.classList.add("active");     paraBtn.setAttribute("aria-selected", "true");
    topicBtn.classList.remove("active"); topicBtn.setAttribute("aria-selected", "false");
    paraWrap.classList.remove("hidden");
    topicWrap.classList.add("hidden");
    title.textContent    = "Paste Research Content";
    subtitle.textContent = "Paste any article, notes, or paragraph — AI extracts the viral angle";
  }
}

// ── Download & Transcribe ───────────────────────────────────
async function startDownload() {
  const raw  = document.getElementById("urlInput").value.trim();
  const urls = raw.split("\n").map(u => u.trim()).filter(u => u.length > 0);

  if (urls.length === 0) { showToast("Paste at least one reel link", "error"); return; }

  const btn  = document.getElementById("downloadBtn");
  const prog = document.getElementById("progressBlock");
  const bar  = document.getElementById("progressBar");
  const lbl  = document.getElementById("progressLabel");

  btn.disabled = true;
  prog.classList.remove("hidden");
  bar.style.width  = "15%";
  lbl.textContent  = `Queuing ${urls.length} reel(s)...`;

  try {
    const res  = await fetch(`${API}/api/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Download failed");

    activeJobId = data.job_id;
    pollJob(activeJobId, bar, lbl, btn, prog);
  } catch (e) {
    showToast(`Error: ${e.message}`, "error");
    btn.disabled = false;
    prog.classList.add("hidden");
  }
}

function pollJob(jobId, bar, lbl, btn, prog) {
  let dots = 0;
  jobPollTimer = setInterval(async () => {
    try {
      const res  = await fetch(`${API}/api/job/${jobId}`);
      const data = await res.json();

      const w = parseFloat(bar.style.width) || 15;
      if (w < 85) bar.style.width = Math.min(w + 5, 85) + "%";

      dots = (dots + 1) % 4;
      lbl.textContent = (data.progress || "Processing") + ".".repeat(dots);

      if (data.status === "done") {
        clearInterval(jobPollTimer);
        bar.style.width = "100%";
        lbl.textContent = "Done!";

        const results = data.result || [];
        const ok  = results.filter(r => r.status === "success").length;
        const bad = results.filter(r => r.status === "error").length;

        showToast(
          bad === 0 ? `✅ ${ok} reel(s) transcribed & stored` : `✅ ${ok} done · ❌ ${bad} failed`,
          bad === 0 ? "success" : "error"
        );

        document.getElementById("urlInput").value = "";
        setTimeout(() => {
          btn.disabled = false;
          prog.classList.add("hidden");
          bar.style.width = "0%";
        }, 2000);

        loadStyleMemory();
        checkHealth();
      }
    } catch {
      clearInterval(jobPollTimer);
      btn.disabled = false;
      prog.classList.add("hidden");
      showToast("Connection lost while tracking job", "error");
    }
  }, 1500);
}

// ── Style Memory UI ────────────────────────────────────────
async function loadStyleMemory() {
  try {
    const res  = await fetch(`${API}/api/style-memory`);
    const data = await res.json();
    renderTranscripts(data.transcripts || []);
    document.getElementById("transcriptCount").textContent =
      `${data.count} reel${data.count !== 1 ? "s" : ""}`;
  } catch {
    // health check shows backend errors
  }
}

function renderTranscripts(transcripts) {
  const container = document.getElementById("transcriptList");
  if (transcripts.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <span class="empty-icon">🎞️</span>
        <p>No reels added yet.<br/>Add links above to train your style.</p>
      </div>`;
    return;
  }
  container.innerHTML = transcripts.map((t, i) => `
    <div class="transcript-item" id="ti-${i}">
      <div class="transcript-thumb">🎬</div>
      <div class="transcript-info">
        <div class="transcript-title" title="${escapeHtml(t.title)}">${escapeHtml(t.title)}</div>
        <div class="transcript-preview">${escapeHtml(t.preview)}</div>
      </div>
      <button class="transcript-delete" title="Remove" onclick="deleteTranscript(${t.index})">✕</button>
    </div>
  `).join("");
}

async function deleteTranscript(index) {
  try {
    const res = await fetch(`${API}/api/style-memory/${index}`, { method: "DELETE" });
    if (!res.ok) throw new Error("Failed to delete");
    showToast("Reel removed from style memory", "success");
    loadStyleMemory();
    checkHealth();
  } catch (e) { showToast(`Error: ${e.message}`, "error"); }
}

async function clearStyleMemory() {
  if (!confirm("Clear all style memory? This cannot be undone.")) return;
  try {
    await fetch(`${API}/api/style-memory`, { method: "DELETE" });
    showToast("Style memory cleared", "success");
    loadStyleMemory();
    checkHealth();
  } catch (e) { showToast(`Error: ${e.message}`, "error"); }
}

// ── Script Generation ──────────────────────────────────────
async function generateScript() {
  const topic = currentMode === "topic"
    ? document.getElementById("topicInput").value.trim()
    : document.getElementById("paragraphInput").value.trim();

  if (!topic) {
    showToast(currentMode === "topic" ? "Enter a topic first" : "Paste your research content first", "error");
    return;
  }

  // Build provider override — include selected Groq model if applicable
  let providerOverride = currentProvider;
  const selectedModel  = document.getElementById("modelSelect")?.value;

  // Show loading state
  document.getElementById("inputCard").classList.add("hidden");
  document.getElementById("outputCard").classList.add("hidden");
  document.getElementById("loadingCard").classList.remove("hidden");
  document.getElementById("generateBtn").disabled = true;

  // Update loading subtitle with provider info
  const providerLabel = { groq: `Groq (${selectedModel || "llama-3.3-70b"})`, ollama: "Ollama (local)", anthropic: "Anthropic Claude" };
  document.getElementById("loadingSubtitle").textContent =
    `Generating via ${providerLabel[currentProvider] || currentProvider}...`;

  animateLoadingSteps();

  try {
    const body = {
      topic,
      is_paragraph: currentMode === "paragraph",
      provider: providerOverride,
    };

    // Pass selected Groq model as a hint in topic if needed
    // (actual model selection is server-side via env, but we show it in UI)
    const res = await fetch(`${API}/api/generate-script`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Generation failed");

    displayScript(data);
  } catch (e) {
    showToast(`Error: ${e.message}`, "error");
    document.getElementById("loadingCard").classList.add("hidden");
    document.getElementById("inputCard").classList.remove("hidden");
    document.getElementById("generateBtn").disabled = false;
    clearInterval(loadingTimer);
  }
}

function animateLoadingSteps() {
  const steps = ["lstep1", "lstep2", "lstep3", "lstep4"];
  let idx = 0;
  steps.forEach(id => {
    const el = document.getElementById(id);
    el.classList.remove("active", "done");
  });
  document.getElementById(steps[0]).classList.add("active");

  loadingTimer = setInterval(() => {
    if (idx < steps.length - 1) {
      document.getElementById(steps[idx]).classList.remove("active");
      document.getElementById(steps[idx]).classList.add("done");
      idx++;
      document.getElementById(steps[idx]).classList.add("active");
    }
  }, 2200);
}

function displayScript(data) {
  clearInterval(loadingTimer);

  const scriptText  = data.script || "";
  const styleCount  = data.style_examples_used || 0;
  const modelLabel  = data.model || "Unknown model";

  // Extract viral score
  const scoreMatch = scriptText.match(/(\d+)\s*\/\s*140/);
  const score      = scoreMatch ? parseInt(scoreMatch[1]) : null;

  document.getElementById("scriptOutput").innerHTML = highlightScript(scriptText);
  document.getElementById("styleInfo").innerHTML =
    styleCount > 0
      ? `✨ ${styleCount} style reel${styleCount !== 1 ? "s" : ""} used · ${modelLabel}`
      : `⚠️ No style reels yet — add some for voice matching · ${modelLabel}`;

  // Score banner
  if (score !== null) {
    const banner = document.getElementById("scoreBanner");
    banner.classList.remove("hidden");
    const sv = document.getElementById("scoreValue");
    sv.textContent = score;
    if      (score >= 115) sv.style.background = "linear-gradient(135deg,#34d399,#22d3ee)";
    else if (score >= 90)  sv.style.background = "linear-gradient(135deg,#fb923c,#fbbf24)";
    else                   sv.style.background = "linear-gradient(135deg,#f87171,#ec4899)";
    sv.style.webkitBackgroundClip = "text";
    sv.style.webkitTextFillColor  = "transparent";
    sv.style.backgroundClip       = "text";
  }

  document.getElementById("loadingCard").classList.add("hidden");
  document.getElementById("outputCard").classList.remove("hidden");
  document.getElementById("inputCard").classList.remove("hidden");
  document.getElementById("generateBtn").disabled = false;
}

function highlightScript(text) {
  return text.split("\n").map(line => {
    const u = line.toUpperCase();
    if (u.includes("HOOK"))                           return `<span class="script-section-hook">${escapeHtml(line)}</span>`;
    if (u.includes("PROBLEM"))                        return `<span class="script-section-problem">${escapeHtml(line)}</span>`;
    if (u.includes("POINT") || u.includes("VALUE"))  return `<span class="script-section-value">${escapeHtml(line)}</span>`;
    if (u.includes("CLOSER") || u.includes("CLOSING")) return `<span class="script-section-closer">${escapeHtml(line)}</span>`;
    if (u.includes("CTA"))                            return `<span class="script-section-cta">${escapeHtml(line)}</span>`;
    if (u.includes("/20") || u.includes("/140"))      return `<span class="script-score-line">${escapeHtml(line)}</span>`;
    if (u.includes("FACT") || line.startsWith("✓") || line.startsWith("✅") || line.startsWith("⚠")) {
      return `<span class="script-factcheck-line">${escapeHtml(line)}</span>`;
    }
    return escapeHtml(line);
  }).join("\n");
}

function resetOutput() {
  document.getElementById("outputCard").classList.add("hidden");
  document.getElementById("scoreBanner").classList.add("hidden");
  document.getElementById("inputCard").classList.remove("hidden");
}

async function copyScript() {
  const output = document.getElementById("scriptOutput");
  const text   = output.innerText || output.textContent;
  try {
    await navigator.clipboard.writeText(text);
    showToast("Script copied! ✅", "success");
    const btn = document.getElementById("copyBtn");
    btn.textContent = "✅";
    setTimeout(() => btn.textContent = "📋", 2000);
  } catch {
    showToast("Copy failed — select and copy manually", "error");
  }
}

// ── Toast ──────────────────────────────────────────────────
function showToast(msg, type = "default", duration = 3500) {
  const toast = document.getElementById("toast");
  toast.textContent = msg;
  toast.className   = `toast ${type}`;
  setTimeout(() => toast.classList.add("hidden"), duration);
}

// ── Utils ──────────────────────────────────────────────────
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
