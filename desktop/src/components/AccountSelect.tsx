import { useEffect, useId, useRef, useState } from "react";
import type { Account } from "../types";
import { useT } from "../i18n";
import { Icon } from "./common";

/** A select-only combobox whose popup uses the same theme on every OS. */
export function AccountSelect({
  accounts,
  value,
  onChange,
}: {
  accounts: Account[];
  value: number | null;
  onChange(value: number): void;
}) {
  const t = useT(),
    id = useId(),
    host = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false),
    [active, setActive] = useState(0);
  const options = [
    ...(accounts.length > 1 ? [{ id: -1, name: t("All accounts") }] : []),
    ...accounts,
  ];
  const selected = options.findIndex((option) => option.id === value);
  const search = useRef({ text: "", time: 0 });
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!host.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  useEffect(() => {
    if (open)
      document
        .getElementById(`${id}-${active}`)
        ?.scrollIntoView({ block: "nearest" });
  }, [active, open, id]);
  const choose = (index: number) => {
    if (options[index]) onChange(options[index].id);
    setOpen(false);
  };
  return (
    <div
      className="account-select"
      ref={host}
      onBlur={(event) => {
        if (!host.current?.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <button
        type="button"
        className="account-trigger"
        role="combobox"
        aria-label={t("Account")}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-controls={id}
        aria-activedescendant={open ? `${id}-${active}` : undefined}
        disabled={!options.length}
        onClick={() => {
          setActive(Math.max(0, selected));
          setOpen((v) => !v);
        }}
        onKeyDown={(event) => {
          const key = event.key;
          if (key === "Escape") {
            event.stopPropagation();
            setOpen(false);
            return;
          }
          if (key === "Enter" || key === " ") {
            event.preventDefault();
            if (open) choose(active);
            else {
              setActive(Math.max(0, selected));
              setOpen(true);
            }
            return;
          }
          if (["ArrowDown", "ArrowUp", "Home", "End"].includes(key)) {
            event.preventDefault();
            setOpen(true);
            setActive((current) =>
              key === "Home"
                ? 0
                : key === "End"
                  ? options.length - 1
                  : Math.max(
                      0,
                      Math.min(
                        options.length - 1,
                        (open ? current : Math.max(0, selected)) +
                          (key === "ArrowDown" ? 1 : -1),
                      ),
                    ),
            );
            return;
          }
          if (
            key.length === 1 &&
            !event.ctrlKey &&
            !event.metaKey &&
            !event.altKey
          ) {
            const now = performance.now();
            search.current = {
              text:
                (now - search.current.time < 700 ? search.current.text : "") +
                key.toLocaleLowerCase(),
              time: now,
            };
            const index = options.findIndex((option) =>
              option.name.toLocaleLowerCase().startsWith(search.current.text),
            );
            if (index >= 0) {
              event.preventDefault();
              setActive(index);
              setOpen(true);
            }
          }
        }}
      >
        <Icon name="wallet" size={17} />
        <span>{options[selected]?.name ?? t("Add account")}</span>
        <Icon name="down" size={14} />
      </button>
      {open && (
        <div
          id={id}
          className="account-options"
          role="listbox"
          aria-label={t("Account")}
        >
          {options.map((option, index) => (
            <button
              type="button"
              tabIndex={-1}
              role="option"
              key={option.id}
              id={`${id}-${index}`}
              aria-selected={option.id === value}
              className={index === active ? "is-active" : ""}
              onPointerMove={() => setActive(index)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(index)}
            >
              <span>{option.name}</span>
              {option.id === value && <Icon name="check" size={16} />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
