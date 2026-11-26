import {
  Children,
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useRef,
  type ReactNode,
} from "react";
import { useT } from "../i18n";

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    plus: <path d="M12 5v14M5 12h14" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    back: <path d="m14 6-6 6 6 6" />,
    forward: <path d="m10 6 6 6-6 6" />,
    appearance: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 3v18" />
        <path d="M12 3a9 9 0 0 1 0 18Z" fill="currentColor" stroke="none" />
      </>
    ),
    database: (
      <>
        <ellipse cx="12" cy="5" rx="8" ry="3" />
        <path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0" />
      </>
    ),
    folder: <path d="M3 7V4h6l3 3h9v13H3Z" />,
    monitor: (
      <>
        <rect x="3" y="4" width="18" height="13" rx="2" />
        <path d="M8 21h8m-4-4v4" />
      </>
    ),
    search: (
      <>
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="m16 16 5 5" />
      </>
    ),
    chart: (
      <>
        <path d="M4 19V5m0 14h16M7 14l4-5 4 3 5-7" />
      </>
    ),
    list: (
      <>
        <path d="M9 6h11M9 12h11M9 18h11" />
        <path d="M4 6h.01M4 12h.01M4 18h.01" />
      </>
    ),
    wallet: (
      <>
        <path d="M20 8V5H5a2 2 0 0 0 0 4h15v11H5a2 2 0 0 1-2-2V7" />
        <path d="M20 12h-5v4h5" />
      </>
    ),
    settings: (
      <>
        <path d="M4 7h16M4 17h16" />
        <circle cx="9" cy="7" r="3" />
        <circle cx="15" cy="17" r="3" />
      </>
    ),
    download: (
      <>
        <path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4" />
      </>
    ),
    dots: (
      <>
        <circle cx="5" cy="12" r="1" />
        <circle cx="12" cy="12" r="1" />
        <circle cx="19" cy="12" r="1" />
      </>
    ),
    edit: (
      <>
        <path d="m14 5 5 5M4 20l5-1L20 8a2 2 0 0 0-4-4L5 15z" />
      </>
    ),
    trash: (
      <>
        <path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    up: <path d="m6 14 6-6 6 6" />,
    down: <path d="m6 10 6 6 6-6" />,
    play: <path d="m8 4 12 8-12 8z" />,
    leaf: (
      <>
        <path d="M5 20C4 7 11 2 21 3c1 10-4 17-16 17ZM5 20 17 7M10 15h7M12 12V6" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] ?? paths.dots}
    </svg>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose(): void;
  wide?: boolean;
}) {
  const t = useT(),
    id = useId(),
    ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const focus = () =>
      (
        ref.current?.querySelector<HTMLElement>(
          "input:not([disabled]),select:not([disabled]),textarea:not([disabled])",
        ) ?? ref.current?.querySelector<HTMLElement>("button:not([disabled])")
      )?.focus();
    focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        close.current();
      }
      if (event.key !== "Tab") return;
      const nodes = [
        ...ref.current!.querySelectorAll<HTMLElement>(
          'button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]',
        ),
      ];
      const first = nodes[0],
        last = nodes.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    ref.current?.addEventListener("keydown", keydown);
    const node = ref.current;
    return () => {
      node?.removeEventListener("keydown", keydown);
      previous?.focus();
    };
  }, []);
  return (
    <div
      className="modal-shade"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={ref}
        className={`modal ${wide ? "modal-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
      >
        <div className="modal-heading">
          <h2 id={id}>{title}</h2>
          <button
            className="icon-button"
            type="button"
            onClick={onClose}
            aria-label={t("Close")}
          >
            <Icon name="close" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  const id = useId(),
    labelId = `${id}-label`,
    hintId = `${id}-hint`;
  const associate = (child: ReactNode): ReactNode => {
    if (
      !isValidElement<{
        children?: ReactNode;
        id?: string;
        "aria-labelledby"?: string;
        "aria-describedby"?: string;
      }>(child)
    )
      return child;
    if (
      typeof child.type !== "string" ||
      ["input", "select", "textarea"].includes(child.type)
    ) {
      return cloneElement(child, {
        id,
        "aria-labelledby": labelId,
        "aria-describedby": hint ? hintId : undefined,
      });
    }
    return cloneElement(
      child,
      {},
      Children.map(child.props.children, associate),
    );
  };
  return (
    <div className="field">
      <label id={labelId} htmlFor={id}>
        {label}
      </label>
      {Children.map(children, associate)}
      {hint && <small id={hintId}>{hint}</small>}
    </div>
  );
}
export function Empty({
  title,
  message,
  action,
}: {
  title: string;
  message?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name="chart" size={30} />
      </span>
      <h3>{title}</h3>
      {message && <p>{message}</p>}
      {action}
    </div>
  );
}
export function Gain({
  value,
  children,
}: {
  value: string;
  children?: ReactNode;
}) {
  return (
    <span
      className={
        value.startsWith("-") ? "loss" : value.startsWith("+") ? "gain" : ""
      }
    >
      {children ?? value}
    </span>
  );
}
export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : String(error);
