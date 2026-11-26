import { useLayoutEffect, useRef } from "react";
import type { ChartData, ChartPoint } from "../types";

export function PriceChart({
  data,
  color,
  onHover,
  loading = false,
}: {
  data: ChartData | null;
  color: string;
  onHover(point: ChartPoint | null, index?: number | null): void;
  loading?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null),
    canvas = useRef<HTMLCanvasElement>(null);
  const cursor = useRef<HTMLDivElement>(null),
    label = useRef<HTMLSpanElement>(null),
    dot = useRef<HTMLDivElement>(null);
  const current = useRef({ data, onHover });
  current.current = { data, onHover };
  const geometry = useRef<{ x: number; y: number }[]>([]);
  const index = useRef<number | null>(null);
  useLayoutEffect(() => {
    const container = host.current!,
      surface = canvas.current!;
    const draw = () => {
      const rect = container.getBoundingClientRect(),
        dpr = window.devicePixelRatio || 1;
      surface.width = Math.round(rect.width * dpr);
      surface.height = Math.round(rect.height * dpr);
      const ctx = surface.getContext("2d")!;
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, rect.width, rect.height);
      const points = data?.points ?? [];
      geometry.current = [];
      if (points.length < 2) return;
      let min = Infinity,
        max = -Infinity;
      points.forEach((p) => {
        min = Math.min(min, p.value);
        max = Math.max(max, p.value);
      });
      if (data?.baseline != null) {
        min = Math.min(min, data.baseline);
        max = Math.max(max, data.baseline);
      }
      if (min === max) {
        min--;
        max++;
      }
      const pad = 3,
        top = 38,
        bottom = 22;
      // Today's graph reserves the regular-session slots, matching the Qt chart.
      const slots = Math.max(data?.slots ?? 0, points.length);
      const x = (i: number) => pad + (i / (slots - 1)) * (rect.width - 2 * pad);
      const y = (v: number) =>
        top + ((max - v) / (max - min)) * (rect.height - top - bottom);
      if (data?.baseline != null) {
        ctx.beginPath();
        ctx.setLineDash([2, 5]);
        ctx.strokeStyle =
          getComputedStyle(container).getPropertyValue("--border");
        ctx.lineWidth = 1;
        ctx.moveTo(0, y(data.baseline));
        ctx.lineTo(rect.width, y(data.baseline));
        ctx.stroke();
        ctx.setLineDash([]);
      }
      geometry.current = points.map((p, i) => ({ x: x(i), y: y(p.value) }));
      if (index.current !== null && geometry.current[index.current]) {
        const xy = geometry.current[index.current];
        cursor.current!.style.transform = `translate3d(${xy.x}px,0,0)`;
        cursor.current!.style.setProperty("--cursor-y", `${xy.y}px`);
      }
      ctx.beginPath();
      geometry.current.forEach((p, i) =>
        i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y),
      );
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.stroke();
      const last = geometry.current.at(-1)!;
      dot.current!.style.transform = `translate3d(${last.x}px,${last.y}px,0)`;
      dot.current!.style.color = color;
    };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(container);
    return () => observer.disconnect();
  }, [data, color]);
  useLayoutEffect(() => {
    const node = host.current!;
    const leave = () => {
      index.current = null;
      cursor.current!.hidden = true;
      node.classList.remove("chart-scrubbing");
      current.current.onHover(null);
    };
    const select = (i: number) => {
      const points = current.current.data?.points;
      if (!points?.length || !geometry.current[i]) return;
      const p = points[i],
        xy = geometry.current[i];
      cursor.current!.hidden = false;
      cursor.current!.style.transform = `translate3d(${xy.x}px,0,0)`;
      cursor.current!.style.setProperty("--cursor-y", `${xy.y}px`);
      const date = new Date(p.time * 1000);
      label.current!.textContent = date.toLocaleString(
        document.documentElement.lang,
        { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" },
      );
      label.current!.style.transform = `translateX(${Math.min(0, Math.max(-110, node.clientWidth - xy.x - 150))}px)`;
      node.classList.add("chart-scrubbing");
      if (i !== index.current) {
        index.current = i;
        current.current.onHover(p, i);
      }
    };
    const move = (event: PointerEvent) => {
      const positions = geometry.current;
      if (positions.length < 2) return;
      const x = event.clientX - node.getBoundingClientRect().left;
      const dx = positions[1].x - positions[0].x;
      select(
        Math.max(
          0,
          Math.min(positions.length - 1, Math.round((x - positions[0].x) / dx)),
        ),
      );
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        leave();
        return;
      }
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const n = geometry.current.length;
      select(
        Math.max(
          0,
          Math.min(
            n - 1,
            (index.current ?? n - 1) + (event.key === "ArrowRight" ? 1 : -1),
          ),
        ),
      );
    };
    node.addEventListener("pointermove", move);
    node.addEventListener("pointerleave", leave);
    node.addEventListener("keydown", key);
    node.addEventListener("blur", leave);
    return () => {
      node.removeEventListener("pointermove", move);
      node.removeEventListener("pointerleave", leave);
      node.removeEventListener("keydown", key);
      node.removeEventListener("blur", leave);
    };
  }, []);
  return (
    <div
      ref={host}
      className="price-chart"
      tabIndex={0}
      role="group"
      aria-label="Price history / 价格走势"
      aria-busy={loading}
    >
      <canvas ref={canvas} aria-hidden="true" />
      <div
        ref={dot}
        className={`chart-live-dot ${data?.live ? "" : "no-pulse"}`}
        hidden={!data?.live || (data?.points.length ?? 0) < 2}
      >
        <i />
        <b />
      </div>
      <div ref={cursor} className="chart-cursor" hidden>
        <span ref={label} />
        <i />
      </div>
      {(data?.points.length ?? 0) < 2 && (
        <div className="chart-message">
          {loading
            ? document.documentElement.lang === "zh-CN"
              ? "加载中…"
              : "Loading…"
            : data?.message}
        </div>
      )}
    </div>
  );
}

export function Sparkline({
  points,
  negative,
}: {
  points: [number, number][];
  negative?: boolean;
}) {
  if (points.length < 2) return <span className="sparkline-empty" />;
  const values = points.map((p) => p[1]),
    min = Math.min(...values),
    max = Math.max(...values);
  const line = values
    .map(
      (v, i) =>
        `${(i / (values.length - 1)) * 88},${28 - ((v - min) / (max - min || 1)) * 24}`,
    )
    .join(" ");
  return (
    <svg
      className={`sparkline ${negative ? "loss" : "gain"}`}
      viewBox="0 0 88 32"
      aria-hidden="true"
    >
      <polyline
        points={line}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  );
}
