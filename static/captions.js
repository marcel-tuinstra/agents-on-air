/* One caption timeline for live audio, silent reading, and history. */
(function (scope) {
  "use strict";

  function fit(text, width, measure, maxLines = 2) {
    text = String(text || "");
    if (!text) return [];
    if (!(width > 0)) return [text];
    const characters = Array.from(text);
    const segments = [];
    let start = 0;
    while (start < characters.length) {
      let cursor = start;
      for (let line = 0; line < maxLines && cursor < characters.length; line++) {
        let end = cursor;
        while (end < characters.length && measure(characters.slice(cursor, end + 1).join("")) <= width)
          end++;
        if (end === cursor) end++;
        if (end < characters.length) {
          let space = end;
          while (space > cursor && !/\s/u.test(characters[space - 1])) space--;
          if (space > cursor) end = space;
        }
        cursor = end;
      }
      segments.push(characters.slice(start, cursor).join(""));
      start = cursor;
    }
    return segments;
  }

  class StudioCaptionModel {
    constructor(segment = (text) => [text]) {
      this.segment = segment;
      this.reset();
    }
    reset() {
      this.records = [];
      this.items = [];
      this.index = -1;
      this.paused = false;
      this.history = false;
      this.due = 0;
      this.expired = false;
      this.trimmed = 0;
    }
    get current() { return this.items[this.index] || null; }
    get visible() { return !!this.current && (!this.expired || this.paused || this.history); }
    hold(text) { return Math.min(7000, Math.max(2500, String(text).trim().split(/\s+/u).length * 260)); }
    append(text, meta, now, { initial = false } = {}) {
      text = String(text || "");
      if (!text.trim()) return false;
      const oldCurrent = this.current,
        oldDue = this.due,
        wasExpired = this.expired;
      const id = Symbol("caption");
      const record = { id, text, meta };
      this.records.push(record);
      this.items.push(...this.segmentRecord(record));
      if (this.records.length > 200) {
        // Keep the passage being read, even when a burst fills the waiting queue.
        const pinned = !initial && (!wasExpired || this.paused || this.history) ? oldCurrent?.id : null;
        const remove = this.records.findIndex((entry) => entry.id !== pinned);
        const [removed] = this.records.splice(remove, 1);
        this.items = this.items.filter((item) => item.id !== removed.id);
        this.trimmed++;
        this.index = oldCurrent ? this.items.findIndex((item) =>
          item.id === oldCurrent.id && item.offset === oldCurrent.offset) : -1;
      }
      if (initial) this.index = this.items.length - 1;
      else if (wasExpired && !this.paused && !this.history) this.index = this.items.findIndex((item) => item.id === id);
      else if (!this.paused && !this.history && this.index < 0) this.index = 0;
      this.expired = false;
      this.due = oldCurrent && !wasExpired && !initial && this.current?.id === oldCurrent.id && this.current?.offset === oldCurrent.offset
        ? oldDue
        : now + (this.index === this.items.length - 1 ? 4000 : this.hold(this.current?.text || text));
      return id;
    }
    segmentRecord(record) {
      let offset = 0;
      return this.segment(record.text).map((text) => {
        const item = { ...record.meta, text, id: record.id, offset };
        offset += text.length;
        return item;
      });
    }
    reflow(now, { preserve = true } = {}) {
      const selected = preserve ? this.current : null;
      this.items = this.records.flatMap((record) => this.segmentRecord(record));
      if (selected) {
        const found = this.items.findIndex((item) => item.id === selected.id && item.offset <= selected.offset && item.offset + item.text.length > selected.offset);
        this.index = found >= 0 ? found : Math.min(this.index, this.items.length - 1);
      }
      if (this.index >= this.items.length) this.index = this.items.length - 1;
      if (!this.paused && !this.history && this.current) this.due = now + this.hold(this.current.text);
    }
    step(direction) {
      const next = this.index + direction;
      if (next < 0 || next >= this.items.length) return false;
      this.index = next;
      this.paused = true;
      this.history = true;
      this.expired = false;
      return true;
    }
    setPaused(value, now) {
      this.paused = !!value;
      if (!this.paused) {
        this.history = false;
        this.expired = false;
        this.due = now + this.hold(this.current?.text || "");
      }
    }
    alignAudio(audio) {
      if (this.paused || this.history || !audio?.playing || !audio.captionRecordId) return;
      const cue = audio.captionCues?.[audio.captionIndex],
        start = (audio.sourceStart || 0) + (cue?.sourceStart || 0),
        end = (audio.sourceStart || 0) + (cue?.sourceEnd || start),
        offset = start + Math.floor(Math.max(0, Math.min(1, audio.captionProgress || 0)) * Math.max(0, end - start));
      const at = this.items.findIndex((item) => item.id === audio.captionRecordId &&
        item.offset <= offset && offset < item.offset + item.text.length);
      if (at >= 0) {
        this.index = at;
        this.expired = false;
      }
    }
    tick(now, audioActive = false) {
      if (!this.visible || this.paused || this.history || audioActive || now < this.due) return false;
      if (this.index < this.items.length - 1) {
        this.index++;
        this.due = now + (this.index === this.items.length - 1 ? 4000 : this.hold(this.current.text));
      } else this.expired = true;
      return true;
    }
    resolve(audio) {
      return this.current;
    }
  }

  scope.StudioCaptionFit = fit;
  scope.StudioCaptionModel = StudioCaptionModel;
})(typeof window === "undefined" ? globalThis : window);
