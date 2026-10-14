/* Local audio queue. No microphone, cloud request, or transcript persistence. */
(function (scope) {
  "use strict";
  function chunks(text, max = 480) {
    const out = [];
    let rest = text.trim();
    while (rest.length) {
      let end = Math.min(max, rest.length);
      if (end < rest.length) {
        const cut = rest.slice(0, end).search(/[.!?]\s+[^.!?]*$/);
        if (cut > max / 3) end = cut + 1;
        else {
          const space = rest.lastIndexOf(" ", end);
          if (space > 0) end = space;
        }
      }
      out.push(rest.slice(0, end).trim());
      rest = rest.slice(end).trim();
    }
    return out;
  }
  function captionSegments(text, max = 80) {
    const out = [];
    let start = 0;
    while (start < text.length) {
      while (start < text.length && /\s/.test(text[start])) start++;
      if (start >= text.length) break;
      let end = Math.min(start + max, text.length);
      if (end < text.length) {
        const segment = text.slice(start, end),
          sentence = segment.search(/[.!?](?:\s|$)/);
        if (sentence > Math.floor(max * 0.45)) end = start + sentence + 1;
        else {
          const space = segment.lastIndexOf(" ");
          if (space > 0) end = start + space;
        }
      }
      const value = text.slice(start, end).trim();
      if (value) out.push({ text: value, sourceStart: start, sourceEnd: end });
      start = end;
    }
    return out;
  }
  function captionChunks(text, max = 80) {
    return captionSegments(text, max).map((c) => c.text);
  }
  function captionWeight(caption) {
    const words = caption.text.match(/[\p{L}\p{N}]+(?:['’][\p{L}]+)*/gu) || [];
    return words.length === 1 && words[0].length >= caption.text.length * 0.85
      ? Math.max(0.2, caption.text.length / 5)
      : Math.max(1, words.length);
  }
  function speechCaptionCues(text, duration) {
    const captions = captionSegments(text);
    if (!captions.length) return [];
    const weights = captions.map(captionWeight),
      total = weights.reduce((a, b) => a + b, 0);
    let cursor = 0;
    return captions.map((caption, i) => {
      const start = cursor;
      cursor =
        i === captions.length - 1
          ? duration
          : cursor + (duration * weights[i]) / total;
      return { ...caption, start, end: cursor };
    });
  }
  const VISEMES = {
    X: [1, 0],
    A: [0.9, 0],
    B: [1.15, 0.18],
    C: [1, 0.58],
    D: [1.06, 1],
    E: [0.68, 0.52],
    F: [0.43, 0.42],
    G: [0.95, 0.2],
    H: [1, 0.68],
  };
  function visemeAt(cues, time) {
    if (!cues?.length || time < 0) return { code: "X", width: 1, open: 0 };
    let low = 0,
      high = cues.length - 1,
      index = -1;
    while (low <= high) {
      const mid = (low + high) >> 1;
      if (cues[mid].start <= time) {
        index = mid;
        low = mid + 1;
      } else high = mid - 1;
    }
    const cue = cues[index];
    if (!cue || time >= cue.end) return { code: "X", width: 1, open: 0 };
    const target = VISEMES[cue.value] || VISEMES.X,
      previous =
        cues[index - 1]?.end >= cue.start - 0.001
          ? VISEMES[cues[index - 1]?.value] || VISEMES.X
          : VISEMES.X;
    const blend = ["A", "X"].includes(cue.value)
      ? 1
      : Math.min(
          1,
          (time - cue.start) / Math.min(0.035, (cue.end - cue.start) / 2),
        );
    return {
      code: cue.value,
      width: previous[0] + (target[0] - previous[0]) * blend,
      open: previous[1] + (target[1] - previous[1]) * blend,
    };
  }

  // Small deterministic formant synthesizer. It makes original pseudo-speech locally;
  // no voice samples, remote endpoint, or Piper process is involved.
  const PHONES = [
    { v: "D", f: [730, 1090, 2440], s: "a" },
    { v: "C", f: [530, 1840, 2480], s: "e" },
    { v: "B", f: [390, 1990, 2550], s: "i" },
    { v: "E", f: [570, 840, 2410], s: "o" },
    { v: "F", f: [440, 1020, 2240], s: "u" },
    { v: "C", f: [620, 1500, 2600], s: "ae" },
    { v: "B", f: [510, 1250, 2200], s: "sh" },
    { v: "C", f: [660, 1700, 2380], s: "ya" },
  ];
  function hash(value) {
    let h = 2166136261;
    for (let i = 0; i < value.length; i++) {
      h ^= value.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }
  function random(seed) {
    let x = seed >>> 0;
    return () => {
      x = (x + 0x6d2b79f5) >>> 0;
      let t = x;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function readingPlan(text) {
    const tokens = [
      ...text.matchAll(/[\p{L}\p{N}]+(?:['’][\p{L}]+)*|[,;:.!?]/gu),
    ];
    const words = tokens.filter((t) => /[\p{L}\p{N}]/u.test(t[0]));
    const count = Math.max(1, words.length),
      phonemes = [],
      wordTimes = [];
    let cursor = 0,
      r = random(hash(text));
    for (let wi = 0; wi < words.length; wi++) {
      const word = words[wi],
        syllables = Math.max(1, Math.ceil(word[0].length / 5)),
        wordDuration = 0.31;
      wordTimes.push({
        index: wi,
        sourceStart: word.index,
        sourceEnd: word.index + word[0].length,
        start: cursor,
        end: cursor + wordDuration,
      });
      for (let si = 0; si < syllables; si++) {
        const start = cursor + (si * wordDuration) / syllables,
          end = cursor + ((si + 1) * wordDuration) / syllables;
        const phone = PHONES[Math.floor(r() * PHONES.length)];
        phonemes.push({ start, end, value: phone.v, phone });
      }
      cursor += wordDuration;
      const following = tokens[tokens.indexOf(word) + 1];
      if (following) {
        const mark = following[0];
        cursor += /[.!?]/.test(mark) ? 0.24 : /[,;]/.test(mark) ? 0.13 : 0.035;
      } else cursor += 0.08;
    }
    const duration = Math.max(0.48, cursor),
      captions = captionSegments(text);
    const wordTimeAt = (offset) => {
      if (!wordTimes.length) return 0;
      for (const word of wordTimes) {
        if (offset <= word.sourceStart) return word.start;
        if (offset < word.sourceEnd)
          return (
            word.start +
            ((word.end - word.start) * (offset - word.sourceStart)) /
              (word.sourceEnd - word.sourceStart)
          );
      }
      return duration;
    };
    const capStarts = captions.map((c) => {
      const start = wordTimeAt(c.sourceStart),
        end = wordTimeAt(c.sourceEnd);
      return { ...c, start, end: Math.max(start + 0.06, end) };
    });
    return { duration, captions: capStarts, phonemes };
  }
  function measuredVoicePlan(item) {
    const profile = voiceProfile(item.profile),
      key =
        scope.StudioThemes?.[profile.channel]?.voiceSlots[profile.slot] ||
        (profile.channel === "midnight"
          ? "midnight"
          : profile.channel === "paper"
            ? "paper"
            : profile.slot % 2
              ? "pocket-soft"
              : "pocket-pixel"),
      voice = scope.StudioVoiceProfiles?.[key];
    if (!voice) throw Error("Channel-klankprofiel ontbreekt");
    const r = random(
        hash(item.profile + "|" + item.messageId + "|" + item.text),
      ),
      phonemes = [];
    let cursor = 0,
      sourceOffset = 0;
    for (const char of item.text) {
      if (/[\p{L}\p{N}]/u.test(char)) {
        const template =
            voice.templates[Math.floor(r() * voice.templates.length)],
          start = cursor;
        phonemes.push({
          start,
          end: start + voice.duration,
          sourceStart: sourceOffset,
          sourceEnd: sourceOffset + char.length,
          value: template.mouth,
          template,
          pitch: template.pitch * (1 + (r() * 2 - 1) * voice.pitchVariation),
          phase: r() * Math.PI * 2,
          level: 0.92 + r() * 0.16,
        });
        cursor += voice.interval;
      } else if (/[.!?]/.test(char))
        cursor += voice.sentencePause ?? voice.interval * 2.5;
      else if (/[,;:]/.test(char))
        cursor += voice.commaPause ?? voice.interval * 1.3;
      else if (/\s/.test(char)) cursor += voice.space;
      sourceOffset += char.length;
    }
    const duration = Math.max(0.48, cursor + 0.05),
      at = (offset) =>
        phonemes.find((p) => p.sourceEnd > offset)?.start ?? duration;
    const captions = captionSegments(item.text).map((c) => ({
      ...c,
      start: at(c.sourceStart),
      end: at(c.sourceEnd),
    }));
    return { voice, duration, phonemes, captions, key };
  }
  function makeMeasuredVoice(context, item) {
    const plan = measuredVoicePlan(item),
      rate = 48000,
      length = Math.ceil(plan.duration * rate),
      buffer = context.createBuffer(1, length, rate),
      data = buffer.getChannelData(0),
      voice = plan.voice;
    // New oscillator notes for this message. Only aggregate frequency, envelope
    // and cadence parameters came from the reference; no recorded PCM is loaded.
    for (const p of plan.phonemes) {
      const first = Math.round(p.start * rate),
        last = Math.min(length, Math.round(p.end * rate));
      for (let n = first; n < last; n++) {
        const t = (n - first) / rate,
          attack = Math.min(1, t / voice.attack),
          release = Math.min(1, (last - n) / (rate * 0.004)),
          envelope =
            attack *
            Math.exp(-Math.max(0, t - voice.attack) / voice.decay) *
            release;
        let sample = 0;
        if (p.template.partials) {
          for (const [ratio, gain] of p.template.partials) {
            if (p.pitch * ratio < rate * 0.45)
              sample +=
                Math.sin((p.phase + 2 * Math.PI * p.pitch * t) * ratio) * gain;
          }
        } else {
          for (let h = 1; h <= p.template.harmonics.length; h++) {
            if (p.pitch * h > rate * 0.45) break;
            sample +=
              Math.sin((p.phase + 2 * Math.PI * p.pitch * t) * h) *
              p.template.harmonics[h - 1];
          }
        }
        data[n] += sample * envelope * p.level;
      }
    }
    let energy = 0;
    for (const sample of data) energy += sample * sample;
    const gain = voice.rms / Math.max(0.0001, Math.sqrt(energy / length));
    for (let n = 0; n < length; n++)
      data[n] = 0.85 * Math.tanh((data[n] * gain) / 0.85);
    return {
      buffer,
      cues: plan.phonemes.map(({ start, end, value }) => ({
        start,
        end,
        value,
      })),
      captions: plan.captions,
      duration: plan.duration,
    };
  }
  function voiceProfile(profile = "midnight-0") {
    const split = profile.lastIndexOf("-"),
      name = profile.slice(0, split),
      slotText = profile.slice(split + 1);
    const slot = Math.max(0, Math.min(10, Number(slotText) || 0));
    const channel =
      scope.StudioThemes?.[name] || ["paper", "pocket"].includes(name)
        ? name
        : "midnight";
    return { channel, slot, source: "synthesized" };
  }
  function makeGarble(context, item) {
    return makeMeasuredVoice(context, item);
  }
  function clockTime(context) {
    const stamp = context.getOutputTimestamp?.();
    return stamp?.contextTime > 0 ? stamp.contextTime : context.currentTime;
  }

  class StudioSpeech {
    constructor(change, cast = () => ({ channel: "midnight", slot: 0 })) {
      this.change = change;
      this.cast = cast;
      this.enabled = true;
      this.mode = "garble";
      this.paused = false;
      this.queue = [];
      this._current = null;
      this.generation = 0;
      this.known = new Map();
      try {
        this.muted =
          scope.localStorage?.getItem("studio-gibberish-muted") === "true";
      } catch {
        this.muted = false;
      }
      this.status = "Gibberish on";
    }
    get current() {
      this.refreshCaption();
      return this._current;
    }
    set current(value) {
      this._current = value;
    }
    get needsGesture() {
      return !!this.context && this.context.state !== "running" && !this.paused;
    }
    idleStatus() {
      return this.needsGesture
        ? "Click the studio to start sound"
        : this.muted
          ? "Gibberish muted"
          : "Gibberish on";
    }
    init() {
      try {
        this.context ||= new (scope.AudioContext || scope.webkitAudioContext)();
        this.output = this.context.createGain();
        this.output.gain.value = this.muted ? 0 : 1;
        this.output.connect(this.context.destination);
        this.status = this.idleStatus();
      } catch {
        this.enabled = false;
        this.status = "This browser cannot start audio";
      }
      this.change();
    }
    async unlock() {
      if (
        !this.enabled ||
        this.paused ||
        !this.context ||
        this.context.state === "running"
      )
        return;
      try {
        await this.context.resume();
        this.status = this.idleStatus();
        this.change();
        this.pump();
      } catch {
        this.status = "Click again to start audio";
        this.change();
      }
    }
    setMuted(muted) {
      this.muted = !!muted;
      try {
        scope.localStorage?.setItem(
          "studio-gibberish-muted",
          String(this.muted),
        );
      } catch {}
      if (this.output)
        this.output.gain.setTargetAtTime(
          this.muted ? 0 : 1,
          this.context.currentTime,
          0.015,
        );
      this.status = this.idleStatus();
      this.change();
    }
    profile(id) {
      const { channel, slot } = this.cast(id);
      return `${channel}-${slot}`;
    }
    cancelCurrent(requeue = false) {
      const item = this._current;
      this.generation++;
      this.abort?.abort();
      try {
        this.node?.stop();
        this.node?.disconnect();
        this.analyser?.disconnect();
      } catch {}
      this.node = null;
      this.analyser = null;
      this.busy = false;
      this.failed = false;
      if (item) {
        item.playing = false;
        if (requeue) {
          delete item.startedAt;
          delete item.cues;
          delete item.audio;
          this.queue.unshift(item);
        }
      }
      this._current = null;
    }
    reset() {
      this.cancelCurrent(false);
      this.queue = [];
      this.known.clear();
      this.paused = false;
      if (this.context?.state === "suspended" && this.enabled) this.unlock();
      this.status = this.idleStatus();
      this.change();
    }
    disable() {
      this.enabled = false;
      this.cancelCurrent(false);
      this.queue = [];
      this.paused = false;
      this.status = "Gibberish stopped";
      this.change();
    }
    async pause() {
      if (!this.enabled || !this.context) return;
      this.paused = !this.paused;
      await (this.paused ? this.context.suspend() : this.context.resume());
      this.change();
      if (!this.paused) this.pump();
    }
    retry() {
      if (!this.failed) return;
      const item = this._current;
      this.failed = false;
      this._current = null;
      if (item) this.queue.unshift(item);
      this.pump();
    }
    skip() {
      const rest = this.queue.slice();
      this.cancelCurrent(false);
      this._current = null;
      this.queue = rest;
      this.status = "Next segment";
      this.change();
      this.pump();
    }
    offer(m, agents = [], manual = false, previousText) {
      if (!this.enabled) return;
      const plainText = StudioText.plainText(m.text),
        text = plainText.replace(/https?:\/\/\S+/g, "").trim();
      if (!text) return;
      let spoken = text;
      if (!manual) {
        const old =
          this.known.get(m.id) ??
          (previousText === undefined
            ? ""
            : StudioText.plainText(previousText)
                .replace(/https?:\/\/\S+/g, "")
                .trim());
        if (old === text) return;
        if (old) {
          if (text.startsWith(old)) spoken = text.slice(old.length).trim();
          else return;
        }
        this.known.set(m.id, text);
      }
      if (this.needsGesture) this.queue = [];
      const pieces = chunks(spoken);
      if (this.queue.length + pieces.length > 200) {
        this.status =
          "Queue full. Play this message later from the transcript.";
        this.change();
        return;
      }
      const profile = this.profile(m.agentId, agents);
      for (const text of pieces)
        this.queue.push({
          text,
          captionText: text,
          messageId: m.id,
          agentId: m.agentId,
          profile,
          speaker: m.speaker,
          original: m.text,
        });
      this.change();
      this.pump();
    }
    has(id) {
      return (
        this._current?.agentId === id ||
        this.queue.some((m) => m.agentId === id)
      );
    }
    speaking(id) {
      return (
        !!this._current?.playing && this._current.agentId === id && !this.paused
      );
    }
    refreshCaption() {
      const item = this._current;
      if (!item) return;
      if (!item.playing || item.startedAt == null || !this.context) {
        item.caption = "";
        item.captionProgress = 0;
        item.captionIndex = 0;
        return;
      }
      const elapsed = Math.max(0, clockTime(this.context) - item.startedAt),
        captions = item.captionCues || [];
      let i = 0;
      while (i < captions.length - 1 && elapsed >= captions[i].end) i++;
      const cue = captions[i];
      item.caption = cue?.text || "";
      item.captionIndex = i;
      item.captionProgress = cue
        ? Math.max(
            0,
            Math.min(
              1,
              (elapsed - cue.start) / Math.max(0.001, cue.end - cue.start),
            ),
          )
        : 0;
      item.elapsed = elapsed;
      item.duration = item.duration || item.audio?.duration || 0;
      item.progress = item.duration
        ? Math.max(0, Math.min(1, elapsed / item.duration))
        : 0;
    }
    mouth(id) {
      if (!this.speaking(id)) return visemeAt([], 0);
      const item = this._current;
      return visemeAt(item.cues, clockTime(this.context) - item.startedAt);
    }
    async pump() {
      if (
        this.busy ||
        this.failed ||
        this.paused ||
        !this.enabled ||
        !this.queue.length ||
        !this.context ||
        this.context.state !== "running"
      )
        return;
      this.busy = true;
      const generation = ++this.generation,
        item = this.queue.shift();
      this._current = item;
      item.playing = false;
      item.caption = "";
      try {
        const audio = makeGarble(this.context, item);
        item.cues = audio.cues;
        item.captionCues = audio.captions;
        item.duration = audio.duration;
        if (generation !== this.generation || !this.enabled) return;
        const node = this.context.createBufferSource();
        this.node = node;
        node.buffer = audio.buffer;
        node.connect(this.output || this.context.destination);
        item.playing = true;
        this.status = this.muted
          ? "Gibberish muted"
          : item.speaker + " · gibberish";
        this.change();
        await new Promise((resolve, reject) => {
          node.onended = resolve;
          item.startedAt = clockTime(this.context);
          try {
            node.start();
          } catch (e) {
            reject(e);
          }
        });
      } catch (error) {
        if (generation !== this.generation) return;
        this.node?.disconnect();
        this.status = "Audio could not start · retry or skip";
        this.failed = true;
        this.busy = false;
        if (this._current) this._current.playing = false;
        this.change();
        return;
      }
      if (generation !== this.generation) return;
      this.node?.disconnect();
      this._current = null;
      this.node = null;
      this.busy = false;
      if (!this.queue.length) this.status = this.idleStatus();
      this.change();
      this.pump();
    }
  }
  scope.StudioVisemeAt = visemeAt;
  scope.StudioSpeech = StudioSpeech;
  scope.StudioSpeechChunks = chunks;
  scope.StudioCaptionChunks = captionChunks;
  scope.StudioSpeechCaptionCues = speechCaptionCues;
  scope.StudioGarble = {
    readingPlan,
    makeGarble,
    voiceProfile,
    measuredVoicePlan,
    phones: PHONES,
  };
})(typeof window === "undefined" ? globalThis : window);
