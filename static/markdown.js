/* Local Markdown presentation. No raw HTML, remote images or executable URLs. */
(function (scope) {
  "use strict";
  function speechDuration(text) {
    const words = String(text).trim().split(/\s+/u).filter(Boolean).length;
    return Math.min(300000, Math.max(6000, (words / 180) * 60000 + 2000));
  }
  function isRecent(chat, days, now = Date.now() / 1000) {
    return (
      chat.status === "working" || Number(chat.updatedAt) >= now - days * 86400
    );
  }
  function safeLink(href) {
    try {
      const url = new URL(href);
      return ["https:", "http:"].includes(url.protocol) ? url.href : null;
    } catch {
      return null;
    }
  }
  function plainText(text) {
    return String(text)
      .replace(/!?\[([^\]]+)\]\([^\n]*?\)/g, "$1")
      .replace(/[*_`#~]/g, "");
  }
  function escape(text) {
    return String(text).replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  }
  let parser;
  function fragment(text) {
    if (!parser) {
      const renderer = new scope.marked.Renderer();
      renderer.html = ({ text }) => escape(text);
      renderer.image = ({ text, href }) => {
        const url = safeLink(href);
        return url
          ? `<a href="${escape(url)}">${escape(text || "Image")}</a>`
          : `<span>${escape(text || "Image")} (local file)</span>`;
      };
      renderer.checkbox = ({ checked }) => (checked ? "☑ " : "☐ ");
      parser = new scope.marked.Marked({ renderer, gfm: true, breaks: false });
    }
    const clean = scope.DOMPurify.sanitize(parser.parse(String(text)), {
      RETURN_DOM_FRAGMENT: true,
      ALLOWED_TAGS: [
        "p",
        "br",
        "strong",
        "em",
        "del",
        "s",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "pre",
        "code",
        "hr",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "a",
        "span",
      ],
      ALLOWED_ATTR: ["href", "title", "start", "class"],
      ALLOW_DATA_ATTR: false,
      ALLOW_ARIA_ATTR: false,
    });
    for (const a of clean.querySelectorAll("a")) {
      const url = safeLink(a.getAttribute("href"));
      if (url) {
        a.href = url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
      } else {
        const span = document.createElement("span");
        span.textContent = a.textContent;
        span.title =
          "Lokale bestandslink · open dit bestand vanuit Codex of Claude";
        a.replaceWith(span);
      }
    }
    for (const table of clean.querySelectorAll("table")) {
      const wrap = document.createElement("div");
      wrap.className = "table-scroll";
      wrap.tabIndex = 0;
      wrap.setAttribute("role", "region");
      wrap.setAttribute("aria-label", "Table");
      table.replaceWith(wrap);
      wrap.append(table);
    }
    return clean;
  }
  const rendered = new WeakMap();
  function render(element, text) {
    if (rendered.get(element) === text) return;
    rendered.set(element, text);
    element.classList.add("markdown");
    element.replaceChildren(fragment(text));
  }
  const api = {
    speechDuration,
    isRecent,
    safeLink,
    plainText,
    fragment,
    render,
  };
  scope.StudioText = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof window === "undefined" ? globalThis : window);
