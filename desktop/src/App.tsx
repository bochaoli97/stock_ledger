import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import packageInfo from "../package.json";
import {
  api,
  type Account,
  type ChartData,
  type ChartPoint,
  type Holding,
  type RuntimeInfo,
  type Settings,
  type Snapshot,
  type Transaction,
} from "./types";
import { LanguageContext, useT } from "./i18n";
import { Empty, errorText, Gain, Icon, Modal } from "./components/common";
import {
  AccountEditor,
  PriceEditor,
  TransactionEditor,
} from "./components/Editors";
import { FinancePage } from "./components/FinancePage";
import { AnimationStudio } from "./components/AnimationStudio";
import { NumberTicker, type TickerHandle } from "./components/NumberTicker";
import { AccountSelect } from "./components/AccountSelect";
import { PriceChart, Sparkline } from "./components/PriceChart";
import { compareMoney } from "./ticker/engine";

export default function App() {
  const [initial, setInitial] = useState<Snapshot | null>(null),
    [error, setError] = useState("");
  const load = useCallback(() => {
    setError("");
    try {
      api()
        .request<Snapshot>("snapshot")
        .then(setInitial)
        .catch((e) => setError(errorText(e)));
    } catch (e) {
      setError(errorText(e));
    }
  }, []);
  useEffect(load, [load]);
  if (!initial)
    return (
      <main className="startup">
        <Icon name="leaf" size={44} />
        <h1>Stock Ledger</h1>
        <p>{error || "正在打开你的账本 / Opening your ledger…"}</p>
        {error && (
          <button className="button primary" onClick={load}>
            重试 / Retry
          </button>
        )}
      </main>
    );
  return <LedgerApp initial={initial} />;
}

type Page = "overview" | "activity" | "finance" | "settings" | "studio";
type Editor =
  | { kind: "account"; initial?: Account }
  | { kind: "transaction"; initial?: Transaction; symbol?: string }
  | { kind: "prices" };
