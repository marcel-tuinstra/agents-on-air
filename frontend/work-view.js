/* Shared work rendering keeps its own selection, not the chat/audio controller's state. */
(function (scope) {
  function create(
    root,
    { stage = scope.StudioStage, onSelection = () => {} } = {},
  ) {
    const q = (selector) => root.querySelector(selector),
      StudioStage = stage;
    let snapshot = null,
      message = null,
      selected = "",
      focusAgent = null;
    let workKey = "",
      workChat = "",
      latestWorkId = null,
      selectedWorkId = null;
    let activeWorkArtifact = null,
      activeWorkMessageId = null;
    function validArtifactURL(url) {
      try {
        const u = new URL(url, location.href);
        return u.origin === location.origin &&
          /^\/api\/artifacts\/[A-Za-z0-9_-]+$/.test(u.pathname) &&
          !u.search &&
          !u.hash
          ? u.pathname
          : null;
      } catch {
        return null;
      }
    }
    function workTime(at) {
      return Number.isFinite(Number(at))
        ? new Intl.DateTimeFormat("en-GB", {
            hour: "2-digit",
            minute: "2-digit",
          }).format(Number(at) * 1000)
        : "";
    }
    function workText(el, message, event) {
      const label = document.createElement("p");
      label.className = "work-label";
      label.textContent = "Recorded activity";
      const title = document.createElement("h2");
      title.className = "work-title";
      title.textContent = event?.label || "Contribution recorded";
      const p = document.createElement("p");
      p.className = "work-empty";
      p.textContent = message
        ? "No local image or recorded diff is linked to this contribution. Open the transcript for the full text."
        : "No shared work is available in this chat yet.";
      el.append(label, title, p);
    }
    function browseWork(offset) {
      const works = StudioStage.workArtifacts(snapshot, message);
      const index = works.findIndex(
        (work) => work.artifact.id === selectedWorkId,
      );
      const target = works[index + offset];
      if (target) {
        selectedWorkId = target.artifact.id;
        renderWork();
      }
    }
    function renderWork() {
      const m = message,
        works = StudioStage.workArtifacts(snapshot, m);
      const newestId = works[0]?.artifact.id || null;
      if (workChat !== selected || latestWorkId !== newestId) {
        workChat = selected;
        latestWorkId = newestId;
        selectedWorkId = newestId;
      }
      let index = works.findIndex(
        (item) => item.artifact.id === selectedWorkId,
      );
      if (index < 0) {
        index = 0;
        selectedWorkId = newestId;
      }
      const work = works[index],
        a = work?.artifact,
        event = work?.event;
      const lastEvent = (snapshot.events || []).at(-1);
      const key = [
        m?.id,
        a?.id,
        event?.id,
        lastEvent?.id,
        works.length,
        focusAgent,
      ].join("|");
      if (workKey === key) return;
      workKey = key;
      q("[data-work-navigation]").hidden = works.length < 2;
      q("[data-work-position]").textContent = works.length
        ? `${index + 1} / ${works.length}`
        : "";
      q("[data-work-newer]").disabled = index === 0;
      q("[data-work-older]").disabled = index >= works.length - 1;
      const activity = q("[data-work-activity]");
      activity.hidden = !a || !lastEvent || lastEvent.at <= work.at;
      if (!activity.hidden) {
        const contributor = (snapshot.agents || []).find(
          (agent) => agent.id === lastEvent.agentId,
        );
        const note =
          index > 0
            ? "Viewing earlier work."
            : "Showing the last shared image or diff.";
        activity.textContent = `${contributor?.name || "Agent"} · ${workTime(lastEvent.at)} · ${lastEvent.label || "New activity"}. ${note}`;
      }
      activeWorkArtifact = null;
      activeWorkMessageId = a?.messageId || (!a ? m?.id : null);
      const detail = q("[data-open-work-detail]");
      detail.hidden = !activeWorkMessageId;
      const box = q("[data-work-content]");
      box.replaceChildren();
      const source = q("[data-work-source]");
      const actor = a
        ? (snapshot.agents || []).find((agent) => agent.id === a.agentId)
        : null;
      source.textContent = a
        ? `${actor?.name || actor?.model || "Agent"} · ${workTime(work.at)} · ${typeof a.provenance === "string" ? a.provenance : "local source"}`
        : m
          ? `${m.speaker} · ${workTime(m.at)} · recorded contribution`
          : lastEvent
            ? `${lastEvent.label || "Activity"} · ${workTime(lastEvent.at)}`
            : "No recorded contribution";
      if (a?.kind === "image" && validArtifactURL(a.url)) {
        activeWorkArtifact = a;
        q("[data-work-kind]").textContent = "Local image";
        const pair = StudioStage.pairImages(snapshot, a);
        if (
          pair &&
          validArtifactURL(pair.before.url) &&
          validArtifactURL(pair.after.url)
        ) {
          const grid = document.createElement("div");
          grid.className = "work-pair";
          for (const [label, item] of [
            ["Before", pair.before],
            ["After", pair.after],
          ]) {
            const figure = document.createElement("figure"),
              image = document.createElement("img"),
              caption = document.createElement("figcaption");
            image.src = validArtifactURL(item.url);
            image.alt = item.label || `${label} image`;
            image.onerror = () => {
              figure.replaceChildren(
                document.createTextNode("Local image unavailable."),
              );
              activeWorkArtifact = null;
            };
            caption.textContent = label + " · " + (item.label || "image");
            figure.append(image, caption);
            grid.append(figure);
          }
          box.append(grid);
        } else {
          const image = document.createElement("img");
          image.className = "work-image";
          image.src = validArtifactURL(a.url);
          image.alt = a.label || "Local image";
          image.onerror = () => {
            activeWorkArtifact = null;
            box.replaceChildren();
            workText(box, m, lastEvent);
            q("[data-work-kind]").textContent = "No shared work";
          };
          box.append(image);
          const label = document.createElement("p");
          label.className = "work-image-label";
          label.textContent = a.label || "Local image";
          box.append(label);
        }
        return;
      }
      if (a?.kind === "diff" && typeof a.text === "string") {
        activeWorkArtifact = a;
        q("[data-work-kind]").textContent = "Recorded change";
        const title = document.createElement("h2");
        title.className = "work-title";
        title.textContent = a.label || "Code change";
        const pre = document.createElement("pre");
        pre.className = "diff-view";
        const lines = StudioStage.diffLines(a.text);
        for (const line of lines) {
          const row = document.createElement("span");
          row.className = "diff-line diff-" + line.kind;
          row.textContent = line.text;
          pre.append(row);
        }
        const legend = document.createElement("p");
        legend.className = "diff-legend";
        for (const kind of ["added", "removed"]) {
          const item = document.createElement("span");
          item.className = "diff-count-" + kind;
          item.textContent =
            (kind === "added" ? "+" : "−") +
            lines.filter((line) => line.kind === kind).length +
            " " +
            kind;
          legend.append(item);
        }
        pre.tabIndex = 0;
        pre.setAttribute("aria-label", "Recorded diff");
        box.append(title, legend, pre);
        return;
      }
      q("[data-work-kind]").textContent = "No shared work";
      workText(box, m, lastEvent);
    }

    function refresh() {
      renderWork();
      onSelection({
        artifact: activeWorkArtifact,
        messageId: activeWorkMessageId,
      });
    }
    q("[data-work-newer]").addEventListener("click", () => {
      browseWork(-1);
      refresh();
    });
    q("[data-work-older]").addEventListener("click", () => {
      browseWork(1);
      refresh();
    });
    return {
      render(nextSnapshot, nextMessage, chatId, agentId) {
        snapshot = nextSnapshot;
        message = nextMessage;
        selected = chatId;
        focusAgent = agentId;
        refresh();
      },
      reset() {
        snapshot = null;
        message = null;
        workKey = "";
        workChat = "";
        latestWorkId = null;
        selectedWorkId = null;
      },
    };
  }
  scope.StudioWorkView = { create };
  if (typeof module !== "undefined") module.exports = { create };
})(typeof window === "undefined" ? globalThis : window);
