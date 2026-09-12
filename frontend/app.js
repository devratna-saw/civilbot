const API = "";
let sessionId = localStorage.getItem("civilbot_session") || crypto.randomUUID();
localStorage.setItem("civilbot_session", sessionId);
let mode = "general";

const chatScroll = document.getElementById("chatScroll");
const msgInput = document.getElementById("msgInput");
const sendBtn = document.getElementById("sendBtn");

function addMessage(role, text) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = text;
  wrap.appendChild(bubble);
  chatScroll.appendChild(wrap);
  chatScroll.scrollTop = chatScroll.scrollHeight;
  return bubble;
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// Small hand-rolled markdown renderer (headers, bold, italic, inline code,
// unordered/ordered lists, horizontal rules) - avoids a CDN dependency for
// a handful of formatting rules the model actually uses in replies.
function renderMarkdown(raw) {
  const lines = escapeHtml(raw).split("\n");
  let html = "";
  let inList = null; // 'ul' | 'ol' | null
  const closeList = () => {
    if (inList) { html += `</${inList}>`; inList = null; }
  };
  const inline = (s) =>
    s
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>");

  for (const line of lines) {
    if (/^\s*(---|\*\*\*)\s*$/.test(line)) { closeList(); html += "<hr>"; continue; }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { closeList(); const lvl = Math.min(h[1].length + 2, 6); html += `<h${lvl}>${inline(h[2])}</h${lvl}>`; continue; }
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    if (ul) { if (inList !== "ul") { closeList(); html += "<ul>"; inList = "ul"; } html += `<li>${inline(ul[1])}</li>`; continue; }
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ol) { if (inList !== "ol") { closeList(); html += "<ol>"; inList = "ol"; } html += `<li>${inline(ol[1])}</li>`; continue; }
    if (line.trim() === "") { closeList(); html += "<br>"; continue; }
    closeList();
    html += `<div>${inline(line)}</div>`;
  }
  closeList();
  return html;
}

function fmtToolCalls(toolCalls) {
  if (!toolCalls || !toolCalls.length) return "";
  return toolCalls
    .map((tc) => `<b>engine call:</b> ${tc.tool}(${JSON.stringify(tc.args)})\n<b>result:</b> ${JSON.stringify(tc.result, null, 2)}`)
    .join("\n\n");
}

async function sendMessage() {
  const text = msgInput.value.trim();
  if (!text) return;
  addMessage("user", escapeHtml(text));
  msgInput.value = "";
  autoGrow();
  sendBtn.disabled = true;
  const thinking = addMessage("bot", "…");

  try {
    const res = await fetch(`${API}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text, mode }),
    });
    const data = await res.json();
    if (!res.ok) {
      thinking.parentElement.className = "msg error";
      thinking.textContent = data.detail || "Something went wrong.";
      return;
    }
    if (data.tool_calls && data.tool_calls.length) {
      const toolMsg = document.createElement("div");
      toolMsg.className = "msg tool";
      const b = document.createElement("div");
      b.className = "bubble";
      b.textContent = fmtToolCalls(data.tool_calls);
      toolMsg.appendChild(b);
      chatScroll.insertBefore(toolMsg, thinking.parentElement);
    }
    thinking.innerHTML = renderMarkdown(data.reply);
    sessionId = data.session_id;
    localStorage.setItem("civilbot_session", sessionId);
  } catch (e) {
    thinking.parentElement.className = "msg error";
    thinking.textContent = "Network error talking to the server.";
  } finally {
    sendBtn.disabled = false;
    chatScroll.scrollTop = chatScroll.scrollHeight;
  }
}

sendBtn.addEventListener("click", sendMessage);
msgInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
function autoGrow() {
  msgInput.style.height = "auto";
  msgInput.style.height = Math.min(msgInput.scrollHeight, 160) + "px";
}
msgInput.addEventListener("input", autoGrow);

document.querySelectorAll(".mode-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".mode-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    mode = btn.dataset.mode;
  });
});

document.getElementById("newChatBtn").addEventListener("click", () => {
  sessionId = crypto.randomUUID();
  localStorage.setItem("civilbot_session", sessionId);
  chatScroll.innerHTML = "";
  addMessage("bot", "New chat started. How can I help?");
  document.getElementById("uploadResult").textContent = "";
});

// ---------- PDF upload ----------
const pdfInput = document.getElementById("pdfInput");
const uploadBox = document.getElementById("uploadBox");
const uploadResult = document.getElementById("uploadResult");

pdfInput.addEventListener("change", async () => {
  const file = pdfInput.files[0];
  if (!file) return;
  uploadResult.textContent = "Parsing " + file.name + " ...";
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch(`${API}/api/upload-pdf?session_id=${encodeURIComponent(sessionId)}`, {
      method: "POST",
      body: form,
    });
    const data = await res.json();
    if (!res.ok) {
      uploadResult.textContent = "Error: " + (data.detail || "could not parse file");
      return;
    }
    const q = data.quantities.map((x) => `${x.label}=${x.value.toPrecision(4)}`).join(", ") || "none detected";
    uploadResult.innerHTML = `<span class="quantity">${data.filename}</span> · ${data.page_count}p · extracted: ${q}\nAsk about it in chat — it'll be used as context for your next message.`;
  } catch (e) {
    uploadResult.textContent = "Network error uploading file.";
  }
});

