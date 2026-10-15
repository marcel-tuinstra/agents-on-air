(() => {
  "use strict";
  const root = document.getElementById("studio-hub"),
    q = (s) => root.querySelector(s),
    reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const themes = window.StudioThemes;
  const studioNames = Object.fromEntries(
    Object.entries(themes).map(([id, pack]) => [id, pack.name]),
  );
  const rigStyle = () => themes[theme].rig;
  const providerMeta = {
    codex: { name: "Codex", icon: "/openai.svg" },
    claude: { name: "Claude Code", icon: "/anthropic.svg" },
  };
  let theme = Object.keys(themes)[0],
    selected = "",
    view = "full",
    savedSelection = false,
    catalog = [],
    groups = [],
    providers = [],
    selectedProviderHealthy = null,
    groupOpen = {},
    snapshot = null;
  let ready = false,
    online = false,
    clock = 0,
    last = 0,
    lastPaint = 0,
    lastRoomCheck = 0,
    rosterKey = null,
    displayAgents = [],
    focusAgent = null,
    activeWorkArtifact = null,
    activeWorkMessageId = null;
  let filter = "all",
    expanded = false,
    seen = null,
    initialSnapshot = true;
  const captionText = q("[data-caption-text]"),
    captionBubble = q(".speech-bubble"),
    captionCanvas = document.createElement("canvas"),
    captionMeasure = captionCanvas.getContext("2d");
  function captionWidth() {
    const style = getComputedStyle(captionText);
    captionMeasure.font = style.font;
    const liveWidth = captionText.clientWidth - parseFloat(style.paddingLeft || 0) - parseFloat(style.paddingRight || 0),
      laneWidth = captionBubble.parentElement?.clientWidth || 0,
      width = liveWidth > 0 ? liveWidth : Math.max(120, laneWidth - 130);
    return Math.max(20, width - 6);
  }
  function measuredCaptionFit(text, lines = 2) {
    const style = getComputedStyle(captionText),
      spacing = Number.parseFloat(style.letterSpacing) || 0;
    return StudioCaptionFit(text, captionWidth(), (part) =>
      captionMeasure.measureText(part).width + Math.max(0, Array.from(part).length - 1) * spacing, lines);
  }
  function captionSegments(text) {
    return measuredCaptionFit(text);
  }
  function renderCaptionText(text) {
    if (captionText.textContent === text && captionText.dataset.renderedWidth === String(captionWidth())) return;
    const fragment = document.createDocumentFragment();
    for (const line of measuredCaptionFit(text, 1)) {
      const row = document.createElement("span");
      row.style.display = "block";
      row.style.whiteSpace = "nowrap";
      row.textContent = line;
      fragment.append(row);
    }
    captionText.replaceChildren(fragment);
    captionText.dataset.renderedWidth = String(captionWidth());
  }
  const captions = new StudioCaptionModel(captionSegments);
  let audioWasActive = false,
    captionEpoch = 0;
  function clearCaptions() {
    captionEpoch++;
    if (captionBubble.contains(document.activeElement)) document.activeElement.blur();
    captions.reset();
    updateCaption();
  }
  let narrationConfig = {
      enabled: false,
      mode: "off",
      note: "Studio updates are not configured.",
    },
    narration = null;
  const appearances = new Map(),
    talkUntil = new Map(),
    arrivedAt = new Map();

  const scratch = document.createElement("canvas");
  scratch.width = scratch.height = 256;
  const sx = scratch.getContext("2d");
  let currentViseme = { code: "X", width: 1, open: 0 };
  const rig = StudioRig.create();
  function frame(id) {
    return rig.frame(theme, id);
  }
  function drawFace(ctx, id, opening, blink, time) {
    rig.face(ctx, theme, id, { ...currentViseme, open: opening }, blink, time);
  }
  function drawChannelPortraits() {
    const selectedTheme = theme;
    try {
      for (const canvas of root.querySelectorAll("[data-channel-portrait]")) {
        theme = canvas.dataset.channelPortrait;
        sx.clearRect(0, 0, 256, 256);
        sx.drawImage(frame(0, 0), 0, 0);
        drawFace(sx, 0, 0, 0, 0);
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, 128, 128);
        ctx.imageSmoothingEnabled = rigStyle() !== "pocket";
        const [x, y, w, h] = themes[theme].portrait,
          scale = 116 / Math.max(w, h);
        ctx.drawImage(
          scratch,
          x,
          y,
          w,
          h,
          (128 - w * scale) / 2,
          (128 - h * scale) / 2,
          w * scale,
          h * scale,
        );
      }
    } finally {
      theme = selectedTheme;
    }
  }

  try {
    const p = JSON.parse(
      localStorage.getItem("studio-live-preferences") || "{}",
    );
    if (Object.hasOwn(studioNames, p.theme)) theme = p.theme;
    if (p.view === "ambient") view = p.view;
    if (typeof p.chat === "string" && p.chat) {
      selected = p.chat;
      savedSelection = true;
    }
    if (p.groups && typeof p.groups === "object") groupOpen = p.groups;
  } catch {}
  function save() {
    try {
      localStorage.setItem(
        "studio-live-preferences",
        JSON.stringify({ theme, chat: selected, view, groups: groupOpen }),
      );
    } catch {}
  }
  function icon(provider) {
    const el = document.createElement("span");
    el.className = "provider-icon";
    el.style.setProperty(
      "--provider-icon",
      `url("${(providerMeta[provider] || providerMeta.codex).icon}")`,
    );
    el.setAttribute("aria-hidden", "true");
    return el;
  }
  const boot = new StudioBoot(q, reduced);
  let loadTarget = "loading";
  function updateLoading() {
    boot.setTarget(loadTarget);
  }
  function finishIntro() {
    boot.finish();
  }
  function setTheme() {
    root.dataset.theme = rigStyle();
    root.dataset.channel = theme;
    q("[data-header-channel]").textContent = themes[theme].shortName;
    updateHeaderTitle();
    root.style.setProperty("--set-y", themes[theme].sceneryPosition + "%");
    root.style.setProperty("--studio-image", `url("${themes[theme].scenery}")`);
    q("[data-studio]").textContent = studioNames[theme];
    root
      .querySelectorAll('[name="studio-channel"]')
      .forEach((i) => (i.checked = i.value === theme));
    if (ready) {
      drawChannelPortraits();
      paint();
    }
  }
  function updateHeaderTitle() {
    q("[data-open-picker]").title =
      (snapshot?.chat.title || "Your chats") + " · " + studioNames[theme];
  }
  function showError(message) {
    q("[data-error]").textContent = message || "";
    q("[data-error]").hidden = !message;
  }
  function connection(label, state) {
    const el = q("[data-connection]");
    el.dataset.state = state;
    el.title = label;
    q("[data-connection-label]").textContent = label;
  }
  function statusLabel(s) {
    return (
      {
        working: "Working",
        idle: "Done",
        interrupted: "Interrupted",
        error: "Error",
        unknown: "Unknown status",
      }[s] || "Unknown status"
    );
  }
  function panel(name, open, trigger) {
    const el = q(name === "picker" ? ".chat-picker" : ".transcript-panel"),
      back = q(
        name === "picker" ? "[data-picker-backdrop]" : "[data-drawer-backdrop]",
      ),
      button = q(
        name === "picker" ? "[data-open-picker]" : "[data-open-transcript]",
      );
    if (open) {
      closePanel(name === "picker" ? "transcript" : "picker");
      el.hidden = false;
      back.hidden = false;
      el.setAttribute("role", "dialog");
      el.setAttribute("aria-modal", "true");
      el.dataset.returnFocus = (trigger || button).dataset.returnFocus || "";
      el._returnFocus = trigger || button;
      button?.setAttribute("aria-expanded", "true");
      (name === "picker"
        ? q("[data-search]")
        : q("[data-close-transcript]")
      ).focus();
    } else {
      el.hidden = true;
      back.hidden = true;
      button?.setAttribute("aria-expanded", "false");
      (el._returnFocus || button)?.focus({ preventScroll: true });
      el._returnFocus = null;
    }
  }
  function closePanel(name) {
    const el = q(name === "picker" ? ".chat-picker" : ".transcript-panel");
    if (!el.hidden) panel(name, false);
  }
  function trap(e) {
    if (q(".settings-page").open) return;
    if (e.key === "Escape") {
      if (!q(".transcript-panel").hidden) closePanel("transcript");
      else if (!q(".chat-picker").hidden) closePanel("picker");
      return;
    }
    if (e.key !== "Tab") return;
    const el = !q(".transcript-panel").hidden
      ? q(".transcript-panel")
      : !q(".chat-picker").hidden
        ? q(".chat-picker")
        : null;
    if (!el) return;
    const items = [
      ...el.querySelectorAll(
        'button:not(:disabled),input:not(:disabled),select:not(:disabled),summary,[tabindex="0"]',
      ),
    ].filter((x) => x.getClientRects().length);
    if (!items.length) return;
    const first = items[0],
      end = items.at(-1);
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      end.focus();
    } else if (!e.shiftKey && document.activeElement === end) {
      e.preventDefault();
      first.focus();
    }
  }
  function renderCatalog() {
    const list = q(".chat-list"),
      active = document.activeElement,
      focusChat = active?.dataset?.chat,
      focusGroup = active?.dataset?.group,
      term = q("[data-search]").value.toLocaleLowerCase();
    const matching = catalog
      .filter((c) => StudioStage.recent(c))
      .filter((c) =>
        `${c.title} ${c.providerLabel || ""} ${c.model || ""} ${c.groupLabel || ""}`
          .toLocaleLowerCase()
          .includes(term),
      );
    const definitions = [...groups];
    for (const c of matching)
      if (!definitions.some((g) => g.id === c.groupId))
        definitions.push({
          id: c.groupId || c.provider + ":recent",
          label: c.groupLabel || "Recent",
          provider: c.provider,
          order: 1000,
        });
    definitions.sort(
      (a, b) =>
        (a.provider === "codex" ? 0 : 1) - (b.provider === "codex" ? 0 : 1) ||
        (a.order || 0) - (b.order || 0),
    );
    const frag = document.createDocumentFragment();
    for (const g of definitions) {
      const chats = matching.filter(
        (c) => (c.groupId || c.provider + ":recent") === g.id,
      );
      if (!chats.length) continue;
      const details = document.createElement("details");
      details.className = "chat-group";
      details.open = term
        ? true
        : (groupOpen[g.id] ??
          (!g.collapsed || chats.some((c) => c.id === selected)));
      const summary = document.createElement("summary");
      summary.className = "group-title";
      summary.dataset.group = g.id;
      summary.append(icon(g.provider));
      const name = document.createElement("span");
      name.textContent = g.label;
      const count = document.createElement("small");
      count.textContent = String(chats.length);
      summary.append(name, count);
      details.append(summary);
      const children = document.createElement("div");
      children.className = "group-chats";
      for (const c of chats.sort(
        (a, b) => (b.lastActivityAt || 0) - (a.lastActivityAt || 0),
      )) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "chat-button";
        b.dataset.chat = c.id;
        b.setAttribute("aria-current", String(c.id === selected));
        b.setAttribute(
          "aria-label",
          `${c.title} · ${c.providerLabel || c.provider}`,
        );
        b.append(icon(c.provider));
        const title = document.createElement("strong");
        title.textContent = c.title;
        b.append(title);
        b.addEventListener("click", () => choose(c.id));
        children.append(b);
      }
      details.append(children);
      details.addEventListener("toggle", () => {
        if (details.isConnected && !term) {
          groupOpen[g.id] = details.open;
          save();
        }
      });
      frag.append(details);
    }
    if (!matching.length) {
      const p = document.createElement("p");
      p.className = "empty-list";
      p.textContent = term
        ? "No active chats found."
        : "No chats active in the last 24 hours.";
      frag.append(p);
    }
    list.replaceChildren(frag);
    if (focusChat)
      list
        .querySelector(`[data-chat="${CSS.escape(focusChat)}"]`)
        ?.focus({ preventScroll: true });
    if (focusGroup)
      list
        .querySelector(`[data-group="${CSS.escape(focusGroup)}"]`)
        ?.focus({ preventScroll: true });
    return matching;
  }
  function emptyStage(reason) {
    loadTarget = "empty";
    updateLoading();
    q("[data-no-selection-copy]").textContent =
      reason || "Find chats active in the last 24 hours in Your chats.";
    q("[data-header-chat]").textContent = "Your chats";
    updateHeaderTitle();
    q("[data-header-provider]").replaceChildren();
  }
  function choose(id) {
    if (id === selected && snapshot) {
      closePanel("picker");
      return;
    }
    speech.reset();
    selected = id;
    save();
    snapshot = null;
    seen = null;
    initialSnapshot = true;
    clearCaptions();
    focusAgent = null;
    activeWorkArtifact = null;
    activeWorkMessageId = null;
    workView.reset();
    rosterKey = null;
    displayAgents = [];
    q("[data-cast-list]").replaceChildren();
    narration = null;
    q("[data-summary-status]").replaceChildren();
    filter = "all";
    expanded = false;
    talkUntil.clear();
    arrivedAt.clear();
    q("[data-no-selection]").hidden = true;
    q("[data-ready]").hidden = true;
    loadTarget = "loading";
    updateLoading();
    q("[data-load-label]").textContent = "Loading chat…";
    showError("");
    closePanel("picker");
    renderCatalog();
    connect();
  }
  function expireSelected() {
    selected = "";
    save();
    snapshot = null;
    seen = null;
    speech.reset();
    clearCaptions();
    rosterKey = null;
    displayAgents = [];
    q("[data-cast-list]").replaceChildren();
    emptyStage(
      "This chat has been inactive for 24 hours. Choose an active chat to keep watching.",
    );
    connect();
  }
  const connectionStream = new StudioStream();
  function connect() {
    online = false;
    selectedProviderHealthy = null;
    connectionStream.connect(selected, {
      connecting: () => connection("Connecting…", "connecting"),
      catalog: (data) => {
        catalog = data.chats || [];
        groups = data.groups || [];
        providers = data.providers || [];
        q("[data-sources]").textContent = providers
          .map(
            (p) =>
              `${providerMeta[p.id]?.name || p.id}: ${p.connected ? "connected" : p.error || "unavailable"}`,
          )
          .join(" · ");
        const matching = renderCatalog(),
          decision = StudioStage.selectionDecision(
            catalog,
            selected,
            providers,
          );
        if (decision === "expired") {
          expireSelected();
          return;
        }
        if (decision === "unavailable") {
          selectedProviderHealthy = false;
          online = false;
          connection("Source unavailable", "offline");
          const provider = providers.find(
            (p) => p.id === selected.split(":")[0],
          );
          showError(
            (provider?.error || "The selected chat source is unavailable.") +
              " The last received work remains visible.",
          );
          if (snapshot) renderRoomState();
          else
            q("[data-load-label]").textContent =
              "The selected source is unavailable. This chat will resume when it reconnects.";
          return;
        }
        if (selected) {
          selectedProviderHealthy = true;
          if (snapshot) {
            online = true;
            connection("Connected · local viewer", "online");
            showError("");
            renderRoomState();
          }
        } else if (!savedSelection && matching.length) {
          savedSelection = true;
          choose(matching[0].id);
        } else emptyStage();
      },
      snapshot: (incoming) => {
        if (incoming.chat.id !== selected) return;
        if (
          selectedProviderHealthy === true &&
          !StudioStage.recent(incoming.chat)
        ) {
          expireSelected();
          return;
        }
        const previous = seen;
        seen = new Map((incoming.messages || []).map((m) => [m.id, m.text]));
        if (previous) {
          for (const m of incoming.messages || [])
            if (m.role === "assistant" && previous.get(m.id) !== m.text) {
              talkUntil.set(
                m.agentId,
                performance.now() + StudioText.speechDuration(m.text),
              );
              arrivedAt.set(m.agentId, performance.now());
              const captionId = enqueueCaption(m, previous.get(m.id));
              speech.offer(m, incoming.agents, false, previous.get(m.id), captionId);
            }
        } else if (initialSnapshot) {
          const latest = (incoming.messages || [])
            .filter((m) => m.role === "assistant")
            .at(-1);
          if (latest) {
            captions.append(StudioText.plainText(latest.text), {
              speaker: latest.speaker,
              at: latest.at,
              messageId: latest.id,
              agentId: latest.agentId,
            }, performance.now(), { initial: true });
          }
          initialSnapshot = false;
        }
        snapshot = incoming;
        online = selectedProviderHealthy !== false;
        connection(
          online ? "Connected · local viewer" : "Source unavailable",
          online ? "online" : "offline",
        );
        loadTarget = "ready";
        updateLoading();
        if (online) showError("");
        render();
      },
      heartbeat: (data) => {
        online = !!data.sourceHealthy && selectedProviderHealthy !== false;
        connection(
          online ? "Connected · local viewer" : "Source unavailable",
          online ? "online" : "offline",
        );
        renderRoomState();
      },
      "source-error": (data) => {
        online = false;
        speech.reset();
        talkUntil.clear();
        connection("Source unavailable", "offline");
        showError(data.error || "The chat source is unavailable.");
        renderRoomState();
      },
      disconnect: () => {
        online = false;
        speech.reset();
        talkUntil.clear();
        connection("Disconnected · reconnecting…", "offline");
        showError(
          "Disconnected from the local viewer. The last received work remains visible.",
        );
        renderRoomState();
      },
    });
  }
  function enqueueCaption(m, old) {
    const full = StudioText.plainText(m.text);
    const previous = old === undefined ? "" : StudioText.plainText(old);
    const added =
      previous && full.startsWith(previous)
        ? full.slice(previous.length)
        : full;
    return captions.append(added, {
      speaker: m.speaker, at: m.at, messageId: m.id, agentId: m.agentId,
    }, performance.now());
  }
  function captionCurrent() {
    return captions.current;
  }
  async function resumeCaptions() {
    const epoch = captionEpoch;
    const selectedCaption = captions.current,
      fromHistory = captions.history;
    captions.setPaused(false, performance.now());
    if (fromHistory && selectedCaption)
      await speech.restartFrom(captions.records, selectedCaption);
    else if (speech.mode !== "off" && speech.paused)
      await speech.pause();
    if (epoch !== captionEpoch) return false;
    updateCaption();
    if (snapshot) renderWork();
    return true;
  }
  async function replayMessage(m) {
    const epoch = captionEpoch;
    const id = captions.append(StudioText.plainText(m.text), {
      speaker: m.speaker, at: m.at, messageId: m.id, agentId: m.agentId,
    }, performance.now());
    if (!id) return;
    const selectedCaption = captions.items.find((item) => item.id === id);
    captions.index = captions.items.indexOf(selectedCaption);
    captions.setPaused(false, performance.now());
    updateCaption();
    await speech.restartFrom(captions.records.filter((record) => record.id === id), selectedCaption);
    if (epoch !== captionEpoch) return;
    updateCaption();
    renderWork();
  }
  function speaking(id) {
    if (speech.enabled && speech.context?.state === "running" && !speech.failed && speech.mode !== "off")
      return speech.speaking(id);
    return online && !captions.paused && !captions.history && captions.visible &&
      captions.current?.agentId === id && performance.now() < captions.due;
  }
  function sprite(agent) {
    if (agent?.isMain) return 0;
    const key = selected;
    if (!appearances.has(key)) appearances.set(key, new Map());
    const map = appearances.get(key);
    if (!map.has(agent.id)) map.set(agent.id, map.size + 1);
    return ((map.get(agent.id) - 1) % 10) + 1;
  }
  function latest(agentId) {
    return (
      snapshot?.messages
        ?.filter((m) => m.agentId === agentId && m.role === "assistant")
        .at(-1) || null
    );
  }
  function renderRoomState() {
    if (!snapshot) return;
    const el = q("[data-room-state]");
    const state = StudioStage.roomState(snapshot.chat, online);
    root.dataset.room = state;
    el.dataset.state = state;
    el.textContent =
      state === "offline"
        ? "Source disconnected. The last received work remains visible."
        : state === "waiting"
          ? "No new activity for an hour · lights dimmed. The host is waiting."
          : snapshot.statusNote || "Live recorded activity";
    q("[data-host-status]").textContent =
      state === "waiting"
        ? "Waiting for activity"
        : state === "offline"
          ? "Disconnected"
          : speaking(snapshot.agents.find((a) => a.isMain)?.id)
            ? "Speaking"
            : statusLabel(snapshot.agents.find((a) => a.isMain)?.status);
    paint();
  }
  function renderCast() {
    const agents = snapshot.agents || [],
      main = agents.find((a) => a.isMain);
    const others = agents
      .filter((a) => !a.isMain)
      .sort(
        (a, b) =>
          Number(b.status === "working") - Number(a.status === "working") ||
          (b.lastActivityAt || 0) - (a.lastActivityAt || 0),
      )
      .slice(0, 10);
    displayAgents = others;
    const key = others.map((a) => a.id).join("|");
    if (rosterKey !== key) {
      rosterKey = key;
      const frag = document.createDocumentFragment();
      for (const a of others) {
        const card = document.createElement("div");
        card.className = "cast-member";
        card.dataset.uid = a.id;
        card.dataset.shadow = String(sprite(a) > 5);
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 96;
        canvas.setAttribute("aria-hidden", "true");
        const info = document.createElement("span");
        info.className = "cast-info";
        const name = document.createElement("strong"),
          status = document.createElement("small");
        info.append(name, status);
        const button = document.createElement("button");
        button.type = "button";
        button.setAttribute("aria-label", a.name + ": read contribution");
        button.addEventListener("click", () => {
          focusAgent = a.id;
          filter = a.id;
          expanded = false;
          openTranscript(button);
        });
        card.append(canvas, info, button);
        frag.append(card);
      }
      q("[data-cast-list]").replaceChildren(frag);
    }
    for (const card of q("[data-cast-list]").children) {
      const a = others.find((x) => x.id === card.dataset.uid);
      if (!a) {
        card.remove();
        continue;
      }
      card.querySelector("strong").textContent = a.name;
      card.querySelector("small").textContent = speaking(a.id)
        ? "Speaking"
        : statusLabel(a.status);
      card.dataset.speaking = String(speaking(a.id));
    }
    updateCaption();
    q("[data-cast-empty]").hidden = !!others.length;
    q("[data-hostname]").textContent =
      (main?.model || "Lead agent") + " · lead agent";
    q("[data-host-status]").textContent =
      root.dataset.room === "waiting"
        ? "Waiting for activity"
        : root.dataset.room === "offline"
          ? "Disconnected"
          : main && speaking(main.id)
            ? "Speaking"
            : statusLabel(main?.status);
  }
  function currentMessage() {
    const c = captionCurrent();
    if (captions.history && c?.messageId) {
      const m = snapshot.messages.find((x) => x.id === c.messageId);
      if (m) return m;
    }
    const audio = speech.current;
    if (audio?.playing && audio.messageId) {
      const m = snapshot.messages.find((x) => x.id === audio.messageId);
      if (m) return m;
    }
    if (c?.messageId) {
      const m = snapshot.messages.find((x) => x.id === c.messageId);
      if (m) return m;
    }
    return (
      snapshot.messages.filter((m) => m.role === "assistant").at(-1) || null
    );
  }
  const workView = StudioWorkView.create(root, {
    onSelection: (selection) => {
      activeWorkArtifact = selection.artifact;
      activeWorkMessageId = selection.messageId;
    },
  });
  function renderWork() {
    workView.render(snapshot, currentMessage(), selected, focusAgent);
  }
  function updateCaption() {
    const current = speech.current;
    if (speech.context?.state === "running" && !speech.paused && !speech.failed)
      captions.alignAudio(current);
    const c = captions.resolve(current),
      text = c?.text || "";
    renderCaptionText(text);
    q("[data-caption-speaker]").textContent = c?.speaker || "";
    const at = c?.at || snapshot?.messages.find((m) => m.id === c?.messageId)?.at;
    q("[data-caption-time]").textContent = at
      ? new Intl.DateTimeFormat("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
        }).format(at * 1000)
      : "";
    captionBubble.hidden = !captions.visible && !captionBubble.contains(document.activeElement);
    const agent = snapshot?.agents?.find((a) => a.id === c?.agentId);
    captionBubble.dataset.speakerKind = agent && !agent.isMain && c?.origin !== "narration" ? "subagent" : "lead";
    captionBubble.dataset.speakerId = c?.agentId || "";
    const bubbleSpeaker = q("[data-bubble-speaker]");
    if (bubbleSpeaker) {
      bubbleSpeaker.hidden = captionBubble.hidden || captionBubble.dataset.speakerKind !== "subagent";
      q("[data-bubble-name]").textContent = agent?.name || c?.speaker || "";
    }
    for (const card of q("[data-cast-list]").children)
      card.dataset.captionActive = String(!captionBubble.hidden && captionBubble.dataset.speakerKind === "subagent" && card.dataset.uid === c?.agentId);
    q("[data-caption-back]").disabled = captions.index <= 0;
    q("[data-caption-next]").disabled =
      captions.index < 0 || captions.index >= captions.items.length - 1;
    const pause = q("[data-caption-pause]");
    pause.setAttribute("aria-pressed", String(captions.paused));
    pause.dataset.paused = String(captions.paused);
    pause.setAttribute("aria-label", captions.paused ? "Resume captions" : "Pause captions");
    pause.title = pause.getAttribute("aria-label");
    refreshCastSpeaking();
  }
  function refreshCastSpeaking() {
    if (!snapshot) return;
    for (const card of q("[data-cast-list]").children) {
      const agent = snapshot.agents.find((a) => a.id === card.dataset.uid);
      if (!agent) continue;
      const active = speaking(agent.id);
      card.dataset.speaking = String(active);
      card.querySelector("small").textContent = active ? "Speaking" : statusLabel(agent.status);
    }
    const main = snapshot.agents.find((a) => a.isMain);
    q("[data-host-status]").textContent =
      root.dataset.room === "waiting" ? "Waiting for activity" :
      root.dataset.room === "offline" ? "Disconnected" :
      main && speaking(main.id) ? "Speaking" : statusLabel(main?.status);
  }
  function renderTranscript() {
    if (!snapshot) return;
    const agents = snapshot.agents || [],
      messages = snapshot.messages || [],
      select = q("[data-filter]"),
      key = agents.map((a) => a.id + a.name).join("|");
    if (select.dataset.key !== key) {
      select.dataset.key = key;
      select.replaceChildren(
        new Option("Everyone", "all"),
        ...agents.map((a) => new Option(a.name + " · " + a.model, a.id)),
      );
      if (!agents.some((a) => a.id === filter)) filter = "all";
    }
    select.value = filter;
    const relevant = messages.filter(
        (m) => filter === "all" || m.agentId === filter,
      ),
      shown = expanded ? relevant : relevant.slice(-12);
    q("[data-logcount]").textContent = `(${relevant.length})`;
    q("[data-history-note]").textContent = [
      snapshot.historyLimited
        ? "Recent transcript, up to 200 messages. Older messages remain in the source app."
        : "Recorded user and agent messages.",
      ...(snapshot.warnings || []),
    ]
      .filter(Boolean)
      .join(" ");
    const frag = document.createDocumentFragment();
    for (const m of [...shown].reverse()) {
      const row = document.createElement("article");
      row.className = "log";
      row.dataset.messageId = m.id;
      const time = document.createElement("time");
      time.dateTime = new Date(m.at * 1000).toISOString();
      time.textContent = new Intl.DateTimeFormat("en-GB", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }).format(m.at * 1000);
      const body = document.createElement("div"),
        name = document.createElement("strong"),
        text = document.createElement("div");
      name.textContent = m.speaker;
      StudioText.render(text, m.text);
      body.append(name);
      if (m.role === "assistant") {
        const play = document.createElement("button");
        play.type = "button";
        play.className = "read-message";
        play.textContent = "Play";
        play.disabled = !speech.enabled;
        play.addEventListener("click", () => { void replayMessage(m); });
        body.append(play);
      }
      body.append(text);
      row.append(time, body);
      frag.append(row);
    }
    if (!shown.length) {
      const p = document.createElement("p");
      p.textContent = "No recorded messages for this speaker.";
      frag.append(p);
    }
    q(".logs").replaceChildren(frag);
    q("[data-more]").hidden = relevant.length <= 12;
    q("[data-more]").textContent = expanded
      ? "Show latest messages"
      : `Show more messages (${relevant.length - 12})`;
  }
  function openTranscript(trigger, messageId) {
    panel("transcript", true, trigger);
    renderTranscript();
    if (messageId) {
      expanded = true;
      renderTranscript();
      q(".logs")
        .querySelector(`[data-message-id="${CSS.escape(messageId)}"]`)
        ?.scrollIntoView({ block: "center" });
    }
  }
  function render() {
    if (!snapshot || !ready) return;
    q("[data-speech-latest]").disabled =
      !speech.enabled ||
      !snapshot.messages?.some((m) => m.role === "assistant");
    q("[data-title]").textContent = snapshot.chat.title;
    q("[data-header-chat]").textContent = snapshot.chat.title;
    updateHeaderTitle();
    const provider = q("[data-provider]");
    provider.replaceChildren(
      icon(snapshot.chat.provider),
      document.createTextNode(
        snapshot.chat.providerLabel || snapshot.chat.provider,
      ),
    );
    q("[data-header-provider]").replaceChildren(icon(snapshot.chat.provider));
    const main = snapshot.agents.find((a) => a.isMain);
    q("[data-summary]").textContent =
      main?.model || snapshot.chat.model || "Local chat";
    root.dataset.view = view;
    q("[data-view-toggle]").title =
      view === "ambient" ? "Full scene" : "Compact view";
    q("[data-view-toggle]").setAttribute(
      "aria-label",
      q("[data-view-toggle]").title,
    );
    q("[data-view-toggle]").setAttribute(
      "aria-pressed",
      String(view === "ambient"),
    );
    renderRoomState();
    renderCast();
    updateCaption();
    renderWork();
    if (!q(".transcript-panel").hidden) renderTranscript();
    paint();
  }
  function draw(canvas, agent, waiting = false) {
    if (!ready || !agent || !canvas) return;
    const id = sprite(agent),
      text = latest(agent.id)?.text || "",
      elapsed = performance.now() - (arrivedAt.get(agent.id) || 0),
      talk = !waiting && speaking(agent.id),
      ch = text[Math.floor(elapsed / 65) % Math.max(1, text.length)] || " ";
    const mouth =
        !waiting && speech.enabled && speech.context?.state === "running" && !speech.failed && speech.current?.playing
          ? speech.mouth(agent.id)
          : null,
      amount = waiting
        ? 0
        : (mouth?.open ??
          (talk && !reduced.matches
            ? /[aeou]/i.test(ch)
              ? 0.8
              : /[i]/i.test(ch)
                ? 0.45
                : /[ .,!mbp]/i.test(ch)
                  ? 0.05
                  : 0.27
            : 0));
    currentViseme = waiting
      ? { code: "X", width: 1, open: 0 }
      : mouth || {
          code: amount > 0.3 ? "C" : amount > 0 ? "B" : "X",
          width: 1,
          open: amount,
        };
    canvas.dataset.viseme = currentViseme.code;
    canvas.dataset.mouthOpen = amount.toFixed(3);
    const rest = waiting
      ? StudioBody.pose({
          id,
          time: clock,
          waiting: true,
          reduced: reduced.matches,
        }).sleep
      : 0;
    const blink = reduced.matches
        ? waiting
          ? 1
          : 0
        : waiting
          ? 0.45 + rest * 0.55
          : Math.max(
              0,
              1 - Math.abs(((clock + id * 983) % (3900 + id * 271)) - 95) / 95,
            ),
      ctx = canvas.getContext("2d"),
      z = canvas.width,
      shadow = id > 5 && !waiting;
    ctx.clearRect(0, 0, z, z);
    ctx.save();
    ctx.scale(z / 256, z / 256);
    const paintCtx = shadow ? sx : ctx;
    if (shadow) sx.clearRect(0, 0, 256, 256);
    if (window.StudioBody?.draw) {
      StudioBody.draw(paintCtx, {
        frame: frame(id, 0),
        id,
        theme: rigStyle(),
        time: clock,
        talking: talk,
        waiting,
        pointing: !!agent.isMain && talk && !!activeWorkArtifact,
        reduced: reduced.matches,
        drawFace: () => drawFace(paintCtx, id, amount, blink, clock),
      });
    } else {
      paintCtx.drawImage(frame(id, 0), 0, 0);
      drawFace(paintCtx, id, amount, blink, clock);
    }
    if (shadow) {
      sx.globalCompositeOperation = "source-in";
      sx.fillStyle = rigStyle() === "paper" ? "#465354" : "#8490a7";
      sx.fillRect(0, 0, 256, 256);
      sx.globalCompositeOperation = "source-over";
      ctx.drawImage(scratch, 0, 0);
    }
    ctx.restore();
  }
  function paint() {
    if (!snapshot || !ready || document.hidden) return;
    const main = snapshot.agents.find((a) => a.isMain);
    const waiting = root.dataset.room === "waiting";
    q("[data-host]").dataset.pose = waiting ? "waiting" : "active";
    draw(q("[data-host]"), main, waiting);
    for (const card of q("[data-cast-list]").children) {
      const agent = displayAgents.find((a) => a.id === card.dataset.uid);
      draw(card.querySelector("canvas"), agent);
    }
    const active = snapshot.agents.find((a) => a.id === captionBubble.dataset.speakerId);
    if (active && captionBubble.dataset.speakerKind === "subagent")
      draw(q("[data-bubble-portrait]"), active);
  }
  function tick(now) {
    requestAnimationFrame(tick);
    clock += last ? Math.min(100, now - last) : 0;
    last = now;
    if (document.hidden) return;
    if (now - lastPaint > 1000 / 30) {
      paint();
      lastPaint = now;
    }
    let changed = false;
    for (const [id, end] of talkUntil)
      if (now > end) {
        talkUntil.delete(id);
        changed = true;
      }
    if (changed && snapshot) renderCast();
    speech.dropUnavailableAudio();
    const audioClockActive = speech.enabled && speech.context?.state === "running" && !speech.failed && speech.mode !== "off" &&
      (!!speech.current?.playing || !!speech.current || speech.queue.length > 0);
    if (captions.tick(now, audioClockActive)) {
      updateCaption();
      renderWork();
    }
    if (snapshot && now - lastRoomCheck >= 1000) {
      lastRoomCheck = now;
      renderRoomState();
    }
    if (speech.current?.playing && speech.context?.state === "running") updateCaption();
  }
  const speech = new StudioSpeech(
    () => {
      const mute = q("[data-audio-mute]");
      mute.setAttribute("aria-pressed", String(speech.muted));
      mute.title = speech.muted ? "Unmute gibberish" : "Mute gibberish";
      mute.setAttribute("aria-label", mute.title);
      q("[data-audio-on]").style.display = speech.muted ? "none" : "";
      q("[data-audio-off]").style.display = speech.muted ? "" : "none";
      q("[data-audio-off]").removeAttribute("hidden");
      q("[data-speech-pause]").disabled = !speech.enabled;
      q("[data-speech-pause]").title = speech.paused
        ? "Resume audio"
        : "Pause audio";
      q("[data-speech-pause]").setAttribute(
        "aria-label",
        q("[data-speech-pause]").title,
      );
      q("[data-speech-skip]").disabled = !speech.current;
      q("[data-speech-retry]").disabled = !speech.failed;
      q("[data-speech-latest]").disabled =
        !speech.enabled ||
        !snapshot?.messages?.some((m) => m.role === "assistant");
      q("[data-speech-status]").textContent = speech.status || "";
      q("[data-speech-status]").title = speech.status || "";
      const audioActive = speech.enabled && speech.context?.state === "running" && !speech.failed && speech.mode !== "off" &&
        (!!speech.current?.playing || !!speech.current || speech.queue.length > 0);
      if (audioWasActive && !audioActive && !captions.paused && !captions.history && captions.items.length) {
        captions.due = performance.now() + (captions.index === captions.items.length - 1
          ? 4000 : captions.hold(captions.current?.text || ""));
        captions.expired = false;
      }
      audioWasActive = audioActive;
      if (snapshot) {
        renderCast();
        updateCaption();
        renderWork();
        if (!q(".transcript-panel").hidden) renderTranscript();
      }
    },
    (id) => ({
      channel: theme,
      slot: sprite(
        snapshot?.agents?.find((a) => a.id === id) || { id, isMain: false },
      ),
    }),
  );
  q("[data-open-picker]").addEventListener("click", (e) =>
    panel("picker", true, e.currentTarget),
  );
  q("[data-open-picker-empty]").addEventListener("click", (e) =>
    panel("picker", true, e.currentTarget),
  );
  q("[data-close-picker]").addEventListener("click", () =>
    closePanel("picker"),
  );
  q("[data-picker-backdrop]").addEventListener("click", () =>
    closePanel("picker"),
  );
  q("[data-open-transcript]").addEventListener("click", (e) =>
    openTranscript(e.currentTarget),
  );
  q("[data-close-transcript]").addEventListener("click", () =>
    closePanel("transcript"),
  );
  q("[data-drawer-backdrop]").addEventListener("click", () =>
    closePanel("transcript"),
  );
  document.addEventListener("keydown", trap);
  root.querySelectorAll('[name="studio-channel"]').forEach((input) =>
    input.addEventListener("change", () => {
      if (input.checked) {
        speech.reset();
        clearCaptions();
        theme = input.value;
        setTheme();
        save();
      }
    }),
  );
  q("[data-search]").addEventListener("input", renderCatalog);
  q("[data-view-toggle]").addEventListener("click", () => {
    view = view === "full" ? "ambient" : "full";
    save();
    render();
  });
  q("[data-open-work-detail]").addEventListener("click", (e) => {
    if (activeWorkMessageId)
      openTranscript(e.currentTarget, activeWorkMessageId);
  });
  q("[data-filter]").addEventListener("change", (e) => {
    filter = e.target.value;
    renderTranscript();
  });
  q("[data-more]").addEventListener("click", () => {
    expanded = !expanded;
    renderTranscript();
  });
  q("[data-caption-back]").addEventListener("click", async () => {
    if (!captions.step(-1)) return;
    const epoch = captionEpoch;
    updateCaption();
    if (speech.mode !== "off" && !speech.paused) await speech.pause();
    if (epoch !== captionEpoch) return;
    updateCaption();
    renderWork();
  });
  captionBubble.addEventListener("focusout", () => queueMicrotask(updateCaption));
  const reflowCaptions = () => {
    captions.reflow(performance.now());
    if (snapshot) updateCaption();
  };
  if (typeof ResizeObserver !== "undefined")
    new ResizeObserver(reflowCaptions).observe(captionText);
  else window.addEventListener("resize", reflowCaptions);
  document.fonts?.ready.then(reflowCaptions);
  document.fonts?.addEventListener?.("loadingdone", reflowCaptions);
  q("[data-caption-next]").addEventListener("click", async () => {
    if (captions.step(1)) {
      const epoch = captionEpoch;
      updateCaption();
      if (speech.mode !== "off" && !speech.paused) await speech.pause();
      if (epoch !== captionEpoch) return;
      updateCaption();
      renderWork();
    }
  });
  q("[data-caption-pause]").addEventListener("click", async () => {
    const epoch = captionEpoch;
    if (!captions.paused) {
      captions.setPaused(true, performance.now());
      updateCaption();
      if (speech.mode !== "off" && !speech.paused) await speech.pause();
    } else {
      await resumeCaptions();
    }
    if (epoch !== captionEpoch) return;
    updateCaption();
    renderWork();
  });
  q("[data-audio-mute]").addEventListener("click", () =>
    speech.setMuted(!speech.muted),
  );
  window.addEventListener("pointerdown", () => speech.unlock());
  window.addEventListener("keydown", () => speech.unlock());
  q("[data-speech-pause]").addEventListener("click", async () => {
    const epoch = captionEpoch;
    if (captions.paused) await resumeCaptions();
    else {
      captions.setPaused(true, performance.now());
      updateCaption();
      await speech.pause();
    }
    if (epoch !== captionEpoch) return;
    updateCaption();
    renderWork();
  });
  q("[data-speech-skip]").addEventListener("click", () => speech.skip());
  q("[data-speech-retry]").addEventListener("click", () => speech.retry());
  q("[data-speech-latest]").addEventListener("click", () => {
    const m = snapshot?.messages.filter((m) => m.role === "assistant").at(-1);
    if (m) void replayMessage(m);
  });
  q("[data-summarize]").addEventListener("click", async () => {
    if (!selected || !narrationConfig.enabled || narrationConfig.mode === "off")
      return;
    const chatId = selected,
      button = q("[data-summarize]");
    button.disabled = true;
    q("[data-summary-status]").textContent = "Preparing studio update…";
    try {
      const response = await fetch("/api/narration", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chatId }),
      });
      const data = await response.json();
      if (!response.ok) throw Error(data.error || "Studio update failed");
      if (selected !== chatId) return;
      narration = data;
      q("[data-summary-status]").textContent =
        "AI studio update · on request · original contributions in transcript";
      const main = snapshot?.agents.find((a) => a.isMain),
        at = Number(data.createdAt) || Date.now() / 1000;
      const narrationCaptionId = captions.append(StudioText.plainText(data.text || ""), {
        speaker: "AI studio update", at, messageId: null,
        agentId: main?.id || null, origin: "narration",
      }, performance.now());
      if (narrationCaptionId) {
        captions.index = captions.items.findIndex((item) => item.id === captions.records.at(-1).id);
        captions.setPaused(false, performance.now());
        updateCaption();
      }
      if (main && speech.mode !== "off") {
        speech.reset();
        speech.offer(
          {
            id: "narration:" + at,
            agentId: main.id,
            speaker: "AI studio update",
            at,
            text: data.text || "",
            role: "assistant",
          },
          snapshot.agents,
          true,
          undefined,
          narrationCaptionId,
        );
      }
    } catch (error) {
      if (selected === chatId)
        q("[data-summary-status]").textContent =
          error.message || "Studio update failed";
    } finally {
      button.disabled = false;
    }
  });
  const configRequest = new LatestRequest();
  async function loadNarrationConfig() {
    try {
      await configRequest.run(
        async () => {
          const response = await fetch("/api/narration/config");
          if (!response.ok) throw Error("Configuration unavailable");
          return response.json();
        },
        (config) => {
          narrationConfig = config;
          const button = q("[data-summarize]");
          button.hidden = !config.enabled;
          button.disabled = !config.enabled || config.mode === "off";
          button.title = button.disabled
            ? config.note || "Studio updates are not configured."
            : "Create a studio update from this chat on request.";
        },
      );
    } catch {} // Keep the last confirmed configuration while disconnected.
  }
  window.addEventListener("studio-settings-saved", loadNarrationConfig);
  window.addEventListener("pagehide", () => {
    connectionStream.stop();
    speech.disable();
  });
  document.addEventListener("visibilitychange", () => {
    last = 0;
  });
  setInterval(() => {
    renderCatalog();
    const decision = StudioStage.selectionDecision(
      catalog,
      selected,
      providers,
    );
    if (decision === "expired") expireSelected();
    else if (snapshot) renderRoomState();
  }, 60000);
  root.dataset.view = view;
  setTheme();
  loadNarrationConfig();
  speech.init();
  Promise.all(
    Object.entries(themes).map(
      ([channel, pack]) =>
        new Promise((resolve, reject) => {
          const image = new Image();
          image.onload = () => {
            rig.setImage(image, channel);
            resolve();
          };
          image.onerror = reject;
          image.src = pack.cast;
        }),
    ),
  )
    .then(() => {
      ready = true;
      drawChannelPortraits();
      if (snapshot) render();
      requestAnimationFrame(tick);
    })
    .catch(() => {
      finishIntro();
      showError(
        "A channel's cast could not be loaded. Check its theme files and refresh.",
      );
    });
  connect();
})();
