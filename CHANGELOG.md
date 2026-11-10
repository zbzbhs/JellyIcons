# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/)。

## [1.7.0] - 2026-11-10

两条硬需求：**能换台电脑直接用**（单文件 exe），**界面要好看**（不再用
ttk 那套系统灰控件）。

### Added — 单文件 exe

- `build_exe.py`：PyInstaller 一键打包，默认 `--onefile --windowed`
  （31.7 MB，双击即跑，**目标机器不需要装 Python**），`--console` 出
  带控制台的调试版。
- `make_icon.py`：纯 PIL 生成多尺寸 `assets/jellyicons.ico`
  （16/24/32/48/64/128/256），深色圆角底 + 三颗方块，中间那颗压扁。
- `jellyicons/paths.py`：源码与打包两种形态的资源/数据目录解析。打包后
  `__file__` 在只读的 `_MEIxxxx` 里，日志、心跳、comtypes 代码缓存统一
  落到 exe 同级目录，不可写时退到 `%LOCALAPPDATA%\JellyIcons`。
- `run.py --watchdog`：打包后没法再 `-m jellyicons.watchdog`，看门狗改成
  self-exec（`JellyIcons.exe --watchdog`）。

### Added — 自绘控制面板

- `jellyicons/ui.py` 取代 `panel.py`：无边框 Tk 窗口 + 颜色键透明
  （`-transparentcolor`），整块界面由 PIL 渲染成一张图贴到 Canvas 上，
  圆角以外全透明。深色渐变卡片、自绘开关/按钮/下拉、hover 高亮、
  拖标题栏移动、右上角折叠/关闭。
- 64 段实时频谱（绿柱 + 黄色峰值保持）、状态卡（模式/引擎/图标数/FPS/
  音频状态/低频电平条）、8 个模式按钮（高亮当前模式、标注原位或接管）、
  自动轮换开关、音频设备下拉、停止并退出、三行热键提示。
- `docs/ui_grab.png` 是真实运行时的截图；`ui.render_preview()` 可离线出图
  （README 的 `docs/ui_preview.png`）。

### Fixed

- **打包后 comtypes 起不来**：`_bootstrap_comtypes()` 用
  `spec_from_file_location` 加载 `comtypes/client/_code_cache.py`，而
  PyInstaller 把 .py 打进 PYZ，磁盘上并没有这个文件 →
  `FileNotFoundError`，桌面布局读不到、一个 overlay 都建不出来。
  打包形态改为直接造一个只带 `_find_gen_dir` 的替身模块。
- **打包后 `No module named 'email'`**：原先 EXCLUDE 里剔了标准库
  （想瘦身），但 comtypes 生成 UIAutomation 代码时 `importlib.metadata`
  依赖 `email`。改成只剔第三方大包（matplotlib/scipy/pandas 等）。
- **`--windowed` 下日志炸**：`sys.stdout` 是 `None`，
  `logging.StreamHandler(None)` 每次 emit 抛 AttributeError。改为
  `sys.stdout or sys.stderr`，两者都没有就不挂流式 handler。
- **「自由」模式每帧抛异常**（真机上暴露）：`if ctx.bands` 对 numpy 数组
  是真值歧义 → `ValueError`，连续 3 次后被切换器判定为坏模式跳过。
  在 `ModeContext.__init__` 单点收口成 `list(bands)`。新增
  `test_numpy_bands_do_not_break_modes` 回归。
- **面板底部按钮被窗口裁掉**：`_measure()` 按快照里的 `mode_count` 算高度，
  `_draw_modes()` 却按 `app.mode_list` 画，两者不一致时底部超界。
  改为同一份数据源 `_modes()`。
- **折叠态仍在画整块面板**：`_render()` 和 `render_preview()` 各写一份
  绘制顺序，折叠逻辑只改了一边。抽出 `_draw_sections()` 单一入口。
- **折叠态按钮行为反了**：折叠时命中表里那一格仍报 `collapse`，
  点它只会再折叠一次（视觉上是展开图标）。改为按状态报 `expand`。
- 音频模块里 4 处 `print()` 改为 logger（windowed 版没有 stdout）。

### Changed

