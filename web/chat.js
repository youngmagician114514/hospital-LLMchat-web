const chatMain = document.getElementById("chatMain");
const chatLog = document.getElementById("chatLog");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");
const quickNewChatBtn = document.getElementById("quickNewChatBtn");
const modelChip = document.getElementById("modelChip");

let sessionId = localStorage.getItem("hospital_dialogue_session_id");
let localHistory = [];
let isRequesting = false;
let autoFollowupCount = 0;

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
  localStorage.setItem("hospital_dialogue_session_id", sessionId);
}

function resizeInput() {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 210)}px`;
}

function scrollToBottom() {
  chatLog.scrollTop = chatLog.scrollHeight;
}

function refreshSendStyle() {
  if (isRequesting) {
    sendBtn.disabled = true;
    sendBtn.classList.remove("active");
    return;
  }
  const hasText = messageInput.value.trim().length > 0;
  sendBtn.disabled = !hasText;
  sendBtn.classList.toggle("active", hasText);
}

function setBusyState(busy) {
  isRequesting = busy;
  if (newChatBtn) newChatBtn.disabled = busy;
  if (quickNewChatBtn) quickNewChatBtn.disabled = busy;
  refreshSendStyle();
}

function enterConversationMode() {
  chatMain.classList.remove("is-empty");
}

function backToEmptyMode() {
  chatMain.classList.add("is-empty");
}

function appendMessage(role, text, meta = "") {
  const row = document.createElement("div");
  row.className = `row ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  row.appendChild(bubble);

  if (meta) {
    const metaDiv = document.createElement("div");
    metaDiv.className = "meta";
    metaDiv.textContent = meta;
    bubble.appendChild(metaDiv);
  }

  chatLog.appendChild(row);
  scrollToBottom();
}

function createStreamingBubble(initialText = "正在整理问诊思路...") {
  const row = document.createElement("div");
  row.className = "row assistant";

  const bubble = document.createElement("div");
  bubble.className = "bubble streaming";
  bubble.textContent = initialText;
  row.appendChild(bubble);

  chatLog.appendChild(row);
  scrollToBottom();

  let buffer = "";
  return {
    push(delta) {
      buffer += delta;
      bubble.textContent = buffer;
      bubble.classList.add("streaming");
      scrollToBottom();
    },
    finalize(text, meta) {
      bubble.classList.remove("streaming");
      bubble.textContent = text;
      if (meta) {
        const metaDiv = document.createElement("div");
        metaDiv.className = "meta";
        metaDiv.textContent = meta;
        bubble.appendChild(metaDiv);
      }
      scrollToBottom();
    },
    fail(detail) {
      row.className = "row assistant";
      bubble.classList.remove("streaming");
      bubble.textContent = detail;
      scrollToBottom();
    }
  };
}

function maybeAppendFollowup(replyText) {
  if (autoFollowupCount >= 2) return;
  if (/[？?]/.test(replyText)) return;
  autoFollowupCount += 1;
  appendMessage(
    "assistant",
    "为了继续问诊，请补充：症状持续时间、加重动作、缓解方式，以及是否伴随上肢麻木或头晕。"
  );
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

async function streamReply(userText) {
  setBusyState(true);
  enterConversationMode();
  appendMessage("user", userText);
  const streamNode = createStreamingBubble();

  try {
    const res = await fetch("/api/dialogue/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        message: userText,
        history: localHistory,
        use_server_history: true
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
          if (event.type === "token" && event.delta) {
            streamNode.push(event.delta);
          } else if (event.type === "done") {
            doneEvent = event;
          } else if (event.type === "error") {
            throw new Error(event.detail || "流式问诊失败");
          }
        }
      }
    }

    if (!doneEvent) throw new Error("问诊流中断");

    sessionId = doneEvent.session_id || sessionId;
    localStorage.setItem("hospital_dialogue_session_id", sessionId);
    localHistory = doneEvent.history || [];
    const meta = `${doneEvent.model} · ${doneEvent.latency_ms}ms`;
    streamNode.finalize(doneEvent.reply || "", meta);
    maybeAppendFollowup(doneEvent.reply || "");
  } catch (err) {
    streamNode.fail(`请求失败：${err.message}`);
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
  messageInput.value = "";
  resizeInput();
  refreshSendStyle();
  await streamReply(text);
}

async function clearDialogueSession() {
  try {
    await fetch("/api/dialogue/session/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId })
    });
  } catch (_) {}
}

async function startNewChat() {
  if (isRequesting) return;
  await clearDialogueSession();
  sessionId = generateSessionId();
  localStorage.setItem("hospital_dialogue_session_id", sessionId);
  localHistory = [];
  autoFollowupCount = 0;
  chatLog.innerHTML = "";
  backToEmptyMode();
}

async function clearCurrentChat() {
  if (isRequesting) return;
  await clearDialogueSession();
  localHistory = [];
  autoFollowupCount = 0;
  chatLog.innerHTML = "";
  backToEmptyMode();
}

async function refreshHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (modelChip) {
      modelChip.textContent = `模型：${data.provider}`;
    }
  } catch (_) {
    if (modelChip) {
      modelChip.textContent = "模型：不可用";
    }
  }
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendMessage();
});

messageInput.addEventListener("input", () => {
  resizeInput();
  refreshSendStyle();
});

messageInput.addEventListener("keydown", async (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    await sendMessage();
  }
});

if (newChatBtn) {
  newChatBtn.addEventListener("click", startNewChat);
}
if (quickNewChatBtn) {
  quickNewChatBtn.addEventListener("click", startNewChat);
}

resizeInput();
refreshSendStyle();
refreshHealth();
setInterval(refreshHealth, 20000);
