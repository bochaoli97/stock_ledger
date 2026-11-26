# 股票账本（Stock Ledger）

[English](README.md) | **简体中文**

本地投资账本，使用 **React + TypeScript + Electron** 桌面界面，以及 Python / SQLite 账务核心。金额由 Decimal 精确计算，数据保存在自己的电脑上。

## 直接使用 Windows 版

下载 [Windows x64 压缩包](desktop/release/StockLedger-Windows-x64.zip)，完整解压后双击 `Stock Ledger.exe`。不需要另外安装 Python 或 Node.js。

沿用原账本时，把原 `data` 文件夹复制到 exe 旁。数据库为 `data/stock_ledger.db`，每日备份在 `data/backups/`；设置里也可手动备份和导出 CSV。

## 功能

- 多账户、期初现金和持仓、全部账户合并视图。
- 十二类交易及修改、删除，自动重算现金、成本、股数、盈亏、股息。
- 股票和加密货币；数量支持八位小数。
- 实时报价、历史图表、图表滑动查看、持仓列表与个股详情；关闭实时报价可离线使用。
- Robinhood 风格数字滚动：独立数位、最短环形路径、中途接续、千分位扩缩。金额可以选中和复制。
- 可选财务收支页：月份、金额算式、自动承接余额、类别排序、多行备注。
- 深浅主题、中英文、字号，以及设置里的实际 GPU 状态、设备和渲染后端。

## 从源码运行

需要 Node.js 24 LTS 和 Python 3.12+。Python 运行服务只使用标准库，无第三方 GUI 依赖。

```bash
npm --prefix desktop ci
npm --prefix desktop run dev
```

Windows 可运行 `run_desktop.bat`；Linux / WSL 可运行 `bash run_desktop.sh`。开发版复用项目的 `data/stock_ledger.db`。通过 `STOCK_LEDGER_DB` 可指定另一个数据库；通过 `STOCK_LEDGER_PYTHON` 可指定 Python 解释器。

## 测试与打包

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
npm --prefix desktop test
npm --prefix desktop run build
npm --prefix desktop run test:browser
```

在目标操作系统中安装 PyInstaller 后，可以用 `npm --prefix desktop run package` 打包。Windows 输出包含 Python 服务的桌面程序。

详细说明和原生 Windows GPU 验证命令见 [desktop/README.md](desktop/README.md)。

## 项目结构

| 文件或目录 | 用途 |
| --- | --- |
| `desktop/src/` | React 界面、图表和独立数字动画引擎 |
| `desktop/electron/` | 桌面窗口、本地进程通信、GPU 诊断和文件对话框 |
| `desktop_backend.py` | 无 GUI 依赖的 Python 业务服务 |
| `ledger.py`、`finance.py` | 投资账务和财务收支的 Decimal 计算 |
| `storage.py` | SQLite、设置和备份 |
| `quotes.py` | 行情、历史价格和股票搜索 |
| `csv_export.py`、`i18n.py` | CSV 格式和共享翻译 |
| `test_ledger.py`、`test_desktop_backend.py` | 不需要图形环境的业务回归测试 |
| `desktop/tests/` | Electron 交互测试和冻结的原数字动画对照数据 |
