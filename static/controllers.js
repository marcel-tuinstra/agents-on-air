/* Small controllers with explicit dependencies, shared by the app and tests. */
(function (scope) {
  class StudioBoot {
    constructor(query, reduced, schedule = setTimeout) {
      this.query = query;
      this.target = "loading";
      this.done = reduced.matches;
      query("[data-skip-intro]").addEventListener("click", () => this.finish());
      schedule(() => this.finish(), reduced.matches ? 0 : 5000);
      reduced.addEventListener("change", () => {
        if (reduced.matches) this.finish();
      });
    }
    setTarget(target) {
      this.target = target;
      this.render();
    }
    finish() {
      this.done = true;
      this.render();
    }
    render() {
      const q = this.query,
        waiting = !this.done || this.target === "loading";
      q(".load").hidden = !waiting;
      q("[data-ready]").hidden = waiting || this.target !== "ready";
      q("[data-no-selection]").hidden = waiting || this.target !== "empty";
      if (this.done) {
        q(".load").classList.remove("building");
        q("[data-skip-intro]").hidden = true;
        q(".load h1").textContent = "Connecting to your studio";
        q("[data-load-label]").textContent = "Waiting for local chat data…";
      }
    }
  }
  class LatestRequest {
    constructor() {
      this.generation = 0;
    }
    async run(load, apply) {
      const generation = ++this.generation;
      const value = await load();
      if (generation === this.generation) apply(value);
    }
  }
  const api = { StudioBoot, LatestRequest };
  Object.assign(scope, api);
  if (typeof module !== "undefined") module.exports = api;
})(typeof window === "undefined" ? globalThis : window);
