# 股票账本（Stock Ledger）

[English](README.md) | **简体中文**

本地投资账本，使用 **React + TypeScript + Electron** 桌面界面，以及 Python / SQLite 账务核心。金额由 Decimal 精确计算，数据保存在自己的电脑上。

## 直接使用 Windows 版

下载 [Windows x64 压缩包](desktop/release/StockLedger-Windows-x64.zip)，完整解压后双击 `Stock Ledger.exe`。不需要另外安装 Python 或 Node.js。

沿用原账本时，把原 `data` 文件夹复制到 exe 旁。数据库为 `data/stock_ledger.db`，每日备份在 `data/backups/`；设置里可手动备份，账户页和财务收支页可按时间范围导出 CSV。

## 功能

- 多账户、期初现金和持仓、全部账户合并视图。
- 十二类交易及修改、删除，自动重算现金、成本、股数、盈亏、股息。
- 股票和加密货币；数量支持八位小数。
- 实时报价、历史图表、图表滑动查看、持仓列表与个股详情；关闭实时报价可离线使用。
- Robinhood 风格数字滚动：独立数位、最短环形路径、中途接续、千分位扩缩。金额可以选中和复制。
- 可选财务收支页：月份、金额算式、自动承接余额、类别排序、多行备注。
- 深浅主题、中英文、字号，以及设置里的实际 GPU 状态、设备和渲染后端。
- 账户概览／交易记录页导出账户 CSV，财务收支页导出收支 CSV；支持全部时间、近期、指定年份和自定义范围，弹窗会沿用页面的时间筛选。

账户 CSV 包括交易明细、期末持仓和年度汇总；财务 CSV 包括月度汇总、年度汇总和收支明细。时间边界均包含在内，可以只填开始或结束时间。筛选不会丢失之前的交易成本或月份余额；历史持仓截至所选结束日期，历史行情价格与依赖它的市值／未实现盈亏留空。

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

## 在 WSL 中一键打包 Windows 版

首次准备：

1. 使用 Windows 上的 WSL，保持 Windows 程序互操作开启；在 WSL 终端运行 `powershell.exe -NoProfile -Command 'Write-Output OK'` 应能显示 `OK`。
2. 在 **Windows** 安装 Python 3.12 或更新版本，包含 pip 与 venv。可以先在 PowerShell 中用 `py -3 --version` 验证。WSL 的 Linux Python 不可替代 Windows Python。
3. 首次构建需要联网下载 npm、PyInstaller 和 Electron 依赖。Windows Node.js 24+ 可自行安装；未安装或版本过旧时，脚本会下载并校验官方便携版，不修改全局 Node.js。

在 WSL 里进入仓库根目录，只需运行：

```bash
bash build_windows.sh
```

脚本会自动识别项目位置，支持项目放在 WSL 的 `/home/...` 或 `/mnt/c/...`，也支持路径含空格。它通过 Windows PowerShell 调用 Windows Python，在 Windows 临时目录复制程序源码、创建独立 Python 环境、安装依赖、运行测试、构建前端、用 PyInstaller 打包 Python 服务，再用 Electron Builder 生成 Windows 应用。整个流程不使用 WSL 的 Linux `node_modules`，也不复制用户账本。

最后会启动打包后的 exe，用临时数据库验证中文通信、SQLite 和内置 Python，然后生成：

- `desktop/release/StockLedger-Windows-x64.zip`：常见 x64 Windows 的完整可运行压缩包；ARM64 环境名称为 `StockLedger-Windows-arm64.zip`。
- `desktop/test-results/windows-native/report.json`：构建状态、工具版本、exe 路径和 ZIP 的 SHA-256。
- `desktop/test-results/windows-native/logs/`、`tests/`：各步骤日志、窗口测试截图和图形信息。

**完整解压 ZIP 后，双击其中的 `StockLedger/Stock Ledger.exe`。** 接收程序的电脑无需安装 Node.js 或 Python。不要只复制 exe，运行需要同目录的资源文件。沿用账本时，再将原 `data` 文件夹复制到 exe 旁；发布压缩包会排除数据库和用户数据。

常用参数：

```bash
# 手动指定 Windows Python，可使用 WSL 路径或带引号的 Windows 路径
bash build_windows.sh --python '/mnt/c/path/to/python.exe'

# 复用专用 Windows 构建目录，保留下载缓存，适合重复打包
bash build_windows.sh --work-dir 'C:\Users\your-name\AppData\Local\Temp\StockLedgerBuild'

# 跳过业务、单元和开发窗口测试，仍构建并验证最终 exe
bash build_windows.sh --skip-tests

# 额外要求 Windows 测试窗口启用 GPU 硬件合成
bash build_windows.sh --require-gpu

bash build_windows.sh --help
```

`--work-dir` 只能指定空目录或脚本已标记的专用构建目录。失败时命令会返回非零状态，报告和日志保留错误原因；只有构建、exe 验证和 ZIP 校验全部成功后，才会报告完成。默认不强制 GPU，软件渲染环境也可打包。

常见问题：找不到 Windows Python 时使用 `--python`；`powershell.exe` 无法启动时检查 WSL 的 `[interop] enabled` 配置并从 Windows 运行 `wsl --shutdown` 后重新打开；依赖下载失败时查看日志并检查 Windows 侧的网络或代理配置。

PyInstaller 必须在目标系统运行（[官方说明](https://www.pyinstaller.org/en/stable/)），这里通过 [WSL 的 Windows 程序互操作](https://learn.microsoft.com/en-us/windows/wsl/filesystems)完成 Windows 原生构建。

如需 NSIS 安装包或单文件 portable 启动包，请在 Windows 的 Node.js / Python 环境执行：

```powershell
python -m pip install -r desktop/requirements-build.txt
npm --prefix desktop ci
npm --prefix desktop run package
```

安装包输出在 `desktop/release/`。Linux AppImage 和 macOS dmg 仍在对应目标系统使用 `npm --prefix desktop run package` 构建。

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
