/* One selected chat stream, with cancellation across reconnects and chat switches. */
(function (scope) {
  class StudioStream {
    constructor({
      create = (url) => new EventSource(url),
      schedule = (callback, delay) => setTimeout(callback, delay),
      cancel = (timer) => clearTimeout(timer),
    } = {}) {
      this.create = create;
      this.schedule = schedule;
      this.cancel = cancel;
      this.generation = 0;
      this.source = null;
      this.timer = null;
    }
    connect(chat, handlers) {
      this.stop();
      const generation = this.generation;
      const open = () => {
        if (generation !== this.generation) return;
        handlers.connecting?.();
        const source = (this.source = this.create(
          "/api/events" + (chat ? "?chat=" + encodeURIComponent(chat) : ""),
        ));
        const current = () =>
          generation === this.generation && this.source === source;
        for (const name of [
          "catalog",
          "snapshot",
          "heartbeat",
          "source-error",
        ]) {
          source.addEventListener(name, (event) => {
            if (!current()) return;
            let data;
            try {
              data = JSON.parse(event.data);
            } catch {
              disconnect();
              return;
            }
            handlers[name]?.(data);
          });
        }
        const disconnect = () => {
          if (!current()) return;
          this.source = null;
          source.close();
          handlers.disconnect?.();
          this.timer = this.schedule(open, 2000);
        };
        source.onerror = disconnect;
      };
      open();
    }
    stop() {
      ++this.generation;
      this.cancel(this.timer);
      this.timer = null;
      this.source?.close();
      this.source = null;
    }
  }
  scope.StudioStream = StudioStream;
  if (typeof module !== "undefined") module.exports = { StudioStream };
})(typeof window === "undefined" ? globalThis : window);
