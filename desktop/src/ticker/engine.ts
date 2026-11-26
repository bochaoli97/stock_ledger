/** A deterministic port of ticker.py. No React, browser timers, or money floats. */
export const GEARS = {
  heavy: 650,
  integer: 450,
  decimal: 320,
  cents: 260,
  expand: 350,
  collapse: 260,
  scrubWidth: 180,
  color: 600,
} as const;
export const OUT_CUBIC_CSS =
  "cubic-bezier(0.3333333333333333,1,0.6666666666666666,1)";
export const outCubic = (t: number) => 1 - (1 - t) ** 3;
export const outQuad = (t: number) => 1 - (1 - t) ** 2;
export const modulo = (n: number) => ((n % 10) + 10) % 10;
type RGB = [number, number, number];
type Tween = { from: number; to: number; start: number; duration: number };
const progress = (t: Tween, now: number) =>
  Math.min(1, Math.max(0, (now - t.start) / t.duration));
const sample = (t: Tween, now: number) =>
  t.from + (t.to - t.from) * outCubic(progress(t, now));
const rgb = (hex: string): RGB => {
  if (!/^#[\da-f]{6}$/i.test(hex))
    throw new Error("Ticker colors must be six-digit hex values");
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as RGB;
};
export const colorCss = (c: RGB) => `rgb(${c.map(Math.round).join(",")})`;

export function slotRank(key: string): number {
  if (key === "placeholder") return Infinity;
  if (key === "sign") return 1001;
  if (key === "prefix") return 1000;
  if (key === "dot") return 0;
  const [kind, n] = key.split("_");
  if (kind === "dec") return -Number(n);
  if (kind === "int") return Number(n) + 0.1;
  if (kind === "comma") return 3 * Number(n) - 0.5;
  throw new Error(`Unknown ticker slot: ${key}`);
}

export function textToSlots(text: string): Map<string, string> | null {
  const match = /^([+-]?)(\$?)([0-9]+(?:,[0-9]{3})*)(?:\.([0-9]+))?$/.exec(
    text,
  );
  if (!match || match[0] !== text) return null;
  const [, sign, prefix, integer, decimal] = match;
  const slots = new Map<string, string>();
  if (sign) slots.set("sign", sign);
  if (prefix) slots.set("prefix", prefix);
  if (decimal !== undefined) {
    slots.set("dot", ".");
    [...decimal].forEach((char, i) => slots.set(`dec_${i + 1}`, char));
  }
  let digit = 0,
    comma = 0;
  for (const char of [...integer].reverse()) {
    slots.set(char === "," ? `comma_${++comma}` : `int_${digit++}`, char);
  }
  return slots;
}

/** Compare formatted decimals exactly, including values beyond Number.MAX_SAFE_INTEGER. */
export function compareMoney(a: string, b: string): number {
  const parts = (text: string) => {
    const [integer, fraction = ""] = text
      .replace(/[+$,]/g, "")
      .replace(/^-/, "")
      .split(".");
    const whole = integer.replace(/^0+/, "") || "0";
    const decimals = fraction.replace(/0+$/, "");
    const negative = text.startsWith("-") && (whole !== "0" || decimals !== "");
    return { whole, decimals, negative };
  };
  const x = parts(a),
    y = parts(b);
  if (x.negative !== y.negative) return x.negative ? -1 : 1;
  let result = Math.sign(x.whole.length - y.whole.length);
  if (!result) result = x.whole < y.whole ? -1 : x.whole > y.whole ? 1 : 0;
  if (!result) {
    const len = Math.max(x.decimals.length, y.decimals.length);
    const xd = x.decimals.padEnd(len, "0"),
      yd = y.decimals.padEnd(len, "0");
    result = xd < yd ? -1 : xd > yd ? 1 : 0;
  }
  return x.negative ? -result : result;
}

export class CharacterTrack {
  readonly digit: boolean;
  readonly rank: number;
  char: string;
  target: string;
  offset: number;
  targetOffset: number;
  width = 1;
  opacity = 1;
  removing = false;
  scroll: Tween | null = null;
  appear: Tween | null = null;
  color: RGB;
  colorTween: { from: RGB; start: number } | null = null;
  scrollRevision = 0;
  scrollDuration = 0;
  appearDuration = 0;

  constructor(
    readonly key: string,
    char: string,
    readonly neutral: RGB,
  ) {
    this.digit = key.startsWith("int_") || key.startsWith("dec_");
    this.rank = slotRank(key);
    this.char = this.target = char;
    this.validate(char);
    this.offset = this.targetOffset = this.digit ? Number(char) : 0;
    this.color = [...neutral];
  }
  private validate(char: string) {
    if (this.digit && !/^[0-9]$/.test(char))
      throw new Error(`Numeric slot ${this.key} cannot contain ${char}`);
    if (!this.digit && this.key !== "placeholder" && /[0-9]/.test(char))
      throw new Error("Static slot contains digits");
  }
  clearColor() {
    this.colorTween = null;
    this.color = [...this.neutral];
  }
  flash(color: RGB, now: number) {
    this.color = [...color];
    this.colorTween = { from: [...color], start: now };
  }
  resize(to: number, duration: number, now: number) {
    this.removing = to === 0;
    if (this.removing) this.clearColor();
    this.appear =
      this.width === to ? null : { from: this.width, to, start: now, duration };
    this.appearDuration = duration;
  }
  setTarget(
    char: string,
    duration: number,
    flash: RGB | null,
    now: number,
    retarget = false,
  ) {
    this.validate(char);
    if (char === this.target && !retarget) return;
    this.target = char;
    if (!this.digit) {
      this.char = char;
      return;
    }
    let from = modulo(this.offset),
      to = Number(char);
    if (Math.abs(to - from) > 5) {
      if (from < to) from += 10;
      else to += 10;
    }
    this.offset = from;
    this.targetOffset = to;
    this.scroll = { from, to, duration, start: now };
    this.scrollDuration = duration;
    this.scrollRevision++;
    if (flash) this.flash(flash, now);
    else this.clearColor();
  }
  tick(now: number) {
    if (this.scroll) {
      this.offset = sample(this.scroll, now);
      if (progress(this.scroll, now) === 1) {
        this.char = this.target;
        this.offset = this.targetOffset = Number(this.target);
        this.scroll = null;
      }
    }
    if (this.appear) {
      this.width = this.opacity = sample(this.appear, now);
      if (progress(this.appear, now) === 1) this.appear = null;
    }
    if (this.colorTween) {
      const t = Math.min(
        1,
        Math.max(0, (now - this.colorTween.start) / GEARS.color),
      );
      const eased = outQuad(t);
      this.color = this.neutral.map(
        (v, i) =>
          this.colorTween!.from[i] + (v - this.colorTween!.from[i]) * eased,
      ) as RGB;
      if (t === 1) this.clearColor();
    }
  }
  settle() {
    this.scroll = this.appear = null;
    this.char = this.target;
    if (this.digit) this.offset = this.targetOffset = Number(this.target);
    this.width = this.opacity = 1;
    this.removing = false;
    this.clearColor();
  }
  get active() {
    return !!(this.scroll || this.appear || this.colorTween);
  }
}

export class TickerModel {
  tracks = new Map<string, CharacterTrack>();
  targetSlots = new Map<string, string>();
  text = "";
  price: string | null = null;
  scrubbing = false;
  private neutral: RGB;
  constructor(neutral = "#FFFFFF") {
    this.neutral = rgb(neutral);
  }

  setText(text: string, { flash = true, animate = true, now = 0 } = {}) {
    if (
      animate &&
      this.tracks.size &&
      text === this.text &&
      !flash === this.scrubbing
    )
      return;
    const parsed = textToSlots(text);
    const oldPrice = this.price,
      oldText = this.text,
      previous = this.targetSlots;
    const enteringScrub = !flash && !this.scrubbing;
    this.scrubbing = !flash;
    this.price = parsed ? text : null;
    this.text = text;
    const slots = (this.targetSlots =
      parsed ?? new Map([["placeholder", text]]));
    if (!parsed || oldPrice === null || !animate) {
      const same =
        slots.size === previous.size &&
        [...slots].every(([k, c]) => previous.get(k) === c) &&
        this.tracks.size === slots.size &&
        [...slots.keys()].every((k) => this.tracks.has(k));
      if (same) this.tracks.forEach((track) => track.settle());
      else
        this.tracks = new Map(
          [...slots].map(([key, char]) => [
            key,
            new CharacterTrack(key, char, this.neutral),
          ]),
        );
      return;
    }
    const change = compareMoney(text, oldPrice);
    const flashColor: RGB | null =
      flash && change ? rgb(change > 0 ? "#00C805" : "#FF5000") : null;
    const changed = [...new Set([...previous.keys(), ...slots.keys()])]
      .filter(
        (key) => key.startsWith("int_") && previous.get(key) !== slots.get(key),
      )
      .sort((a, b) => slotRank(b) - slotRank(a));
    const heavy = changed[0];
    for (const [key, track] of this.tracks) {
      if (!flash) track.clearColor();
      if (!slots.has(key) && !track.removing)
        track.resize(0, !flash ? GEARS.scrubWidth : GEARS.collapse, now);
      else if (enteringScrub && track.appear)
        track.resize(track.removing ? 0 : 1, GEARS.scrubWidth, now);
    }
    for (const [key, char] of slots) {
      let track = this.tracks.get(key);
      const newSlot = !previous.has(key);
      if (!track) {
        track = new CharacterTrack(key, char, this.neutral);
        this.tracks.set(key, track);
        track.width = track.opacity = 0;
        track.resize(1, !flash ? GEARS.scrubWidth : GEARS.expand, now);
        if (track.digit && flashColor) track.flash(flashColor, now);
        continue;
      }
      if (track.removing)
        track.resize(1, !flash ? GEARS.scrubWidth : GEARS.expand, now);
      const old = track.target;
      const duration =
        key === "dec_2"
          ? GEARS.cents
          : key.startsWith("dec_")
            ? GEARS.decimal
            : key.startsWith("int_") &&
                key === heavy &&
                Math.abs(Number(char) - Number(old)) % 10 === 1
              ? GEARS.heavy
              : GEARS.integer;
      const demote =
        !!heavy &&
        key.startsWith("int_") &&
        key !== heavy &&
        !!track.scroll &&
        track.scrollDuration === GEARS.heavy;
      track.setTarget(
        char,
        duration,
        char !== old ? flashColor : null,
        now,
        demote,
      );
      if (newSlot && track.digit && flashColor && old === char)
        track.flash(flashColor, now);
      else if (old === char && text !== oldText) track.clearColor();
    }
    this.removeCollapsed();
  }
  tick(now: number) {
    this.tracks.forEach((track) => track.tick(now));
    this.removeCollapsed();
  }
  private removeCollapsed() {
    for (const [key, track] of this.tracks) {
      if (track.removing && !track.appear && track.width <= 0.001)
        this.tracks.delete(key);
    }
  }
  settle() {
    for (const [key, track] of this.tracks) {
      if (!this.targetSlots.has(key)) this.tracks.delete(key);
      else track.settle();
    }
  }
  get ordered() {
    return [...this.tracks.values()].sort((a, b) => b.rank - a.rank);
  }
  get active() {
    return [...this.tracks.values()].some((track) => track.active);
  }
}
