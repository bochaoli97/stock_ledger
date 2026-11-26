# Stock Ledger · React desktop

本地桌面版使用 **React + TypeScript + Electron**，由 Vite 构建。账务、行情、CSV、财务收支与 SQLite 继续调用仓库原有的 Python 模块，运行服务不依赖 PyQt6。

选择 Electron 是为了随程序固定 Chromium 版本，方便控制数字动画的表现。默认保留硬件加速和垂直同步；是否实际使用 GPU，由操作系统、驱动和 Chromium 的检测结果决定。

## 启动

已生成可直接运行的 [Windows x64 3.0.1 压缩包](release/StockLedger-Windows-x64.zip)。完整解压后双击 `Stock Ledger.exe`，不需要安装 Node.js 或 Python。使用原账本时，将原来的 `data` 文件夹复制到 exe 旁边。

从源码启动时，按下面步骤准备开发环境。

需要 Node.js 24 LTS 和 Python 3.12 或更新版本。在仓库根目录运行：

```bash
npm --prefix desktop ci
npm --prefix desktop run dev
```

Windows 也可以运行仓库根目录的 `run_desktop.bat`。Linux / WSL 使用 `bash run_desktop.sh`。

若 Python 不在默认路径中，指定解释器即可，不需要安装 PyQt6：

```bash
STOCK_LEDGER_PYTHON=/path/to/python npm --prefix desktop run dev
```

PowerShell：

```powershell
$env:STOCK_LEDGER_PYTHON = 'C:\path\to\python.exe'
npm --prefix desktop run dev
```

Ubuntu / WSL 需要图形桌面（例如 WSLg）与 Electron 的系统依赖。若报缺少 `libnss3.so` / `libnspr4.so`，安装系统发行版提供的 `libnss3`、`libnspr4`；不要关闭硬件加速来处理缺少动态库的问题。

开发版直接使用原来的 `data/stock_ledger.db`，保留原表结构，并在启动时执行原有的每日备份。另开一个测试账本可以指定：

```bash
STOCK_LEDGER_DB=/absolute/path/test.db npm --prefix desktop run dev
```

桌面界面统一通过上述 React / Electron 入口启动。

## 已接入的功能

- 多账户、合并账户、期初现金与期初持仓；合并视图的交易为只读。
- 全部十二类交易、预览、修改、删除、完整历史重算，以及现金不足时的确认。
- 持仓、成本、盈亏、股息、账户明细、个股历史与交易筛选。
- 10 秒行情更新、股票搜索、手动价格、历史走势图与鼠标滑动查看。
- 可选财务收支页：月份、金额算式、备注、余额承接、类别排序与时间范围筛选。
- 深浅主题、中英文、字号、SQLite 备份与原有格式的 CSV 导出。
- 设置中的「动画测试」提供明确标注的示例序列，用于检查动画，不会写入真实账本。

## 数字动画的约定

`src/ticker/engine.ts` 是从旧版数字组件移植的独立状态模型，控制数位身份、滚动位置、宽度、透明度和颜色。原始行为冻结在 `tests/fixtures/qt-ticker-reference.json`，参考来源见 [基准说明](tests/fixtures/README.md)。React 不参与动画的逐帧更新。

| 行为 | 保留的规则 |
| --- | --- |
| 数位身份 | `int_0`、`int_1`、`dec_1`、`comma_1` 等稳定槽位；静态字符不进入数字轨道 |
| 滚动方向 | 原实现的纵向镜像，最短 0–9 环形路径，差值为 5 时保留原方向 |
| 时长 | 小数第二位 260ms，其他小数位 320ms，整数通常 450ms；只有最高变化整数位满足原条件时使用 650ms |
| 中途更新 | 接续当前小数偏移；保留换挡、重复值去重，以及已有数位的对象身份 |
| 横向变化 | 展开 350ms，收起 260ms；滑动时 180ms；中途反向从当前宽度继续 |
| 缓动 | 滚动和扩缩为 OutCubic；红绿恢复为 OutQuad，600ms |
| 滑动 | 与实时报价使用相同纵向分级；滑动保持中性色，移出时恢复最新值 |
| 生命周期 | 第一次显示、占位符、隐藏与销毁时按原约定处理，不重播旧账户数值 |

`src/ticker/dom.ts` 用原生 Web Animations API 驱动数字条的 `transform`。其 cubic-bezier 的时间轴为线性，曲线精确对应 `1 - (1 - t)^3`。字体宽度取十个数字的最大测量宽度加固定间距。

扩缩时缩放裁剪层，并在内部施加逆变换，保持字形比例。宽度、颜色等小范围更新使用 `requestAnimationFrame`，按显示器刷新节奏运行，空闲时停止。图表曲线缓存为静态 Canvas，游标与脉冲是独立元素；滑动不需要访问 Python 服务。

金额上方有可选中的真实文本层，拖动可高亮并复制完整金额；重复的滚动字符保留为不可选中的装饰层，避免复制出隐藏数字。财务备注使用多行文本框，Enter 换行，点击保存按钮才提交。

## GPU 状态

图形加速由 Electron / Chromium 根据操作系统、显卡和驱动选择，不绑定 NVIDIA 或某一型号。兼容的 NVIDIA、AMD、Intel 设备都使用同一套检测与渲染逻辑；设备或驱动不可用时可回退为软件渲染。

打开 **设置 → 图形加速** 可看到：

- **GPU 硬件加速已启用**：GPU 合成状态启用，且检测到的后端不是软件渲染器。
- **当前使用软件渲染**：硬件加速被禁用、GPU 合成不可用或正在使用软件渲染器。
- 图形设备、实际渲染后端和 `gpu_compositing` 状态；可点击「重新检测」。

