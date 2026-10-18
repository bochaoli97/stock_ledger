"""
i18n.py -- the interface language (English / 简体中文)

Text is written in English in the code and wrapped in tr():
    tr("Cash")                                   -> "现金" when Chinese is on
    tr("{n} transactions", n=12)                 -> "12 笔交易"
The English text is the lookup key, so anything without a translation simply shows in English.
test_ledger.py checks that every tr("...") in the code has an entry here with the same {placeholders}.
"""

from __future__ import annotations

LANGUAGES = {"en": "English", "zh": "中文"}
DEFAULT_LANGUAGE = "zh"  # used until a language is picked in the menu
_lang = "en"


def set_language(code: str) -> None:
    global _lang
    _lang = code if code in LANGUAGES else "en"


def language() -> str:
    return _lang


def tr(text: str, **values) -> str:
    """Translate English UI text into the current language, then fill in {placeholders}."""
    if _lang == "zh":
        text = ZH.get(text, text)
    return text.format(**values) if values else text


ZH: dict[str, str] = {
    # ---- app, window, top bar
    "Stock Ledger": "股票账本",
    "No account": "没有账户",
    "+ Add transaction": "+ 添加交易",
    "Update prices": "更新价格",
    "Live": "实时",
    "Offline, retrying…": "离线，正在重试…",
    "Updated {time}": "更新于 {time}",
    " · no quote: {symbols}": " · 无报价：{symbols}",
    "Total assets": "总资产",
    "Net worth (all accounts)": "净资产（全部账户）",
    "All accounts": "全部账户",
    "Stocks": "股票",
    "No holdings yet": "暂无持仓",
    "{n} holding": "{n} 只持仓",
    "{n} holdings": "{n} 只持仓",
    "{n} share": "{n} 股",
    "{n} shares": "{n} 股",
    "{n} coin": "{n} 个",
    "{n} coins": "{n} 个",
    # ---- stats
    "Cash": "现金",
    "Market value": "市值",
    "Cost basis": "持仓成本",
    "Unrealized P/L": "未实现盈亏",
    "Realized P/L": "已实现盈亏",
    "Dividends + interest": "股息 + 利息",
    "Net deposits": "净入金",
    "Fees & commissions": "手续费与佣金",
    "{pct}% of total": "占总资产 {pct}%",
    "{symbols} at cost": "{symbols} 按成本计",
    "{symbols} etc. at cost": "{symbols} 等按成本计",
    "{n} stock": "{n} 只股票",
    "{n} stocks": "{n} 只股票",
    "Incl. commissions": "含佣金",
    "Needs prices": "需要价格",
    "Div {div} · Int {int}": "股息 {div} · 利息 {int}",
    "In {deposits} · Out {withdrawals}": "存入 {deposits} · 取出 {withdrawals}",
    # ---- chart
    "Today": "今天",
    "Past week": "过去一周",
    "Past month": "过去一个月",
    "Past 3 months": "过去三个月",
    "Year to date": "今年以来",
    "Past year": "过去一年",
    "All time": "全部时间",
    "Past 6 months": "过去六个月",
    "1D": "1天",
    "1W": "1周",
    "1M": "1个月",
    "3M": "3个月",
    "YTD": "今年",
    "1Y": "1年",
    "ALL": "全部",
    "No transactions yet": "还没有交易",
    "Turn on Live prices to see the chart": "打开实时报价即可查看图表",
    "Loading…": "加载中…",
    "No chart data": "没有图表数据",
    "No holdings": "没有持仓",
    "Couldn't load the chart (offline?)": "图表加载失败（是否离线？）",
    # ---- tabs and tables
    "Accounts": "账户",
    "Account": "账户",
    "Total": "合计",
    "% of Total": "占比",
    "Net Deposits": "净入金",
    "Double-click an account to open it": "双击账户可打开它",
    "Holdings": "持仓",
    "Transactions": "交易记录",
    "Double-click a stock to open its page": "双击股票打开详情页",
    "View details": "查看详情",
    "Back": "返回",
    "Show closed": "显示已清仓",
    "All": "全部",
    "Reset filters": "重置筛选",
    "Delete": "删除",
    "Edit": "编辑",
    "Showing {shown} of {total}": "显示 {shown} / {total} 笔",
    "{total} total": "共 {total} 笔",
    "Symbol": "代码",
    "Shares": "股数",
    "Avg Cost": "平均成本",
    "Cost Basis": "持仓成本",
    "Price": "价格",
    "Day Change": "今日涨跌",
    "Market Value": "市值",
    "P/L %": "盈亏 %",
    "Dividends": "股息",
    "Date": "日期",
    "Type": "类型",
    "Quantity": "数量",
    "Fee": "手续费",
    "Amount": "金额",
    "Cash Change": "现金变动",
    "Cash Balance": "现金余额",
    "Note": "备注",
    "Shares After": "交易后股数",
    "Avg Cost After": "交易后平均成本",
    # ---- transaction types
    "Deposit": "存入",
    "Withdrawal": "取出",
    "Buy": "买入",
    "Sell": "卖出",
    "Dividend": "股息",
    "Interest": "利息",
    "Shares In": "股份转入",
    "Shares Out": "股份转出",
    "Split": "拆股",
    "Symbol Change": "代码变更",
    "Distribution": "派发",
    # ---- stock page
    "Your position": "我的持仓",
    "Average cost": "平均成本",
    "Today's return": "今日收益",
    "Total return": "总收益",
    "History": "历史记录",
    # ---- menus
    "New account…": "新建账户…",
    "Edit account…": "编辑账户…",
    "Delete account…": "删除账户…",
    "Add transaction": "添加交易",
    "Update prices…": "更新价格…",
    "Export current account to CSV…": "导出当前账户为 CSV…",
    "Back up database…": "备份数据库…",
    "Open data folder": "打开数据文件夹",
    "Dark mode": "深色模式",
    "Text size": "字号",
    "Small": "小",
    "Standard": "标准",
    "Large": "大",
    "Extra large": "特大",
    "User guide": "使用说明",
    "About": "关于",
    "Exit": "退出",
    # ---- dialogs: common
    "Save": "保存",
    "Cancel": "取消",
    "Invalid input": "输入有误",
    # ---- add / edit transaction
    "Add Transaction": "添加交易",
    "Edit Transaction": "编辑交易",
    "Quantity (shares)": "数量（股）",
    "Share change": "股数变化",
    "Cost per share": "每股成本",
    "New symbol": "新代码",
    "New Symbol": "新代码",
    "New shares received": "换得的新股数",
    "Ticker change or merger conversion: the whole position moves to the new symbol with its "
    "cost basis (no gain or loss). Enter the new shares received; for 1-for-1, press All.":
        "股票改代码或合并换股：整个持仓连同持仓成本转到新代码下（不产生盈亏）。"
        "填写换得的新股数；一换一时点“全部”即可。",
    "{old_qty} shares of {symbol} become {qty} shares of {new}; cost basis {cost} carries over":
        "{symbol} {old_qty} 股换成 {new} {qty} 股；持仓成本 {cost} 一并转过去",
    "Received symbol": "获得的代码",
    "Quantity received": "获得数量",
    "Cost basis moved (%)": "转移成本比例（%）",
    "Spin-off, warrants or rights handed out on a stock you hold: the new security becomes its own "
    "position and takes the given percent of the stock's cost basis (0 moves none). Your shares "
    "of the stock stay the same. Does not affect cash.":
        "分拆、派发认股权证或配股权等：新证券单独成为一个持仓，并从原股票的持仓成本中按所填比例分走一部分"
        "（填 0 表示不转移成本）。原股票的股数不变，不影响现金。",
    "{pct}% of {symbol}'s cost basis ({moved}) goes to {qty} {new}; {symbol} average cost becomes {avg}":
        "{symbol} 持仓成本的 {pct}%（{moved}）转给 {new} {qty} 份；{symbol} 平均成本变为 {avg}",
    "Deposit amount": "存入金额",
    "Withdrawal amount": "取出金额",
    "Dividend amount": "股息金额",
    "Interest amount": "利息金额",
    "Fee amount": "费用金额",
    "Cash transferred in from a bank (also use this for opening cash).":
        "从银行转入的现金（期初现金也用这一项）。",
    "Cash transferred out to a bank.": "转出到银行的现金。",
    "Cash decreases by quantity × price + fee.": "现金减少 数量 × 价格 + 手续费。",
    "Cash increases by quantity × price − fee; realized P/L uses average cost.":
        "现金增加 数量 × 价格 − 手续费；已实现盈亏按平均成本计算。",
    "Cash dividend. If it is reinvested, also record a separate Buy.":
        "现金股息。如果股息再投资，请另外记一笔买入。",
    "Interest earned on cash (e.g. money market fund income).": "现金产生的利息（例如货币基金收益）。",
    "Other fees, such as account maintenance or ADR fees.": "其他费用，例如账户管理费或 ADR 费用。",
    "Shares transferred in from elsewhere or held at account opening. Does not affect cash.":
        "从别处转入的股份，或开户时已持有的股份。不影响现金。",
    "Shares transferred to another account; reduces the position at average cost. Does not affect cash.":
        "转到其他账户的股份，按平均成本减少持仓。不影响现金。",
    "Enter the change in shares: 10 shares split 4-for-1 become 40, so enter 30. "
    "Use a negative number for a reverse split.":
        "填写股数的变化：10 股按 1 拆 4 变成 40 股，就填 30。合股（反向拆股）填负数。",
    "Currently holding {qty} shares of {symbol}, average cost {avg}":
        "当前持有 {symbol} {qty} 股，平均成本 {avg}",
    "No shares of {symbol} currently held": "当前没有持有 {symbol}",
    "Trade value {value}": "成交金额 {value}",
    "Cash change {value}": "现金变动 {value}",
    "Estimated realized P/L {value}": "预计已实现盈亏 {value}",
    # ---- account dialog
    "New Account": "新建账户",
    "Edit Account": "编辑账户",
    "Create Account": "创建账户",
    "Account name *": "账户名称 *",
    "Broker": "券商",
    "Opening balances": "期初余额",
    "Optional, can be added later": "可选，之后也可以再添加",
    "Opening date": "期初日期",
    "Opening cash": "期初现金",
    "Opening positions": "期初持仓",
    "SYMBOL": "代码",
    "SHARES": "股数",
    "COST / SHARE": "每股成本",
    "{n} position · {total} total cost": "{n} 个持仓 · 总成本 {total}",
    "{n} positions · {total} total cost": "{n} 个持仓 · 总成本 {total}",
    "Fill in the cells and press + (or Enter) to add each stock.": "填好各格后按 +（或回车）逐个添加股票。",
    "Please enter an account name": "请输入账户名称",
    "Opening cash cannot be negative": "期初现金不能为负数",
    "Opening position not added yet: {error}": "期初持仓还没有添加：{error}",
    "Opening position": "期初持仓",
    # ---- prices dialog
    "Update Prices": "更新价格",
    "Live prices are on: prices here are replaced automatically for symbols that have a live quote. "
    "Use this for holdings without one (e.g. CDs or private funds). Leave blank to clear.":
        "实时报价已打开：有实时报价的股票，这里的价格会被自动替换。"
        "这里用于没有报价的持仓（例如定期存单或私募基金）。留空即清除。",
    "Live prices are off, so prices are entered by hand. They are used to compute market value "
    "and unrealized P/L. Leave blank to clear.":
        "实时报价已关闭，价格需要手动填写，用来计算市值和未实现盈亏。留空即清除。",
    "PRICE": "价格",
    "LAST UPDATED": "更新日期",
    "Price for {symbol} must be greater than 0": "{symbol} 的价格必须大于 0",
    # ---- symbol search
    "Closed": "已清仓",
    # ---- messages
    "Data folder location:\n{path}": "数据文件夹位置：\n{path}",
    "There are no accounts yet. Create one now?": "还没有账户，现在创建一个吗？",
    "Welcome! Start by creating an account and entering its opening cash and positions "
    "(both optional; you can add them later).":
        "欢迎！请先创建一个账户，并填写期初现金和持仓（都可以不填，之后再添加）。",
    'An account named "{name}" already exists. Please choose another name.':
        "已经有名为“{name}”的账户了，请换一个名称。",
    'An account named "{name}" already exists.': "已经有名为“{name}”的账户了。",
    "Delete Account": "删除账户",
    'Delete the account "{name}" and its {n} transactions?\n\n'
    "This cannot be undone (daily automatic backups are in the data\\backups folder).":
        "删除账户“{name}”及其 {n} 笔交易？\n\n此操作无法撤销（每天的自动备份在 data\\backups 文件夹中）。",
    "Cannot Save": "无法保存",
    "Saving this would make the books inconsistent:\n{error}": "保存后账目会前后矛盾：\n{error}",
    "Insufficient Cash": "现金不足",
    "After this transaction the cash balance goes negative (lowest {low}).\n"
    "If this is margin or a deposit you have not recorded yet, you can still save. Save anyway?":
        "这笔交易之后现金余额会变成负数（最低 {low}）。\n如果是融资，或者有还没记录的入金，仍然可以保存。确定保存吗？",
    "Please select a transaction in the Transactions tab first.": "请先在“交易记录”页选中一笔交易。",
    "Cannot Delete": "无法删除",
    "Deleting this would make the books inconsistent:\n{error}\n\n"
    "Edit or delete the later related transactions first.":
        "删除后账目会前后矛盾：\n{error}\n\n请先修改或删除之后的相关交易。",
    "Delete Transaction": "删除交易",
    "Delete this transaction?\n\n{desc}": "删除这笔交易？\n\n{desc}",
    "Please select a stock first.": "请先选中一只股票。",
    "The current account has no open positions.": "当前账户没有持仓。",
    "Error replaying the ledger: {error}": "重算账本时出错：{error}",
    "{n} transactions": "{n} 笔交易",
    "{n} account": "{n} 个账户",
    "{n} accounts": "{n} 个账户",
    "This is the combined view of all accounts. Choose one account to add a transaction.":
        "这是全部账户的汇总视图。请先选择一个账户，再添加交易。",
    "Data file: {path}": "数据文件：{path}",
    "Choose a folder to export to": "选择导出到的文件夹",
    "Exported:\n{files}": "已导出：\n{files}",
    "Back Up Database": "备份数据库",
    "SQLite database": "SQLite 数据库",
    "All files": "所有文件",
    "Backup complete:\n{path}": "备份完成：\n{path}",
    "User Guide": "使用说明",
    "1. When creating an account you can enter opening cash and positions.\n"
    "2. For every buy, sell, dividend, deposit or withdrawal, click \"+ Add transaction\" (Ctrl+N).\n"
    "   In the Symbol box, type a ticker or a company name and pick from the list.\n"
    "3. Cash balance, shares, average cost and P/L are all calculated from the transactions.\n"
    "   To fix a mistake, double-click it in the Transactions tab, or select it and press Delete.\n"
    "4. With \"Live\" on, prices update every {seconds} seconds from Yahoo Finance.\n"
    "   Turn it off to work offline and enter prices by hand with \"Update prices\".\n"
    "5. Hover over the chart to see your total assets at any point; pick a range below it.\n"
    "   Changes for ranges other than 1D leave out deposits and withdrawals.\n"
    "6. Click a stock in the Stocks list for its own page with chart and history.\n"
    "7. Dividend reinvestment: record a Dividend, then a Buy.\n"
    "8. Stock split: record a Split with the number of shares added (total cost is unchanged).\n"
    "9. Cost basis uses the average cost method.\n"
    "10. With two or more accounts, \"All accounts\" in the account menu adds them up (read-only).\n"
    "11. In the Transactions tab, the Period box narrows the list to the past month, 3 or 6 months, a year,\n"
    "   a calendar year, or dates you type.\n"
    "12. Optional: ⋯ → Finance page adds a Finance button with a monthly income and expense sheet for money\n"
    "   outside your brokerage accounts. Double-click a month to edit it; every amount can carry a comment.\n"
    "   The All accounts view then also shows the net worth including that cash balance.\n\n"
    "Data is stored in:\n{path}\nIt is backed up to the backups folder the first time you open the app each day.":
        "1. 创建账户时可以填写期初现金和持仓。\n"
        "2. 每次买入、卖出、收到股息、存入或取出资金，都点“+ 添加交易”（Ctrl+N）记一笔。\n"
        "   在代码框里输入股票代码或公司名称，从列表中选择即可。\n"
        "3. 现金余额、股数、平均成本和盈亏都由交易记录自动计算。\n"
        "   记错了可以在“交易记录”页双击修改，或选中后按 Delete 删除。\n"
        "4. 打开“实时”后，每 {seconds} 秒从 Yahoo Finance 更新一次价格。\n"
        "   关闭后可离线使用，用“更新价格”手动填写价格。\n"
        "5. 鼠标移到图表上可查看任意时刻的总资产；图表下方可选择时间范围。\n"
        "   除 1天 以外的范围，涨跌金额已扣除存入和取出的资金。\n"
        "6. 点击“股票”列表中的股票，可打开它的详情页，查看图表和历史记录。\n"
        "7. 股息再投资：先记一笔股息，再记一笔买入。\n"
        "8. 拆股：记一笔拆股，填写增加的股数（总成本不变）。\n"
        "9. 持仓成本按平均成本法计算。\n"
        "10. 有两个或更多账户时，账户菜单里的“全部账户”会把它们加在一起显示（只读）。\n"
        "11. 在“交易记录”页，用“时间范围”可以只看过去一个月、3 个月、6 个月、一年、某个自然年，\n"
        "   或自己输入的起止日期。\n"
        "12. 可选功能：⋯ → 财务收支页，会多出一个“财务收支”按钮，打开按月统计的收支表，记录股票账户之外的钱。\n"
        "   双击某个月份即可编辑，每一项金额都可以加注释。\n"
        "   这时“全部账户”视图还会显示包含这笔现金结余的净资产。\n\n"
        "数据保存在：\n{path}\n每天第一次打开软件时会自动备份到 backups 文件夹。",
    "{app} {version}\n\nA local bookkeeping tool. Your data stays on your own computer;\n"
    "only stock symbols (and what you type into a symbol box) are sent to Yahoo Finance\n"
    "for live prices and suggestions.":
        "{app} {version}\n\n本地记账工具，数据只保存在你自己的电脑上；\n"
        "只有股票代码（以及你在代码框里输入的内容）会发送给 Yahoo Finance，\n用于获取实时价格和搜索提示。",
    # ---- transactions: period filter
    "Period": "时间范围",
    "Custom range…": "自定义范围…",
    "From": "从",
    "To": "到",
    "e.g. 2026-09-30; leave one blank for no limit": "例如 2026-09-30；留空表示不限",
    # ---- finance page
    "Finance": "财务收支",
    "Salary income": "工资收入",
    "Interest income": "利息收入",
    "Other income": "杂项收入",
    "Credit card payments": "信用卡还款",
    "Other expenses": "杂项支出",
    "+ Add month": "+ 添加月份",
    "Categories…": "收支项目…",
    "Income and expenses outside your brokerage accounts, month by month": "股票账户之外的收入与支出，按月统计",
    "Balance": "结余",
    "Income": "收入",
    "Expenses": "支出",
    "Net change": "净变化",
    "as of {month}": "截至 {month}",
    "{avg} / month": "月均 {avg}",
    "Totals for the period": "所选时段合计",
    "No months in this period.": "这个时段没有月份。",
    "{first} to {last} · {months}": "{first} 至 {last} · {months}",
    "No months yet. Click + Add month to enter the first one.": "还没有任何月份。点击“+ 添加月份”录入第一个月。",
    "e.g. 2026-01; leave one blank for no limit": "例如 2026-01；留空表示不限",
    "Finance page": "财务收支页",
    "Stock accounts net worth": "股票账户净资产",
    "Stock accounts cash": "股票账户现金",
    "Finance cash balance": "财务收支现金结余",
    "= stock accounts net worth + finance cash balance": "= 股票账户净资产 + 财务收支现金结余",
    "Part of stock accounts net worth": "已包含在股票账户净资产中",
    "Outside brokerage accounts, as of {month}": "股票账户之外，截至 {month}",
    "{n} month": "{n} 个月",
    "{n} months": "{n} 个月",
    "Double-click a month to edit it · a • marks a cell with a comment": "双击某个月份可编辑 · 带 • 的格子有注释",
    "Month": "月份",
    "Opening": "起始资金",
    "Total income": "收入合计",
    "Total expenses": "支出合计",
    "Ending balance": "月末结余",
    "Select a month to see the sums and comments in it.": "选中一个月份，可在这里查看其中的算式和注释。",
    "Opening {opening} · Income {income} · Expenses {expenses} · Ending {ending}":
        "起始 {opening} · 收入 {income} · 支出 {expenses} · 月末 {ending}",
    "Please select a month in the table first.": "请先在表格中选中一个月份。",
    "Add some categories first (Categories…).": "请先添加收支项目（点“收支项目…”）。",
    "Add Month": "添加月份",
    "Edit Month": "编辑月份",
    "Delete Month": "删除月份",
    "Delete {month} with all its amounts and comments?": "删除 {month} 及其所有金额和注释？",
    # ---- finance: month dialog
    "Opening balance": "起始资金",
    "CATEGORY": "项目",
    "AMOUNT": "金额",
    "COMMENT": "注释",
    "Invalid": "无效",
    "An amount can be a sum, like 1250.50+1250.50; the parts are kept so you can see them later.":
        "金额可以填算式，例如 1250.50+1250.50；各项会保留下来，之后还能看到。",
    "Leave blank to continue from the previous month's ending balance ({value})": "留空则承接上月月末结余（{value}）",
    "Income {income} · Expenses {expenses} · Ending balance {ending}": "收入 {income} · 支出 {expenses} · 月末结余 {ending}",
    "{month} already exists. Double-click it in the table to edit it.": "{month} 已经存在，请在表格中双击它进行编辑。",
    "{category}: {error}": "{category}：{error}",
    # ---- finance: categories dialog
    "Income and Expense Categories": "收支项目",
    "Type a name and press Add. To change a name, select it, edit the text and press Rename.":
        "输入名称后点“添加”。要改名，先选中它，修改文字后点“重命名”。",
    "Add": "添加",
    "Rename": "重命名",
    "Up": "上移",
    "Down": "下移",
    "Please enter a name": "请输入名称",
    '"{name}" is already in the list': "“{name}”已经在列表中了",
    "Please select a category first.": "请先选中一个项目。",
    "Delete Categories": "删除项目",
    "Deleting these categories also deletes their {n} amounts and comments in the months already entered.\n\n"
    "Continue?": "删除这些项目，也会删除它们在已录入月份中的 {n} 个金额和注释。\n\n要继续吗？",
    # ---- finance.py
    "Invalid month, please use a format like 2026-09": "月份无效，请使用 2026-09 这样的格式",
    "Cannot divide by zero": "不能除以零",
    # ---- ledger.py: input checks and books that don't add up
    '"{value}" is not a valid number': "“{value}”不是有效的数字",
    "Invalid date, please use a format like 2026-09-30": "日期无效，请使用 2026-09-30 这样的格式",
    "Unknown transaction type: {type}": "未知的交易类型：{type}",
    "Please enter a symbol": "请输入股票代码",
    "Please enter the new symbol": "请输入新代码",
    "The new symbol must differ from the old one": "新代码不能和原代码相同",
    "{date} {symbol}: no shares held to change into {new}": "{date} {symbol}：没有持股，无法换成 {new}",
    "Amount must be greater than 0": "金额必须大于 0",
    "Share change cannot be 0": "股数变化不能为 0",
    "Quantity must be greater than 0": "数量必须大于 0",
    "Price must be greater than 0": "价格必须大于 0",
    "Cost per share cannot be negative": "每股成本不能为负数",
    "Cost basis moved must be between 0 and 100%": "转移成本比例必须在 0 到 100% 之间",
    "{date} {symbol}: no shares held at the time of the distribution": "{date} {symbol}：派发时没有持股",
    "Fee cannot be negative": "手续费不能为负数",
    "{date} {symbol}: no shares held at the time of the split": "{date} {symbol}：拆股时没有持股",
    "{date} {symbol}: reverse split removes {removed} shares, but only {held} shares were held":
        "{date} {symbol}：合股要减少 {removed} 股，但当时只持有 {held} 股",
    "{date} {type} {qty} shares of {symbol}, but only {held} shares were held":
        "{date} {type} {symbol} {qty} 股，但当时只持有 {held} 股",
}
