(function () {
  const rig = StudioRig.create();
  let ready = false;
  Promise.all(
    Object.entries(window.StudioThemes).map(
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
    })
    .catch(() => {
      document.querySelector("#status").textContent =
        "A channel image could not be loaded.";
    });
  window.drawTrialActor = (canvas, channel, id, mouth, time, talking) => {
    if (!ready) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.scale(canvas.width / 256, canvas.height / 256);
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    StudioBody.draw(ctx, {
      frame: rig.frame(channel, id),
      id,
      theme: window.StudioThemes[channel].rig,
      time,
      talking,
      reduced,
      drawFace: () =>
        rig.face(
          ctx,
          channel,
          id,
          mouth,
          reduced ? 0 : time % 4700 < 130 ? 0.9 : 0,
          time,
        ),
    });
    ctx.restore();
    canvas.dataset.viseme = mouth.code;
  };
})();
