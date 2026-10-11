# Prompt Manager

[简体中文](#简体中文) | [English](#english)

---

## 简体中文

**Prompt Manager** 是一个本地优先的桌面提示词管理器，使用 Python + PySide6 构建。它以 Markdown 作为提示词的原生格式，提供占位符替换、固定预设导入、分组与置顶、拖拽导出，并内置一个可选的 Agent 面板（通过 OpenAI 兼容接口调用外部模型）来辅助管理本地提示词。

所有数据保存在本地 SQLite 数据库中，不上传云端，不依赖外部服务。

### 核心特性

- **双类别管理**：区分「提示词预设」与「固定预设」。固定预设可以被其他提示词通过 `=====IMPORT: 名称=====` 引用，从而组合出可复用的提示词片段。
- **占位符替换**：使用 `=====REPLACE: 标题=====` 标记需要用户填写的部分。渲染时会弹出输入对话框，输入值会被记忆，下次使用自动填充。
- **Markdown 编辑器**：基于 `QPlainTextEdit` 的实现，带语法高亮、标题折叠、行内查找/替换、选中扩展、整行复制/剪切、整行上移/下移，以及 `=====IMPORT:` 名称自动补全（支持中文拼音首字母匹配）。
- **渲染预览**：在编辑与 Markdown 渲染视图之间一键切换，不破坏编辑器撤销栈。
- **分组、置顶与拖拽排序**：条目可以放入一级分组，也可以置顶。支持在同一分组或同一置顶区域内拖拽排序。
- **拖拽为文件**：从列表拖出条目即会生成临时 Markdown 文件，可拖入其他编辑器或聊天窗口；临时文件会在可配置的保留时间后自动清理。
- **本地数据库备份与恢复**：一键备份到数据目录下按日期命名的文件夹，可从历史快照恢复数据库。
- **Agent 面板（可选）**：内嵌对话界面，支持 OpenAI、Ollama、Gemini 和 GLM 的 OpenAI 兼容接口。Agent 可以调用一组受控工具来列出、读取、创建、更新、删除提示词，并管理分组。生成回复前会自动创建数据库快照，程序关闭时清理。
- **临时文本**：一个独立的 Markdown 便签面板，内容自动保存，用于在编辑提示词时随手记录。
- **可自定义快捷键**：所有编辑与导航操作均可在设置中查看和修改，并会检测重复冲突。
- **跨平台打包**：`build.py` 使用 PyInstaller 生成单文件可执行程序，并在 Windows / macOS 上自动生成多分辨率图标。

### 技术栈

| 组件 | 说明 |
| --- | --- |
| 语言 | Python ≥ 3.10 |
| GUI | PySide6 ≥ 6.6, < 7 |
| 存储 | SQLite（`sqlite3` 标准库），WAL 模式 |
| HTTP | `urllib.request`（标准库），无第三方 HTTP 依赖 |
| 打包 | PyInstaller（`build.py` 中调用） |

### 项目结构

```text
prompt_manager/
├── __init__.py                  # 包版本
├── __main__.py                  # python -m prompt_manager 入口
├── app.py                       # 应用主入口、日志、Windows 任务栏身份
├── service.py                   # 用例层：校验、渲染、备份等
├── storage.py                   # SQLite 仓储、备份/恢复/迁移
├── models.py                    # Prompt / PromptGroup 领域模型
├── placeholders.py              # REPLACE / IMPORT 标记解析与渲染
├── agent.py                     # OpenAI 兼容传输层与工具定义
├── agent_panel.py               # 内嵌 Agent 对话面板
├── database_maintenance.py      # 备份线程、恢复对话框、Agent 会话快照
├── drag_exports.py              # 拖拽导出的临时 Markdown 管理
├── editor.py                    # Markdown 编辑器与查找/替换栏
├── editor_highlighting.py       # 语法高亮、折叠标记、解析辅助
├── icon.py                      # 程序化绘制的应用图标
├── logging_setup.py             # 轮转日志与异常钩子
├── ui.py                        # 主窗口
├── ui_actions.py                # 数据库维护与 Agent 工具执行
├── ui_constants.py              # 样式表、默认快捷键、列表项角色
├── ui_list_actions.py           # 列表、分组、置顶、拖拽排序
├── ui_settings.py               # 设置对话框与模型列表刷新
└── ui_widgets.py                # 列表行、填充对话框、拖拽列表控件
launcher.py                      # PyInstaller 入口
build.py                         # 打包脚本
pyproject.toml                   # 项目元数据与依赖
```

### 环境要求

- Python 3.10 或更高版本
- 一个可用的图形桌面环境（PySide6 依赖 Qt 的平台支持）
- 可选：本地 Ollama 服务，或 OpenAI / Gemini / GLM 的 API Key（仅在使用 Agent 面板时需要）

### 安装

从源码运行：

```bash
git clone https://github.com/AlyoshaLV999/Prompt-Manager.git
cd Prompt-Manager

# 建议使用虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e .
```

也可以直接安装依赖而不安装包本身：

```bash
pip install "PySide6>=6.6,<7"
```

### 运行

三种等价的启动方式：

```bash
# 已安装为包
prompt-manager

# 未安装包，直接以模块运行
python -m prompt_manager

# 使用 PyInstaller 入口脚本
python launcher.py
```

#### 命令行选项

| 选项 | 说明 |
| --- | --- |
| `--data-dir PATH` | 覆盖默认的数据目录（数据库与日志所在位置） |
| `--migrate-from PATH` | 首次启动时从指定的旧版 SQLite 数据库导入 |

示例：

```bash
python -m prompt_manager --data-dir ./local-data
```

### 数据与配置

所有持久化内容都存放在**数据目录**中的 `prompts.sqlite3` 内，包括：提示词、分组、占位符记忆值、应用设置、临时文本、以及所有 Agent 服务商配置（含 API Key）。

数据目录的解析顺序：

1. 命令行 `--data-dir` 参数
2. 环境变量 `PROMPT_MANAGER_DATA_DIR`
3. 平台默认目录：
   - Windows：`%APPDATA%\PromptManager`
   - macOS：`~/Library/Application Support/PromptManager`
   - Linux：`$XDG_DATA_HOME/prompt-manager`（缺省为 `~/.local/share/prompt-manager`）

日志写入数据目录中的 `prompt_manager.log`，单文件上限 10 MiB，保留 5 个轮转文件。

#### 环境变量

| 变量 | 用途 |
| --- | --- |
| `PROMPT_MANAGER_DATA_DIR` | 覆盖默认数据目录 |
| `PROMPT_MANAGER_LEGACY_DATABASE` | 指定旧版数据库路径（迁移候选项） |
| `OPENAI_API_KEY` | 在未保存 Key 时作为 OpenAI 服务商的后备 Key |
| `GEMINI_API_KEY` | 同上，用于 Gemini |
| `GLM_API_KEY` | 同上，用于 GLM |

> Agent 面板中保存的 API Key 会被持久化到本地数据库。环境变量仅作为未填写 Key 时的后备来源。

#### 旧版数据库迁移

如果你曾在旧版本中使用过本项目，且数据库位于可执行文件或工作目录旁边，程序首次启动时会自动尝试迁移。也可以显式指定：

```bash
python -m prompt_manager --migrate-from /path/to/old/prompts.sqlite3
```

### 使用方法

#### 提示词与固定预设

1. 左侧选择「提示词预设」或「固定预设」。
2. 点击「新建」创建条目，或点击已有条目编辑内容。
3. 编辑区支持 Markdown 语法高亮和标题折叠，修改会在 650 毫秒后自动保存。
4. 在「固定预设」中编写的片段可以通过 `=====IMPORT: 片段名称=====` 被其他提示词引用；导入是递归的，并会检测循环引用。

#### 占位符

在内容中写入：

```markdown
=====REPLACE: 目标语言=====
```

点击「渲染」（或双击列表中的条目）时，会弹出输入对话框收集值。输入内容会以标题为键记忆在该条目下，下次自动带出。渲染时会先递归展开所有 `IMPORT`，再替换所有 `REPLACE`。

#### 分组、置顶与排序

- 点击列表右上角的「新建分组」创建一级分组。
- 每个条目行上的 ☰ 按钮用于设置所属分组；📌 用于置顶。
- 在同一条目区域内拖拽即可调整顺序；将条目拖到分组标题上即可移入该分组。

#### 拖拽导出

从列表中直接拖出条目即可将渲染后的 Markdown 作为临时文件导出，可拖入其他编辑器或聊天窗口。临时文件保存在数据目录下的 `drag_export_md/`，超过保留时间后自动清理。保留时间在「设置 → 快捷键」页面中配置，范围 1 到 1440 分钟。

#### 数据库备份与恢复

- **备份数据库**：在 Agent 面板顶部的按钮区点击「备份数据库」，快照会写入数据目录下按 `YY-MM-DD` 命名的文件夹。
- **恢复数据库**：点击「恢复数据库」，从列表中选择一个快照，确认后会覆盖当前数据库并刷新界面。

#### Agent 面板

点击左下角的「Agent」按钮打开面板。在「设置 → Agent 设置」中选择服务商并填写 API 地址、模型和 API Key：

| 服务商 | 默认 API 地址 | 默认模型 |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Ollama | `http://localhost:11434/v1` | `qwen2.5:7b` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` |
| GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |

Agent 支持的能力：

- 列出、读取、创建、更新、删除提示词
- 列出与创建一级分组、把提示词移入或移出分组
- 在编辑器中打开指定提示词
- 读取聊天中附加的本地文本文件（可拖拽到输入框）

Agent 使用的模型可以通过工具调用操作本地数据库。每次生成回复之前，程序会自动对数据库做一次带标记的快照，关闭程序时清理这些快照。你也可以随时点击「备份数据库」生成长期保留的手动备份。

#### 快捷键

所有快捷键在「设置 → 快捷键」中可查看和修改。默认值包括：

| 动作 | 默认快捷键 |
| --- | --- |
| 插入替换占位符 | `Ctrl+Alt+R` |
| 插入导入占位符 | `Ctrl+Alt+I` |
| 打开设置 | `Ctrl+,` |
| 查找 | `Ctrl+F` |
| 查找和替换 | `Ctrl+R` |
| 扩展选区 | `Ctrl+W` |
| 复制整行（无选区时） | `Ctrl+C` |
| 剪切整行（无选区时） | `Ctrl+X` |
| 上移/下移当前行 | `Alt+Shift+↑` / `Alt+Shift+↓` |
| 折叠/展开当前段落 | `Ctrl+-` / `Ctrl++` |
| 递归展开当前段落 | `Ctrl+Alt++` |
| 展开/折叠全部段落 | `Ctrl+Shift++` / `Ctrl+Shift+-` |
| 重命名条目 | `F2` |

此外，双击 `Shift` 会复制当前选中的提示词。

### 构建可执行文件

`build.py` 使用 PyInstaller 生成单文件可执行程序。需要先安装 PyInstaller：

```bash
pip install pyinstaller
python build.py
```

输出位于 `dist/`，Windows 和 macOS 会自动生成并嵌入多分辨率应用图标；Linux 下由 Qt 在运行时设置窗口图标。

可执行文件不会打包用户数据。数据库始终位于上面所述的数据目录中，替换可执行文件不会影响你的提示词和设置。

### 数据安全说明

- Agent 生成的回复可能调用工具修改本地数据库。每次生成前都会拍摄快照，`关闭程序时会删除本次运行的 Agent 快照`。如果你需要在关闭程序后仍保留一份可恢复的状态，请在需要时手动点击「备份数据库」。
- 恢复数据库会完整覆盖当前的提示词、分组、设置和临时文本，操作不可撤销。

### License

MIT

---

## English

**Prompt Manager** is a local-first desktop prompt manager built with Python and PySide6. It treats Markdown as the native format for prompts, and provides placeholder substitution, fixed-preset imports, grouping and pinning, drag-to-export, plus an optional Agent panel that talks to any OpenAI-compatible provider to help you organize your local prompts.

All data lives in a local SQLite database. Nothing is uploaded, and no external service is required.

### Features

- **Two categories**: "Prompt presets" and "Fixed presets". Fixed presets can be referenced from other prompts via `=====IMPORT: Name=====`, letting you compose reusable snippets.
- **Placeholder substitution**: Use `=====REPLACE: Title=====` to mark user-fillable sections. Values are collected through a dialog, remembered per prompt, and pre-filled next time.
- **Markdown editor**: Built on `QPlainTextEdit`, with syntax highlighting, heading folding, in-place find/replace, selection expansion, whole-line copy/cut, move line up/down, and `=====IMPORT:` name completion (with Chinese pinyin-initial matching).
- **Render preview**: Toggle between editing and a rendered Markdown view without disturbing the undo stack.
- **Groups, pinning, drag reorder**: Prompts can be placed into first-level groups or pinned. Reordering is supported within the same group or pinned region.
- **Drag out as a file**: Dragging an entry out of the list writes a temporary Markdown file that can be dropped into other editors or chat windows. Temporary files expire after a configurable retention period.
- **Local backup and restore**: One-click backup into a date-named folder inside the data directory, and restore from any historical snapshot.
- **Optional Agent panel**: An embedded chat UI supporting OpenAI, Ollama, Gemini, and GLM's OpenAI-compatible endpoints. The Agent can call a controlled set of tools to list, read, create, update, and delete prompts, and to manage groups. A database snapshot is taken before every generated reply and cleaned up on shutdown.
- **Temporary text**: An independent Markdown scratch pad, autosaved, for jotting notes while editing prompts.
- **Customizable shortcuts**: Every editing and navigation action can be viewed and remapped in settings, with duplicate detection.
- **Cross-platform packaging**: `build.py` invokes PyInstaller to produce a single-file executable, generating multi-resolution icons on Windows and macOS.

### Tech Stack

| Component | Detail |
| --- | --- |
| Language | Python ≥ 3.10 |
| GUI | PySide6 ≥ 6.6, < 7 |
| Storage | SQLite (`sqlite3`), WAL mode |
| HTTP | `urllib.request` from the standard library |
| Packaging | PyInstaller, driven by `build.py` |

### Project Structure

```text
prompt_manager/
├── __init__.py                  # Package version
├── __main__.py                  # python -m prompt_manager entry
├── app.py                       # App entry, logging, Windows taskbar identity
├── service.py                   # Use cases: validation, rendering, backups
├── storage.py                   # SQLite repository, backups, migration
├── models.py                    # Prompt / PromptGroup domain models
├── placeholders.py              # REPLACE / IMPORT marker parsing and rendering
├── agent.py                     # OpenAI-compatible transport and tool schema
├── agent_panel.py               # Embedded Agent conversation panel
├── database_maintenance.py      # Backup thread, restore dialog, Agent session snapshots
├── drag_exports.py              # Temporary Markdown exports for dragging
├── editor.py                    # Markdown editor and find/replace bar
├── editor_highlighting.py       # Syntax highlighting, folding, parsing helpers
├── icon.py                      # Programmatically drawn application icon
├── logging_setup.py             # Rotating log and exception hooks
├── ui.py                        # Main window
├── ui_actions.py                # Database maintenance and Agent tool dispatch
├── ui_constants.py              # Stylesheet, default shortcuts, list item roles
├── ui_list_actions.py           # List, grouping, pinning, drag reorder
├── ui_settings.py               # Settings dialog and model list refresh
└── ui_widgets.py                # List rows, fill dialog, drag list widget
launcher.py                      # PyInstaller entry point
build.py                         # Packaging script
pyproject.toml                   # Project metadata and dependencies
```

### Requirements

- Python 3.10 or newer
- A graphical desktop environment supported by Qt (required by PySide6)
- Optional: a local Ollama server, or API keys for OpenAI / Gemini / GLM (only needed to use the Agent panel)

### Installation

Run from source:

```bash
git clone https://github.com/AlyoshaLV999/Prompt-Manager.git
cd Prompt-Manager

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e .
```

You can also install dependencies without installing the package itself:

```bash
pip install "PySide6>=6.6,<7"
```

### Running

All three entry points are equivalent:

```bash
# Installed as a package
prompt-manager

# As a module without installing
python -m prompt_manager

# Via the PyInstaller entry script
python launcher.py
```

#### CLI options

| Option | Description |
| --- | --- |
| `--data-dir PATH` | Override the default data directory (database and logs) |
| `--migrate-from PATH` | Import from a legacy SQLite database on first launch |

Example:

```bash
python -m prompt_manager --data-dir ./local-data
```

### Data and Configuration

Everything persistent lives in a single SQLite file `prompts.sqlite3` inside the **data directory**: prompts, groups, remembered placeholder values, application settings, temporary text, and all Agent provider configuration (including API keys).

The data directory is resolved in this order:

1. The `--data-dir` command-line option
2. The `PROMPT_MANAGER_DATA_DIR` environment variable
3. Platform default:
   - Windows: `%APPDATA%\PromptManager`
   - macOS: `~/Library/Application Support/PromptManager`
   - Linux: `$XDG_DATA_HOME/prompt-manager` (defaults to `~/.local/share/prompt-manager`)

Logs are written to `prompt_manager.log` in the same directory, capped at 10 MiB with 5 rotated backups.

#### Environment variables

| Variable | Purpose |
| --- | --- |
| `PROMPT_MANAGER_DATA_DIR` | Override the default data directory |
| `PROMPT_MANAGER_LEGACY_DATABASE` | Path to a legacy database (migration candidate) |
| `OPENAI_API_KEY` | Fallback key for OpenAI when none is saved |
| `GEMINI_API_KEY` | Fallback key for Gemini |
| `GLM_API_KEY` | Fallback key for GLM |

> API keys saved in the Agent panel are persisted in the local database. Environment variables are used only as a fallback when no key is saved.

#### Legacy database migration

If you used an older build that stored the database next to the executable or in the working directory, the application will try to migrate it automatically on first launch. You can also point it explicitly:

```bash
python -m prompt_manager --migrate-from /path/to/old/prompts.sqlite3
```

### Usage

#### Prompts and fixed presets

1. Pick "Prompt presets" or "Fixed presets" on the left.
2. Click **New** to create an entry, or click an existing entry to edit it.
3. The editor supports Markdown highlighting and heading folding. Changes are autosaved after 650 ms.
4. Snippets written as fixed presets can be referenced from other prompts via `=====IMPORT: Snippet name=====`. Imports are expanded recursively and circular references are detected.

#### Placeholders

Write in the content:

```markdown
=====REPLACE: Target language=====
```

When you click **Render** (or double-click the entry in the list), a dialog collects values. Values are remembered per prompt keyed by title and pre-filled next time. Rendering expands all `IMPORT`s first, then substitutes all `REPLACE`s.

#### Groups, pinning, and ordering

- Click **New group** in the list header to create a first-level group.
- The ☰ button on each row assigns the entry to a group; 📌 pins it.
- Drag within the same region to reorder; drop an entry onto a group header to move it into that group.

#### Drag export

Dragging an entry out of the list writes the rendered Markdown as a temporary file that can be dropped into other editors or chat windows. Temporary files live in `drag_export_md/` under the data directory and expire after the configured retention period, adjustable from 1 to 1440 minutes in **Settings → Shortcuts**.

#### Database backup and restore

- **Backup database**: click the button in the Agent panel header; snapshots are written into a `YY-MM-DD`-named folder inside the data directory.
- **Restore database**: click the button, pick a snapshot, and confirm. The current database is overwritten and the UI is refreshed.

#### Agent panel

Click **Agent** at the bottom-left to toggle the panel. In **Settings → Agent settings**, choose a provider and fill in the API URL, model, and API key:

| Provider | Default API URL | Default model |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Ollama | `http://localhost:11434/v1` | `qwen2.5:7b` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` |
| GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |

The Agent can:

- List, read, create, update, and delete prompts
- List and create first-level groups, and move prompts into or out of groups
- Open a given prompt in the editor
- Read local text files attached to the chat (drag them onto the input field)

Because the model can modify your local database through tool calls, a tagged snapshot is taken before every generated reply and removed on shutdown. Use the **Backup database** button to keep a long-lived manual backup at any time.

#### Shortcuts

All shortcuts can be viewed and remapped in **Settings → Shortcuts**. Defaults include:

| Action | Default shortcut |
| --- | --- |
| Insert replace placeholder | `Ctrl+Alt+R` |
| Insert import placeholder | `Ctrl+Alt+I` |
| Open settings | `Ctrl+,` |
| Find | `Ctrl+F` |
| Find and replace | `Ctrl+R` |
| Expand selection | `Ctrl+W` |
| Copy line (no selection) | `Ctrl+C` |
| Cut line (no selection) | `Ctrl+X` |
| Move line up / down | `Alt+Shift+↑` / `Alt+Shift+↓` |
| Fold / unfold section | `Ctrl+-` / `Ctrl++` |
| Recursively unfold section | `Ctrl+Alt++` |
| Expand / collapse all | `Ctrl+Shift++` / `Ctrl+Shift+-` |
| Rename entry | `F2` |

Double-tapping `Shift` copies the currently selected prompt.

### Building an executable

`build.py` drives PyInstaller to produce a single-file executable. Install PyInstaller first:

```bash
pip install pyinstaller
python build.py
```

Output lands in `dist/`. On Windows and macOS a multi-resolution application icon is generated and embedded automatically; on Linux the window icon is set by Qt at runtime.

User data is deliberately not bundled. The database always lives in the data directory described above, so replacing the executable does not replace your prompts or settings.

### Data safety notes

- Agent replies can invoke tools that modify the local database. A snapshot is taken before every generation and **removed when the application closes**. Use the **Backup database** button whenever you want a copy that survives a restart.
- Restoring a database fully overwrites the current prompts, groups, settings, and temporary text, and cannot be undone.

### License

MIT
