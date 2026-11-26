import {
  CharacterTrack,
  colorCss,
  modulo,
  OUT_CUBIC_CSS,
  TickerModel,
} from "./engine";

type Slot = {
  track: CharacterTrack;
  shell: HTMLSpanElement;
  unscale: HTMLSpanElement;
  reel: HTMLSpanElement;
  width: number;
  revision: number;
  animation: Animation | null;
  layout: string;
  color: string;
  text: string;
};
// getComputedStyle(...).font can be empty with tabular-nums: that OpenType
// feature cannot be serialized into the CSS font shorthand. Use the longhands.
const canvasFont = (style: CSSStyleDeclaration) =>
  `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;

/** React never participates in the frame loop. Each reel is a stable composited layer. */
export class TickerRenderer {
  readonly model: TickerModel;
  private slots = new Map<string, Slot>();
  private frame = 0;
  private disposed = false;
  private height: number;
  private context: CanvasRenderingContext2D;
  private observer: ResizeObserver;
  private font: string;
  private hidden = false;
  private selection: HTMLSpanElement;

  constructor(
    private host: HTMLElement,
    neutral: string,
  ) {
    this.model = new TickerModel(neutral);
    // Only this real value is selectable. Reel copies remain decorative so
    // selecting/copying an amount never includes the hidden 0–9 repetitions.
    this.selection = document.createElement("span");
    this.selection.className = "ticker-selection";
    host.append(this.selection);
    this.context = document.createElement("canvas").getContext("2d")!;
    const style = getComputedStyle(host);
    this.font = canvasFont(style);
    this.context.font = this.font;
    this.height =
      parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.2;
    host.style.height = `${this.height}px`;
    this.observer = new ResizeObserver(() => {
      const next = getComputedStyle(host);
      if (canvasFont(next) !== this.font) {
        this.font = canvasFont(next);
        this.context.font = this.font;
        this.height =
          parseFloat(next.lineHeight) || parseFloat(next.fontSize) * 1.2;
        host.style.height = `${this.height}px`;
        this.clearSlots();
        this.model.settle();
        this.render();
      }
    });
    this.observer.observe(host);
    document.addEventListener("visibilitychange", this.visibility);
    document.fonts.ready.then(() => {
      if (!this.disposed) {
        this.context.font = this.font;
        this.clearSlots();
        this.render();
      }
    });
  }
  private now() {
    return Number(document.timeline.currentTime ?? performance.now());
  }
  private visibility = () => {
    this.hidden = document.hidden;
    if (this.hidden) this.settle();
  };
  setText(text: string, flash = true, animate = true) {
    if (this.disposed) return;
    if (text === this.model.text && !flash === this.model.scrubbing && animate)
      return;
    const now = this.now();
    // Read the same clock used by WAAPI before replacing an in-flight trajectory.
    this.model.tick(now);
    this.model.setText(text, {
      flash,
      animate: animate && !this.hidden && !document.hidden,
      now,
    });
    this.host.setAttribute("aria-label", text);
    if (this.selection.textContent !== text) this.selection.textContent = text;
    this.render();
    this.schedule();
  }
  settle() {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.model.settle();
    this.render();
  }
  private schedule() {
    if (!this.frame && this.model.active && !this.disposed && !this.hidden)
      this.frame = requestAnimationFrame(this.tick);
  }
  private tick = (now: number) => {
    this.frame = 0;
    this.model.tick(now);
    this.render();
    this.schedule();
  };
  private makeSlot(track: CharacterTrack): Slot {
    const shell = document.createElement("span");
    shell.className = "ticker-slot";
    shell.dataset.slot = track.key;
    shell.setAttribute("aria-hidden", "true");
    const unscale = document.createElement("span");
    unscale.className = "ticker-unscale";
    const reel = document.createElement("span");
    reel.className = "ticker-reel";
    let width: number;
    if (track.digit) {
      width =
        Math.max(
          ...[..."0123456789"].map((c) => this.context.measureText(c).width),
        ) + 2;
      // The negative glyph positions preserve ticker.py's mirrored reel direction.
      // Enough repeated glyphs cover both normalized and wraparound trajectories.
      for (let value = -1; value <= 21; value++) {
        const glyph = document.createElement("span");
        glyph.className = "ticker-glyph";
        glyph.textContent = String(modulo(value));
        glyph.style.top = `${-value * this.height}px`;
        reel.append(glyph);
      }
    } else {
      width =
        (track.key === "sign"
          ? Math.max(...[..."+-"].map((c) => this.context.measureText(c).width))
          : this.context.measureText(track.char).width) + 2;
      reel.textContent = track.char;
    }
    shell.style.width = unscale.style.width = reel.style.width = `${width}px`;
    shell.style.height =
      unscale.style.height =
      reel.style.height =
        `${this.height}px`;
    unscale.append(reel);
    shell.append(unscale);
    this.host.append(shell);
    return {
      track,
      shell,
      unscale,
      reel,
      width,
      revision: -1,
      animation: null,
      layout: "",
      color: "",
      text: track.char,
    };
  }
  private render() {
    for (const [key, slot] of this.slots) {
      if (this.model.tracks.get(key) !== slot.track) {
        slot.animation?.cancel();
        slot.shell.remove();
        this.slots.delete(key);
      }
    }
    let x = 0;
    for (const track of this.model.ordered) {
      let slot = this.slots.get(track.key);
      if (!slot) {
        slot = this.makeSlot(track);
        this.slots.set(track.key, slot);
      }
      const factor = Math.max(0.00001, track.width);
      const layout = `${x},${factor},${track.opacity}`;
      if (slot.layout !== layout) {
        // Scale the CLIP, then undo the scale on its content. Glyphs retain their
        // original aspect ratio as a new integer/comma expands or collapses.
        slot.shell.style.transform = `translate3d(${x}px,0,0) scaleX(${factor})`;
        slot.unscale.style.transform = `scaleX(${1 / factor})`;
        slot.shell.style.opacity = String(track.opacity);
        slot.layout = layout;
      }
      const color = colorCss(track.color);
      if (color !== slot.color) {
        slot.reel.style.color = color;
        slot.color = color;
      }
      if (track.digit) {
        if (track.scroll && slot.revision !== track.scrollRevision) {
          slot.animation?.cancel();
          const { from, to, start, duration } = track.scroll;
          slot.reel.style.transform = `translate3d(0,${from * this.height}px,0)`;
          slot.reel.style.willChange = "transform";
          slot.animation = slot.reel.animate(
            [
              { transform: `translate3d(0,${from * this.height}px,0)` },
              { transform: `translate3d(0,${to * this.height}px,0)` },
            ],
            { duration, easing: OUT_CUBIC_CSS, fill: "both" },
          );
          slot.animation.startTime = start;
          slot.revision = track.scrollRevision;
        } else if (!track.scroll) {
          slot.reel.style.transform = `translate3d(0,${track.offset * this.height}px,0)`;
          slot.animation?.cancel();
          slot.animation = null;
          slot.reel.style.willChange = "";
        }
      } else if (track.char !== slot.text) {
        slot.reel.textContent = track.char;
        slot.text = track.char;
      }
      x += slot.width * track.width;
    }
    const width = `${Math.max(60, Math.ceil(x) + 15)}px`;
    if (this.host.style.width !== width) this.host.style.width = width;
  }
  private clearSlots() {
    this.slots.forEach((slot) => {
      slot.animation?.cancel();
      slot.shell.remove();
    });
    this.slots.clear();
  }
  dispose() {
    this.disposed = true;
    if (this.frame) cancelAnimationFrame(this.frame);
    this.observer.disconnect();
    document.removeEventListener("visibilitychange", this.visibility);
    this.clearSlots();
    this.selection.remove();
  }
}