- 启动脚本仍保留（源码用户），但**首选**是 exe。
- README 安装节改为「方式一：直接用 exe / 方式二：从源码跑」，并说明
  为什么必须用独立 Python 而不是微软商店版。
- exe 带上完整版本资源（`version_info.txt` + `--version-file`）：属性页
  有产品名、文件说明、版本号，不再是空白。

### Known issue — SmartScreen 会拦一次

未签名的独立 exe 从网上下载后首次运行，会看到「Windows 已保护你的电脑」。
这不是病毒告警，是「无代码签名 + 带 Internet 标记」的标准反应。README
的安装节写清了三种处理：点「更多信息 → 仍要运行」、`Unblock-File` /
右键属性解除锁定、或用 `Get-FileHash` 核对哈希后自行决定。

彻底消除需要代码签名证书（EV 立刻建立信誉，OV 需累积下载量）或向微软
提交误报申诉——都不在代码范围内，所以写进文档而不是假装不存在。

### Tests

- 新增 `tests/test_ui.py`（14 项）：高度必须装下所有区块、折叠态只剩
  标题栏、命中区不越界、每个模式按钮可点、点击投递正确命令、拖动后松手
  不算点击、波形峰值保持、频段数异常不崩、离线渲染出图、色调对比度。
- 新增 `tests/test_modes.py` 的 numpy 回归 2 项。
- 合计 **122 项单测 + 1 个端到端冒烟**，全绿；`pyflakes` 全仓零告警。

## [1.6.0] - 2026-11-09

从"一个效果"变成"一套效果系统"。核心是**双引擎**：同一份桌面、同一份
音频，可以走两条完全不同的动画路径，模式自己声明属于哪一档。

### Added — 双引擎

- `jellyicons/modes/base.py`：`Transform`（sx/sy/dx/dy/alpha）+
  `blended(k)` + `clamp(engine)`；`Mode` / `ModeContext` 接口。
- **`overlay` 引擎**：只缩放、绝不位移。`clamp()` 对 overlay 硬性把
  `dx=dy=0`、`alpha=1`，代码级保证"图标永远待在自己格子里"。
- **`takeover` 引擎**：副本可以位移、聚拢、绕圈、拼人形。关键：移动的是
  我们自己的分层窗口，**一个字节都不写 explorer 的图标坐标**，退出时
  副本归位 1:1 再把真图标放回来。所以随时强杀都不会打乱桌面布局
  （这是与把 `LVM_SETITEMPOSITION` 写进 `IconLayouts` 的方案的本质区别）。

### Added — 8 种模式

| 模式 | 引擎 | 说明 |
|---|---|---|
| 律动 `jelly` | overlay | 壁纸原版果冻：压扁回弹 |
| 音浪 `bands` | overlay | 64 段频谱分 8 子带，各图标各跳各的 |
| 烟花 `firework` | overlay | 重拍触发从屏幕中心扩散的涟漪 |
| 自由 `free` | takeover | 随鼓点散开再聚拢 |
| 两年半 `kun` | takeover | 7 槽位拼小人运球，跳满 12 秒一轮才下场 |
| 心动 `heart` | takeover | 图标沿心形参数方程流动 |
| 海浪 `wave` | takeover | 波峰错开、起伏传递 |
| 星环 `ring` | takeover | 三层同心环奇偶反向旋转 |

### Added — 切换器与收敛

- `jellyicons/modes/switcher.py`：自动轮换（每模式 `dwell_s` 停留，
  `kun` 用 `wants_exit()` 等跳完一轮）、手动上/下一个、`BLEND_S=0.20`
  过渡、`WIND_DOWN_S=0.35` 音乐停下时的平滑归位。
- **失败降级**：某个模式的 `tick()` 抛异常时只退化成静止，连续 3 次
  自动跳过该模式——一个模式的 bug 不能拖垮整个程序。

### Added — 控制面板与热键

- `jellyicons/panel.py`：Tk 控制面板（独立线程）。音频设备下拉、64 段
  实时波形（含峰值线）、8 个模式按钮、自动轮换开关、停止按钮、状态行。
  所有交互只 `app.post()` 消息 + `app.snapshot()` 读快照，绝不跨线程
  碰窗口或桌面。tkinter 缺失时静默降级为无面板运行。
