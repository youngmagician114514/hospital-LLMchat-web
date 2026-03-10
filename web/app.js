const chatLog = document.getElementById("chatLog");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const clearBtn = document.getElementById("clearBtn");
const newChatBtn = document.getElementById("newChatBtn");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const modelChip = document.getElementById("modelChip");
const promptBtn = document.getElementById("promptBtn");
const closePromptBtn = document.getElementById("closePromptBtn");
const promptPanel = document.getElementById("promptPanel");
const promptText = document.getElementById("promptText");

let sessionId = localStorage.getItem("hospital_chat_session_id");
let localHistory = [];
let isRequesting = false;

function generateSessionId() {
  const cryptoObj = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (cryptoObj && typeof cryptoObj.getRandomValues === "function") {
    try {
      const bytes = new Uint8Array(16);
      cryptoObj.getRandomValues(bytes);
      return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    } catch (_) {}
  }
  return `${Date.now().toString(16)}${Math.random().toString(16).slice(2, 14)}`;
}

if (!sessionId) {
  sessionId = generateSessionId();
  localStorage.setItem("hospital_chat_session_id", sessionId);
}

function resizeInput() {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 220)}px`;
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
  let copied = false;
  try {
    await navigator.clipboard.writeText(text);
    copied = true;
  } catch (_) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try {
      copied = document.execCommand("copy");
    } catch (_) {
      copied = false;
    }
    document.body.removeChild(ta);
  }

  if (button) {
    const oldText = button.textContent;
    button.textContent = copied ? "已复制" : "复制失败";
    setTimeout(() => {
      button.textContent = oldText;
    }, 1200);
  }
}

function appendInlineRichText(target, text) {
  const segments = text.split(/(`[^`]+`)/g);
  for (const segment of segments) {
    if (!segment) continue;
    if (segment.startsWith("`") && segment.endsWith("`") && segment.length >= 2) {
      const code = document.createElement("code");
      code.className = "inline-code";
      code.textContent = segment.slice(1, -1);
      target.appendChild(code);
    } else {
      target.appendChild(document.createTextNode(segment));
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
  target.innerHTML = "";
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
      await streamReply(options.userText, options.requestHistory, {
        appendUserMessage: false,
        thinkingText: "正在重新生成..."
      });
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

function createStreamingAssistantCard(thinkingText) {
  const row = document.createElement("div");
  row.className = "message-row assistant";

  const card = document.createElement("div");
  card.className = "message-card";

  const body = document.createElement("div");
  body.className = "message-body is-streaming";
  body.textContent = thinkingText;
  card.appendChild(body);

  const metaDiv = document.createElement("div");
  metaDiv.className = "meta";
  card.appendChild(metaDiv);

  row.appendChild(card);
  chatLog.appendChild(row);
  scrollToBottom();

  let accumulated = "";
  return {
    push(delta) {
      accumulated += delta;
      renderAssistantContent(body, accumulated);
      body.classList.add("is-streaming");
      scrollToBottom();
    },
    finalize(finalText, metaText, options) {
      body.classList.remove("is-streaming");
      renderAssistantContent(body, finalText);
      metaDiv.textContent = metaText || "";
      card.appendChild(buildToolbar(finalText, options));
      scrollToBottom();
    },
    fail(errorText) {
      row.className = "message-row error";
      body.classList.remove("is-streaming");
      body.textContent = errorText;
      metaDiv.textContent = "";
      scrollToBottom();
    }
  };
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
  } catch (_) {
    statusDot.classList.remove("ok");
    statusDot.classList.add("err");
    statusText.textContent = "离线";
    modelChip.textContent = "模型：不可用";
  }
}

function parseSsePayloads(rawChunk) {
  const events = [];
  const blocks = rawChunk.split("\n\n");
  for (const block of blocks) {
    if (!block.trim()) continue;
    const lines = block.split("\n");
    let dataLine = "";
    for (const line of lines) {
      if (line.startsWith("data:")) {
        dataLine += line.slice(5).trim();
      }
    }
    if (!dataLine) continue;
    try {
      events.push(JSON.parse(dataLine));
    } catch (_) {}
  }
  return events;
}

async function streamReply(userText, historySnapshot, options = {}) {
  const appendUserMessage = options.appendUserMessage !== false;
  const thinkingText = options.thinkingText || "正在思考中...";

  setBusyState(true);
  if (appendUserMessage) appendMessage("user", userText);
  const streamCard = createStreamingAssistantCard(thinkingText);

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        message: userText,
        history: historySnapshot,
        use_server_history: false
      })
    });

    if (!res.ok || !res.body) {
      let detail = `HTTP ${res.status}`;
      try {
        const payload = await res.json();
        detail = payload.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let doneEvent = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";

      for (const chunk of chunks) {
        const events = parseSsePayloads(`${chunk}\n\n`);
        for (const event of events) {
          if (event.type === "token") {
            if (event.delta) streamCard.push(event.delta);
          } else if (event.type === "done") {
            doneEvent = event;
          } else if (event.type === "error") {
            throw new Error(event.detail || "流式生成失败");
          }
        }
      }
    }

    if (!doneEvent) throw new Error("流式返回中断");

    sessionId = doneEvent.session_id;
    localStorage.setItem("hospital_chat_session_id", sessionId);
    localHistory = doneEvent.history || [];

    streamCard.finalize(
      doneEvent.reply,
      `${doneEvent.model} - ${doneEvent.latency_ms}ms`,
      { userText, requestHistory: historySnapshot }
    );
  } catch (err) {
    streamCard.fail(`请求失败：${err.message}`);
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
  await streamReply(text, historySnapshot, { appendUserMessage: true });
}

async function clearServerSession() {
  try {
    await fetch("/api/session/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId })
    });
  } catch (_) {}
}

async function startNewChat() {
  if (isRequesting) return;
  await clearServerSession();
  resetSessionState();
  chatLog.innerHTML = "";
  appendMessage("assistant", "新会话已创建。");
}

async function clearCurrentChat() {
  if (isRequesting) return;
  await clearServerSession();
  localHistory = [];
  chatLog.innerHTML = "";
  appendMessage("assistant", "会话已清空。");
}

async function loadPrompt() {
  try {
    const res = await fetch("/api/prompt");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    promptText.textContent = `${data.system_prompt}\n\n固定输出格式：\n${data.required_output_format}`;
    promptPanel.classList.remove("hidden");
  } catch (err) {
    promptText.textContent = `提示词加载失败：${err.message}`;
    promptPanel.classList.remove("hidden");
  }
}

function closePromptPanel() {
  promptPanel.classList.add("hidden");
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
promptBtn.addEventListener("click", loadPrompt);
closePromptBtn.addEventListener("click", closePromptPanel);

appendMessage("assistant", "系统已就绪。");
resizeInput();
refreshHealth();
setInterval(refreshHealth, 20000);
