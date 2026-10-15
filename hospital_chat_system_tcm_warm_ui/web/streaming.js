(() => {
  // Drain received text over several paints, including responses arriving in one burst.
  function createWriter(render) {
    let pending = [];
    let shown = "";
    let received = "";
    let timer = null;
    let stopped = false;
    let waiters = [];
    const settle = () => { const list = waiters; waiters = []; list.forEach(resolve => resolve()); };
    function tick() {
      timer = null;
      if (stopped) return;
      const count = Math.min(16, Math.max(3, Math.ceil(pending.length / 160)));
      shown += pending.splice(0, count).join("");
      render(shown);
      if (pending.length) timer = setTimeout(tick, 24);
      else settle();
    }
    return {
      push(delta) {
        if (stopped || !delta) return;
        received += delta;
        pending.push(...Array.from(delta));
        if (timer === null) timer = setTimeout(tick, 24);
      },
      finish() {
        if (stopped || (!pending.length && timer === null)) return Promise.resolve();
        return new Promise(resolve => waiters.push(resolve));
      },
      stop() {
        stopped = true;
        clearTimeout(timer);
        timer = null;
        pending = [];
        settle();
      },
      getText: () => received
    };
  }

  async function* readEvents(response) {
    if (!response.body) throw new Error("浏览器未提供流式响应");
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    function parse(block) {
      const data = block.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
      return data && data !== "[DONE]" ? JSON.parse(data) : null;
    }
    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
        buffer = buffer.replace(/\r\n/g, "\n");
        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const event = parse(block);
          if (event) yield event;
        }
        if (done) {
          if (buffer.trim()) { const event = parse(buffer); if (event) yield event; }
          break;
        }
      }
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }
  function createReasoningPanel({ onUpdate = () => {} } = {}) {
    const element = document.createElement("details");
    element.className = "reasoning-panel";
    const summary = document.createElement("summary");
    summary.append(document.createTextNode("思考过程"));
    const state = document.createElement("span");
    state.className = "reasoning-state";
    summary.append(state);
    const content = document.createElement("div");
    content.className = "reasoning-content";
    element.append(summary, content);
    let writer;

    function reset() {
      writer?.stop();
      element.hidden = true;
      element.open = false;
      element.dataset.state = "idle";
      state.textContent = "";
      content.textContent = "";
      writer = createWriter(text => {
        const follow = content.scrollHeight - content.scrollTop - content.clientHeight < 24;
        content.textContent = text;
        if (follow) content.scrollTop = content.scrollHeight;
        onUpdate();
      });
    }
    function complete() {
      if (element.dataset.state === "interrupted") return;
      element.dataset.state = "done";
      state.textContent = "已完成";
    }
    reset();
    return {
      element,
      reset,
      push(delta) {
        if (!delta) return;
        element.hidden = false;
        element.dataset.state = "streaming";
        state.textContent = "进行中";
        writer.push(delta);
      },
      complete,
      async finish() {
        // A long, collapsed trace must not delay an already received answer.
        writer.stop();
        content.textContent = writer.getText();
        complete();
      },
      fail() {
        writer.stop();
        content.textContent = writer.getText();
        element.dataset.state = "interrupted";
        state.textContent = "已中断";
      }
    };
  }
  window.StreamUI = { createWriter, readEvents, createReasoningPanel };
})();
