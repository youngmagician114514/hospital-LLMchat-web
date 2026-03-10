const caseInput = document.getElementById("caseInput");
const diagnoseBtn = document.getElementById("diagnoseBtn");
const clearBtn = document.getElementById("clearBtn");
const fillDemoBtn = document.getElementById("fillDemoBtn");
const copyBtn = document.getElementById("copyBtn");
const modelChip = document.getElementById("modelChip");

const outDiagnosis = document.getElementById("outDiagnosis");
const outMain = document.getElementById("outMain");
const outSecondary = document.getElementById("outSecondary");
const outPrescription = document.getElementById("outPrescription");
const outReason = document.getElementById("outReason");

let sessionId = localStorage.getItem("hospital_diagnosis_session_id");
let lastResultText = "";
let isRequesting = false;

if (!sessionId) {
  const seed = `${Date.now().toString(16)}${Math.random().toString(16).slice(2, 12)}`;
  sessionId = seed;
  localStorage.setItem("hospital_diagnosis_session_id", sessionId);
}

function setResultMeta(text) {
  const node = document.getElementById("resultMeta");
  if (node) {
    node.textContent = text;
  }
}

function setBusyState(busy) {
  isRequesting = busy;
  diagnoseBtn.disabled = busy;
  clearBtn.disabled = busy;
  fillDemoBtn.disabled = busy;
}

function extractField(raw, label, nextLabel) {
  const tail = nextLabel ? `(?=${nextLabel}[：:])` : "$";
  const reg = new RegExp(`${label}[：:]\\s*([\\s\\S]*?)\\s*${tail}`);
  const match = raw.match(reg);
  return match ? match[1].trim() : "";
}

function parseStructuredReply(rawText) {
  const source = `${rawText || ""}`.trim();
  const labels = ["西医诊断", "主证", "兼证", "方药", "理由"];
  const output = {
    "西医诊断": "",
    "主证": "",
    "兼证": "",
    "方药": "",
    "理由": ""
  };
  labels.forEach((label, index) => {
    const nextLabel = labels[index + 1] || null;
    output[label] = extractField(source, label, nextLabel);
  });

  const hasAny = Object.values(output).some((item) => item);
  if (!hasAny) {
    output["西医诊断"] = "未明确";
    output["主证"] = "未明确";
    output["兼证"] = "未明确";
    output["方药"] = "未明确";
    output["理由"] = source || "未明确";
  } else {
    labels.forEach((label) => {
      if (!output[label]) output[label] = "未明确";
    });
  }
  return output;
}

function renderOutput(structured) {
  outDiagnosis.textContent = structured["西医诊断"];
  outMain.textContent = structured["主证"];
  outSecondary.textContent = structured["兼证"];
  outPrescription.textContent = structured["方药"];
  outReason.textContent = structured["理由"];
}

function renderError(detail) {
  outDiagnosis.textContent = "请求失败";
  outMain.textContent = "-";
  outSecondary.textContent = "-";
  outPrescription.textContent = "-";
  outReason.textContent = detail;
}

function buildFullResultText(structured) {
  return [
    `西医诊断：${structured["西医诊断"]}`,
    `主证：${structured["主证"]}`,
    `兼证：${structured["兼证"]}`,
    `方药：${structured["方药"]}`,
    `理由：${structured["理由"]}`
  ].join("\n");
}

async function diagnose() {
  if (isRequesting) return;
  const message = caseInput.value.trim();
  if (!message) {
    setResultMeta("请先输入病历信息");
    caseInput.focus();
    return;
  }

  setBusyState(true);
  setResultMeta("正在生成...");

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        message,
        history: [],
        use_server_history: false
      })
    });

    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const payload = await res.json();
        detail = payload.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }

    const data = await res.json();
    sessionId = data.session_id || sessionId;
    localStorage.setItem("hospital_diagnosis_session_id", sessionId);

    const structured = parseStructuredReply(data.reply || "");
    renderOutput(structured);
    lastResultText = buildFullResultText(structured);
    setResultMeta(`${data.model} · ${data.latency_ms}ms`);
  } catch (err) {
    renderError(err.message);
    setResultMeta("生成失败");
    lastResultText = "";
  } finally {
    setBusyState(false);
  }
}

function clearOutput() {
  outDiagnosis.textContent = "-";
  outMain.textContent = "-";
  outSecondary.textContent = "-";
  outPrescription.textContent = "-";
  outReason.textContent = "-";
  setResultMeta("");
  lastResultText = "";
}

async function clearSession() {
  try {
    await fetch("/api/session/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId })
    });
  } catch (_) {}
}

async function clearAll() {
  if (isRequesting) return;
  await clearSession();
  caseInput.value = "";
  clearOutput();
}

function fillDemo() {
  caseInput.value = "主诉：颈项酸痛伴左上肢麻木2周。\n现病史：两周前劳累受凉后诱发，休息后无明显缓解，久坐及低头后加重。\n查体：颈椎活动受限，左侧压颈试验阳性。\n影像学：颈椎MRI提示C5/6轻度椎间盘突出。\n舌脉：舌暗红，苔薄白，脉弦。";
}

async function copyResult() {
  if (!lastResultText) return;
  let ok = false;
  try {
    await navigator.clipboard.writeText(lastResultText);
    ok = true;
  } catch (_) {
    const ta = document.createElement("textarea");
    ta.value = lastResultText;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try {
      ok = document.execCommand("copy");
    } catch (_) {
      ok = false;
    }
    document.body.removeChild(ta);
  }
  const oldText = copyBtn.textContent;
  copyBtn.textContent = ok ? "已复制" : "复制失败";
  setTimeout(() => {
    copyBtn.textContent = oldText;
  }, 1200);
}

async function refreshHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    modelChip.textContent = `模型：${data.provider}`;
  } catch (_) {
    modelChip.textContent = "模型：不可用";
  }
}

diagnoseBtn.addEventListener("click", diagnose);
clearBtn.addEventListener("click", clearAll);
fillDemoBtn.addEventListener("click", fillDemo);
copyBtn.addEventListener("click", copyResult);

caseInput.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    diagnose();
  }
});

refreshHealth();
setInterval(refreshHealth, 20000);
