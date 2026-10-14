(() => {
  const key = "hospital_thinking_level";
  const levels = ["off", "low", "high", "max"];
  const controls = document.getElementById("thinkingControls");
  let selected = "low";
  try {
    const saved = localStorage.getItem(key);
    if (levels.includes(saved)) selected = saved;
  } catch (_) {}

  function render() {
    controls?.querySelectorAll("button[data-thinking]").forEach(button => {
      button.setAttribute("aria-pressed", String(button.dataset.thinking === selected));
    });
  }

  controls?.addEventListener("click", event => {
    const button = event.target.closest("button[data-thinking]");
    if (!button || button.disabled || !levels.includes(button.dataset.thinking)) return;
    selected = button.dataset.thinking;
    try { localStorage.setItem(key, selected); } catch (_) {}
    render();
  });

  window.ModelControls = {
    getThinkingLevel: () => selected,
    formatMeta: data => {
      const labels = { off: "思考：关闭", low: "思考：中", high: "思考：高", max: "思考：超高" };
      const level = labels[data.thinking_level];
      return [data.model || "模型", level, `${data.latency_ms || 0}ms`].filter(Boolean).join(" · ");
    },
    setBusy: busy => controls?.querySelectorAll("button").forEach(button => { button.disabled = busy; })
  };
  render();
})();
