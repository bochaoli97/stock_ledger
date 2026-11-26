import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  api,
  type Category,
  type FinanceData,
  type FinanceMonth,
} from "../types";
import { useT } from "../i18n";
import { Empty, errorText, Field, Gain, Icon, Modal } from "./common";
import { CsvExportButton } from "./CsvExport";

type Confirm = (
  title: string,
  message: string,
  action: () => Promise<void>,
) => void;
export function FinancePage({
  today,
  onChanged,
  confirm,
  report,
  onNotice,
}: {
  today: string;
  onChanged(): void;
  confirm: Confirm;
  report(error: unknown): void;
  onNotice(message: string): void;
}) {
  const t = useT();
  const [data, setData] = useState<FinanceData | null>(null),
    [period, setPeriod] = useState("ALL");
  const [first, setFirst] = useState(""),
    [last, setLast] = useState("");
  const [editor, setEditor] = useState<FinanceMonth | "new" | null>(null),
    [categories, setCategories] = useState(false);
  const [revision, setRevision] = useState(0),
    [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setRevision((v) => v + 1);
    onChanged();
  }, [onChanged]);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api()
      .request<FinanceData>("finance.snapshot", { period, first, last })
      .then((value) => {
        if (!cancelled) setData(value);
      })
      .catch((e) => {
        if (!cancelled) report(e);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [period, first, last, revision, report]);
  const years = [
    ...new Set(data?.all_months.map((m) => m.slice(0, 4)) ?? []),
  ].reverse();
  return (
    <section className="finance-page" aria-busy={loading}>
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            {t("Income")} & {t("Expenses")}
          </p>
          <h1>{t("Finance")}</h1>
        </div>
        <div className="page-actions">
          <CsvExportButton
            kind="finance"
            scope={t("Finance")}
            initialRange={{ period, first, last }}
            onNotice={onNotice}
            periods={[
              { code: "ALL", label: "All time" },
              { code: "3M", label: "Past 3 months" },
              { code: "6M", label: "Past 6 months" },
              { code: "1Y", label: "Past year" },
              ...years.map((year) => ({ code: year, label: year })),
            ]}
          />
          <button className="button primary" onClick={() => setEditor("new")}>
            <Icon name="plus" size={17} />
            {t("Add month")}
          </button>
        </div>
      </div>
      <div className="stat-grid finance-stats">
        {[
          ["Income", "income"],
          ["Expenses", "expenses"],
          ["Net cash flow", "net"],
          ["Ending balance", "ending"],
        ].map(([label, key]) => (
          <div className="stat" key={key}>
            <span>{t(label)}</span>
            <strong>
              <Gain value={data?.summary[key as "income"] ?? "-"} />
            </strong>
          </div>
        ))}
      </div>
      <div className="section-heading">
        <div className="filters">
          <select
            aria-label={t("All time")}
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          >
            {[
              ["ALL", "All time"],
              ["3M", "Past 3 months"],
              ["6M", "Past 6 months"],
              ["1Y", "Past year"],
              ...years.map((y) => [y, y]),
              ["CUSTOM", "Custom range"],
            ].map(([code, label]) => (
              <option key={code} value={code}>
                {t(label)}
              </option>
            ))}
          </select>
          {period === "CUSTOM" && (
            <>
              <input
                type="month"
                aria-label={t("From")}
                value={first}
                onChange={(e) => setFirst(e.target.value)}
              />
              <input
                type="month"
                aria-label={t("To")}
                value={last}
                onChange={(e) => setLast(e.target.value)}
              />
            </>
          )}
        </div>
        <button
          className="button secondary"
          onClick={() => setCategories(true)}
        >
          {t("Manage categories")}
        </button>
      </div>
      {!data?.months.length ? (
        <Empty
          title={t("No months yet")}
          message={t("Add a month to start tracking income and expenses.")}
        />
      ) : (
        <div className="table-scroll">
          <table className="finance-table">
            <thead>
              <tr>
                <th>{t("Month")}</th>
                <th>{t("Opening balance")}</th>
                {data.categories.map((c) => (
                  <th key={c.id}>{c.name}</th>
                ))}
                <th>{t("Income")}</th>
                <th>{t("Expenses")}</th>
                <th>{t("Ending balance")}</th>
                <th aria-label={t("Edit")} />
              </tr>
            </thead>
            <tbody>
              {[...data.months].reverse().map((month) => (
                <tr key={month.month} onDoubleClick={() => setEditor(month)}>
                  <td>{month.month}</td>
                  <td>{month.opening}</td>
                  {data.categories.map((c) => (
                    <td
                      key={c.id}
                      title={
                        month.entries[c.id]?.comment || month.entries[c.id]?.raw
                      }
                    >
                      {month.entries[c.id]?.amount ?? "—"}
                      {month.entries[c.id]?.comment && (
                        <span className="comment-mark" />
                      )}
                    </td>
                  ))}
                  <td>{month.income}</td>
                  <td>{month.expenses}</td>
                  <td>{month.ending}</td>
                  <td>
                    <div className="row-actions">
                      <button
                        className="icon-button"
                        aria-label={t("Edit month")}
                        onClick={() => setEditor(month)}
                      >
                        <Icon name="edit" size={16} />
                      </button>
                      <button
                        className="icon-button"
                        aria-label={t("Delete month")}
                        onClick={() =>
                          confirm(
                            t("Delete month"),
                            `${month.month} — ${t("This permanently deletes the selected record.")}`,
                            async () => {
                              await api().request("finance.month.delete", {
                                month: month.month,
                              });
                              reload();
                            },
                          )
                        }
                      >
                        <Icon name="trash" size={16} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th>{t("Total")}</th>
                <td />
                <>
                  {data.categories.map((c) => (
                    <td key={c.id}>
                      {data.summary.categories[c.id] ?? "$0.00"}
                    </td>
                  ))}
                </>
                <td>{data.summary.income}</td>
                <td>{data.summary.expenses}</td>
                <td>{data.summary.ending}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {editor && data && (
        <MonthEditor
          initial={editor === "new" ? undefined : editor}
          today={today}
          categories={data.categories}
          onClose={() => setEditor(null)}
          onSaved={reload}
        />
      )}
      {categories && data && (
        <CategoryEditor
          data={data}
          onClose={() => setCategories(false)}
          onSaved={reload}
        />
      )}
    </section>
  );
}

function MonthEditor({
  initial,
  categories,
  today,
  onClose,
  onSaved,
}: {
  initial?: FinanceMonth;
  categories: Category[];
  today: string;
  onClose(): void;
  onSaved(): void;
}) {
  const t = useT();
  const [month, setMonth] = useState(initial?.month ?? today.slice(0, 7)),
    [opening, setOpening] = useState(initial?.opening_raw ?? "");
  const [entries, setEntries] = useState<
    Record<string, { raw: string; comment: string }>
  >(
    Object.fromEntries(
      categories.map((c) => [
        c.id,
        {
          raw: initial?.entries[c.id]?.raw ?? "",
          comment: initial?.entries[c.id]?.comment ?? "",
        },
      ]),
    ),
  );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api().request("finance.month.save", {
        month,
        original_month: initial?.month,
        opening,
        entries,
      });
      onSaved();
      onClose();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={t(initial ? "Edit month" : "Add month")}
      onClose={() => !busy && onClose()}
      wide
    >
      <form className="editor-form" onSubmit={save}>
        <div className="form-grid">
          <Field label={t("Month")}>
            <input
              type="month"
              required
              readOnly={!!initial}
              value={month}
              onChange={(e) => setMonth(e.target.value)}
            />
          </Field>
          <Field
            label={t("Opening balance")}
            hint={t("Carry forward automatically")}
          >
            <input
              inputMode="decimal"
              value={opening}
              placeholder="—"
              onChange={(e) => setOpening(e.target.value)}
            />
          </Field>
        </div>
        {(["income", "expense"] as const).map((kind) => (
          <div key={kind}>
            <h3>{t(kind === "income" ? "Income" : "Expenses")}</h3>
            {categories
              .filter((c) => c.kind === kind)
              .map((c) => (
                <div className="form-grid" key={c.id}>
                  <Field label={c.name}>
                    <input
                      inputMode="text"
                      placeholder="1250.50 + 1250.50"
                      value={entries[c.id]?.raw ?? ""}
                      onChange={(e) =>
                        setEntries((rows) => ({
                          ...rows,
                          [c.id]: { ...rows[c.id], raw: e.target.value },
                        }))
                      }
                    />
                  </Field>
                  <Field label={t("Comment")}>
                    <textarea
                      rows={2}
                      value={entries[c.id]?.comment ?? ""}
                      onChange={(e) =>
                        setEntries((rows) => ({
                          ...rows,
                          [c.id]: { ...rows[c.id], comment: e.target.value },
                        }))
                      }
                    />
                  </Field>
                </div>
              ))}
          </div>
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
            disabled={busy}
            onClick={onClose}
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

function CategoryEditor({
  data,
  onClose,
  onSaved,
}: {
  data: FinanceData;
  onClose(): void;
  onSaved(): void;
}) {
  const t = useT();
  type Item = { id: number | null; name: string };
  const [groups, setGroups] = useState<Record<"income" | "expense", Item[]>>({
    income: data.categories.filter((c) => c.kind === "income"),
    expense: data.categories.filter((c) => c.kind === "expense"),
  });
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [acknowledged, setAcknowledged] = useState(false);
  const deletedUsed = data.categories.some(
    (c) => !groups[c.kind].some((i) => i.id === c.id) && data.usage[c.id] > 0,
  );
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (deletedUsed && !acknowledged) return;
    setBusy(true);
    try {
      await api().request("finance.categories.save", groups);
      onSaved();
      onClose();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const move = (kind: "income" | "expense", index: number, delta: number) =>
    setGroups((g) => {
      const list = [...g[kind]],
        other = index + delta;
      [list[index], list[other]] = [list[other], list[index]];
      return { ...g, [kind]: list };
    });
  return (
    <Modal
      title={t("Manage categories")}
      onClose={() => !busy && onClose()}
      wide
    >
      <form className="editor-form" onSubmit={save}>
        {(["income", "expense"] as const).map((kind) => (
          <div key={kind}>
            <div className="section-heading compact">
              <h3>{t(kind === "income" ? "Income" : "Expenses")}</h3>
              <button
                type="button"
                className="text-button"
                onClick={() =>
                  setGroups((g) => ({
                    ...g,
                    [kind]: [...g[kind], { id: null, name: "" }],
                  }))
                }
              >
                <Icon name="plus" size={16} />
                {t("Add category")}
              </button>
            </div>
            {groups[kind].map((item, i) => (
              <div className="category-row" key={item.id ?? `new-${i}`}>
                <input
                  required
                  aria-label={t("Name")}
                  value={item.name}
                  onChange={(e) =>
                    setGroups((g) => ({
                      ...g,
                      [kind]: g[kind].map((c, j) =>
                        i === j ? { ...c, name: e.target.value } : c,
                      ),
                    }))
                  }
                />
                <button
                  type="button"
                  className="icon-button"
                  disabled={i === 0}
                  aria-label={t("Move up")}
                  onClick={() => move(kind, i, -1)}
                >
                  <Icon name="up" size={16} />
                </button>
                <button
                  type="button"
                  className="icon-button"
                  disabled={i === groups[kind].length - 1}
                  aria-label={t("Move down")}
                  onClick={() => move(kind, i, 1)}
                >
                  <Icon name="down" size={16} />
                </button>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={t("Delete")}
                  onClick={() => {
                    setGroups((g) => ({
                      ...g,
                      [kind]: g[kind].filter((_, j) => i !== j),
                    }));
                    setAcknowledged(false);
                  }}
                >
                  <Icon name="trash" size={16} />
                </button>
              </div>
            ))}
          </div>
        ))}
        {deletedUsed && (
          <label className="warning checkbox-label">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />
            {t("Deleting categories also deletes their entries.")}
          </label>
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
          <button
            className="button primary"
            disabled={busy || (deletedUsed && !acknowledged)}
          >
            {t("Save")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