function LedgerApp({ initial }: { initial: Snapshot }) {
  const [data, setData] = useState(initial),
    [page, setPage] = useState<Page>("overview");
  const [symbol, setSymbol] = useState<string | null>(null),
    [range, setRange] = useState("1D");
  const [chart, setChart] = useState<ChartData | null>(null),
    [chartLoading, setChartLoading] = useState(false);
  const [editor, setEditor] = useState<Editor | null>(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [confirmation, setConfirmation] = useState<{
    title: string;
    message: string;
    action: () => Promise<void>;
  } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false),
    [updating, setUpdating] = useState(false);
  const account = useRef(data.account_id),
    context = useRef(0),
    settingsRevision = useRef(0);
  account.current = data.account_id;
  const report = useCallback((e: unknown) => setError(errorText(e)), []);
  const refresh = useCallback(() => {
    const aid = account.current,
      token = context.current;
    api()
      .request<Snapshot>("snapshot", { account_id: aid })
      .then((next) => {
        if (token === context.current) setData(next);
      })
      .catch(report);
  }, [report]);
  const saved = useCallback((next: Snapshot) => {
    setData(next);
    setError("");
  }, []);
  const selectAccount = async (id: number) => {
    const token = ++context.current;
    setSymbol(null);
    setPage("overview");
    setRange("1D");
    setChart(null);
    try {
      const next = await api().request<Snapshot>("account.select", {
        account_id: id,
      });
      if (token === context.current) saved(next);
    } catch (e) {
      report(e);
    }
  };
  const changeSettings = async (changes: Partial<Settings>) => {
    const revision = ++settingsRevision.current,
      previous = data.settings;
    setData((current) => ({
      ...current,
      settings: { ...current.settings, ...changes },
    }));
    try {
      const next = await api().request<Snapshot>("settings.save", {
        ...changes,
        account_id: account.current,
      });
      if (revision === settingsRevision.current) saved(next);
    } catch (e) {
      if (revision === settingsRevision.current)
        setData((current) => ({ ...current, settings: previous }));
      report(e);
    }
  };
  useEffect(() => {
    document.documentElement.dataset.theme = data.settings.theme;
    document.documentElement.lang =
      data.settings.language === "zh" ? "zh-CN" : "en";
    const zoom: Record<string, number> = {
      Small: 0.9,
      Standard: 1,
      Large: 1.1,
      "Extra large": 1.25,
    };
    document.documentElement.style.fontSize = `${16 * (zoom[data.settings.text_size] ?? 1.1)}px`;
  }, [data.settings]);
  useEffect(() => {
    if (!data.settings.live || !data.holdings.some((p) => p.open)) {
      setUpdating(false);
      return;
    }
    let cancelled = false,
      pending = false;
    const aid = data.account_id,
      token = context.current;
    const update = async () => {
      if (pending) return;
      pending = true;
      setUpdating(true);
      const revision = settingsRevision.current;
      try {
        const next = await api().request<Snapshot>("quotes.refresh", {
          account_id: aid,
        });
        if (
          !cancelled &&
          token === context.current &&
          revision === settingsRevision.current
        )
          setData(next);
      } catch {
        if (!cancelled)
          setNotice(
            data.settings.language === "zh"
              ? "行情暂不可用，稍后自动重试"
              : "Quotes unavailable. Retrying automatically.",
          );
      } finally {
        pending = false;
        if (!cancelled) setUpdating(false);
      }
    };
    update();
    const timer = setInterval(update, 10000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [
    data.account_id,
    data.settings.live,
    data.holdings
      .filter((p) => p.open)
      .map((p) => p.symbol)
      .join(","),
    data.settings.language,
  ]);
  const chartKey = `${data.account_id}:${symbol}:${range}`;
  const previousChartKey = useRef("");
  useEffect(() => {
    if (page !== "overview") return;
    let cancelled = false;
    if (previousChartKey.current !== chartKey) {
      setChart(null);
      previousChartKey.current = chartKey;
    }
    setChartLoading(true);
    api()
      .request<ChartData>("chart", {
        account_id: data.account_id,
        symbol: symbol ?? "",
        range,
      })
      .then((value) => {
        if (!cancelled) setChart(value);
      })
      .catch((e) => {
        if (!cancelled) {
          setChart(null);
          report(e);
        }
      })
      .finally(() => {
        if (!cancelled) setChartLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [data, page, symbol, range, chartKey, report]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (document.querySelector('[role="dialog"]')) return;
      if ((e.ctrlKey || e.metaKey) && e.key === "n") {
        e.preventDefault();
        if (
          account.current !== null &&
          account.current !== -1 &&
          page !== "finance"
        )
          setEditor({ kind: "transaction", symbol: symbol ?? undefined });
      }
      if (e.key === "F5") {
        e.preventDefault();
        refresh();
      }
      if (e.key === "Escape") {
        setSymbol(null);
        setPage("overview");
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [page, symbol, refresh]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 7000);
    return () => clearTimeout(timer);
  }, [notice]);
  const confirm = (
    title: string,
    message: string,
    action: () => Promise<void>,
  ) => setConfirmation({ title, message, action });
  const holding = data.holdings.find((p) => p.symbol === symbol);
  const neutral = data.settings.theme === "dark" ? "#FFFFFF" : "#111315";
  return (
    <LanguageContext.Provider
      value={{
        language: data.settings.language,
        translations: data.translations,
      }}
    >
      <Shell
        data={data}
        page={page}
        setPage={(value) => {
          setPage(value);
          setSymbol(null);
        }}
        selectAccount={selectAccount}
        onAdd={() =>
          setEditor({ kind: "transaction", symbol: symbol ?? undefined })
        }
        updating={updating}
        onSettings={() => setPage("settings")}
        onSymbol={(value) => {
          setSymbol(value);
          setPage("overview");
          setRange("1D");
        }}
      >
        {error && (
          <div className="banner error-banner" role="alert">
            <span>{error}</span>
            <button
              className="icon-button"
              onClick={() => setError("")}
              aria-label="Close"
            >
              <Icon name="close" size={16} />
            </button>
          </div>
        )}
        {notice && (
          <div className="banner notice-banner" role="status">
            <span>{notice}</span>
          </div>
        )}
        {!data.accounts.length && page === "overview" ? (
          <FirstAccount onAdd={() => setEditor({ kind: "account" })} />
        ) : page === "overview" ? (
          <>
            {symbol && (
              <button
                className="back-link"
                onClick={() => {
                  setSymbol(null);
                  setRange("1D");
                }}
              >
                <Icon name="back" size={17} />
                <Translated text="Back to portfolio" />
              </button>
            )}
            {!symbol && data.account_id === -1 && data.finance_balance && (
              <NetWorth data={data} />
            )}
            <Hero
              key={`${data.account_id}:${symbol ?? "account"}:${neutral}`}
              title={
                symbol
                  ? holding?.name && holding.name !== symbol
                    ? `${holding.name} · ${symbol}`
                    : symbol
                  : data.account_id === -1
                    ? "Net worth (all accounts)"
                    : "Portfolio"
              }
              value={symbol ? (holding?.price ?? "-") : data.summary.total}
              data={chart}
              range={range}
              onRange={setRange}
              neutral={neutral}
              loading={chartLoading}
            />
            {symbol && holding ? (
              <>
                <HoldingStats holding={holding} />
                <Activity
                  data={data}
                  symbol={symbol}
                  onEdit={(txn) =>
                    setEditor({ kind: "transaction", initial: txn })
                  }
                  onDelete={(txn) =>
                    confirm(
                      "Delete transaction",
                      "This permanently deletes the selected record.",
                      async () =>
                        saved(
                          await api().request("transaction.delete", {
                            account_id: txn.account_id,
                            id: txn.id,
                          }),
                        ),
                    )
                  }
                />
              </>
            ) : (
              <>
                <Stats summary={data.summary} />
                {data.account_id === -1 && (
                  <AccountTable
                    accounts={data.accounts}
                    onSelect={selectAccount}
                  />
                )}
                <Holdings
                  data={data}
                  onOpen={(value) => {
                    setSymbol(value);
                    setRange("1D");
                  }}
                  onPrices={() => setEditor({ kind: "prices" })}
                />
                <Activity
                  data={data}
                  compact
                  onEdit={(txn) =>
                    setEditor({ kind: "transaction", initial: txn })
                  }
                  onDelete={(txn) =>
                    confirm(
                      "Delete transaction",
                      "This permanently deletes the selected record.",
                      async () =>
                        saved(
                          await api().request("transaction.delete", {
                            account_id: txn.account_id,
                            id: txn.id,
                          }),
                        ),
                    )
                  }
                />
              </>
            )}
          </>
        ) : page === "activity" ? (
          <Activity
            data={data}
            onEdit={(txn) => setEditor({ kind: "transaction", initial: txn })}
            onDelete={(txn) =>
              confirm(
                "Delete transaction",
                "This permanently deletes the selected record.",
                async () =>
                  saved(
                    await api().request("transaction.delete", {
                      account_id: txn.account_id,
                      id: txn.id,
                    }),
                  ),
              )
            }
          />
        ) : page === "finance" ? (
          <FinancePage
            today={data.today}
            onChanged={refresh}
            confirm={confirm}
            report={report}
          />
        ) : page === "studio" ? (
          <AnimationStudio neutral={neutral} />
        ) : (
          <SettingsPage
            data={data}
            onChange={changeSettings}
            report={report}
            onNotice={setNotice}
            onAddAccount={() => setEditor({ kind: "account" })}
            onEditAccount={(a) => setEditor({ kind: "account", initial: a })}
            onPrices={() => setEditor({ kind: "prices" })}
            onStudio={() => setPage("studio")}
            onDeleteAccount={(a) =>
              confirm(
                "Delete account",
                "Delete this account and all its transactions?",
                async () => {
                  context.current++;
                  saved(
                    await api().request("account.delete", { account_id: a.id }),
                  );
                },
              )
            }
          />
        )}
      </Shell>
      {editor?.kind === "account" && (
        <AccountEditor
          snapshot={data}
          initial={editor.initial}
          onSaved={saved}
          onClose={() => setEditor(null)}
        />
      )}
      {editor?.kind === "transaction" && (
        <TransactionEditor
          snapshot={data}
          initial={editor.initial}
          symbol={editor.symbol}
          onSaved={saved}
          onClose={() => setEditor(null)}
        />
      )}
      {editor?.kind === "prices" && (
        <PriceEditor
          snapshot={data}
          onSaved={saved}
          onClose={() => setEditor(null)}
        />
      )}
      {confirmation && (
        <ConfirmDialog
          title={confirmation.title}
          message={confirmation.message}
          busy={confirmBusy}
          onClose={() => !confirmBusy && setConfirmation(null)}
          onConfirm={async () => {
            setConfirmBusy(true);
            try {
              await confirmation.action();
              setConfirmation(null);
            } catch (e) {
              report(e);
            } finally {
              setConfirmBusy(false);
            }
          }}
        />
      )}
    </LanguageContext.Provider>
  );
}

function Translated({ text }: { text: string }) {
  return <>{useT()(text)}</>;
}
function Shell({
  data,
  page,
  setPage,
  selectAccount,
  onAdd,
  updating,
  onSettings,
  onSymbol,
  children,
}: {
  data: Snapshot;
  page: Page;
  setPage(page: Page): void;
  selectAccount(id: number): void;
  onAdd(): void;
  updating: boolean;
  onSettings(): void;
  onSymbol(symbol: string): void;
  children: React.ReactNode;
}) {
  const t = useT();
  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand" onClick={() => setPage("overview")}>
          <Icon name="leaf" size={27} />
          <span>
            stock<span className="brand-light">ledger</span>
          </span>
        </button>
        <nav className="primary-nav" aria-label="Main navigation">
          <button
            className={page === "overview" ? "active" : ""}
            onClick={() => setPage("overview")}
          >
            {t("Investing")}
          </button>
          <button
            className={page === "activity" ? "active" : ""}
            onClick={() => setPage("activity")}
          >
            {t("Activity")}
          </button>
          {data.settings.finance && (
            <button
              className={page === "finance" ? "active" : ""}
              onClick={() => setPage("finance")}
            >
              {t("Finance")}
            </button>
          )}
        </nav>
        <div className="topbar-actions">
          <button
            className="icon-button mobile-add"
            aria-label={t("New transaction")}
            disabled={
              data.account_id === null ||
              data.account_id === -1 ||
              page === "finance"
            }
            onClick={onAdd}
          >
            <Icon name="plus" />
          </button>
          <AccountSelect
            accounts={data.accounts}
            value={data.account_id}
            onChange={selectAccount}
          />
          <button
            className={`icon-button ${page === "settings" ? "selected" : ""}`}
            aria-label={t("Settings")}
            onClick={onSettings}
          >
            <Icon name="settings" />
          </button>
        </div>
      </header>
      <div className="workspace">
        <main className="main-content">{children}</main>
        <aside className="sidebar">
          <div className="sidebar-heading">
            <h2>{t("Stocks")}</h2>
            <Icon name="list" size={18} />
          </div>
          {data.holdings
            .filter((p) => p.open)
            .map((p) => (
              <button
                className="stock-row"
                key={p.symbol}
                onClick={() => onSymbol(p.symbol)}
              >
                <span className="stock-name">
                  <strong>{p.symbol}</strong>
                  <small>
                    {p.quantity} {t("Shares")}
                  </small>
                </span>
                <Sparkline
                  points={p.points}
                  negative={p.change.startsWith("-")}
                />
                <span className="stock-price">
                  <strong>{p.price}</strong>
                  <small>
                    <Gain value={p.change_pct || p.change} />
                  </small>
                </span>
              </button>
            ))}
          {!data.holdings.some((p) => p.open) && (
            <p className="sidebar-empty">
              {t("Your holdings will appear here.")}
            </p>
          )}
          <div className="sidebar-footer">
            <span
              className={`live-status ${data.settings.live ? "is-live" : ""}`}
            >
              <i />
              {t(
                updating
                  ? "Updating"
                  : data.settings.live
                    ? "Live prices"
                    : "Offline",
              )}
            </span>
            {data.updated_at && (
              <small>
                {t("Updated")} {data.updated_at}
              </small>
            )}
          </div>
          <button
            className="button primary sidebar-add"
            disabled={
              data.account_id === null ||
              data.account_id === -1 ||
              page === "finance"
            }
            onClick={onAdd}
          >
            <Icon name="plus" size={18} />
            {t("New transaction")}
          </button>
        </aside>
      </div>
      <footer className="app-footer">
        <span>Stock Ledger</span>
        <span>{t("A local ledger for your investments.")}</span>
      </footer>
    </div>
  );
}

function FirstAccount({ onAdd }: { onAdd(): void }) {
  const t = useT();
  return (
    <Empty
      title={t("Create your first account")}
      message={t("Record your opening cash and holdings to get started.")}
      action={
        <button className="button primary" onClick={onAdd}>
          <Icon name="plus" size={17} />
          {t("Add account")}
        </button>
      }
    />
  );
}

function Hero({
  title,
  value,
  data,
  range,
  onRange,
  neutral,
  loading,
}: {
  title: string;
  value: string;
  data: ChartData | null;
  range: string;
  onRange(value: string): void;
  neutral: string;
  loading: boolean;
}) {
  const t = useT(),
    ticker = useRef<TickerHandle>(null),
    change = useRef<HTMLSpanElement>(null),
    period = useRef<HTMLSpanElement>(null);
  const initial = useRef(value),
    hovered = useRef<number | null>(null);
  const latest = useRef({ value, data, range });
  latest.current = { value, data, range };
  const labels: Record<string, string> = {
    "1D": "Today",
    "1W": "Past week",
    "1M": "Past month",
    "3M": "Past 3 months",
    YTD: "Year to date",
    "1Y": "Past year",
    ALL: "All time",
  };
  const update = useCallback(
    (point: ChartPoint | null, index: number | null = null) => {
      hovered.current = point === null ? null : index;
      const now = latest.current;
      ticker.current?.setText(point?.text ?? now.value, point === null);
      const delta = point?.change ?? now.data?.change ?? "",
        pct = point?.percent ?? now.data?.percent ?? "";
      if (change.current) {
        change.current.textContent = `${delta}${pct ? ` (${pct})` : ""}`;
        change.current.className = delta.startsWith("-") ? "loss" : "gain";
      }
      if (period.current)
        period.current.textContent = point ? "" : t(labels[now.range]);
    },
    [t],
  );
  useEffect(() => {
    const index = hovered.current;
    update(index === null ? null : (data?.points[index] ?? null), index);
  }, [value, data, range, update]);
  const resolvedColor = data?.change.startsWith("-")
    ? neutral === "#FFFFFF"
      ? "#FF5000"
      : "#F04E00"
    : neutral === "#FFFFFF"
      ? "#00C805"
      : "#00A30A";
  return (
    <section className="hero">
      <p className="hero-title">{t(title)}</p>
      <NumberTicker text={initial.current} neutral={neutral} ref={ticker} />
      <div className="hero-change">
        <span ref={change} />
        <span ref={period} className="muted" />
      </div>
      <PriceChart
        data={data}
        color={resolvedColor}
        onHover={update}
        loading={loading}
      />
      <div className="range-tabs" role="group" aria-label={t("Performance")}>
        {Object.keys(labels).map((key) => (
          <button
            key={key}
            aria-pressed={range === key}
            className={range === key ? "active" : ""}
            onClick={() => {
              hovered.current = null;
              onRange(key);
            }}
          >
            {key === "ALL" ? t("All") : key}
          </button>
        ))}
      </div>
    </section>
  );
}
function NetWorth({ data }: { data: Snapshot }) {
  const t = useT();
  return (
    <div className="net-worth">
      <div>
        <span>{t("Net worth")}</span>
        <strong>{data.finance_balance?.net_worth}</strong>
      </div>
      <div>
        <span>{t("Stock accounts")}</span>
        <b>{data.summary.total}</b>
      </div>
      <div>
        <span>{t("Finance")}</span>
        <b>{data.finance_balance?.balance}</b>
        <small>{data.finance_balance?.month}</small>
      </div>
    </div>
  );
}
function Stats({ summary }: { summary: Snapshot["summary"] }) {
  const t = useT();
  return (
    <section className="stats-section">
      <div className="buying-power">
        <span>{t("Buying power")}</span>
        <strong>{summary.cash}</strong>
      </div>
      <div className="stat-grid">
        {[
          ["Market value", "market_value"],
          ["Cost basis", "cost"],
          ["Unrealized P/L", "unrealized"],
          ["Realized P/L", "realized"],
          ["Investment income", "income"],
          ["Net deposits", "net_deposits"],
          ["Commissions & fees", "fees"],
        ].map(([label, key]) => (
          <div className="stat" key={key}>
            <span>{t(label)}</span>
            <strong>
              <Gain value={summary[key as "total"]} />
            </strong>
            {key === "unrealized" && <small>{summary.unrealized_pct}</small>}
          </div>
        ))}
      </div>
    </section>
  );
}
function HoldingStats({ holding: p }: { holding: Holding }) {
  const t = useT();
  return (
    <div className="stat-grid holding-stats">
      {[
        ["Shares", p.quantity],
        ["Market value", p.market_value],
        ["Average cost", p.avg_cost],
        ["Unrealized P/L", p.unrealized],
        ["Realized P/L", p.realized],
        ["Dividends", p.dividends],
      ].map(([label, value]) => (
        <div className="stat" key={label}>
          <span>{t(label)}</span>
          <strong>
            <Gain value={value} />
          </strong>
        </div>
      ))}
    </div>
  );
}
function AccountTable({
  accounts,
  onSelect,
}: {
  accounts: Account[];
  onSelect(id: number): void;
}) {
  const t = useT();
  return (
    <section className="section">
      <div className="section-heading">
        <h2>{t("Account details")}</h2>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>{t("Account")}</th>
              <th>{t("Cash")}</th>
              <th>{t("Market value")}</th>
              <th>{t("Net worth")}</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => (
              <tr
                className="clickable"
                key={a.id}
                onClick={() => onSelect(a.id)}
              >
                <td>
                  <strong>{a.name}</strong>
                  <small>{a.broker}</small>
                </td>
                <td>{a.summary.cash}</td>
                <td>{a.summary.market_value}</td>
                <td>{a.summary.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Holdings({
  data,
  onOpen,
  onPrices,
}: {
  data: Snapshot;
  onOpen(symbol: string): void;
  onPrices(): void;
}) {
  const t = useT(),
    [closed, setClosed] = useState(false),
    [sort, setSort] = useState({ key: "symbol", direction: 1 });
  const rows = useMemo(
    () =>
      data.holdings
        .filter((p) => closed || p.open)
        .sort((a, b) => {
          const x = a[sort.key as keyof Holding] as string,
            y = b[sort.key as keyof Holding] as string;
          return (
            (sort.key === "symbol"
              ? x.localeCompare(y)
              : x === "-"
                ? -1
                : y === "-"
                  ? 1
                  : compareMoney(x, y)) * sort.direction
          );
        }),
    [data.holdings, closed, sort],
  );
  return (
    <section className="section">
      <div className="section-heading">
        <h2>{t("Holdings")}</h2>
        <button className="text-button" onClick={onPrices}>
          {t("Manage prices")}
        </button>
      </div>
      <label className="checkbox-label show-closed">
        <input
          type="checkbox"
          checked={closed}
          onChange={(e) => setClosed(e.target.checked)}
        />
        {t("Show closed positions")}
      </label>
      {!rows.length ? (
        <Empty title={t("No holdings yet")} />
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {[
                  ["Symbol", "symbol"],
                  ["Shares", "quantity"],
                  ["Average cost", "avg_cost"],
                  ["Price", "price"],
                  ["Market value", "market_value"],
                  ["Unrealized P/L", "unrealized"],
                ].map(([label, key]) => (
                  <th key={key}>
                    <button
                      onClick={() =>
                        setSort((s) => ({
                          key,
                          direction: s.key === key ? -s.direction : 1,
                        }))
                      }
                    >
                      {t(label)}
                      {sort.key === key && (
                        <Icon
                          name={sort.direction === 1 ? "up" : "down"}
                          size={12}
                        />
                      )}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.symbol} onDoubleClick={() => onOpen(p.symbol)}>
                  <td>
                    <button
                      className="symbol-link"
                      onClick={() => onOpen(p.symbol)}
                    >
                      {p.symbol}
                    </button>
                    {p.name !== p.symbol && <small>{p.name}</small>}
                  </td>
                  <td>{p.quantity}</td>
                  <td>{p.avg_cost}</td>
                  <td>{p.price}</td>
                  <td>{p.market_value}</td>
                  <td>
                    <Gain value={p.unrealized} />
                    <small>
                      <Gain value={p.unrealized_pct} />
                    </small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Activity({
  data,
  symbol,
  compact = false,
  onEdit,
  onDelete,
}: {
  data: Snapshot;
  symbol?: string;
  compact?: boolean;
  onEdit(txn: Transaction): void;
  onDelete(txn: Transaction): void;
}) {
  const t = useT();
  const [query, setQuery] = useState(""),
    [type, setType] = useState(""),
    [selectedSymbol, setSelectedSymbol] = useState(""),
    [period, setPeriod] = useState("ALL");
  const [first, setFirst] = useState(""),
    [last, setLast] = useState(""),
    [page, setPage] = useState(0),
    [reverse, setReverse] = useState(false);
  useEffect(
    () => setPage(0),
    [query, type, selectedSymbol, period, first, last, symbol, data.account_id],
  );
  const bounds =
    period === "CUSTOM"
      ? [first, last]
      : (data.periods.find((p) => p.code === period)?.bounds ?? []);
  const rows = data.transactions.filter(
    (row) =>
      (!symbol || row.symbol === symbol || row.symbol2 === symbol) &&
      (!selectedSymbol ||
        row.symbol === selectedSymbol ||
        row.symbol2 === selectedSymbol) &&
      (!type || row.type === type) &&
      (!query ||
        `${row.symbol} ${row.symbol2} ${row.note}`
          .toLowerCase()
          .includes(query.toLowerCase())) &&
      (!bounds[0] || row.date >= bounds[0]) &&
      (!bounds[1] || row.date <= bounds[1]),
  );
  if (reverse) rows.reverse();
  const pageSize = compact ? 8 : 60,
    pages = Math.max(1, Math.ceil(rows.length / pageSize)),
    actualPage = Math.min(page, pages - 1);
  const shown = rows.slice(actualPage * pageSize, (actualPage + 1) * pageSize);
  return (
    <section className="section activity">
      <div className="section-heading">
        <h2>{t(symbol ? "Transactions" : "Activity")}</h2>
        <span className="muted count">{rows.length}</span>
      </div>
      {!compact && (
        <div className="filters activity-filters">
          <label className="search-input">
            <Icon name="search" size={16} />
            <input
              aria-label={t("Search symbols or notes")}
              placeholder={t("Search symbols or notes")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <select
            aria-label={t("All types")}
            value={type}
            onChange={(e) => setType(e.target.value)}
          >
            <option value="">{t("All types")}</option>
            {data.transaction_types.map((type) => (
              <option value={type.code} key={type.code}>
                {type.label}
              </option>
            ))}
          </select>
          {!symbol && (
            <select
              aria-label={t("All symbols")}
              value={selectedSymbol}
              onChange={(e) => setSelectedSymbol(e.target.value)}
            >
              <option value="">{t("All symbols")}</option>
              {[
                ...new Set(
                  data.transactions
                    .flatMap((t) => [t.symbol, t.symbol2])
                    .filter(Boolean),
                ),
              ]
                .sort()
                .map((s) => (
                  <option key={s}>{s}</option>
                ))}
            </select>
          )}
          <select
            aria-label={t("All time")}
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          >
            {data.periods.map((p) => (
              <option key={p.code} value={p.code}>
                {p.label}
              </option>
            ))}
            <option value="CUSTOM">{t("Custom range")}</option>
          </select>
          {period === "CUSTOM" && (
            <>
              <input
                type="date"
                aria-label={t("From")}
                value={first}
                onChange={(e) => setFirst(e.target.value)}
              />
              <input
                type="date"
                aria-label={t("To")}
                value={last}
                onChange={(e) => setLast(e.target.value)}
              />
            </>
          )}
        </div>
      )}
      {!shown.length ? (
        <Empty
          title={t("No transactions found")}
          message={t("Try changing the filters, or add a transaction.")}
        />
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>
                  <button onClick={() => setReverse((v) => !v)}>
                    {t("Date")}
                    <Icon name={reverse ? "up" : "down"} size={12} />
                  </button>
                </th>
                {data.account_id === -1 && <th>{t("Account")}</th>}
                <th>{t("Type")}</th>
                <th>{t("Symbol")}</th>
                <th>{t("Quantity")}</th>
                <th>{t("Price")}</th>
                <th>{t("Cash change")}</th>
                <th>{t(symbol ? "Shares after" : "Cash balance")}</th>
                {symbol && <th>{t("Average after")}</th>}
                <th>{t("Note")}</th>
                <th aria-label={t("Edit")} />
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr
                  key={row.id}
                  onDoubleClick={() => data.account_id !== -1 && onEdit(row)}
                >
                  <td>{row.date}</td>
                  {data.account_id === -1 && <td>{row.account_name}</td>}
                  <td>{row.type_label}</td>
                  <td>
                    <strong>{row.symbol}</strong>
                    {row.symbol2 && <small>{row.symbol2}</small>}
                  </td>
                  <td>{Number(row.quantity) ? row.quantity_text : "—"}</td>
                  <td>
                    {["BUY", "SELL", "SHARES_IN", "DISTRIBUTION"].includes(
                      row.type,
                    )
                      ? row.type === "DISTRIBUTION"
                        ? `${row.price}%`
                        : row.price_text
                      : "—"}
                  </td>
                  <td>
                    <Gain value={row.cash_change} />
                  </td>
                  <td>
                    {symbol
                      ? symbol === row.symbol
                        ? (row.source_shares_after ?? row.shares_after)
                        : row.shares_after
                      : row.cash_after}
                  </td>
                  {symbol && (
                    <td>
                      {symbol === row.symbol
                        ? (row.source_avg_after ?? row.avg_after)
                        : row.avg_after}
                    </td>
                  )}
                  <td className="note-cell" title={row.note}>
                    {row.note || "—"}
                  </td>
                  <td>
                    <div className="row-actions">
                      <button
                        className="icon-button"
                        aria-label={t("Edit transaction")}
                        disabled={data.account_id === -1}
                        onClick={() => onEdit(row)}
                      >
                        <Icon name="edit" size={15} />
                      </button>
                      <button
                        className="icon-button"
                        aria-label={t("Delete transaction")}
                        disabled={data.account_id === -1}
                        onClick={() => onDelete(row)}
                      >
                        <Icon name="trash" size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <div className="pagination">
          <button
            className="icon-button"
            aria-label="Previous page"
            disabled={actualPage === 0}
            onClick={() => setPage((p) => p - 1)}
          >
            <Icon name="back" size={16} />
          </button>
          <span>
            {actualPage + 1} / {pages}
          </span>
          <button
            className="icon-button next-page"
            aria-label="Next page"
            disabled={actualPage + 1 >= pages}
            onClick={() => setPage((p) => p + 1)}
          >
            <Icon name="back" size={16} />
          </button>
        </div>
      )}
    </section>
  );
}

function SettingsPage({
  data,
  onChange,
  report,
  onNotice,
  onAddAccount,
  onEditAccount,
  onDeleteAccount,
  onPrices,
  onStudio,
}: {
  data: Snapshot;
  onChange(changes: Partial<Settings>): void;
  report(error: unknown): void;
  onNotice(message: string): void;
  onAddAccount(): void;
  onEditAccount(a: Account): void;
  onDeleteAccount(a: Account): void;
  onPrices(): void;
  onStudio(): void;
}) {
  const t = useT(),
    [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  useEffect(() => {
    api().runtime().then(setRuntime).catch(report);
  }, [report]);
  const native = async (fn: () => Promise<unknown>, message: string) => {
    try {
      const result = await fn();
      if (result)
        onNotice(
          `${t(message)}: ${Array.isArray(result) ? result.join(", ") : result}`,
        );
    } catch (e) {
      report(e);
    }
  };
  return (
    <section className="settings-page">
      <div className="page-heading">
        <h1>{t("Settings")}</h1>
      </div>
      <div className="settings-group">
        <h2>{t("Appearance")}</h2>
        <label className="setting-row">
          <span>{t("Dark mode")}</span>
          <input
            className="switch"
            type="checkbox"
            checked={data.settings.theme === "dark"}
            onChange={(e) =>
              onChange({ theme: e.target.checked ? "dark" : "light" })
            }
          />
        </label>
        <label className="setting-row">
          <span>{t("Language")}</span>
          <select
            aria-label={t("Language")}
            value={data.settings.language}
            onChange={(e) =>
              onChange({ language: e.target.value as "en" | "zh" })
            }
          >
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </label>
        <label className="setting-row">
          <span>{t("Text size")}</span>
          <select
            aria-label={t("Text size")}
            value={data.settings.text_size}
            onChange={(e) => onChange({ text_size: e.target.value })}
          >
            {["Small", "Standard", "Large", "Extra large"].map((key) => (
              <option key={key} value={key}>
                {t(key)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <section
        className="settings-group gpu-status-card"
        data-mode={runtime?.graphics.mode ?? "unknown"}
      >
        <div className="section-heading compact">
          <h2>{t("Graphics acceleration")}</h2>
          <button
            className="text-button"
            disabled={!runtime}
            onClick={() => {
              setRuntime(null);
              api().runtime().then(setRuntime).catch(report);
            }}
          >
            {t("Refresh graphics info")}
          </button>
        </div>
        <p className="gpu-status">
          <i />
          {t(
            !runtime
              ? "Checking graphics"
              : runtime.graphics.mode === "hardware"
                ? "Hardware acceleration enabled"
                : runtime.graphics.mode === "software"
                  ? "Software rendering"
                  : "Graphics information unavailable",
          )}
        </p>
        {runtime && (
          <dl className="gpu-info">
            <div>
              <dt>{t("Graphics device")}</dt>
              <dd>
                {runtime.graphics.devices
                  .map((device) => device.name)
                  .join(" · ") || t("Graphics information unavailable")}
              </dd>
            </div>
            <div>
              <dt>{t("Renderer")}</dt>
              <dd>
                {runtime.graphics.renderer ||
                  t("Selected automatically by the system")}
              </dd>
            </div>
            <div>
              <dt>{t("GPU compositing")}</dt>
              <dd>{runtime.gpu.gpu_compositing ?? "unknown"}</dd>
            </div>
          </dl>
        )}
      </section>
      <div className="settings-group">
        <h2>{t("Accounts")}</h2>
        {data.accounts.map((a) => (
          <div className="setting-row" key={a.id}>
            <div>
              <strong>{a.name}</strong>
              <small>{a.broker}</small>
            </div>
            <div className="row-actions">
              <button
                className="icon-button"
                aria-label={t("Edit account")}
                onClick={() => onEditAccount(a)}
              >
                <Icon name="edit" size={17} />
              </button>
              <button
                className="icon-button"
                aria-label={t("Delete account")}
                onClick={() => onDeleteAccount(a)}
              >
                <Icon name="trash" size={17} />
              </button>
            </div>
          </div>
        ))}
        <button className="text-button" onClick={onAddAccount}>
          <Icon name="plus" size={16} />
          {t("Add account")}
        </button>
      </div>
      <div className="settings-group">
        <label className="setting-row">
          <span>
            <strong>{t("Live prices")}</strong>
            <small>{t("Refreshes every 10 seconds")}</small>
          </span>
          <input
            className="switch"
            type="checkbox"
            checked={data.settings.live}
            onChange={(e) => onChange({ live: e.target.checked })}
          />
        </label>
        <label className="setting-row">
          <span>
            <strong>{t("Finance page")}</strong>
            <small>{t("Track money outside your brokerage accounts")}</small>
          </span>
          <input
            className="switch"
            type="checkbox"
            checked={data.settings.finance}
            onChange={(e) => onChange({ finance: e.target.checked })}
          />
        </label>
        <button className="text-button" onClick={onPrices}>
          {t("Manage prices")}
        </button>
      </div>
      <div className="settings-group">
        <h2>{t("Local data")}</h2>
        <div className="settings-buttons">
          <button
            className="button secondary"
            onClick={() => native(() => api().backup(), "Backup saved")}
          >
            {t("Back up database")}
          </button>
          <button
            className="button secondary"
            disabled={data.account_id === null || data.account_id === -1}
            onClick={() =>
              native(
                () => api().exportCsv("stock", data.account_id),
                "CSV exported",
              )
            }
          >
            {t("Export account CSV")}
          </button>
          {data.settings.finance && (
            <button
              className="button secondary"
              onClick={() =>
                native(
                  () => api().exportCsv("finance", data.account_id),
                  "CSV exported",
                )
              }
            >
              {t("Export finance CSV")}
            </button>
          )}
          <button
            className="button secondary"
            onClick={() => api().openDataFolder().catch(report)}
          >
            {t("Open data folder")}
          </button>
        </div>
      </div>
      <div className="settings-group">
        <h2>{t("About")}</h2>
        <p className="muted">Stock Ledger {packageInfo.version}</p>
        <button className="text-button" onClick={onStudio}>
          {t("Animation studio")}
        </button>
        <details className="runtime-details">
          <summary>{t("Rendering details")}</summary>
          {runtime && (
            <>
              <p>
                Chromium {runtime.chrome} · Electron {runtime.electron}
              </p>
              <p className="database-path">{runtime.database}</p>
              <dl>
                {Object.entries(runtime.gpu).map(([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
        </details>
      </div>
    </section>
  );
}
function ConfirmDialog({
  title,
  message,
  busy,
  onClose,
  onConfirm,
}: {
  title: string;
  message: string;
  busy: boolean;
  onClose(): void;
  onConfirm(): void;
}) {
  const t = useT();
  return (
    <Modal title={t(title)} onClose={onClose}>
      <p className="confirm-message">{t(message)}</p>
      <div className="modal-actions">
        <button className="button secondary" disabled={busy} onClick={onClose}>
          {t("Cancel")}
        </button>
        <button className="button danger" disabled={busy} onClick={onConfirm}>
          {t(busy ? "Loading" : "Delete")}
        </button>
      </div>
    </Modal>
  );
}
