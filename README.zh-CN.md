# 股票账本（Stock Ledger）

[English](README.md) | **简体中文**

一个简单的本地券商账户记账软件：记录现金余额、持仓，以及每笔交易的成本和盈亏。
只用 Python 标准库（tkinter 界面 + sqlite3 数据库），数据保存在你自己的电脑上。
会发送到网上的只有两样东西：你的股票代码（用于获取实时价格），以及你在代码框里输入的内容（用于提示匹配的股票）。两者都可以关闭。

## 功能

- Robinhood 风格的界面：深色模式（也可切换浅色），大字显示总资产，下方是资产走势图
  （1天 / 1周 / 1个月 / 3个月 / 今年 / 1年 / 全部），鼠标移到图上可查看任意时刻的数值；右侧“股票”列表
  显示每只持仓今天的迷你走势图和价格
- 多账户（例如 Fidelity 个人账户和 Roth IRA）；新建账户时可以填写期初现金和期初持仓
- 交易类型：存入、取出、买入、卖出、股息、利息、费用、股份转入、股份转出、拆股、代码变更
- 除了股票也能记加密货币：比特币记为 `BTC-USD`（以太坊 `ETH-USD`，依此类推），数量精确到 0.00000001
- 自动计算现金余额（含每笔交易后的余额）、持股数、平均成本、持仓成本、已实现盈亏和累计股息
- 单只股票详情：双击股票可查看它的每一笔交易，以及每笔交易后的持股数和平均成本
- 每 10 秒从 Yahoo Finance 获取实时价格：市值、未实现盈亏、今日涨跌和总资产随行情变化；
  开盘期间，今天走势线的末端有一个闪烁的圆点标出最新价格，和 Robinhood 一样
- 关闭实时报价即可完全离线使用，改为手动填写价格
- 像 Robinhood 一样边输入边搜索股票：输入代码或公司名称（如“apple”“berkshire”），用鼠标或 ↑↓ + 回车
  从列表中选择。已持有的股票排在最前并显示股数；打开实时报价时，其他匹配结果来自 Yahoo
  （离线时只提示本账户的股票）
- 记错了双击即可修改或删除，所有数字自动重算；前后矛盾的记录（比如卖出多于持有的股数）会被拒绝
- 可调字号（⋯ 菜单 → 字号：小 / 标准 / 大 / 特大）
- 中英文界面（⋯ 菜单 → Language / 语言）；第一次启动时默认为中文
- 导出 CSV（可直接用 Excel 打开）、手动备份数据库、每天自动备份

## 文件

| 文件 | 用途 |
|---|---|
| `app.py` | 图形界面和程序入口 |
| `ledger.py` | 记账逻辑（独立于界面，可单独测试） |
| `storage.py` | 数据存储（SQLite） |
| `quotes.py` | 实时行情和历史价格（Yahoo Finance，不需要 API key） |
| `ui.py` | 外观：深色/浅色主题、字体、图表等自绘控件 |
| `i18n.py` | 界面语言：中英文文字 |
| `test_ledger.py` | 测试：记账逻辑、存储、行情、股票搜索和翻译（不需要联网） |
| `icon.ico` | 程序图标 |
| `build_exe.bat` | 在 Windows 上打包 exe |
| `build_from_wsl.sh` | 在 WSL 里一条命令打包 exe（调用 Windows 版 Python） |

---

## 1. 在 WSL 中搭建开发环境

**1. 把项目放进 WSL**（在 WSL 终端里操作，假设 zip 下载到了 Windows 的“下载”文件夹）：

```bash
cd ~
cp /mnt/c/Users/<你的 Windows 用户名>/Downloads/stock_ledger.zip .
unzip stock_ledger.zip
cd stock_ledger
```

**2. 创建 conda 环境**（要用 `xft` 版本的 Tk，它在 Linux 上能使用真正的平滑字体）：

```bash
conda create -n stockledger -c conda-forge python=3.12 "tk=8.6.*=xft*" xorg-libxft -y
conda activate stockledger
python -c "import tkinter; tkinter._test()"   # 弹出一个小窗口，说明图形界面正常
```

**3. 安装中日韩字体**：使用中文界面，或者账户名称、备注里有中日韩文字时需要安装，否则在 WSL 里会显示成方框：

```bash
sudo apt update && sudo apt install -y fonts-noto-cjk
```

**4. 用 VS Code 打开**：

