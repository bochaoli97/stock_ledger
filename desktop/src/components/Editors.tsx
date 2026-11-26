import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  api,
  type Account,
  type Snapshot,
  type Suggestion,
  type Transaction,
} from "../types";
import { useT } from "../i18n";
import { errorText, Field, Gain, Icon, Modal } from "./common";

export function SymbolInput({
  value,
  onChange,
  id,
  "aria-labelledby": labelledBy,
}: {
  value: string;
  onChange(value: string): void;
  id?: string;
  "aria-labelledby"?: string;
}) {
  const [items, setItems] = useState<Suggestion[]>([]),
    [open, setOpen] = useState(false),
    [active, setActive] = useState(0);
  const generation = useRef(0),
    box = useRef<HTMLDivElement>(null);
  const listId =
    "symbols-" + useRef(Math.random().toString(36).slice(2)).current;
  useEffect(() => {
    const token = ++generation.current;
    if (!value.trim()) {
      setItems([]);
      return;
    }
    const timer = setTimeout(
      () =>
        api()
          .request<Suggestion[]>("symbols.search", { query: value })
          .then((result) => {
            if (token === generation.current) {
              setItems(result.slice(0, 8));
              setActive(0);
            }
          })
          .catch(() => {
            if (token === generation.current) setItems([]);
          }),
      180,
    );
    return () => {
      clearTimeout(timer);
      generation.current++;
    };
  }, [value]);
  const pick = (item: Suggestion) => {
    onChange(item.symbol);
    setOpen(false);
  };
  return (
    <div
      className="symbol-input"
      ref={box}
      onBlur={(e) => {
        if (!box.current?.contains(e.relatedTarget)) setOpen(false);
      }}
    >
      <input
        id={id}
        aria-labelledby={labelledBy}
        value={value}
        autoComplete="off"
        spellCheck={false}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open && !!items.length}
        aria-controls={listId}
        aria-activedescendant={
          open && items[active] ? `${listId}-${active}` : undefined
        }
        onChange={(e) => {
          onChange(e.target.value.toUpperCase());
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (!open || !items.length) return;
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            setActive(
              (i) =>
                (i + (e.key === "ArrowDown" ? 1 : items.length - 1)) %
                items.length,
            );
          }
          if (e.key === "Enter") {
            e.preventDefault();
            pick(items[active]);
          }
          if (e.key === "Escape") {
            e.stopPropagation();
            setOpen(false);
          }
        }}
      />
      {open && !!items.length && (
        <div className="suggestions" id={listId} role="listbox">
          {items.map((item, i) => (
            <button
              key={item.symbol}
              type="button"
              role="option"
              id={`${listId}-${i}`}
              aria-selected={i === active}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => pick(item)}
            >
              <strong>{item.symbol}</strong>
              <span>{item.name}</span>
              {item.holding && <small>{item.holding}</small>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

type EditorProps = {
  snapshot: Snapshot;
  onSaved(data: Snapshot): void;
  onClose(): void;
};
export function AccountEditor({
  snapshot,
  initial,
  onSaved,
  onClose,
}: EditorProps & { initial?: Account }) {
  const t = useT();
  const [form, setForm] = useState({
    name: initial?.name ?? "",
    broker: initial?.broker ?? "",
    note: initial?.note ?? "",
    date: snapshot.today,
    cash: "",
  });
  const [positions, setPositions] = useState<
    { symbol: string; quantity: string; price: string }[]
  >([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const set = (key: string, value: string) =>
    setForm((f) => ({ ...f, [key]: value }));
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      onSaved(
        await api().request<Snapshot>("account.save", {
          ...form,
          id: initial?.id,
          positions,
        }),
      );
      onClose();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={t(initial ? "Edit account" : "Add account")}
      onClose={() => !busy && onClose()}
      wide
    >
      <form onSubmit={save} className="editor-form">
        <div className="form-grid">
          <Field label={t("Name")}>
            <input
              required
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
            />
          </Field>
          <Field label={t("Broker")}>
            <input
              value={form.broker}
              onChange={(e) => set("broker", e.target.value)}
            />
          </Field>
        </div>
        <Field label={t("Note")}>
          <input
            value={form.note}
            onChange={(e) => set("note", e.target.value)}
          />
        </Field>
        {!initial && (
          <>
            <h3>{t("Opening balances")}</h3>
            <div className="form-grid">
              <Field label={t("Opening date")}>
                <input
                  required
                  type="date"
                  value={form.date}
                  onChange={(e) => set("date", e.target.value)}
                />
              </Field>
              <Field label={t("Opening cash")}>
                <input
                  inputMode="decimal"
                  placeholder="0.00"
                  value={form.cash}
                  onChange={(e) => set("cash", e.target.value)}
                />
              </Field>
            </div>
            <div className="section-heading compact">
              <h3>{t("Opening positions")}</h3>
              <button
                type="button"
                className="text-button"
                onClick={() =>
                  setPositions((p) => [
                    ...p,
                    { symbol: "", quantity: "", price: "" },
                  ])
                }
              >
                <Icon name="plus" size={16} />
                {t("Add position")}
              </button>
            </div>
            {positions.map((position, i) => (
              <div className="position-editor" key={i}>
                {(["symbol", "quantity", "price"] as const).map((key) => (
                  <Field
                    key={key}
                    label={t(
                      key === "symbol"
                        ? "Symbol"
                        : key === "quantity"
                          ? "Shares"
                          : "Cost / share",
                    )}
                  >
                    {key === "symbol" ? (
                      <SymbolInput
                        value={position.symbol}
                        onChange={(value) =>
                          setPositions((p) =>
                            p.map((row, j) =>
                              j === i ? { ...row, symbol: value } : row,
                            ),
                          )
                        }
                      />
                    ) : (
                      <input
                        inputMode="decimal"
                        required
                        value={position[key]}
                        onChange={(e) =>
                          setPositions((p) =>
                            p.map((row, j) =>
                              j === i ? { ...row, [key]: e.target.value } : row,
                            ),
                          )
                        }
                      />
                    )}
                  </Field>
                ))}
                <button
                  className="icon-button"
                  type="button"
                  aria-label={t("Delete")}
                  onClick={() =>
                    setPositions((p) => p.filter((_, j) => i !== j))
                  }
                >
                  <Icon name="close" size={17} />
                </button>
              </div>
            ))}
          </>
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            onClick={onClose}
            disabled={busy}
          >
            {t("Cancel")}
          </button>
          <button className="button primary" disabled={busy}>
            {t(busy ? "Loading" : "Save account")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function TransactionEditor({
  snapshot,
  initial,
  symbol = "",
  onSaved,
  onClose,
}: EditorProps & { initial?: Transaction; symbol?: string }) {
  const t = useT();
  const [form, setForm] = useState<Record<string, string>>({
    date: initial?.date ?? snapshot.today,
    type: initial?.type ?? "BUY",
    symbol: initial?.symbol ?? symbol,
    symbol2: initial?.symbol2 ?? "",
    quantity: initial?.quantity ?? "",
    price: initial?.price ?? "",
    amount: initial?.amount ?? "",
    fee: initial?.fee ?? "",
    note: initial?.note ?? "",
  });
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [negative, setNegative] = useState<{ lowest: string } | null>(null);
  const [preview, setPreview] = useState<Record<string, string> | null>(null);
  const [previewError, setPreviewError] = useState("");
  const aid = initial?.account_id ?? snapshot.account_id;
  const fields =
    snapshot.transaction_types.find((type) => type.code === form.type)
      ?.fields ?? [];
  const set = (key: string, value: string) => {
    setForm((f) => ({ ...f, [key]: value }));
    setNegative(null);
    setError("");
  };
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(
      () =>
        api()
          .request<Record<string, string>>("transaction.preview", {
            ...form,
            id: initial?.id,
            account_id: aid,
          })
          .then((value) => {
            if (!cancelled) {
              setPreview(value);
              setPreviewError("");
            }
          })
          .catch((e) => {
            if (!cancelled) {
              setPreview(null);
              setPreviewError(errorText(e));
            }
          }),
      180,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [form, aid, initial?.id]);
  const save = async (e?: FormEvent, allow = false) => {
    e?.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await api().request<Snapshot>("transaction.save", {
        ...form,
        id: initial?.id,
        account_id: aid,
        allow_negative_cash: allow,
      });
      onSaved(result);
      onClose();
    } catch (e) {
      const detail = e as Error & {
        code?: string;
        details?: { lowest: string };
      };
      if (detail.code === "NEGATIVE_CASH") setNegative(detail.details!);
      else setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const holding = snapshot.holdings.find((p) => p.symbol === form.symbol);
  const required = (key: string) => fields.includes(key) && key !== "fee";
  return (
    <Modal
      title={t(initial ? "Edit transaction" : "New transaction")}
      onClose={() => !busy && onClose()}
      wide
    >
      <form onSubmit={save} className="editor-form">
        <div className="form-grid">
          <Field label={t("Type")}>
            <select
              value={form.type}
              onChange={(e) => set("type", e.target.value)}
            >
              {snapshot.transaction_types.map((type) => (
                <option key={type.code} value={type.code}>
                  {type.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("Date")}>
            <input
              required
              type="date"
              value={form.date}
              onChange={(e) => set("date", e.target.value)}
            />
          </Field>
        </div>
        <div className="form-grid">
          {fields.map((key) => (
            <Field
              key={key}
              label={t(
                key === "symbol2"
                  ? "New symbol"
                  : key === "quantity" && form.type === "SPLIT"
                    ? "Share change"
                    : key === "price" && form.type === "DISTRIBUTION"
                      ? "Cost moved %"
                      : key[0].toUpperCase() + key.slice(1),
              )}
            >
              {key === "symbol" || key === "symbol2" ? (
                <SymbolInput
                  value={form[key]}
                  onChange={(value) => set(key, value)}
                />
              ) : (
                <div className="input-with-action">
                  <input
                    inputMode="decimal"
                    required={required(key)}
                    value={form[key]}
                    onChange={(e) => set(key, e.target.value)}
                  />
                  {key === "quantity" && form.type === "SELL" && holding && (
                    <button
                      type="button"
                      onClick={() => set("quantity", holding.quantity_raw)}
                    >
                      {t("All")}
                    </button>
                  )}
                </div>
              )}
            </Field>
          ))}
        </div>
        <Field label={t("Note")}>
          <textarea
            rows={2}
            value={form.note}
            onChange={(e) => set("note", e.target.value)}
          />
        </Field>
        <div className="transaction-preview">
          <span className="eyebrow">{t("Preview")}</span>
          {preview ? (
            <div className="preview-grid">
              {[
                ["Cash change", "cash_change"],
                ["Cash after", "cash_after"],
                ["Shares after", "shares_after"],
                ["Average after", "avg_after"],
              ].map(([label, key]) => (
                <div key={key}>
                  <span>{t(label)}</span>
                  <strong>
                    <Gain value={preview[key]} />
                  </strong>
                </div>
              ))}
            </div>
          ) : (
            <p>{previewError || t("Loading")}</p>
          )}
        </div>
        {negative && (
          <div className="warning" role="alert">
            <strong>{t("Negative cash balance")}</strong>
            <p>
              {t("Lowest cash balance")}: {negative.lowest}
            </p>
            <p>
              {t("Continue only if this is margin or an unrecorded deposit.")}
            </p>
            <button
              type="button"
              className="button danger"
              disabled={busy}
              onClick={() => save(undefined, true)}
            >
              {t("Save anyway")}
            </button>
          </div>
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            disabled={busy}
            onClick={onClose}
          >
            {t("Cancel")}
          </button>
          <button className="button primary" disabled={busy}>
            {t(busy ? "Loading" : "Save transaction")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function PriceEditor({ snapshot, onSaved, onClose }: EditorProps) {
  const t = useT();
  const [prices, setPrices] = useState<Record<string, string>>(
    Object.fromEntries(
      snapshot.holdings
        .filter((p) => p.open)
        .map((p) => [p.symbol, p.price_raw]),
    ),
  );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      onSaved(
        await api().request<Snapshot>("prices.save", {
          prices,
          account_id: snapshot.account_id,
        }),
      );
      onClose();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={t("Manage prices")} onClose={() => !busy && onClose()}>
      <form onSubmit={save} className="editor-form">
        {Object.entries(prices).map(([symbol, value]) => (
          <Field
            key={symbol}
            label={symbol}
            hint={t("At cost until a price is entered")}
          >
            <input
              inputMode="decimal"
              value={value}
              onChange={(e) =>
                setPrices((p) => ({ ...p, [symbol]: e.target.value }))
              }
            />
          </Field>
        ))}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            onClick={onClose}
            disabled={busy}
          >
            {t("Cancel")}
          </button>
          <button className="button primary" disabled={busy}>
            {t("Save")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