- `jellyicons/hotkey.py`：`RegisterHotKey` + 独立消息线程。
  `Ctrl+Alt+F9` 退出、`Ctrl+Alt+→/←` 上/下一个模式、`Ctrl+Alt+Space`
  自动轮换开关。**绝不用 `WH_KEYBOARD_LL`**——低级钩子会堵住系统输入
  队列（历史上真的把鼠标卡死过），`test_no_low_level_hook` 锁死这条。
- `audio_engine.list_loopback_devices()`：枚举可用的 loopback 输出设备，
  `AudioEngine(device_index=...)` 可指定。

### Changed

- 主循环从"单一律动"改为"每帧问切换器要 transforms"；`sx/sy` 降级为
  日志与 `at_rest` 闸门的汇总值。
- 重生签名（跳帧判定）从 `(x, y, size, sx, sy)` 扩到含 `dx/dy/alpha`，
  否则 takeover 每帧位移会被误判为"没变"而跳帧。
- `make_launchers.py` 重写：优先 `.venv\Scripts\python.exe`，其次
  `py -3`、`python`；找不到时给出 `uv venv` 提示。新增
  `启动（无窗口）.bat`。

### Tests

- `tests/test_modes.py`（26 项）：8 模式在极端输入下 600 帧的数值有界性、
  overlay 位移必须硬 0、takeover 必须真的会动、静音时不许大幅形变、
  `Transform.blended/clamp` 契约、切换器轮换/手动/失败降级/归位。
- `tests/test_hotkey.py`（10 项）：默认绑定表、无重复 id、全部带
  `MOD_NOREPEAT`、无低级钩子回归守卫、注册/注销往返。
- `smoke_v13.py` 增加 takeover 位移生效、同签名跳帧、归位正确三项断言。
- **共 105 项单测 + 1 个端到端冒烟，全绿**。
## [1.5.1] - 2026-11-10

修「双击启动.bat，看起来什么都没发生」。

### Fixed — 启动链路

- **启动脚本选中了低完整性的解释器**。`启动.bat` 原来用 `where python`，
  在本机命中的是 `%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe`
  （Microsoft Store 版的 App Execution Alias）。Store 应用跑在 **Low
  完整性**，而桌面图标列表由 explorer（Medium）拥有——Windows 的 UIPI
  不允许低完整性进程通过 UI Automation 读取它的子项，于是
  `snapshot()` 永远返回 0 个图标，程序安静地什么都不做。

  真正的坑藏在文件标签里：`icacls` 显示
  `Mandatory Label\Low Mandatory Level:(I)(NW)` 被继承到了
  `.venv\Scripts\python.exe` 上（工作目录带了该标签）。**Windows 启动
  带 Low 标签的可执行文件时会强制把进程降到 Low**，即使从 Medium 的
  cmd 里启动也一样。把同一个文件复制到 `%LOCALAPPDATA%` 后立刻恢复
  Medium —— 所以这不是代码问题，是选错了解释器。

- **启动脚本改为优先选 Medium 的解释器**：读 `.venv\pyvenv.cfg` 的
  `home` 行拿到 venv 底层的 base python（装在用户 AppData 下，不带该
  标签），再用 `PYTHONPATH` 指到 `.venv\Lib\site-packages`。依次回退
  `py -3`、`python`。`诊断.bat`、`启动（无窗口）.bat`、`静默启动.vbs`
  同样处理。

### Added

- `jellyicons/integrity.py`：读进程完整性（`GetTokenInformation` +
  `TokenIntegrityLevel`），提供 `current_integrity()`、`can_read_desktop()`。
- 启动时自检：完整性不够就**一次性**说清楚原因并退出（返回码 2），
  不再每 0.25 秒刷一行"副本布局不完整"。

### Changed

- 去掉启动脚本里的 `PYTHONIOENCODING=utf-8`：Python 在真控制台上走
  `WriteConsoleW`，任何代码页都能正确显示中文；设了这个变量反而会被
  当成字节流写出，中文变乱码。