下方「渲染信息」保留各项 Chromium GPU 功能状态。检测使用 [Electron 官方 GPU 接口](https://www.electronjs.org/docs/latest/api/app#appgetgpufeaturestatus)。

## 验证

```bash
# TypeScript 与生产构建
npm --prefix desktop run build

# 30 个动画模型测试 + 进程通信、数据路径、GPU 状态测试
npm --prefix desktop test

# Python 服务测试；仅使用临时数据库
python -m unittest -v test_desktop_backend

# Electron 的真实窗口交互测试（需要图形桌面）
npm --prefix desktop run test:browser
```

模型测试使用原组件生成的 **28 组场景、202 个检查点**，比较偏移、宽度、透明度、目标值、动画时长与颜色。颜色的整数舍入允许一个色阶差异。对照数据已冻结，当前测试和运行都不需要 Qt。

真实窗口测试覆盖交易新增/编辑/删除、图表滑动/回位、数位接续、裁剪不变形、金额高亮、账户下拉的主题对比度与键盘操作、GPU 状态、多行备注保存，以及新建账户和合并视图。测试独占临时数据库；网络请求由测试进程中的固定数据替代，不连接 Yahoo，也不打开用户账本。

可以在 Windows 的 Python 环境中一次完成独立构建、全部桌面交互、GPU 检查和 exe 启动验证：

```powershell
python desktop/scripts/validate-windows.py --bootstrap-node --package --require-gpu --archive
```

该命令只复制程序源码到系统临时目录，不复制原账本。缺少 Node.js 时下载并校验官方便携版，Python 依赖安装在独立虚拟环境中。`--require-gpu` 要求测试窗口的 GPU 合成状态为启用；报告、截图、帧间隔和完整 GPU 信息保存在 `desktop/test-results/windows-native/`。报告中的 `executable` 指向测试完成后保留的 Windows 可运行程序。`--archive` 生成 `desktop/release/StockLedger-Windows-x64.zip`，排除账本数据库并验证 ZIP CRC 与 SHA-256。

动画测试会记录每 50ms 更新一次目标时的帧间隔与 GPU 状态，写入 `test-results/`。Windows 的完整 GPU 信息包含实际活动设备和渲染后端；设置 → 图形加速也可以查看实际状态。

3.0.1 验证结果：

- Python 业务与服务：93 个无需图形环境的测试通过。旧界面专用测试已删除，业务、CSV、存储、行情和翻译测试保留。
- TypeScript 动画模型、进程通信、数据路径与 GPU 状态：39 个测试通过。
- Windows 原生窗口的 7 个交互测试全部通过，包括金额拖选、账户下拉深浅主题、备注换行及重新打开后的持久化验证。
- Windows exe 的独立启动通过，包含中文账户、SQLite 和内置 Python 服务；无需安装 Python 即可运行。ZIP 已通过 CRC 与 SHA-256 校验，不包含用户数据库。
- Windows 实测活动设备为 **NVIDIA GeForce RTX 3060**，渲染器为 **ANGLE / Direct3D 11**，硬件加速、GPU 合成与光栅化均已启用。
- Windows 每 50ms 切换目标，约 1.8 秒收集 108 个帧间隔：中位数 **16.7ms**，P95 **16.8ms**。帧间隔为 requestAnimationFrame 回调间隔；120Hz、macOS 和与 Robinhood 客户端的同机对比尚未验证。

旧 Qt 界面、Qt 专用测试、旧打包脚本与过期构建产物已清理。账务核心、业务测试、原数字动画对照数据和用户 `data/` 保留。

## 打包

在**目标操作系统**上安装 Python 的打包工具，然后执行：

```bash
python -m pip install pyinstaller
npm --prefix desktop run package
```

Windows 输出 NSIS 安装包和 portable exe，Linux 输出 AppImage，macOS 输出 dmg，文件在 `desktop/release/`。仅生成可运行目录：

```bash
npm --prefix desktop run package:dir
```

构建目录版后，可以用临时数据库验证打包后的窗口、中文通信和内置 Python 服务：

```bash
npm --prefix desktop run test:package
```

Python 服务通过 PyInstaller 打包，Electron 安装包附带服务可执行文件；用户不需要另外安装 Python。WSL 构建的是 Linux 版本，Windows 版本应在 Windows 的 Node.js 与 Python 环境中构建。

打包版优先使用程序目录旁的 `data/`，目录不可写时使用系统用户数据目录。升级旧程序时保持原数据目录，或通过 `STOCK_LEDGER_DB` 明确指定原数据库。程序不上传账本；开启行情与搜索时仍由原 `quotes.py` 访问 Yahoo。

## 文件

| 文件 | 职责 |
| --- | --- |
| `../desktop_backend.py` | JSON 行协议服务、业务入口、独立网络工作线程 |
| `electron/main.mjs` | 窗口、Python 子进程、原生文件对话框、IPC 权限边界 |
| `electron/preload.cjs` | 向隔离的渲染进程提供有限 API |
| `src/ticker/engine.ts` | 可确定时间的动画状态模型 |
| `src/ticker/dom.ts` | Web Animations 与 DOM 合成层 |
| `src/components/PriceChart.tsx` | 静态曲线、游标和脉冲图层 |
| `src/App.tsx` | 真实账本界面与服务交互 |

前端不使用 JavaScript 浮点数计算账务金额。接口中的 Decimal 以十进制字符串传递；图表坐标沿用原来的浮点序列，滑动显示的金额由 Python 预先格式化。
