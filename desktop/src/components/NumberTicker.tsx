import {
  forwardRef,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
} from "react";
import { TickerRenderer } from "../ticker/dom";

export type TickerHandle = {
  setText(text: string, flash?: boolean, animate?: boolean): void;
  settle(): void;
};
export const NumberTicker = forwardRef<
  TickerHandle,
  { text: string; neutral?: string; className?: string }
>(function NumberTicker({ text, neutral = "#FFFFFF", className = "" }, ref) {
  const host = useRef<HTMLSpanElement>(null);
  const renderer = useRef<TickerRenderer | null>(null);
  const latest = useRef(text);
  latest.current = text;
  useLayoutEffect(() => {
    const view = new TickerRenderer(host.current!, neutral);
    renderer.current = view;
    view.setText(latest.current, true, false);
    return () => {
      view.dispose();
      renderer.current = null;
    };
  }, [neutral]);
  useLayoutEffect(() => {
    renderer.current?.setText(text);
  }, [text]);
  useImperativeHandle(
    ref,
    () => ({
      setText: (value, flash = true, animate = true) =>
        renderer.current?.setText(value, flash, animate),
      settle: () => renderer.current?.settle(),
    }),
    [],
  );
  return (
    <span
      ref={host}
      className={`number-ticker ${className}`}
      aria-label={text}
    />
  );
});
