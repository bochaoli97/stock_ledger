import { useCallback, useEffect, useState, type ReactNode } from "react";
import packageInfo from "../../package.json";
import {
  api,
  type Account,
  type RuntimeInfo,
  type Settings,
  type Snapshot,
} from "../types";
import { useT } from "../i18n";
import { Icon } from "./common";

function SettingsCard({
  icon,
  title,
  description,
  children,
  className = "",
}: {
  icon: string;
  title: string;
  description: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`settings-card ${className}`}>
      <div className="settings-card-heading">
        <span className="settings-card-icon">
          <Icon name={icon} size={21} />
        </span>
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

export function SettingsPage({
  data,
  onChange,
  report,
  onNotice,
  onAddAccount,
  onEditAccount,
  onDeleteAccount,
  onPrices,
  onStudio,
  onBack,
}: {
  data: Snapshot;
  onChange(changes: Partial<Settings>): void;
  report(error: unknown): void;
  onNotice(message: string): void;
  onAddAccount(): void;
  onEditAccount(account: Account): void;
  onDeleteAccount(account: Account): void;
  onPrices(): void;
  onStudio(): void;
  onBack(): void;
}) {
  const t = useT();
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [checking, setChecking] = useState(false);
  const [runtimeError, setRuntimeError] = useState(false);
  const [backupBusy, setBackupBusy] = useState(false);
  const refreshRuntime = useCallback(async () => {
    setChecking(true);
    setRuntimeError(false);
    try {
      setRuntime(await api().runtime());
    } catch (error) {
      setRuntimeError(true);
      report(error);
    } finally {
      setChecking(false);
    }
  }, [report]);
  useEffect(() => {
    void refreshRuntime();
  }, [refreshRuntime]);
  const backup = async () => {
    setBackupBusy(true);
    try {
      const path = await api().backup();
      if (path) onNotice(`${t("Backup saved")}: ${path}`);
    } catch (error) {
      report(error);
    } finally {
      setBackupBusy(false);
    }
  };
  return (
    <section className="settings-page">
      <button className="back-link" onClick={onBack}>
        <Icon name="back" size={17} />
        {t("Back to previous page")}
      </button>
      <div className="page-heading settings-heading">
        <div>
          <p className="eyebrow">Stock Ledger</p>
          <h1>{t("Settings")}</h1>
          <p className="muted">{t("Make your ledger feel at home.")}</p>
        </div>
        <span className="settings-saved">
          <Icon name="check" size={15} />
          {t("Changes save automatically")}
        </span>
      </div>
      <div className="settings-grid">
        <SettingsCard
          icon="appearance"
          title={t("Appearance")}
          description={t("Choose a comfortable look and reading size.")}
        >
          <label className="setting-row">
            <span>
              <strong>{t("Dark mode")}</strong>
              <small>{t("A softer look for low light")}</small>
            </span>
            <input
              className="switch"
              type="checkbox"
              aria-label={t("Dark mode")}
              checked={data.settings.theme === "dark"}
              onChange={(event) =>
                onChange({ theme: event.target.checked ? "dark" : "light" })
              }
            />
          </label>
          <label className="setting-row">
            <span>{t("Language")}</span>
            <select
              aria-label={t("Language")}
              value={data.settings.language}
              onChange={(event) =>
                onChange({ language: event.target.value as "en" | "zh" })
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
              onChange={(event) => onChange({ text_size: event.target.value })}
            >
              {["Small", "Standard", "Large", "Extra large"].map((size) => (
                <option key={size} value={size}>
                  {t(size)}
                </option>
              ))}
            </select>
          </label>
        </SettingsCard>
        <SettingsCard
          icon="settings"
          title={t("Preferences")}
          description={t("Decide what appears in your daily view.")}
        >
          <label className="setting-row">
            <span>
              <strong>{t("Live prices")}</strong>
              <small>{t("Refreshes every 10 seconds")}</small>
            </span>
            <input
              className="switch"
              type="checkbox"
              checked={data.settings.live}
              onChange={(event) => onChange({ live: event.target.checked })}
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
              onChange={(event) => onChange({ finance: event.target.checked })}
            />
          </label>
          <button className="settings-action" onClick={onPrices}>
            <span>{t("Manage prices")}</span>
            <Icon name="forward" size={17} />
          </button>
        </SettingsCard>
        <SettingsCard
          icon="wallet"
          title={t("Accounts")}
          description={t("Manage your accounts and opening balances.")}
          className="settings-card-wide"
        >
          {!data.accounts.length && (
            <p className="settings-empty">{t("No accounts yet")}</p>
          )}
          <div className="settings-account-list">
            {data.accounts.map((account) => (
              <div className="settings-account" key={account.id}>
                <span className="account-avatar" aria-hidden="true">
                  {account.name.slice(0, 1).toUpperCase()}
                </span>
                <div className="settings-account-name">
                  <strong>{account.name}</strong>
                  <small>{account.broker || t("Stock account")}</small>
                </div>
                <strong className="settings-account-value">
                  {account.summary.total}
                </strong>
                <div className="row-actions">
                  <button
                    className="icon-button"
                    aria-label={`${t("Edit account")} · ${account.name}`}
                    onClick={() => onEditAccount(account)}
                  >
                    <Icon name="edit" size={17} />
                  </button>
                  <button
                    className="icon-button danger-text"
                    aria-label={`${t("Delete account")} · ${account.name}`}
                    onClick={() => onDeleteAccount(account)}
                  >
                    <Icon name="trash" size={17} />
                  </button>
                </div>
              </div>
            ))}
          </div>
          <button
            className="button secondary settings-add-account"
            onClick={onAddAccount}
          >
            <Icon name="plus" size={16} />
            {t("Add account")}
          </button>
        </SettingsCard>
        <SettingsCard
          icon="database"
          title={t("Local data")}
          description={t("Your ledger stays on this computer.")}
        >
          <p className="settings-note">
            {t(
              "Back up the entire ledger, including accounts, finance and preferences.",
            )}
          </p>
          <div className="settings-buttons">
            <button
              className="button secondary"
              disabled={backupBusy}
              onClick={backup}
            >
              <Icon name="download" size={16} />
              {t(backupBusy ? "Saving…" : "Back up database")}
            </button>
            <button
              className="button secondary"
              onClick={() => api().openDataFolder().catch(report)}
            >
              <Icon name="folder" size={16} />
              {t("Open data folder")}
            </button>
          </div>
          {runtime && (
            <p className="database-path settings-data-path">
              {runtime.database}
            </p>
          )}
          <p className="settings-note settings-export-note">
            {t("Export CSV by date from your account or Finance page.")}
          </p>
        </SettingsCard>
        <section
          className="settings-card gpu-status-card"
          data-mode={runtime?.graphics.mode ?? "unknown"}
        >
          <div className="settings-card-heading">
            <span className="settings-card-icon">
              <Icon name="monitor" size={21} />
            </span>
            <div>
              <h2>{t("Graphics acceleration")}</h2>
              <p>{t("Rendering status for this device.")}</p>
            </div>
          </div>
          <div className="graphics-status-row">
            <p className="gpu-status">
              <i />
              {t(
                checking
                  ? "Checking graphics"
                  : runtimeError || !runtime
                    ? "Graphics information unavailable"
                    : runtime.graphics.mode === "hardware"
                      ? "Hardware acceleration enabled"
                      : runtime.graphics.mode === "software"
                        ? "Software rendering"
                        : "Graphics information unavailable",
              )}
            </p>
            <button
              className="text-button"
              disabled={checking}
              onClick={refreshRuntime}
            >
              {t("Refresh graphics info")}
            </button>
          </div>
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
          <details className="runtime-details">
            <summary>{t("Rendering details")}</summary>
            {runtime && (
              <>
                <p>
                  Chromium {runtime.chrome} · Electron {runtime.electron}
                </p>
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
        </section>
      </div>
      <div className="settings-about">
        <div className="settings-about-brand">
          <Icon name="leaf" size={23} />
          <div>
            <strong>
              Stock Ledger <span>{packageInfo.version}</span>
            </strong>
            <small>{t("A local ledger for your investments.")}</small>
          </div>
        </div>
        <button className="button secondary" onClick={onStudio}>
          <Icon name="play" size={16} />
          {t("Animation studio")}
          <Icon name="forward" size={16} />
        </button>
      </div>
    </section>
  );
}
