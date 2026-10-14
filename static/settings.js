(() => {
  "use strict";
  const root = document.getElementById("studio-hub"),
    dialog = root.querySelector(".settings-page"),
    form = dialog.querySelector("form"),
    status = dialog.querySelector("[data-settings-status]");
  let current = { mode: "off", availableClis: [] },
    loaded = false,
    busy = false,
    request = 0;
  const field = (n) => form.elements.namedItem(n),
    at = (s) => dialog.querySelector(s);
  function fields(keep = false) {
    const mode = field("mode").value,
      provider = field("provider"),
      old = keep ? current.provider : provider.value;
    provider.replaceChildren(
      ...(mode === "cli"
        ? [
            ["codex", "Codex CLI"],
            ["claude", "Claude Code CLI"],
          ]
        : [
            ["openai", "OpenAI"],
            ["anthropic", "Anthropic"],
          ]
      ).map(([id, name]) => new Option(name, id)),
    );
    if ([...provider.options].some((o) => o.value === old))
      provider.value = old;
    at("[data-custom-settings]").hidden = mode === "off";
    at("[data-key-field]").hidden = mode !== "byok";
    at("[data-model-optional]").hidden = mode !== "cli";
    field("model").required = mode === "byok";
    field("consent").required = mode !== "off";
    at("[data-cli-status]").textContent =
      mode === "cli"
        ? current.availableClis?.includes(provider.value)
          ? "CLI found. Make sure you are signed in."
          : "CLI not found on this server. Install it and sign in before saving."
        : "Use the exact model ID from your provider.";
    at("[data-key-note]").textContent =
      current.hasKey &&
      current.mode === "byok" &&
      current.provider === provider.value
        ? "A key is already set. Leave blank to keep it."
        : "A key is required for this provider.";
  }
  async function open() {
    const generation = ++request;
    if (!dialog.open) dialog.showModal();
    loaded = false;
    status.textContent = "Loading settings…";
    form.querySelector("[type=submit]").disabled = true;
    try {
      const r = await fetch("/api/narration/config");
      if (!r.ok) throw Error();
      const data = await r.json();
      if (generation !== request || !dialog.open) return;
      current = data;
      field("mode").value = current.mode;
      field("model").value = current.model || "";
      field("instructions").value = current.instructions || "";
      field("apiKey").value = "";
      field("consent").checked = false;
      fields(true);
      loaded = true;
      status.textContent = "";
    } catch {
      if (generation === request && dialog.open)
        status.textContent =
          "Could not load settings. Close and reopen to retry.";
    } finally {
      if (generation === request)
        form.querySelector("[type=submit]").disabled = !loaded;
    }
  }
  root.querySelector("[data-open-settings]").addEventListener("click", open);
  at("[data-close-settings]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    request++;
    field("apiKey").value = "";
    root.querySelector("[data-open-settings]").focus();
  });
  field("mode").addEventListener("change", () => {
    field("apiKey").value = "";
    field("consent").checked = false;
    fields();
  });
  field("provider").addEventListener("change", () => {
    field("apiKey").value = "";
    field("consent").checked = false;
    fields();
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!loaded || busy) return;
    busy = true;
    const button = form.querySelector("[type=submit]");
    button.disabled = true;
    status.textContent = "Saving…";
    const payload = Object.fromEntries(
      ["mode", "provider", "model", "apiKey", "instructions"].map((n) => [
        n,
        field(n).value,
      ]),
    );
    payload.consent = field("consent").checked;
    try {
      const r = await fetch("/api/narration/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }),
        data = await r.json();
      if (!r.ok) throw Error(data.error || "Could not save settings.");
      current = data;
      field("apiKey").value = "";
      fields(true);
      status.textContent =
        data.mode === "off"
          ? "Saved. Following original contributions."
          : "Saved. Use “Create studio update” in the studio when you want a presentation.";
      window.dispatchEvent(new CustomEvent("studio-settings-saved"));
    } catch (error) {
      status.textContent =
        error.message || "Could not save settings. Try again.";
    } finally {
      busy = false;
      button.disabled = false;
    }
  });
})();
