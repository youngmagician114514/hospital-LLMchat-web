const chatMain = document.getElementById("chatMain");
const chatLog = document.getElementById("chatLog");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");
const quickNewChatBtn = document.getElementById("quickNewChatBtn");
const modelChip = document.getElementById("modelChip");
const DIALOGUE_SESSION_KEY = "hospital_dialogue_session_id";
const CHAT_PAGE_MARKER_KEY = "hospital_last_chat_page";
const CHAT_PAGE_CURRENT = "independent_dialogue";

let sessionId = localStorage.getItem(DIALOGUE_SESSION_KEY);
let localHistory = [];
let isRequesting = false;
let shouldForceNewDialogueSession = false;

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
  localStorage.setItem(DIALOGUE_SESSION_KEY, sessionId);
}
const lastChatPage = sessionStorage.getItem(CHAT_PAGE_MARKER_KEY);
shouldForceNewDialogueSession = lastChatPage !== CHAT_PAGE_CURRENT;
sessionStorage.setItem(CHAT_PAGE_MARKER_KEY, CHAT_PAGE_CURRENT);

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
  ModelControls.setBusy(busy);
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

function createStreamingBubble(initialText = "回复中…") {
  const row = document.createElement("div");
  row.className = "row assistant";

  const bubble = document.createElement("div");
  bubble.className = "bubble streaming";
  bubble.textContent = initialText;
  const reasoning = StreamUI.createReasoningPanel({ onUpdate: scrollToBottom });
  row.append(reasoning.element, bubble);

  chatLog.appendChild(row);
  scrollToBottom();

  const writer = StreamUI.createWriter(text => {
    bubble.textContent = text;
    scrollToBottom();
  });
  return {
    pushReasoning(delta) {
      if (!writer.getText()) bubble.hidden = true;
      reasoning.push(delta);
    },
    push(delta) {
      reasoning.complete();
      bubble.hidden = false;
      writer.push(delta);
      bubble.classList.add("streaming");
      scrollToBottom();
    },
    async finalize(text, meta) {
      await reasoning.finish();
      if (!writer.getText() && text) writer.push(text);
      await writer.finish();
      bubble.classList.remove("streaming");
      bubble.hidden = false;
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
      reasoning.fail();
      writer.stop();
      row.className = "row assistant";
      bubble.classList.remove("streaming");
      bubble.hidden = false;
      bubble.textContent = [writer.getText(), detail].filter(Boolean).join("\n\n");
      scrollToBottom();
    }
  };
}


async function streamReply(userText) {
  setBusyState(true);
  enterConversationMode();
  appendMessage("user", userText);
  const streamNode = createStreamingBubble(ModelControls.getThinkingLevel() === "off" ? "回复中…" : "思考中…");

  try {
    const res = await fetch("/api/dialogue/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        message: userText,
        history: localHistory,
        use_server_history: true,
        thinking_level: ModelControls.getThinkingLevel()
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

    let doneEvent = null;
    for await (const event of StreamUI.readEvents(res)) {
      if (event.type === "reasoning" && event.delta) {
        streamNode.pushReasoning(event.delta);
      } else if (event.type === "token" && event.delta) {
        streamNode.push(event.delta);
      } else if (event.type === "done") {
        doneEvent = event;
      } else if (event.type === "error") {
        throw new Error(event.detail || "问诊连接中断");
      }
    }

    if (!doneEvent) throw new Error("问诊流中断");

    sessionId = doneEvent.session_id || sessionId;
    localStorage.setItem(DIALOGUE_SESSION_KEY, sessionId);
    localHistory = doneEvent.history || [];
    await streamNode.finalize(doneEvent.reply || "");
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
  localStorage.setItem(DIALOGUE_SESSION_KEY, sessionId);
  localHistory = [];
  chatLog.innerHTML = "";
  backToEmptyMode();
}

async function clearCurrentChat() {
  if (isRequesting) return;
  await clearDialogueSession();
  localHistory = [];
  chatLog.innerHTML = "";
  backToEmptyMode();
}

async function refreshHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (modelChip) {
      modelChip.textContent = data.provider === "stub-test" ? "演示模式" : data.provider;
    }
  } catch (_) {
    if (modelChip) {
      modelChip.textContent = "服务未连接";
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
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
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
if (shouldForceNewDialogueSession) {
  startNewChat();
}
setInterval(refreshHealth, 20000);