- 在 Windows 的 VS Code 中安装 **WSL**（Microsoft 出品）和 **Python** 扩展
- 在 WSL 终端进入项目文件夹，运行 `code .`，VS Code 会以 WSL 模式打开（左下角显示 `WSL: Ubuntu`）
- 第一次打开后，在扩展视图里为 WSL 也安装一次 Python 扩展
- `Ctrl+Shift+P` → `Python: Select Interpreter` → 选择 `stockledger` 这个 conda 环境

## 2. 运行和调试

```bash
conda activate stockledger
python app.py          # 启动软件（窗口会通过 WSLg 显示在 Windows 桌面上）
python test_ledger.py  # 运行测试，检查计算是否正确
```

也可以在 VS Code 中打开 `app.py`，按 `F5` 带断点运行。

开发期间，数据保存在 `stock_ledger/data/stock_ledger.db`。

## 3. 打包成 Windows exe

> PyInstaller 不能跨平台打包：在 WSL（Linux）里打包只能得到 Linux 程序。
> 所以代码在 WSL 里写，但**打包这一步要用 Windows 版 Python**。这只需要设置一次。

**1. 在 Windows 上安装 Python**（只需一次）

从 <https://www.python.org/downloads/windows/> 下载 Python 3.12 或更新版本并安装。
安装时勾选 **Add python.exe to PATH**，其他保持默认即可（默认已包含 tkinter）。

**2. 打包**，两种方法任选一种：

方法 A：在 WSL 终端里运行一条命令（VS Code 的终端也可以）：

```bash
bash build_from_wsl.sh
```

它会把源代码复制到 `C:\Users\<你>\StockLedgerBuild`，用 Windows 版 Python 安装 PyInstaller 并打包，
完成后打开包含 `StockLedger.exe` 的 `dist\StockLedger` 文件夹。

方法 B：把 `app.py ledger.py storage.py quotes.py ui.py i18n.py icon.ico build_exe.bat` 复制到 Windows 上的一个文件夹里，双击 `build_exe.bat`。

第一次打包要下载 PyInstaller，大约 1～2 分钟；之后会快很多。

**3. 使用 exe**

打包结果是一个文件夹 `dist\StockLedger`：里面有 `StockLedger.exe` 和它需要的 `_internal` 文件夹
（Python 和 Tk 都在里面，所以电脑上不需要安装 Python）。文件夹形式比单文件 exe 启动更快
（单文件 exe 每次启动都要先解压到 `%TEMP%`），也更少被杀毒软件误报。

