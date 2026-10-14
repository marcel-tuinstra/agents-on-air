/* Pure presentation rules for the local Agents on Air viewer. */
(function (scope) {
  "use strict";
  const RECENT_WINDOW = 24 * 60 * 60;
  const IDLE_AFTER = 60 * 60;
  function recent(chat, now = Date.now() / 1000) {
    const at = Number(chat?.lastActivityAt);
    return Number.isFinite(at) && at > 0 && at >= now - RECENT_WINDOW;
  }
  function waiting(chat, now = Date.now() / 1000) {
    const at = Number(chat?.lastActivityAt);
    return Number.isFinite(at) && at > 0 && now - at >= IDLE_AFTER;
  }
  function roomState(chat, online, now = Date.now() / 1000) {
    return !online ? "offline" : waiting(chat, now) ? "waiting" : "active";
  }
  function selectionStillActive(catalog, id, now = Date.now() / 1000) {
    return (
      !!id &&
      Array.isArray(catalog) &&
      catalog.some((chat) => chat.id === id && recent(chat, now))
    );
  }
  function selectionDecision(catalog, id, providers, now = Date.now() / 1000) {
    if (!id) return "none";
    const provider = Array.isArray(providers)
      ? providers.find((p) => p.id === id.split(":")[0])
      : null;
    if (!provider?.connected) return "unavailable";
    return selectionStillActive(catalog, id, now) ? "keep" : "expired";
  }
  function workArtifacts(snapshot, message) {
    const artifacts = Array.isArray(snapshot?.artifacts)
      ? snapshot.artifacts
      : [];
    const events = Array.isArray(snapshot?.events) ? snapshot.events : [];
    const byId = new Map(artifacts.map((a) => [a.id, a]));
    const candidates = [];
    for (const event of events) {
      for (const id of event.artifactIds || []) {
        const artifact = byId.get(id);
        if (
          artifact &&
          artifact.agentId === event.agentId &&
          ["image", "diff"].includes(artifact.kind)
        ) {
          candidates.push({
            artifact,
            event,
            at: Number(event.at) || Number(artifact.at) || 0,
          });
        }
      }
    }
    if (candidates.length)
      return candidates.sort(
        (a, b) => b.at - a.at || b.artifact.at - a.artifact.at,
      );
    if (!message) return [];
    const direct = artifacts
      .filter(
        (a) =>
          a.messageId === message.id &&
          a.agentId === message.agentId &&
          ["image", "diff"].includes(a.kind),
      )
      .sort((a, b) => b.at - a.at);
    return direct.map((artifact) => ({
      artifact,
      event: null,
      at: Number(artifact.at) || Number(message.at) || 0,
    }));
  }
  function selectWorkArtifact(snapshot, message) {
    return workArtifacts(snapshot, message)[0] || null;
  }
  function selectArtifact(snapshot, message) {
    return selectWorkArtifact(snapshot, message)?.artifact || null;
  }
  function pairImages(snapshot, artifact) {
    if (!artifact || artifact.kind !== "image") return null;
    const event = (snapshot?.events || []).find(
      (e) =>
        Array.isArray(e.artifactIds) && e.artifactIds.includes(artifact.id),
    );
    if (!event) return null;
    const images = (snapshot?.artifacts || []).filter(
      (a) =>
        event.artifactIds.includes(a.id) &&
        a.kind === "image" &&
        a.agentId === artifact.agentId,
    );
    const before = images.find((a) => a.role === "before"),
      after = images.find((a) => a.role === "after");
    return before && after ? { before, after } : null;
  }
  function appendCaptionParts(state, parts, meta, limit = 80) {
    if (!parts.length)
      return { items: state.items, index: state.index, changed: false };
    const atEnd = state.index >= state.items.length - 1;
    const start = state.items.length;
    const items = state.items.concat(parts.map((text) => ({ ...meta, text })));
    const excess = Math.max(0, items.length - limit);
    if (excess) items.splice(0, excess);
    const index =
      atEnd && !state.paused
        ? Math.min(items.length - 1, start - excess)
        : Math.max(0, state.index - excess);
    return { items, index, changed: index !== state.index };
  }
  function captionParts(input, max = 58) {
    const text = String(input || "")
      .replace(/\s+/gu, " ")
      .trim();
    if (!text) return [];
    const out = [];
    let remaining = text;
    while (remaining.length) {
      if (remaining.length <= max) {
        out.push(remaining);
        break;
      }
      const head = remaining.slice(0, max + 1),
        boundary = [...head.matchAll(/[.!?;,]\s+/gu)].at(-1);
      const cut =
        boundary && boundary.index >= max * 0.42
          ? boundary.index + boundary[0].length
          : head.lastIndexOf(" ");
      const end = cut >= max * 0.42 ? cut : max;
      out.push(remaining.slice(0, end).trim());
      remaining = remaining.slice(end).trim();
    }
    return out;
  }
  function diffLines(input) {
    let inHunk = false;
    return (String(input ?? "").match(/[^\n]*\n|[^\n]+$/g) || []).map(
      (text) => {
        let kind = "context";
        if (
          /^(diff --git |index |\*\*\* |--- |\+\+\+ )/.test(text) &&
          (!inHunk || /^(diff --git |\*\*\* )/.test(text))
        ) {
          kind = "meta";
          inHunk = false;
        } else if (text.startsWith("@@")) {
          kind = "hunk";
          inHunk = true;
        } else if (text.startsWith("\\ No newline")) kind = "meta";
        else if (text.startsWith("+")) kind = "added";
        else if (text.startsWith("-")) kind = "removed";
        return { text, kind };
      },
    );
  }
  const api = {
    diffLines,
    RECENT_WINDOW,
    IDLE_AFTER,
    recent,
    waiting,
    roomState,
    selectionStillActive,
    selectionDecision,
    workArtifacts,
    selectWorkArtifact,
    selectArtifact,
    pairImages,
    appendCaptionParts,
    captionParts,
  };
  scope.StudioStage = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof window === "undefined" ? globalThis : window);
