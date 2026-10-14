(function () {
  "use strict";
  const q = (s) => document.querySelector(s),
    casts = window.StudioThemes;
  let channel = Object.keys(casts)[0],
    run = 0,
    started = false,
    notice = "Ready for the preview.";
  const closed = { code: "X", width: 1, open: 0 };
  const speech = new StudioSpeech(controls, (id) => ({
    channel,
    slot: id === "host" ? 0 : 1,
  }));
  function controls() {
    const active = !!speech.current || speech.queue.length > 0;
    q("#pause").disabled = !active || speech.failed;
    q("#stop").disabled = !active;
    q("#pause").textContent = speech.paused ? "▶" : "Ⅱ";
    q("#pause").title = speech.paused ? "Resume" : "Pause";
    q("#pause").setAttribute("aria-label", q("#pause").title);
    q("#mute").textContent = speech.muted ? "♩" : "♪";
    q("#mute").setAttribute("aria-pressed", String(speech.muted));
    q("#mute").title = speech.muted ? "Unmute sound" : "Mute sound";
    q("#mute").setAttribute("aria-label", q("#mute").title);
    q("#play").textContent = active ? "↻ Start again" : "▶ Listen to the cast";
    q("#status").textContent = speech.failed
      ? speech.status
      : speech.paused
        ? "Paused"
        : active
          ? speech.muted
            ? "Preview playing · muted"
            : (speech.current?.speaker || "The cast") + " is speaking"
          : notice;
    if (started && !active && !speech.failed) {
      started = false;
      notice = "Preview finished. Listen again or try another channel.";
      q("#status").textContent = notice;
      q("#caption").textContent = "Preview finished.";
    }
  }
  function stop(message) {
    ++run;
    started = false;
    notice = message;
    speech.reset();
    q("#caption").textContent = "Press play to hear the cast.";
    q("#progress").value = 0;
    q("#time").textContent = "0:00";
    controls();
  }
  function setChannel(value) {
    stop("Ready for the preview.");
    channel = value;
    const cast = casts[value];
    document.body.dataset.theme = cast.rig;
    document.body.dataset.channel = value;
    q("#scene-label").textContent = cast.name.toUpperCase();
    q("#character").textContent = cast.name;
    q("#role").textContent = cast.role;
    q("#direction").textContent = cast.direction;
    document
      .querySelectorAll("button[data-channel]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.channel === value)),
      );
  }
  q("#play").onclick = async () => {
    const text = q("#trial-text").value.trim();
    if (!text) {
      q("#trial-text").focus();
      notice = "Enter a short sentence first.";
      q("#status").textContent = notice;
      return;
    }
    stop("Starting the preview…");
    const token = run;
    if (!speech.context) speech.init();
    await speech.unlock();
    if (token !== run) return;
    if (!speech.enabled || speech.needsGesture) {
      notice = speech.status;
      controls();
      return;
    }
    speech.offer(
      { id: "trial-host-" + run, agentId: "host", speaker: "Host", text },
      [],
      true,
    );
    speech.offer(
      {
        id: "trial-guest-" + run,
        agentId: "guest",
        speaker: "Guest",
        text: "Everything is ready. Let me show you!",
      },
      [],
      true,
    );
    started = true;
    controls();
    if (matchMedia("(max-width:800px)").matches)
      q(".preview").scrollIntoView({ block: "start", behavior: "instant" });
  };
  q("#pause").onclick = () => speech.pause();
  q("#stop").onclick = () => stop("Preview stopped.");
  q("#mute").onclick = () => speech.setMuted(!speech.muted);
  const channelControls = document.querySelector('[aria-label="Channel"]');
  channelControls.replaceChildren(
    ...Object.entries(casts).map(([id, pack]) => {
      const button = document.createElement("button");
      button.dataset.channel = id;
      button.textContent = pack.shortName;
      button.setAttribute("aria-pressed", String(id === channel));
      return button;
    }),
  );
  document
    .querySelectorAll("button[data-channel]")
    .forEach((b) => (b.onclick = () => setChannel(b.dataset.channel)));
  const timeText = (s) =>
    Math.floor(s / 60) + ":" + String(Math.floor(s % 60)).padStart(2, "0");
  function tick(time) {
    const current = speech.current;
    if (current?.playing) {
      q("#caption").textContent = current.caption || "…";
      q("#progress").value = current.progress || 0;
      q("#time").textContent =
        timeText(current.elapsed || 0) +
        " / " +
        timeText(current.duration || 0);
    }
    for (const [i, canvas] of [
      ...document.querySelectorAll("canvas"),
    ].entries()) {
      const id = i ? "guest" : "host",
        talking = speech.speaking(id);
      canvas.parentElement.classList.toggle("speaking", talking);
      window.drawTrialActor?.(
        canvas,
        channel,
        i,
        talking ? speech.mouth(id) : closed,
        time,
        talking,
      );
    }
    requestAnimationFrame(tick);
  }
  controls();
  requestAnimationFrame(tick);
  window.addEventListener("pagehide", () => {
    ++run;
    speech.disable();
    speech.context?.close();
  });
})();