把整个 `StockLedger` 文件夹复制到固定位置，例如 `D:\StockLedger\`，双击 `StockLedger.exe` 即可运行
（右键 → *发送到 → 桌面快捷方式* 可以创建桌面图标）。
数据保存在 exe 旁边的 `data` 文件夹。更新时，删掉旧的 `StockLedger.exe` 和 `_internal`，复制进新的，
`data` 文件夹不要动。（重新打包也不会碰 `dist\StockLedger` 里的 `data` 文件夹。）

## 4. 数据和备份

- 所有数据都在一个文件里：`data\stock_ledger.db`。复制这个文件就是完整备份。
- 每天第一次打开软件时，会自动备份到 `data\backups\`，保留最近 30 天。
- **⋯ → 备份数据库** 可以随时备份到任意位置（例如云同步文件夹）。
- **⋯ → 导出当前账户为 CSV** 会导出交易记录和持仓两张表，可直接用 Excel 打开。
- 要把在 WSL 里测试时录入的数据带到 exe，把 `data/stock_ledger.db` 复制到 exe 旁边的 `data` 文件夹即可。

## 5. 实时价格

- 顶栏的 **实时** 开关控制是否自动更新（下次打开时会记住）。
- 价格每 10 秒刷新一次（`app.py` 中的 `LIVE_INTERVAL`）。开关旁边显示最后一次更新的时间。
- 持仓表的 **今日涨跌** 列和 **总资产** 下方的“今天”一行，显示相对前一交易日收盘价的变化。
- 数据来自 Yahoo Finance。美股接近实时；部分其他交易所最多延迟 15 分钟。
  非交易时间显示最近的收盘价。
- Yahoo 不认识的代码（例如定期存单、私募基金）会显示“无报价”，请用 **更新价格** 手动填写。
- 股票类别两种写法都可以：`BRK.B` 和 `BRK-B` 都行。
- 加密货币写成“币种-USD”：`BTC-USD`、`ETH-USD`、`SOL-USD`（搜“bitcoin”或“btc”就能找到）。
  只写 `BTC` 是另一样东西：在股市交易的比特币 ETF。加密货币 24 小时交易。
- 新代码（改代码后，或者新上市的认股权证等）只要 Yahoo 开始收录就能获取实时价格；
  在那之前显示“无报价”并按成本计算，也可以用 **更新价格** 手动填写价格。
- 断网时会保留最后取到的价格，并自动重试。

**走势图**

- 大字数字是你的总资产（现金 + 持仓）。鼠标移到图上可查看任意时刻的数值。
- 1天 与前一交易日收盘价（虚线）比较。其他范围显示这段时间的盈亏，并扣除了存入和取出的资金，
  所以存钱进来不会被算作收益。
- 过去的数值由你的交易记录和 Yahoo 的每日收盘价重新算出，并考虑了你记录过的拆股。
- 点击 **股票** 列表中的股票（或在“持仓”页双击），可打开它的详情页，查看价格走势、你的持仓和交易历史。
- **⋯ → 深色模式** 切换深色和浅色主题；**⋯ → Language / 语言** 切换中英文。

## 6. 各种情况怎么记

| 情况 | 记为 |
|---|---|
| 开始记账时账户里已有的现金 | 新建账户时填期初现金（或记一笔存入） |
| 开始记账时已持有的股票 | 新建账户时填期初持仓（或记一笔股份转入，填每股成本） |
| 从银行转入 / 转出到银行 | 存入 / 取出 |
| 买入 / 卖出股票 | 买入 / 卖出（填数量、价格和手续费，现金自动更新） |
| 现金股息 | 股息（填金额） |
| 股息再投资（DRIP） | 先记一笔股息，再记一笔买入 |
| 现金利息（例如 SPAXX 收益） | 利息 |
| 账户费用、ADR 费用等 | 费用 |
| 拆股（1 拆 4：10 股变 40 股） | 拆股，填 **30**（增加的股数）；总成本不变 |
| 合股（反向拆股） | 拆股，填负数 |
| 股票转到其他账户 | 股份转出（按平均成本减少持仓，不产生盈亏） |
| 股票改代码，或合并时换成新股票 | 代码变更：填原代码、新代码和换得的新股数（一换一点 **全部**）；持仓成本一并转过去，不产生盈亏 |
| 免费派发的认股权证 / 配股权 / 股票（例如每股送 1 份权证） | 股份转入：填权证代码、收到的数量，每股成本填 **0**（见下文） |
| 买卖加密货币 | 买入 / 卖出，代码填 `BTC-USD` 等 |

**持仓成本按平均成本法计算**：买入时加上成本（含佣金）；卖出时按当时的平均成本扣除成本，
已实现盈亏 = 卖出所得 − 扣除的成本。支持零碎股。

**免费权证按成本 0 记**：总盈亏是对的，但权证的全部市值会显示为它自己的盈利，而股票保留全部成本。
如果公司之后公布了成本分摊（美国国税局 Form 8937，例如“x% 分给权证”），按它修改这两条记录即可：
调低股票的成本，把相应部分给权证。

小技巧：
- `Ctrl+N` 添加交易；在“交易记录”页选中一笔后，按 `Enter` 编辑，按 `Delete` 删除
- 点击列标题可以排序
- 卖出时点 **全部**，自动填入当前持有的股数
- 同一天的交易按录入顺序处理

## 7. 常见问题

**在 WSL 里运行 `python app.py` 没有窗口**
需要 WSLg（Windows 11 自带；Windows 10 需要较新的版本）。在 Windows PowerShell 中运行 `wsl --update`，然后 `wsl --shutdown` 重启 WSL 再试。

**WSL 里字体很小、有锯齿，或者某些符号显示成 `\u25be`**
你的 Tk 是 `noxft` 版本，在 Linux 上用不了真正的字体。换成 `xft` 版本：
`conda install -n stockledger -c conda-forge "tk=8.6.*=xft*" xorg-libxft`。
这只影响开发时的显示；exe 在 Windows 上使用 Segoe UI（中文界面使用微软雅黑）。

**Windows Defender / 杀毒软件报毒**
PyInstaller 打包的未签名程序偶尔会被误报（文件夹形式比单文件少得多）。可以在 Defender 中把 `StockLedger` 文件夹加入排除项。
第一次运行时 SmartScreen 可能提示“Windows 已保护你的电脑”：点 *更多信息 → 仍要运行*。

**我想要红涨绿跌**
打开 `ui.py`，把开头附近的 `RED_UP` 改成 `True`，重新打包即可。（主题颜色在同一文件的 `PALETTES` 中。）

**添加或修改界面文字**
在代码里用 `tr()` 包住英文文字，例如 `tr("Cash")` 或 `tr("{n} transactions", n=count)`，
再把中文加到 `i18n.py` 的 `ZH` 表里。如果有文字缺少翻译，或者翻译里的 `{占位符}` 对不上，`python test_ledger.py` 会报错。
