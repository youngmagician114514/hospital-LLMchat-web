const chatLog = document.getElementById("chatLog");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const clearBtn = document.getElementById("clearBtn");
const newChatBtn = document.getElementById("newChatBtn");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const modelChip = document.getElementById("modelChip");

let sessionId = localStorage.getItem("hospital_chat_session_id");
let localHistory = [];
let isRequesting = false;

function generateSessionId() {
  const c = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (c && typeof c.getRandomValues === "function") {
    try {
      const buf = new Uint8Array(16);
      c.getRandomValues(buf);
      return Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("");
    } catch (_) {
    }
  }
  return `${Date.now().toString(16)}${Math.random().toString(16).slice(2, 14)}`;
}

if (!sessionId) {
  sessionId = generateSessionId();
  localStorage.setItem("hospital_chat_session_id", sessionId);
}

function resizeInput() {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 180)}px`;
}

function scrollToBottom() {
  chatLog.scrollTop = chatLog.scrollHeight;
}

function setBusyState(busy) {
  isRequesting = busy;
  sendBtn.disabled = busy;
  clearBtn.disabled = busy;
  newChatBtn.disabled = busy;
}

async function copyToClipboard(text, button) {
  let ok = false;
  try {
    await navigator.clipboard.writeText(text);
    ok = true;
  } catch (_) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try {
      ok = document.execCommand("copy");
    } catch (err) {
      ok = false;
    }
    document.body.removeChild(ta);
  }

  if (button) {
    const old = button.textContent;
    button.textContent = ok ? "已复制" : "复制失败";
    setTimeout(() => {
      button.textContent = old;
    }, 1200);
  }
}

function appendInlineRichText(target, text) {
  const parts = text.split(/(`[^`]+`)/g);
  for (const part of parts) {
    if (!part) continue;
    if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
      const inlineCode = document.createElement("code");
      inlineCode.className = "inline-code";
      inlineCode.textContent = part.slice(1, -1);
      target.appendChild(inlineCode);
    } else {
      target.appendChild(document.createTextNode(part));
    }
  }
}

function appendTextBlock(container, text) {
  const block = document.createElement("div");
  block.className = "text-block";
  const lines = text.split("\n");
  lines.forEach((line, idx) => {
    appendInlineRichText(block, line);
    if (idx < lines.length - 1) block.appendChild(document.createElement("br"));
  });
  container.appendChild(block);
}

function appendCodeBlock(container, language, codeText) {
  const block = document.createElement("div");
  block.className = "code-block";

  const header = document.createElement("div");
  header.className = "code-header";

  const lang = document.createElement("span");
  lang.className = "code-lang";
  lang.textContent = language || "text";

  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "code-copy-btn";
  copyBtn.textContent = "复制代码";
  copyBtn.addEventListener("click", async () => {
    await copyToClipboard(codeText, copyBtn);
  });

  header.appendChild(lang);
  header.appendChild(copyBtn);

  const pre = document.createElement("pre");
  const code = document.createElement("code");
  code.textContent = codeText;
  pre.appendChild(code);

  block.appendChild(header);
  block.appendChild(pre);
  container.appendChild(block);
}

function renderAssistantContent(target, text) {
  const source = `${text || ""}`;
  const codeRegex = /```([a-zA-Z0-9_-]+)?\n?([\s\S]*?)```/g;
  let lastIndex = 0;
  let match = null;
  while ((match = codeRegex.exec(source)) !== null) {
    const plain = source.slice(lastIndex, match.index);
    if (plain) appendTextBlock(target, plain.trimEnd());
    appendCodeBlock(target, (match[1] || "text").trim(), match[2] || "");
    lastIndex = codeRegex.lastIndex;
  }
  const tail = source.slice(lastIndex);
  if (tail.trim().length > 0 || target.childNodes.length === 0) {
    appendTextBlock(target, tail.trimEnd());
  }
}

function buildToolbar(messageText, options = {}) {
  const toolbar = document.createElement("div");
  toolbar.className = "message-toolbar";

  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "tool-btn";
  copyBtn.textContent = "复制";
  copyBtn.addEventListener("click", async () => {
    await copyToClipboard(messageText, copyBtn);
  });
  toolbar.appendChild(copyBtn);

  if (options.userText && Array.isArray(options.requestHistory)) {
    const regenBtn = document.createElement("button");
    regenBtn.type = "button";
    regenBtn.className = "tool-btn";
    regenBtn.textContent = "重新生成";
    regenBtn.addEventListener("click", async () => {
      if (isRequesting) return;
      await requestReply(
        options.userText,
        options.requestHistory,
        {
          appendUserMessage: false,
          thinkingText: "正在重新生成回答..."
        }
      );
    });
    toolbar.appendChild(regenBtn);
  }

  return toolbar;
}