- `verify_e2e.py` 重写为**进程内**验证：在 `App._compose` 出口处直接量
  真正送进 `UpdateLayeredWindow` 的画布（`PrintWindow` 抓
  `UpdateLayeredWindow` 表面不可靠，只采到 8 帧、高度序列是
  "抓到/没抓到"）。现在采 500+ 帧，墨迹高度是真的连续起伏。

## [1.5.0] - 2026-11-02

全面审查（约 3500 行）后按优先级修的一批"真会咬人"的问题。
核心原则：**宁可不动，也不要把桌面弄空**。

### Fixed — 桌面安全

- **副本不完整也照样隐藏真图标**：`_prime_before_hide()` 原来只管画，
  不检查画的是不是全部图标。UIA 失败、位图缺失、名称对不上时会出现
  "真图标已隐藏、副本没画出来"的空桌面。现在是硬门槛：必须有有效快照、
  `_desktop_keys` 与 overlay 集合**完全一致**、每一项都绘制成功
  （`ready is True`），任一不满足就保留真图标并 warning。
- **恢复失败仍然清心跳**：`restore()` 原来吞异常、`close()` 无条件清心跳，
  一旦恢复失败看门狗就被"解除武装"，真图标永久消失。现在 `restore()`
  返回 `bool`，只有确认 `IsWindowVisible` 为真才清心跳，失败保留
  `hidden=True` 心跳让看门狗继续重试。
- **`ShowWindow` 返回值被当成成功标志**：它的返回值是"调用前是否可见"，
  不是执行结果。改用 `IsWindowVisible` 判定真实状态。
- **隐藏失败每帧重试**：加 `HIDE_RETRY_S = 0.5` 退避，不再每帧预绘制。
- **正常退出会跳变**：退出前先把缩放归位到 1.0 并按 1:1 重绘，再
  `SW_SHOW`，`EXIT_HOLD_S` 期间继续保留副本，之后才销毁窗口。
- **隐藏期布局冻结**：音乐模式期间 explorer 的 UIA 快照不可信，恢复后
  强制 `_needs_resync` 完整重同步。

### Fixed — 资源与并发

- **PIDL 泄漏**：`enum_desktop_items()` / `build_icon_cache()` /
  `_desktop_pidl_map()` 全部改为 try/finally 所有权管理，枚举器、桌面
  文件夹、`STRRET` 的 `pOleStr`、每个 `ILCombine` 结果都释放。
- **多开互踩心跳**：新增 `SingleInstance`（`Local\JellyIcons.SingleInstance`
  互斥体），第二个实例直接退出，不再覆盖/清除别人的心跳。
- **重名图标串图**：`build_icon_cache()` 现在按 `name`、`name#1`、`name#2`
  分键存各自位图；`_dedupe()` 的编号规则与它对齐（首个用原名）。
  `_hit_test()` 与双击目标也改用唯一 key。
- **双击目标不猜**：扩展名宽松匹配只在**唯一**命中时采用，重名不再乱开。
- **音频流中断后一直"有音乐"**：回调记录 `_last_callback`，超过
  `AUDIO_STALE_S = 0.5` 按静音处理；`is_active()` 为假则标记不可用，
  主循环每 `AUDIO_RETRY_S = 2.0` 尝试重开设备。
- **新图标不显示**：位图缺失时按 5 秒节流增量重载，新增/重命名无需重启。

### Added

- `jellyicons/single_instance.py`：单实例互斥。
- `config.IDLE_FPS = 15`：真图标显示时降到 15 FPS（隐藏期仍 60）。
- 缩放结果缓存 `_scaled_cache`（上限 512），`_calibrate_side()` 变化时清空。
- `diagnose.py` 第 5 项从"名称交集"升级为**副本覆盖率报告**，直接告诉你
  能不能安全隐藏真图标。
- 测试从 47 项增到 **69 项**：`test_audio.py`（5）、`test_pidl.py`（5）、
  `test_single_instance.py`（4），`test_music_mode.py` 增恢复失败/隐藏退避
  用例，`test_app.py` 增覆盖率门槛用例。
- `verify_hide.py`：真实 ListView 隐藏/恢复验证脚本，finally 保证恢复。

### Changed

