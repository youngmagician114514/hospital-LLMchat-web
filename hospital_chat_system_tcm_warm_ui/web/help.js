(() => {
  const pages = [...document.querySelectorAll("article[data-doc]")];
  const navLinks = [...document.querySelectorAll("#docsNav a[data-page]")];
  const outline = document.getElementById("pageOutline");
  const pager = document.getElementById("docPager");
  const sidebar = document.getElementById("docsSidebar");
  const menuButton = document.getElementById("docsMenuBtn");
  let headings = [];
  let scrollQueued = false;

  function updateOutline() {
    const atBottom = window.scrollY > 0 && Math.ceil(window.scrollY + window.innerHeight) >= document.documentElement.scrollHeight - 2;
    const current = atBottom ? headings.at(-1) : [...headings].reverse().find(heading => heading.getBoundingClientRect().top <= 130) || headings[0];
    outline.querySelectorAll("a").forEach(link => {
      if (link.hash === `#${current?.id}`) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  }

  function closeMenu() {
    sidebar.classList.remove("is-open");
    menuButton.setAttribute("aria-expanded", "false");
  }

  function render({ focus = false } = {}) {
    const requested = new URLSearchParams(location.search).get("page");
    const selected = pages.find(page => page.dataset.doc === requested) || pages[0];
    const title = selected.querySelector("h1").textContent;
    pages.forEach(page => { page.hidden = page !== selected; });
    navLinks.forEach(link => {
      if (link.dataset.page === selected.dataset.doc) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.title = `${title} · 帮助文档`;
    document.getElementById("currentDocLabel").textContent = title;
    headings = [...selected.querySelectorAll("h2[id]")];
    outline.replaceChildren(...headings.map(heading => {
      const link = document.createElement("a");
      link.href = `#${heading.id}`;
      link.textContent = heading.textContent;
      return link;
    }));
    const index = pages.indexOf(selected);
    pager.replaceChildren();
    for (const [offset, label, className] of [[-1, "上一篇", "previous"], [1, "下一篇", "next"]]) {
      const page = pages[index + offset];
      if (!page) continue;
      const link = document.createElement("a");
      link.href = `help.html?page=${page.dataset.doc}`;
      link.dataset.page = page.dataset.doc;
      link.className = className;
      const small = document.createElement("small");
      small.textContent = label;
      const text = document.createElement("span");
      text.textContent = page.querySelector("h1").textContent;
      link.append(small, text);
      pager.append(link);
    }
    closeMenu();
    const target = headings.find(heading => `#${heading.id}` === location.hash);
    if (target) target.scrollIntoView();
    else window.scrollTo(0, 0);
    if (focus) document.getElementById("docContent").focus({ preventScroll: true });
    updateOutline();
  }

  document.addEventListener("click", event => {
    const link = event.target.closest("a[data-page]");
    if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    history.pushState(null, "", link.href);
    render({ focus: true });
  });
  menuButton.addEventListener("click", () => {
    const expanded = sidebar.classList.toggle("is-open");
    menuButton.setAttribute("aria-expanded", String(expanded));
  });
  window.addEventListener("popstate", () => render());
  window.addEventListener("scroll", () => {
    if (scrollQueued) return;
    scrollQueued = true;
    requestAnimationFrame(() => { updateOutline(); scrollQueued = false; });
  }, { passive: true });
  render();
})();
