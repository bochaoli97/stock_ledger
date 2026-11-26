import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n";
import { NumberTicker, type TickerHandle } from "./NumberTicker";
import { Icon } from "./common";

const sequences: Record<string, string[]> = {
  "Carry & borrow": [
    "$999.99",
    "$1,000.00",
    "$1,000.01",
    "$999.98",
    "$10,000.00",
    "$9,999.99",
  ],
  "Rapid retargeting": [
    "$123.99",
    "$124.00",
    "$224.00",
    "$226.78",
    "$225.35",
    "$123.45",
    "$123.99",
  ],
  "Negative values": [
    "$0.01",
    "-$0.01",
    "-$12.34",
    "-$12.35",
    "$12.35",
    "$0.00",
  ],
};
export function AnimationStudio({
  neutral,
  onBack,
}: {
  neutral: string;
  onBack(): void;
}) {
  const t = useT(),
    ticker = useRef<TickerHandle>(null);
  const [sequence, setSequence] = useState("Carry & borrow"),
    [running, setRunning] = useState(false);
  const [value, setValue] = useState("$999.99"),
    [scrub, setScrub] = useState(false),
    [speed, setSpeed] = useState(800);
  const runningRef = useRef(false);
  useEffect(() => {
    if (!running) return;
    let index = 0;
    runningRef.current = true;
    const timer = setInterval(() => {
      const next = sequences[sequence][index++ % sequences[sequence].length];
      setValue(next);
      ticker.current?.setText(next, !scrub);
    }, speed);
    return () => {
      runningRef.current = false;
      clearInterval(timer);
    };
  }, [running, sequence, speed, scrub]);
  return (
    <section className="studio">
      <button className="back-link" onClick={onBack}>
        <Icon name="back" size={17} />
        {t("Back to settings")}
      </button>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("Animation preview")}</p>
          <h1>{t("Animation studio")}</h1>
          <p className="muted">{t("Test sequences use sample values.")}</p>
        </div>
      </div>
      <div className="studio-stage">
        <NumberTicker text="$999.99" neutral={neutral} ref={ticker} />
        <span className="eyebrow">{value}</span>
      </div>
      <div className="studio-controls">
        <select
          aria-label={t("Animation preview")}
          value={sequence}
          onChange={(e) => setSequence(e.target.value)}
        >
          {Object.keys(sequences).map((key) => (
            <option key={key} value={key}>
              {t(key)}
            </option>
          ))}
        </select>
        <button
          className="button primary"
          onClick={() => setRunning((v) => !v)}
        >
          <Icon name="play" size={17} />
          {t(running ? "Pause" : "Run sequence")}
        </button>
      </div>
      <label className="setting-row">
        <span>{t("Neutral scrub")}</span>
        <input
          type="checkbox"
          className="switch"
          checked={scrub}
          onChange={(e) => setScrub(e.target.checked)}
        />
      </label>
      <label className="field">
        <span>{t("Value")}</span>
        <input
          aria-label={t("Value")}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            ticker.current?.setText(e.target.value, !scrub);
          }}
        />
      </label>
      <label className="field">
        <span>{speed} ms</span>
        <input
          type="range"
          aria-label="Update interval"
          min={50}
          max={1600}
          step={50}
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
        />
      </label>
    </section>
  );
}