- 删除从未使用的 `JELLY_MAX_H`、`LABEL_FADE_S`、`HOVER_SCALE`。
- `smoke_v13.py` 增加覆盖率断言。
- pyflakes 零告警。

## [1.4.0] - 2026-11-01

针对"动画幅度有点小"的量化排查与调参。先说结论：幅度确实偏小，
横向几乎看不出来。

### 量化（56px 图标，驱动真实 ActivityDetector + JellyState 模拟）

| 场景 | v1.3 横向 | v1.3 纵向 | v1.4 横向 | v1.4 纵向 |
|---|---|---|---|---|
| 强低频（舞曲） | +2.9%，峰峰 0.9px | -8.9%，峰峰 4.0px | +16.1%，峰峰 4.2px | -18.8%，峰峰 6.1px |
| 轻音乐 | +1.9%，峰峰 0.8px | -6.0%，峰峰 4.0px | +12.6%，峰峰 5.2px | -15.4%，峰峰 7.7px |
| 持续无起伏音量 | pulse 恒 0，完全不动 | — | +16.1%，峰峰 4.2px | -18.8%，峰峰 6.1px |

### Fixed
- **横向拉伸几乎看不见**：`AGC_TO_VOL` 0.055 → 0.10。原来 pulse 峰值
  只有 0.0297，仅用到壁纸 pulse 上限（0.055）的 54%。0.10 让 pulse
  打到约 0.0377（68% 上限），保留衰减余量、不会每帧顶死。
- **持续音量完全不动**：`process_pulse` 的 beat 判定要求音量跳升 10%，
  平稳段落永远不触发。调高 `AGC_TO_VOL` 后 steady 场景也能动。
- **bounce 抖动被吃掉一半**：原来 `scaleY += (sin(φ)-1)*amp` 恒带
  `-amp` 偏置，等于把整条曲线下移半幅。改成 `scaleY -= |sin(φ)|*amp`
  只在压缩侧打半波，幅度翻倍且 `sy>1` 帧数仍为 0。
- **横向拉伸会裁边**：`CANVAS_MARGIN` 2 → 4，画布宽度改为按
  `JELLY_MAX_W` 预留（不再用 `side + 2*margin`），本体右边缘不再被裁。

### Added
- `config.JELLY_GAIN_X = 4.2` / `config.JELLY_GAIN_Y = 1.8`：相对壁纸原版
  的变形增益。横向天生不如纵向显眼（只变宽 vs 改变轮廓高度），
  实测 X 需要比 Y 大得多的增益。
- `config.JELLY_MAX_W = 1.35`：画布按理论上限预留本体最大横向放大。
- `tests/test_app.py::test_canvas_fits_max_stretch`：最大拉伸时本体不得
  超出画布（裁边回归）。
- `tests/test_jelly.py::test_scale_bounds_pulse_cap` 增补两条断言：
  实际峰值必须明显看得出在拉（横向 ≥ +8%），且理论上限不超过画布预留。

### Changed
- `tests/test_app.py::test_canvas_independent_of_scale` 扫描区间扩到
  `0.88 ~ 1.22`，覆盖新的放大范围（原来只到 1.0825）。
- `test_body_anchored_bottom_center` 改用 `config.CANVAS_MARGIN` 而非
  硬编码 2，避免留白调整时假失败。
- 单测 46 → 47 项。

## [1.3.0] - 2026-11-01

针对 v1.2.0 的三个反馈（"要播放一会儿才隐藏""隐藏后图标左右动"
"切换不够连贯"）重做核心链路，并新增双击打开。

### Added
- **双击副本打开真实应用**（`jellyicons/click_open.py`）：
  - 只读轮询：`GetAsyncKeyState(VK_LBUTTON)` 取按下沿 + `GetCursorPos`
    + `GetDoubleClickTime`/`SM_CXDOUBLECLK`/`SM_CYDOUBLECLK` 判双击。
    不装全局钩子，也不给 overlay 去掉 `WS_EX_TRANSPARENT` —— 后者会把
    拖动/删除/框选/右键全部吃掉，是旧版踩过的坑。
  - 打开方式实测取舍：`ShellExecuteExW + SEE_MASK_INVOKEIDLIST + lpIDList`
    在本机恒返回 `ERROR_CANCELLED(1223)`，不可用；改用
    `SHGetNameFromIDList(SIGDN_DESKTOPABSOLUTEPARSING)` 把 PIDL 转成
    `::{GUID}`（此电脑/回收站/控制面板等虚拟项）或 `D:\path`
    （文件系统项），再 `ShellExecuteW("open", name)`。
  - 仅在音乐模式隐藏真图标期间启用。
