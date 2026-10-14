/* Cast geometry shared by the studio and voice preview. */
(function (scope) {
  function create() {
    let theme = "midnight",
      channelId = "midnight",
      currentViseme = { code: "X", width: 1, open: 0 };
    const images = {},
      frameCache = new Map();
    function rowOf(id) {
      return id > 5 ? id - 5 : id;
    }
    function cleanCell(ctx) {
      const pixels = ctx.getImageData(0, 0, 256, 256),
        d = pixels.data,
        visited = new Uint8Array(65536),
        parts = [];
      for (let p = 0; p < 65536; p++) {
        if (visited[p] || d[p * 4 + 3] < 100) continue;
        const queue = [p];
        visited[p] = 1;
        let border = false;
        for (let j = 0; j < queue.length; j++) {
          const n = queue[j],
            x = n % 256,
            y = n >> 8;
          if (x < 2 || x > 253 || y < 2 || y > 253) border = true;
          for (const m of [
            x > 0 ? n - 1 : -1,
            x < 255 ? n + 1 : -1,
            y > 0 ? n - 256 : -1,
            y < 255 ? n + 256 : -1,
          ])
            if (m >= 0 && !visited[m] && d[m * 4 + 3] >= 100) {
              visited[m] = 1;
              queue.push(m);
            }
        }
        parts.push({ queue, border });
      }
      const largest = Math.max(...parts.map((p) => p.queue.length));
      for (const part of parts)
        if (
          (part.border && part.queue.length < largest * 0.1) ||
          part.queue.length < 8
        )
          for (const i of part.queue) d[i * 4 + 3] = 0;
      for (let p = 0; p < 65536; p++) if (d[p * 4 + 3] < 100) d[p * 4 + 3] = 0;
      ctx.putImageData(pixels, 0, 0);
    }
    function frameForTheme(id) {
      const row = rowOf(id),
        key = channelId + "-" + row;
      if (frameCache.has(key)) return frameCache.get(key);
      const c = document.createElement("canvas");
      c.width = c.height = 256;
      const cx = c.getContext("2d"),
        g = rigGeometry[theme];
      cx.imageSmoothingEnabled = theme !== "pocket";
      const rows =
        theme === "paper" ? [0, 301, 577, 881, 1172, 1459, 1774] : rigRows;
      cx.drawImage(
        images[channelId],
        g.col[0],
        rows[row],
        g.col[1] - g.col[0],
        rows[row + 1] - rows[row],
        0,
        0,
        256,
        256,
      );
      cleanCell(cx);
      if ((theme === "paper" || theme === "pocket") && row === 2)
        cx.clearRect(0, 242, 256, 14);
      frameCache.set(key, c);
      return c;
    }
    const rigGeometry = {
      midnight: {
        col: [0, 326],
        eye: [
          [
            [170, 108],
            [216, 106],
          ],
          [
            [150, 385],
            [199, 386],
          ],
          [
            [135, 686],
            [183, 686],
          ],
          [
            [150, 959],
            [196, 959],
          ],
          [
            [140, 1251],
            [188, 1251],
          ],
          [
            [141, 1541],
            [190, 1541],
          ],
        ],
        mouth: [
          [191, 143],
          [174, 430],
          [159, 729],
          [174, 1003],
          [165, 1298],
          [166, 1590],
        ],
      },
      paper: {
        col: [326, 591],
        eye: [
          [
            [431, 126],
            [491, 126],
          ],
          [
            [411, 405],
            [502, 405],
          ],
          [
            [405, 691],
            [487, 691],
          ],
          [
            [425, 996],
            [480, 996],
          ],
          [
            [423, 1278],
            [493, 1278],
          ],
          [
            [400, 1553],
            [501, 1553],
          ],
        ],
        mouth: [
          [460, 177],
          [458, 443],
          [446, 725],
          [451, 1050],
          [461, 1332],
          [452, 1605],
        ],
      },
      pocket: {
        col: [591, 887],
        eye: [
          [
            [700, 155],
            [773, 155],
          ],
          [
            [695, 426],
            [771, 426],
          ],
          [
            [695, 737],
            [771, 737],
          ],
          [
            [699, 1010],
            [770, 1010],
          ],
          [
            [697, 1324],
            [774, 1324],
          ],
          [
            [695, 1600],
            [770, 1600],
          ],
        ],
        mouth: [
          [735, 203],
          [733, 471],
          [733, 778],
          [736, 1050],
          [736, 1360],
          [733, 1640],
        ],
      },
    };
    const rigRows = [0, 301, 596, 884, 1172, 1459, 1774];
    function faceForTheme(ctx, id, opening, blink, t) {
      const row = rowOf(id),
        g = rigGeometry[theme],
        rows =
          theme === "paper" ? [0, 301, 577, 881, 1172, 1459, 1774] : rigRows,
        cw = g.col[1] - g.col[0],
        ch = rows[row + 1] - rows[row],
        px = (x) => ((x - g.col[0]) / cw) * 256,
        py = (y) => ((y - rows[row]) / ch) * 256;
      const human = theme === "midnight",
        pixel = theme === "pocket",
        ink = pixel
          ? row === 3
            ? "#f7faff"
            : "#08192e"
          : human
            ? "#3c211c"
            : "#242321";
      ctx.fillStyle = ink;
      ctx.strokeStyle = ink;
      ctx.lineWidth = human ? 1.25 : 2.3;
      ctx.lineCap = "round";
      for (const [ex, ey] of g.eye[row]) {
        const x = px(ex),
          y = py(ey),
          w = pixel ? 9 : human ? 8 : row === 1 ? 9 : 8,
          h = pixel ? 11 : human ? 3.8 : 11,
          open = Math.max(0.1, 1 - blink);
        if (pixel) {
          ctx.fillRect(
            Math.round(x - w),
            Math.round(y - h * open),
            w * 2,
            Math.max(2, Math.round(h * 2 * open)),
          );
          continue;
        }
        if (human) {
          ctx.save();
          ctx.beginPath();
          ctx.ellipse(x, y, w, h * open, 0, 0, Math.PI * 2);
          ctx.clip();
          ctx.fillStyle = "#f4e9dc";
          ctx.fill();
          ctx.fillStyle = "#543d2f";
          ctx.beginPath();
          ctx.ellipse(x + 0.4, y, 3.3, 4.4, 0, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = ink;
          ctx.beginPath();
          ctx.ellipse(x + 0.4, y, 1.5, 3, 0, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();
          ctx.beginPath();
          ctx.moveTo(x - w, y);
          ctx.quadraticCurveTo(x, y - h * open * 1.8, x + w, y);
          ctx.stroke();
          ctx.lineWidth = 1.8;
          ctx.beginPath();
          ctx.moveTo(x - w, y - 8);
          ctx.quadraticCurveTo(x, y - 10, x + w, y - 8);
          ctx.stroke();
          ctx.lineWidth = 1.25;
        } else {
          ctx.fillStyle = ink;
          ctx.beginPath();
          ctx.ellipse(x, y, w, h * open, 0, 0, Math.PI * 2);
          ctx.fill();
          if (open > 0.5) {
            ctx.fillStyle = "#fff8e6";
            ctx.beginPath();
            ctx.ellipse(
              x - 2,
              y - 4 * open,
              2.2,
              2.7 * open,
              0,
              0,
              Math.PI * 2,
            );
            ctx.fill();
          }
        }
      }
      const [ox, oy] = g.mouth[row],
        x = px(ox),
        y = py(oy),
        code = currentViseme.code,
        w = (human ? 9 : pixel ? 8 : 10) * currentViseme.width,
        h = (human ? 7 : pixel ? 10 : 9) * opening;
      ctx.fillStyle = ink;
      ctx.strokeStyle = ink;
      ctx.lineWidth = human ? 1.5 : 2.1;
      if (code === "X" || code === "A") {
        if (pixel) {
          ctx.fillRect(
            Math.round(x - w),
            Math.round(y),
            Math.round(w * 2),
            code === "A" ? 3 : 2,
          );
          return;
        }
        ctx.beginPath();
        ctx.moveTo(x - w, y);
        ctx.quadraticCurveTo(
          x,
          y + (code === "A" ? 0 : human ? 2 : 4),
          x + w,
          y,
        );
        ctx.stroke();
        if (code === "A") {
          ctx.globalAlpha = 0.45;
          ctx.beginPath();
          ctx.moveTo(x - w * 0.55, y + 2);
          ctx.lineTo(x + w * 0.55, y + 2);
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
        return;
      }
      const top = y - Math.max(1.5, h * 0.7),
        height = Math.max(3, h * 1.9);
      ctx.save();
      ctx.beginPath();
      if (pixel) {
        ctx.rect(
          Math.round(x - w),
          Math.round(top),
          Math.round(w * 2),
          Math.round(height),
        );
      } else if (code === "E" || code === "F") {
        ctx.ellipse(x, y + h * 0.25, w, Math.max(2, h), 0, 0, Math.PI * 2);
      } else {
        ctx.moveTo(x - w, top);
        ctx.quadraticCurveTo(x, top - h * 0.25, x + w, top);
        ctx.bezierCurveTo(
          x + w,
          y + height * 0.65,
          x - w,
          y + height * 0.65,
          x - w,
          top,
        );
        ctx.closePath();
      }
      ctx.clip();
      ctx.fillStyle = human ? "#4a2022" : pixel ? ink : "#28201e";
      ctx.fill();
      const teeth = human ? "#f3e5d5" : pixel ? "#ecf4f2" : "#fff1dc",
        tongue = human ? "#bb706f" : pixel ? "#bd8ac9" : "#d98e86";
      if (["B", "G", "H", "C", "D"].includes(code)) {
        ctx.fillStyle = teeth;
        ctx.fillRect(
          x - w,
          top,
          w * 2,
          code === "G"
            ? height * 0.7
            : code === "B"
              ? height * 0.6
              : Math.max(1, height * 0.17),
        );
      }
      if (["C", "D", "H"].includes(code)) {
        ctx.fillStyle = tongue;
        const ty = code === "H" ? y - h * 0.12 : y + h * 0.68;
        if (pixel)
          ctx.fillRect(
            Math.round(x - w * 0.5),
            Math.round(ty),
            Math.round(w),
            Math.max(2, Math.round(h * 0.5)),
          );
        else {
          ctx.beginPath();
          ctx.ellipse(
            x,
            ty,
            w * 0.55,
            Math.max(1.3, h * 0.32),
            0,
            0,
            Math.PI * 2,
          );
          ctx.fill();
        }
      }
      ctx.restore();
    }

    return {
      setImage(image, channel) {
        if (channel) images[channel] = image;
        else images.midnight = images.paper = images.pocket = image;
      },
      frame(channel, id) {
        channelId = channel;
        theme = window.StudioThemes?.[channel]?.rig || channel;
        return frameForTheme(id);
      },
      face(ctx, channel, id, mouth, blink, time) {
        channelId = channel;
        theme = window.StudioThemes?.[channel]?.rig || channel;
        currentViseme = mouth;
        faceForTheme(ctx, id, mouth.open, blink, time);
      },
    };
  }
  scope.StudioRig = { create };
})(window);
