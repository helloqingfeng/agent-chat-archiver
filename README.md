# Agent 聊天记录归档器

<img src="assets/logo.png" width="140" alt="图标：一个带笑脸的归档纸箱，右上角有对话气泡">

一个无需第三方运行时依赖的 Windows 小工具：选择 Agent 工具后，扫描本机预设会话目录，输出单文件、可离线打开的 HTML。

## v11 更新

- **新增应用图标**：窗口、任务栏和打包后的 EXE 都使用同一枚图标。图标由 `make_icon.py` 用 Pillow 绘制生成（`assets/icon.ico` / `icon.png` / `logo.png`），改配色或形状后重新运行该脚本即可；应用本身仍只依赖标准库，Pillow 仅用于生成图标。

## v10 修复重点

- **同一会话跨用户目录合并后不再重复**。多个 Windows 用户目录（例如旧系统迁移过来的 `E:\Users\用户名`）里的同一段会话会合并成一张卡片，正文不再出现重复消息。合并结果按“角色 + 正文 + 分钟级时间戳”去重：同一会话在新旧目录各存一份会合并，而你在不同时间真的重复发过的话仍会保留。
- **合并后的卡片会列出全部来源路径**，方便核对一条会话到底来自哪几个用户目录。
- **WorkBuddy 不再误收无关文档**。以前只要路径中出现 `automation*` 或 `.workbuddy` 就会被当作会话输出收录，现在只认文件上 1~2 层内真正名为 `memory`/`brain`/`automations` 的目录。实测从本机数据中剔除了 32 个 `longbridge` SDK 文档。
- **新增扫描进度条和“取消”按钮**。进度条按文件数显示真实百分比（先轻量统计文件数，再解析），点“取消”会在当前文件处理完后停止，且不生成 HTML。
- **修复偶发崩溃**：扫描线程不再访问界面控件，避免 Tk 跨线程访问导致的随机报错。
- 截断的 `<system-reminder>` 标签（只有开标签、没有闭合）现在也会被剥离。

## 使用

推荐直接双击 `dist\AgentChatArchiver-v10.exe`。也可双击 `启动Agent归档器.bat` 运行源码版。

勾选工具后点击“开始扫描并生成 HTML”，进度条会显示 `已处理/总数`。点击“添加文件夹”可以连续选择多个自定义会话目录，选中目录后可点击“移除选中”。首次运行或修改了数据位置时，建议勾选“强制全量重新扫描”。扫描中途可点“取消”。

也可以命令行运行：

```powershell
python agent_chat_archiver.py --cli --tool Claude --tool Codex --output D:\AgentArchive
```

命令行添加其他工具的目录：

```powershell
python agent_chat_archiver.py --cli --custom E:\my-agent\sessions
```

当前预设：Claude、Codex、Cursor、QwenWork、OpenClaw、ZCode、WorkBuddy、豆包、千问办公、Qoder、opencode、DeepSeekHarness、antigravity、NewMax。程序会检查当前用户目录、Windows 用户文件夹注册表以及各盘符下的 `Users` 目录，以兼容迁移过的配置。

发现多个用户目录时会**全部扫描并合并到同一份归档**（例如旧系统迁移过来的 `E:\Users\用户名`）。同一段会话如果在新旧目录各存一份，会合并成一张卡片，卡片“来源”处列出全部路径；正文按“角色 + 正文 + 分钟级时间戳”去重，因此不同时间真的重复发过的话仍会各自保留。不需要旧目录的数据时，改用“添加文件夹”只指定需要的目录即可。

输出位置填写文件夹即可，程序会自动生成不覆盖旧文件的名称，例如 `Claude-Codex_20261005-143022.html`；多次生成同一秒时会追加 `_01`、`_02`；勾选的来源过多时文件名会简化为“首个工具-等N个来源”。

扫描器按工具使用不同的本地数据目录和格式：

- ZCode：优先读取 `.zcode\cli\db\db.sqlite`（完整会话，含用户消息和 AI 生成的标题）；rollout `model-io` 文件仅在其缺失时提供补充，另外扫描 `.zcode\cli\log` 和工作区报告。
- 千问办公/Qoder：优先扫描各自 `.qwenworkcn\projects`、`.qoder\projects` 下的 JSONL。
- WorkBuddy：扫描 `.workbuddy\sessions`、`brain`、`projects`，并收集 memory、automations 及 `automation-*` 目录下的 Markdown 输出（每日记忆、自动推送日报、自动化报告等）。这些目录必须位于文件上 1~2 层内，因此顺带存在 `automation-*` 文件夹里的无关项目文档（例如某个 SDK 的 `references\*.md`）不会被收录。
- NewMax：优先扫描 `.newmax\conversations\*\messages.jsonl`。
- antigravity：扫描 `.gemini\antigravity\brain` 下的 transcript JSONL 和 Markdown 结论文档。
- Claude：扫描 `.claude\projects`、`.claude\sessions` 和 `AppData\Local\Claude-3p\local-agent-mode-sessions*`；读取 Cowork 的 `audit.jsonl`，并把每个会话 `outputs\*.md` 加入同一会话卡片。

其余工具也会扫描对应的预设目录；没有匹配目录会显示跳过，只有缓存/数据库而没有可读文本时会显示已扫描文件数。不同工具如果使用数据库或加密缓存，建议用“添加文件夹”指定其导出目录或会话目录。如果最终一条记录都没提取到，界面会提示改用其他工具或自定义目录。

扫描结果会按“路径 + 大小 + 修改时间”缓存到 `%LOCALAPPDATA%\AgentChatArchiver\index.json`，文件没变就直接复用上次的解析结果，重复生成会快很多；命令行可用 `--no-cache` 强制全量重新解析。注意缓存只影响速度：合并、去重和排序每次都会重新执行，所以改了数据位置或想强制重算时不必手动删索引。GUI 会记住上次勾选的工具、自定义目录、输出文件夹和缓存选项。

如果结果仍为 0：先查看界面扫描日志。若真实数据在日志没有出现的位置，用“添加文件夹”选中对应工具的根目录；若日志显示“拒绝访问”，请用拥有该目录权限的 Windows 账号运行，不要以另一个账号或受限沙箱运行。

修改解析逻辑后，运行 `python -m unittest test_agent_chat_archiver` 可执行最小测试套件。

## 开发

打包只需一条命令，版本号就是文件名后缀：

```bash
python build.py v11
```

它调用仓库里唯一的 `AgentChatArchiver.spec`（版本号通过 `ACA_NAME` 传入，因此不再需要为每个版本复制 spec），生成 `dist\AgentChatArchiver-v11.exe` 和 `AgentChatArchiver-Windows-v11.zip`，并打印两者的 SHA256。不带版本号则生成 `AgentChatArchiver.exe`。

图标由 `python make_icon.py` 生成到 `assets/`（需要 Pillow，仅开发时用）；spec 会把 `assets/icon.ico` 同时作为 EXE 图标和随包数据打进可执行文件。

仓库只跟踪源码、测试、README 和构建配置；`build\`、`dist\`、发布 ZIP、`__pycache__` 以及生成的归档 HTML 都在 `.gitignore` 中。行尾由 `.gitattributes` 统一（文本存 LF，`.bat` 保持 CRLF），不受本机 `core.autocrlf` 设置影响。