- `jellyicons/activity.py`：**音频活动度检测 + 逐频段 AGC**。
  Wallpaper Engine 交给壁纸的 `audioData` 是它做过 AGC 的 64 段数据，
  低频常年 0.3~1.0；我们原来除以"全频段最大峰值"，低频被中高频压到
  中位数 0.011。现在每段各自跟踪峰值、慢衰减、再归一化。
- `config.py` 新增 `AGC_*`/`ENV_*`/`LEVEL_WEIGHT`/`AGC_TO_VOL`/
  `CANVAS_MARGIN`/`LABEL_GAP`/`EXIT_HOLD_S` 等常量。
- `overlay.py` 新增 `hide()`。
- `shell_icons.system_icon_font()`：读 `SPI_GETICONTITLELOGFONT` 拿系统
  真实的图标标题字体（本机实测 `msyh.ttc` / 12px），标签不再猜字号。
- `tests/test_activity.py`（11 项）；`smoke_v13.py` 端到端冒烟（真窗口 +
  假快照 + 假音乐）。

### Fixed
- **隐藏后图标左右乱动**（根因：窗口 x 随 `sx` 变化）。
  旧 `_origin()` 用 `x0 = cx - int(side*sx)//2`，`int()` 截断使窗口 x
  随缩放抖 1~2px；而 hidden 态合成画布宽固定，两态基准不同还会横跳 8px。
  现在每个图标一块**固定尺寸画布**（`_layout`），窗口 x/y 只由
  `icon.rect` 与画布尺寸决定，与 `sx/sy` 完全无关。
  `test_canvas_independent_of_scale` 锁死这条。
- **Q 弹动画被跳帧逻辑吃掉**：画布尺寸固定后，`_last_state` 若只含
  尺寸，缩放变化会被判"未变化"而跳过重绘。现在状态元组带上
  `(qx, qy)`（`test_scale_change_forces_redraw` 锁死）。
- **隐藏延迟好几秒**：旧判定要 `bass ≥ 0.03` 连续 0.75s，而旧 bass
  中位数只有 0.011、仅 30% 采样过线。现在用 presence（包络 + AGC），
  阈值 0.02 持续 0.15s → 播放到隐藏约 0.2 秒。
- **切换闪空桌面**：隐藏前先 `_prime_before_hide()` 把副本按 1:1 画满，
  再 `SW_HIDE`；恢复后保留副本 `EXIT_HOLD_S=0.12` 秒等 explorer 重绘
  完成再撤。两帧都是零变化。
- **AGC 底噪误触发音乐模式**：AGC 是相对增益，耳机底噪（~0.0005）会被
  放大到 0.025 越过阈值。新增绝对噪声门 `AGC_GATE=0.0015`（实测很轻的
  音乐低频是 0.00946，不会被误伤）。
- **看门狗可能提前退出**：心跳文件原来截断重写，60fps 覆写时读端会读到
  空文件 → 误判主进程已退出 → 强杀保护失效（实测 5 次轮询只有 1 次读到
  内容）。改为 `.tmp` + `os.replace` 原子替换；读到空内容视为并发写入而
  非退出。主进程心跳限频到 0.25s（状态变化时立即写）。
- **音乐模式状态卡在 `init`**：启动时本来就静音的场景，`state` 一直停在
  `STATE_INIT`。现在首个未达开阈值的帧直接落到 `STATE_SHOWN`。

### Changed
- `music_mode.feed(presence, now, allow_exit=True, before_enter=None)`：
  入参语义从裸 bass 改为 presence；`allow_exit=False` 时只允许进入隐藏
  （主循环用它做"等缩放回落到 1.0 再切回真图标"的闸门）；`before_enter`
  在隐藏真图标**之前**执行预绘制。
