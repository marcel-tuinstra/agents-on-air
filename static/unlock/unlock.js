(function (scope) {
  "use strict";

  // Moves focus between the code boxes, spreads pasted codes and submits once all six are filled.
  function attachCodeBoxes(form, boxes) {
    let sent = false;
    const submitWhenFull = () => {
      if (sent || !boxes.every((box) => /^[0-9]$/.test(box.value))) return;
      sent = true;
      form.submit();
    };
    const fill = (index, text) => {
      let at = index;
      for (const digit of String(text).replace(/[^0-9]/g, "")) {
        if (at >= boxes.length) break;
        boxes[at++].value = digit;
      }
      boxes[Math.min(at, boxes.length - 1)].focus();
      submitWhenFull();
    };
    boxes.forEach((box, index) => {
      box.addEventListener("focus", () => box.select());
      box.addEventListener("input", () => {
        const typed = box.value;
        box.value = "";
        fill(index, typed);
      });
      box.addEventListener("paste", (event) => {
        event.preventDefault();
        fill(index, event.clipboardData.getData("text"));
      });
      box.addEventListener("keydown", (event) => {
        if (event.key === "Backspace" && !box.value && index > 0) {
          event.preventDefault();
          boxes[index - 1].value = "";
          boxes[index - 1].focus();
        } else if (event.key === "ArrowLeft" && index > 0) {
          event.preventDefault();
          boxes[index - 1].focus();
        } else if (event.key === "ArrowRight" && index < boxes.length - 1) {
          event.preventDefault();
          boxes[index + 1].focus();
        }
      });
    });
  }

  const api = { attachCodeBoxes };
  Object.assign(scope, api);
  if (typeof module !== "undefined") module.exports = api;
  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", () => {
      const form = document.querySelector("[data-unlock]");
      if (form) attachCodeBoxes(form, [...form.querySelectorAll(".digit")]);
    });
  }
})(typeof window === "undefined" ? globalThis : window);
