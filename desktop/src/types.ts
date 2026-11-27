export type Summary = Record<
  | "total"
  | "cash"
  | "market_value"
  | "cost"
  | "unrealized"
  | "unrealized_pct"
  | "realized"
  | "income"
  | "net_deposits"
  | "fees"
  | "dividends"
  | "interest"
  | "change"
  | "change_pct",
  string
> & { missing: string[] };
export type Account = {
  id: number;
  name: string;
  broker: string;
  note: string;
  summary: Summary;
};
export type Holding = {
  symbol: string;
  name: string;
  quantity: string;
  quantity_raw: string;
  open: boolean;
  avg_cost: string;
  cost: string;
  price: string;
  price_raw: string;
  market_value: string;
  unrealized: string;
  unrealized_pct: string;
  realized: string;
  dividends: string;
  change: string;
  change_pct: string;
  points: [number, number][];
  live: boolean;
};
export type Transaction = {
  id: number;
  account_id: number;
  account_name: string;
  date: string;
  type: string;
  type_label: string;
  symbol: string;
  symbol2: string;
  quantity: string;
  price: string;
  fee: string;
  amount: string;
  note: string;
  quantity_text: string;
  price_text: string;
  amount_text: string;
  fee_text: string;
  cash_change: string;
  cash_after: string;
  shares_after: string;
  avg_after: string;
  realized: string;
  source_shares_after: string | null;
  source_avg_after: string | null;
};
export type Settings = {
  theme: "dark" | "light";
  language: "en" | "zh";
  text_size: string;
  live: boolean;
  finance: boolean;
};
export type Snapshot = {
  account_id: number | null;
  accounts: Account[];
  summary: Summary;
  holdings: Holding[];
  transactions: Transaction[];
  periods: {
    code: string;
    label: string;
    bounds: [string | null, string | null];
  }[];
  settings: Settings;
  finance_balance: { month: string; balance: string; net_worth: string } | null;
  updated_at: string | null;
  today: string;
  transaction_types: { code: string; label: string; fields: string[] }[];
  translations: Record<string, string>;
};
export type ChartPoint = {
  time: number;
  value: number;
  text: string;
  change: string;
  percent: string;
};
export type ChartData = {
  slots: number;
  points: ChartPoint[];
  baseline: number | null;
  live: boolean;
  value: string;
  change: string;
  percent: string;
  message: string;
};
export type Category = { id: number; kind: "income" | "expense"; name: string };
export type FinanceMonth = {
  month: string;
  opening_raw: string;
  opening: string;
  income: string;
  expenses: string;
  ending: string;
  net: string;
  entries: Record<string, { amount: string; raw: string; comment: string }>;
};
export type FinanceData = {
  categories: Category[];
  usage: Record<string, number>;
  months: FinanceMonth[];
  all_months: string[];
  summary: {
    income: string;
    expenses: string;
    net: string;
    ending: string;
    categories: Record<string, string>;
  };
};
export type Suggestion = { symbol: string; name: string; holding: string };
export type RuntimeInfo = {
  electron: string;
  chrome: string;
  gpu: Record<string, string>;
  database: string;
  graphics: {
    mode: "hardware" | "software" | "unknown";
    hardwareAcceleration: boolean;
    renderer: string;
    devices: { name: string; active: boolean }[];
  };
};
export type GoogleDriveStatus = {
  configured: boolean;
  connected: boolean;
  savedSignIn: boolean;
};
export type GoogleDriveBackup = {
  name: string;
  folderName: string;
  url: string;
};
export type LedgerAPI = {
  request<T = unknown>(
    method: string,
    params?: Record<string, unknown>,
  ): Promise<T>;
  backup(): Promise<string | null>;
  googleDriveStatus(): Promise<GoogleDriveStatus>;
  googleDriveBackup(): Promise<GoogleDriveBackup | null>;
  googleDriveDisconnect(): Promise<void>;
  exportCsv(
    kind: "stock" | "finance",
    accountId: number | null,
    range?: CsvExportRange,
  ): Promise<string[] | null>;
  openDataFolder(): Promise<void>;
  runtime(): Promise<RuntimeInfo>;
};
export type CsvExportRange = {
  period: string;
  first?: string;
  last?: string;
};
declare global {
  interface Window {
    ledger?: LedgerAPI;
  }
}
export const api = (): LedgerAPI => {
  if (!window.ledger)
    throw new Error(
      "Please open Stock Ledger with the desktop launcher. / 请通过桌面启动器打开。",
    );
  return window.ledger;
};