function appendMessage(role, text, meta = "", options = {}) {
  const row = document.createElement("div");
  row.className = `message-row ${role}`;

  const card = document.createElement("div");
  card.className = "message-card";

  const body = document.createElement("div");
  body.className = "message-body";
  if (role === "assistant") {
    renderAssistantContent(body, text);
  } else {
    body.textContent = text;
  }
  card.appendChild(body);

  if (meta) {
    const metaDiv = document.createElement("div");
    metaDiv.className = "meta";
    metaDiv.textContent = meta;
    card.appendChild(metaDiv);
  }

  if (role === "assistant") {
    card.appendChild(buildToolbar(text, options));
  }

  row.appendChild(card);
  chatLog.appendChild(row);
  scrollToBottom();
}

function appendLoading(thinkingText = "正在思考中") {
  const row = document.createElement("div");
  row.className = "message-row assistant";
  row.id = "loadingRow";

  const card = document.createElement("div");
  card.className = "message-card typing-card";

  const typing = document.createElement("div");
  typing.className = "typing-line";

  const text = document.createElement("span");
  text.textContent = thinkingText;

  const cursor = document.createElement("span");
  cursor.className = "typing-cursor";
  cursor.textContent = "|";

  const dots = document.createElement("span");
  dots.className = "typing-dots";
  dots.textContent = "...";

  typing.appendChild(text);
  typing.appendChild(cursor);
  typing.appendChild(dots);
  card.appendChild(typing);
  row.appendChild(card);

  chatLog.appendChild(row);
  scrollToBottom();
}

function clearLoading() {
  const node = document.getElementById("loadingRow");
  if (node) node.remove();
}

function resetSessionState() {
  sessionId = generateSessionId();
  localStorage.setItem("hospital_chat_session_id", sessionId);
  localHistory = [];
}

async function refreshHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    statusDot.classList.remove("err");
    statusDot.classList.add("ok");
    statusText.textContent = `在线 - 并发上限 ${data.max_concurrent_model_calls}`;
    modelChip.textContent = `模型：${data.provider}`;
  } catch (err) {
    statusDot.classList.remove("ok");
    statusDot.classList.add("err");
    statusText.textContent = "离线";
    modelChip.textContent = "模型：不可用";
  }
}

async function requestReply(userText, historySnapshot, options = {}) {
  const appendUserMessage = options.appendUserMessage !== false;
  const thinkingText = options.thinkingText || "正在思考中";

  setBusyState(true);
  if (appendUserMessage) {
    appendMessage("user", userText);
  }
  appendLoading(thinkingText);

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        message: userText,
        history: historySnapshot,
        use_server_history: false
      })
    });

    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const payload = await res.json();
        detail = payload.detail || detail;
      } catch (_) {
      }
      throw new Error(detail);
    }

    const data = await res.json();
    sessionId = data.session_id;
    localStorage.setItem("hospital_chat_session_id", sessionId);
    localHistory = data.history;
    clearLoading();
    appendMessage(
      "assistant",
      data.reply,
      `${data.model} - ${data.latency_ms}ms`,
      { userText, requestHistory: historySnapshot }
    );
  } catch (err) {
    clearLoading();
    appendMessage("error", `请求失败：${err.message}`);
  } finally {
    setBusyState(false);
    messageInput.focus();
    resizeInput();
  }
}

async function sendMessage() {
  if (isRequesting) return;
  const text = messageInput.value.trim();
  if (!text) return;
  const historySnapshot = [...localHistory];
  messageInput.value = "";
  resizeInput();
  await requestReply(text, historySnapshot, { appendUserMessage: true });
}

async function clearServerSession() {
  try {
    await fetch("/api/session/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId })
    });
  } catch (_) {
  }
}

async function startNewChat() {
  if (isRequesting) return;
  await clearServerSession();
  resetSessionState();
  chatLog.innerHTML = "";
  appendMessage("assistant", "新会话已创建，请输入病例信息。");
}

async function clearCurrentChat() {
  if (isRequesting) return;
  await clearServerSession();
  localHistory = [];
  chatLog.innerHTML = "";
  appendMessage("assistant", "会话记录已清空。");
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendMessage();
});

messageInput.addEventListener("input", resizeInput);
messageInput.addEventListener("keydown", async (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    await sendMessage();
  }
});

clearBtn.addEventListener("click", clearCurrentChat);
newChatBtn.addEventListener("click", startNewChat);

appendMessage(
  "assistant",
  "系统已就绪。你可以输入病例信息，我会按“西医诊断、主证、兼证、方药”结构给出建议。"
);
resizeInput();
refreshHealth();
setInterval(refreshHealth, 20000);