- 音乐模式阈值：开 `0.02` / 持续 `0.15s`，关 `0.008` / 持续 `1.0s`
  （原来是 0.03/0.75s 与 0.015/3s）。
- `audio_engine._compute_bands()` 不再做全局峰值归一化，返回原始幅度；
  `bass_level()` 降级为兼容接口（只给日志用）。

## [1.2.0] - 2026-10-31

### Added
- **音乐模式**：检测到音乐低频时，真实桌面图标自动隐藏，改由 overlay
  绘制"图标本体 + 文字标签"的果冻副本；音乐停止 3 秒后自动恢复。
  - 隐藏动作 = `ShowWindow(SysListView32, SW_HIDE)`，与 Windows 自带
    "右键桌面 → 查看 → 显示桌面图标"开关操作的是同一个窗口，逐像素
    一致、瞬时、完全可逆；不写注册表、不改窗口样式。
  - 滞回判定（`config.py`）：开 = bass ≥ 0.03 持续 0.75s，
    关 = bass ≤ 0.015 持续 3s，避免节拍间隙来回闪。
  - `jellyicons/music_mode.py`：状态机 + 每次动作前重查句柄（explorer
    重启后句柄会变）+ 恢复失败每帧重试。
  - `jellyicons/watchdog.py`：心跳文件 `JellyIcons/.heartbeat.json`；
    进程被强杀时，独立看门狗子进程（DETACHED_PROCESS）在 ~1s 内
    检测失联并恢复图标显示。正常退出会删心跳文件，看门狗随之退出。
  - 用户本来就把图标隐藏了（`HideIcons=1`）时音乐模式自动禁用，
    不代用户做决定。
  - 隐藏期间 overlay 补画文字标签（真标签随 ListView 一起消失），
    标签不参与 Q 弹变形，与原生一致。
- `[stat]` 健康行增加 `music=shown/hidden` 字段。

### Fixed
- `[stat]` 每 5 秒重置计时起点，导致 `elapsed` 永不增长、限时运行的
  退出条件永不满足。
- 图标本体位置按"格高 × 0.70"估算，随图标尺寸漂移；改为原生布局的
  `格子顶 + ICON_TOP_PAD + 本体边长`，音乐模式下的文字标签不再溢出
  到下一行格子。
- 音乐模式禁用时状态机停在 `init` 而非 `shown`。

## [1.1.0] - 2026-10-31

### Added
- `诊断.bat` / `python run.py --diagnose [秒]`：5 项链路自检（完整性、
  音频、位图、UIA 布局、名称对齐），UIA 失败时转储 Progman→DefView→
  ListView 窗口链。
- `jellyicons/logutil.py`：控制台 + `JellyIcons.log` 双路日志，自动轮转
  （1 MB × 3 备份）。
- 主循环每 5 秒输出 `[stat]` 健康行（overlays/bass/scale/fps/redraw）。
- `tests/test_app.py`：同步去重、消失移除、尺寸重校准、帧跳过共 4 项单测。
- `requirements.txt`、`LICENSE`（MIT）、本 CHANGELOG。

### Fixed
- UIA 桌面列表定位改用 `FindWindow` 句柄链 + `ElementFromHandle`
  （原 UIA 树遍历在真机上恒返回 0 项）。
- `_sync_overlays` 二次同步 `move()` 参数笔误导致的崩溃。
- 重名桌面项互串：同步 key 改为"重名加序号"的唯一下标。
- DPI 感知缺失：创建窗口前 `SetProcessDpiAwareness(2)`，缩放屏不再错位。
- 静音稳态每帧重绘全部窗口的 CPU 浪费：缩放差 < 0.001 整帧跳过。
- 图标尺寸变化（改 DPI/图标大小）时自动重建缩放缓存。
- `diagnose.py`：duration 缺省 TypeError、IntegrityError 路径
  UnboundLocalError。

## [1.0.0] - 2026-10-30

首次交付。UIA 只读 + 全穿透 overlay 的干净架构；壁纸 3795008547 的
processPulse/updateScale 逐行移植；WASAPI loopback 64 段对数频谱；
9 项律动模型单测。