// ---------- Simulator ----------
const simBackdrop = document.getElementById("simBackdrop");
const simTitle = document.getElementById("simTitle");
const simBody = document.getElementById("simBody");
document.getElementById("simClose").addEventListener("click", () => simBackdrop.classList.remove("open"));
simBackdrop.addEventListener("click", (e) => { if (e.target === simBackdrop) simBackdrop.classList.remove("open"); });

document.querySelectorAll(".sim-btn").forEach((btn) => {
  btn.addEventListener("click", () => openSimulator(btn.dataset.sim));
});

function field(id, label, value, type = "number", step = "any") {
  return `<div class="field"><label>${label}</label><input id="${id}" type="${type}" step="${step}" value="${value}"></div>`;
}

function openSimulator(kind) {
  simBackdrop.classList.add("open");
  if (kind === "beam") renderBeamSim();
  if (kind === "column") renderColumnSim();
  if (kind === "truss") renderTrussSim();
}

function renderBeamSim() {
  simTitle.textContent = "Beam calculator";
  simBody.innerHTML = `
    <div class="field-row">
      <div class="field"><label>Support</label>
        <select id="bSupport"><option value="simply_supported">Simply supported</option><option value="cantilever">Cantilever</option></select>
      </div>
      <div class="field"><label>Load type</label>
        <select id="bLoadType"><option value="udl">UDL (N/m)</option><option value="point_midspan">Point (midspan/free end)</option><option value="point_at">Point at distance a</option></select>
      </div>
    </div>
    <div class="field-row">
      ${field("bSpan", "Span (m)", 6)}
      ${field("bLoad", "Load value (N or N/m)", 10000)}
      ${field("bPos", "Load position a (m, point_at only)", "")}
    </div>
    <div class="field-row">
      ${field("bWidth", "Width b (m)", 0.3)}
      ${field("bDepth", "Depth d (m)", 0.5)}
      ${field("bE", "E (Pa)", 200e9)}
    </div>
    <div class="field-row">
      ${field("bAllow", "Allowable stress (Pa, optional)", "")}
      ${field("bDeflRatio", "Deflection limit ratio (L/x)", 360)}
    </div>
    <button class="run-btn" id="bRun">Run</button>
    <div class="result-box" id="bResult"></div>
  `;
  document.getElementById("bRun").addEventListener("click", async () => {
    const body = {
      support_type: document.getElementById("bSupport").value,
      load_type: document.getElementById("bLoadType").value,
      span_m: num("bSpan"),
      load_value: num("bLoad"),
      load_position_m: num("bPos"),
      E_pa: num("bE"),
      section: { shape: "rectangular", width_m: num("bWidth"), depth_m: num("bDepth") },
      allowable_stress_pa: num("bAllow"),
      deflection_limit_ratio: num("bDeflRatio") || 360,
    };
    await runCalc("/api/calc/beam", body, "bResult");
  });
}

