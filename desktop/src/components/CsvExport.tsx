import { useState, type FormEvent } from "react";
import { api, type CsvExportRange } from "../types";
import { useT } from "../i18n";
import { errorText, Field, Icon, Modal } from "./common";

export function CsvExportButton({
  kind,
  accountId = null,
  scope,
  periods,
  initialRange = { period: "ALL" },
  onNotice,
}: {
  kind: "stock" | "finance";
  accountId?: number | null;
  scope?: string;
  periods: { code: string; label: string }[];
  initialRange?: CsvExportRange;
  onNotice(message: string): void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [range, setRange] = useState(initialRange);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const title = t(
    kind === "stock" ? "Export account CSV" : "Export finance CSV",
  );
  const invalid =
    range.period === "CUSTOM" &&
    !!range.first &&
    !!range.last &&
    range.first > range.last;
  const close = () => {
    if (!busy) setOpen(false);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (invalid || busy) return;
    setError("");
    setBusy(true);
    try {
      const files = await api().exportCsv(kind, accountId, range);
      if (files) {
        onNotice(`${t("CSV exported")}: ${files.join(", ")}`);
        setOpen(false);
      }
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button
        className="button secondary"
        disabled={kind === "stock" && (accountId === null || accountId === -1)}
        onClick={() => {
          setRange(initialRange);
          setError("");
          setOpen(true);
        }}
      >
        <Icon name="download" size={17} />
        {title}
      </button>
      {open && (
        <Modal title={title} onClose={close}>
          <form onSubmit={submit}>
            {scope && (
              <p className="export-scope">
                <Icon name="wallet" size={18} />
                {scope}
              </p>
            )}
            <Field label={t("Time range")}>
              <select
                value={range.period}
                disabled={busy}
                onChange={(event) =>
                  setRange({ ...range, period: event.target.value })
                }
              >
                {periods.map((item) => (
                  <option key={item.code} value={item.code}>
                    {t(item.label)}
                  </option>
                ))}
                <option value="CUSTOM">{t("Custom range")}</option>
              </select>
            </Field>
            {range.period === "CUSTOM" && (
              <div className="form-grid">
                <Field label={t("From")} hint={t("Leave blank for no limit")}>
                  <input
                    type={kind === "finance" ? "month" : "date"}
                    value={range.first ?? ""}
                    disabled={busy}
                    onChange={(event) =>
                      setRange({ ...range, first: event.target.value })
                    }
                  />
                </Field>
                <Field label={t("To")} hint={t("Leave blank for no limit")}>
                  <input
                    type={kind === "finance" ? "month" : "date"}
                    value={range.last ?? ""}
                    disabled={busy}
                    onChange={(event) =>
                      setRange({ ...range, last: event.target.value })
                    }
                  />
                </Field>
              </div>
            )}
            <div className="export-summary">
              <strong>{t("Included files")}</strong>
              <p>
                {t(
                  kind === "stock"
                    ? "Transactions · Holdings · Yearly totals"
                    : "Monthly summary · Yearly totals · Entries",
                )}
              </p>
              <small>
                {t(
                  kind === "stock"
                    ? "Activity follows the selected dates. Holdings use the range end; historical market prices are left blank. Earlier transactions remain in balance and cost calculations."
                    : "Includes both boundary months. Opening balances carry forward from earlier months.",
                )}
              </small>
            </div>
            {(invalid || error) && (
              <p className="form-error" role="alert">
                {invalid ? t("Start must precede end") : error}
              </p>
            )}
            <div className="modal-actions">
              <button
                type="button"
                className="button secondary"
                disabled={busy}
                onClick={close}
              >
                {t("Cancel")}
              </button>
              <button className="button primary" disabled={busy || invalid}>
                <Icon name="download" size={17} />
                {t(busy ? "Exporting…" : "Choose folder and export")}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
