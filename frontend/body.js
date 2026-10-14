/* Articulated cut-out rig: original cast artwork, independently pivoted body,
   upper arms and hands. Coordinates use the established 256px cast cells. */
(function (scope) {
  "use strict";
  const layouts = {
    midnight: {
      neck: 151,
      left: [
        [0, 157],
        [68, 150],
        [96, 210],
        [133, 226],
        [124, 256],
        [0, 256],
      ],
      right: [
        [207, 150],
        [256, 155],
        [256, 256],
        [135, 256],
        [132, 225],
        [175, 210],
      ],
      lp: [64, 169],
      rp: [200, 169],
      hands: [
        [74, 221, 68, 35],
        [138, 224, 59, 32],
      ],
    },
    paper: {
      neck: 171,
      left: [
        [0, 178],
        [49, 173],
        [88, 219],
        [129, 230],
        [126, 256],
        [0, 256],
      ],
      right: [
        [209, 173],
        [256, 178],
        [256, 256],
        [128, 256],
        [129, 229],
        [172, 216],
      ],
      lp: [49, 185],
      rp: [208, 185],
      hands: [
        [68, 225, 63, 31],
        [131, 225, 59, 31],
      ],
    },
    pocket: {
      neck: 256,
      left: [
        [0, 166],
        [62, 166],
        [81, 212],
        [81, 256],
        [0, 256],
      ],
      right: [
        [194, 166],
        [256, 166],
        [256, 256],
        [177, 256],
        [177, 212],
      ],
      lp: [53, 195],
      rp: [206, 195],
      hands: [
        [28, 211, 51, 43],
        [179, 211, 51, 43],
      ],
    },
  };
  function pose({
    id = 0,
    time = 0,
    talking = false,
    waiting = false,
    pointing = false,
    reduced = false,
  }) {
    if (reduced)
      return {
        breath: 0,
        lean: 0,
        head: 0,
        left: 0,
        right: 0,
        lh: 0,
        rh: 0,
        tap: 0,
        sleep: 0,
      };
    const t = time / 1000,
      phase = id * 1.618,
      breath = Math.sin(t * 1.34 + phase) * 0.65;
    const gesture =
      (Math.sin(t * 1.9 + phase) + Math.sin(t * 0.73 + phase)) * 0.5;
    const cycle = (t + id * 0.43) % 20,
      smooth = (x) => x * x * (3 - 2 * x);
    const sleep = waiting
      ? cycle < 3
        ? 0
        : cycle < 7
          ? smooth((cycle - 3) / 4)
          : cycle < 16
            ? 1
            : cycle < 17
              ? 1 - smooth(cycle - 16)
              : 0
      : 0;
    const tap =
      waiting && cycle < 2 ? Math.pow(Math.max(0, Math.sin(cycle * 12)), 3) : 0;
    return {
      breath,
      lean: waiting
        ? -0.025 - sleep * 0.035 + Math.sin(t * 0.3 + phase) * 0.004
        : Math.sin(t * 0.43 + phase) * 0.006,
      head: waiting ? sleep * 0.12 : 0,
      sleep,
      left: waiting
        ? -0.012
        : talking
          ? gesture * 0.045
          : Math.sin(t * 0.61 + phase) * 0.006,
      right: waiting
        ? -0.018
        : pointing
          ? -0.12 + Math.sin(t * 1.2) * 0.025
          : talking
            ? -gesture * 0.04
            : Math.sin(t * 0.55 + phase) * 0.006,
      lh: talking ? Math.sin(t * 2.7 + phase) * 0.025 : 0,
      rh: waiting
        ? tap * 0.07
        : talking
          ? Math.sin(t * 2.1 + phase) * 0.028
          : 0,
      tap,
    };
  }
  function polygon(ctx, points) {
    ctx.moveTo(...points[0]);
    for (const p of points.slice(1)) ctx.lineTo(...p);
    ctx.closePath();
  }
  function region(
    ctx,
    frame,
    points,
    pivot,
    rotation,
    hand,
    handRotation,
    lift = 0,
  ) {
    ctx.save();
    ctx.translate(pivot[0], pivot[1]);
    ctx.rotate(rotation);
    ctx.translate(-pivot[0], -pivot[1]);
    // Arm and hand have independent transforms; shared edge is overlapped by 1px.
    ctx.save();
    ctx.beginPath();
    polygon(ctx, points);
    ctx.rect(hand[0], hand[1], hand[2], hand[3]);
    ctx.clip("evenodd");
    ctx.drawImage(frame, 0, 0);
    ctx.restore();
    ctx.save();
    const px = hand[0] + hand[2] / 2,
      py = hand[1] + hand[3] / 2;
    ctx.translate(px, py - lift);
    ctx.rotate(handRotation);
    ctx.translate(-px, -py);
    ctx.beginPath();
    ctx.rect(hand[0] - 1, hand[1] - 1, hand[2] + 2, hand[3] + 2);
    ctx.clip();
    ctx.drawImage(frame, 0, 0);
    ctx.restore();
    ctx.restore();
  }
  function draw(ctx, options) {
    const { frame, theme = "midnight", id = 0, drawFace } = options;
    if (!frame) return;
    const g = layouts[theme] || layouts.midnight,
      p = pose(options);
    ctx.save();
    ctx.translate(128, 252);
    ctx.rotate(p.lean);
    ctx.translate(-128, -252 + p.breath);
    // Body occupies the original silhouette. No newly drawn body or desk can cover a face.
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, 256, 256);
    polygon(ctx, g.left);
    polygon(ctx, g.right);
    ctx.clip("evenodd");
    if (options.waiting && theme !== "pocket") {
      ctx.beginPath();
      ctx.rect(0, g.neck, 256, 256 - g.neck);
      ctx.clip();
    }
    ctx.drawImage(frame, 0, 0);
    ctx.restore();
    region(ctx, frame, g.left, g.lp, p.left, g.hands[0], p.lh);
    region(ctx, frame, g.right, g.rp, p.right, g.hands[1], p.rh, p.tap * 6);
    if (options.waiting && theme !== "pocket") {
      // Move the cleaned head and its drawn eyes/mouth together to avoid face seams.
      ctx.save();
      ctx.translate(128, g.neck + p.sleep * 3);
      ctx.rotate(p.head);
      ctx.translate(-128, -g.neck);
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, 256, g.neck + 2);
      ctx.clip();
      ctx.drawImage(frame, 0, 0);
      ctx.restore();
      if (typeof drawFace === "function") drawFace(ctx);
      ctx.restore();
    } else if (typeof drawFace === "function") drawFace(ctx);
    ctx.restore();
  }
  scope.StudioBody = { draw, pose };
  if (typeof module !== "undefined") module.exports = scope.StudioBody;
})(typeof window === "undefined" ? globalThis : window);