function renderColumnSim() {
  simTitle.textContent = "Column buckling calculator";
  simBody.innerHTML = `
    <div class="field-row">
      ${field("cLength", "Length (m)", 3)}
      ${field("cE", "E (Pa)", 200e9)}
    </div>
    <div class="field-row">
      ${field("cI", "I (m^4)", 8e-6)}
      ${field("cK", "K factor", 1.0)}
    </div>
    ${field("cLoad", "Applied axial load (N)", 50000)}
    <button class="run-btn" id="cRun">Run</button>
    <div class="result-box" id="cResult"></div>
  `;
  document.getElementById("cRun").addEventListener("click", async () => {
    const body = { length_m: num("cLength"), E_pa: num("cE"), I_m4: num("cI"), K: num("cK") || 1.0, applied_load_n: num("cLoad") };
    await runCalc("/api/calc/column", body, "cResult");
  });
}

function renderTrussSim() {
  simTitle.textContent = "Truss calculator (method of joints)";
  const exampleNodes = [
    { id: "A", x_m: 0, y_m: 0, support: "pin" },
    { id: "B", x_m: 2, y_m: 0, support: "none" },
    { id: "C", x_m: 4, y_m: 0, support: "roller_y" },
    { id: "D", x_m: 2, y_m: 2, support: "none" },
  ];
  const exampleMembers = [
    { id: "AB", node_i: "A", node_j: "B" },
    { id: "BC", node_i: "B", node_j: "C" },
    { id: "AD", node_i: "A", node_j: "D" },
    { id: "DC", node_i: "D", node_j: "C" },
    { id: "BD", node_i: "B", node_j: "D" },
  ];
  const exampleLoads = [{ node: "D", fx_n: 0, fy_n: -1000 }];

  simBody.innerHTML = `
    <div class="truss-editor">
      <div class="field"><label>Nodes (JSON array: id, x_m, y_m, support = none|pin|roller_x|roller_y)</label>
        <textarea id="tNodes">${JSON.stringify(exampleNodes, null, 2)}</textarea></div>
      <div class="field"><label>Members (JSON array: id, node_i, node_j, area_m2 optional)</label>
        <textarea id="tMembers">${JSON.stringify(exampleMembers, null, 2)}</textarea></div>
      <div class="field"><label>Loads (JSON array: node, fx_n, fy_n)</label>
        <textarea id="tLoads">${JSON.stringify(exampleLoads, null, 2)}</textarea></div>
    </div>
    <button class="run-btn" id="tRun">Run</button>
    <div class="result-box" id="tResult"></div>
  `;
  document.getElementById("tRun").addEventListener("click", async () => {
    let body;
    try {
      body = {
        nodes: JSON.parse(document.getElementById("tNodes").value),
        members: JSON.parse(document.getElementById("tMembers").value),
        loads: JSON.parse(document.getElementById("tLoads").value),
      };
    } catch (e) {
      document.getElementById("tResult").textContent = "Invalid JSON: " + e.message;
      return;
    }
    await runCalc("/api/calc/truss", body, "tResult");
  });
}

function num(id) {
  const v = document.getElementById(id).value;
  return v === "" ? null : parseFloat(v);
}

async function runCalc(path, body, resultId) {
  const box = document.getElementById(resultId);
  box.textContent = "Running...";
  try {
    const res = await fetch(`${API}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      box.textContent = "Error: " + (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
      return;
    }
    box.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    box.textContent = "Network error: " + e.message;
  }
}
