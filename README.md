# Prompt Manager

[简体中文](#简体中文) | [English](#english)

---

## 简体中文

Prompt Manager 是一个本地运行的 Markdown 提示词管理器，提供桌面图形界面。它把常用的提示词、可复用的固定预设、分组与占位符输入集中在一个窗口里，让你可以直接编辑、复用、复制和整理自己的提示词库。所有数据保存在本机的 SQLite 数据库中，不依赖任何外部服务。

### 核心特性

- **两类条目**：`提示词预设` 用于完整提示词，`固定预设` 用于可被其他提示词复用的片段。
- **分组与置顶**：为每个类别建立一级分组，支持分组折叠、重命名、删除，条目可置顶并拖拽排序。
- **内联重命名**：双击导航栏中的条目标题即可直接改名。
- **Markdown 编辑器**：标题高亮、按标题层级折叠段落、查找/替换、整行复制与剪切、整行上下移动、选区逐级扩展、引号/括号/反引号包裹。
- **占位符输入**：在提示词中使用 `=====REPLACE: 标题=====` 声明输入项，使用提示词时弹窗填写，输入值会被记忆以便下次复用。
- **固定预设导入**：使用 `=====IMPORT: 名称=====` 引用固定预设，渲染时递归展开，并检测循环导入。
- **导入自动补全**：在编辑器中输入导入标记时，可按名称或中文拼音首字母补全固定预设。
- **临时文本面板**：一个持久保存的临时记录区，输入后自动写入本地数据库。
- **内置 Agent 面板**：通过 OpenAI 兼容接口与模型对话，模型可调用受限工具直接读取和管理本机的提示词与分组。
- **附件引用**：Agent 面板支持拖拽或选择本地文本文件，作为对话上下文发送。
- **数据库备份**：一键创建经过完整性校验的 SQLite 快照，保存到按日期命名的子目录。
- **可自定义快捷键**：所有编辑器与全局快捷键都可以在设置中查看和修改。

### 技术栈

| 项目 | 说明 |
| --- | --- |
| 语言 | Python 3.10+ |
| GUI | PySide6（Qt for Python）6.6 ~ 6.x |
| 存储 | SQLite（标准库 `sqlite3`，WAL 模式） |
| 打包 | setuptools + PyInstaller |
| 网络 | 标准库 `urllib`（Agent 的 OpenAI 兼容请求） |

### 快速开始

#### 环境要求

- Python 3.10 或更高版本
- 支持 PySide6 的桌面环境（Windows / macOS / Linux）

#### 安装与运行

```bash
# 1. 克隆仓库
git clone <repository-url>
cd prompt-manager

# 2. 创建并激活虚拟环境（可选但推荐）
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. 安装依赖
python -m pip install -e .

# 4. 启动应用
python -m prompt_manager
```

安装为包后也可以直接使用命令行入口：

```bash
prompt-manager
```

### 构建单文件可执行程序

项目提供 `build.py`，使用 PyInstaller 生成单文件窗口程序，产物位于 `dist/`：

```bash
python -m pip install pyinstaller
python build.py
```

用户数据不会被打包进可执行文件，升级时仍会继续使用系统数据目录中的 `prompts.sqlite3`。

### 命令行参数

| 参数 | 说明 |
| --- | --- |
| `--data-dir PATH` | 覆盖用于保存 SQLite 数据库的持久化目录 |
| `--migrate-from PATH` | 首次启动时从指定的旧版数据库导入数据 |

### 数据目录

数据库文件名固定为 `prompts.sqlite3`，默认位置由平台决定：

| 平台 | 路径 |
| --- | --- |
| Windows | `%APPDATA%\PromptManager\prompts.sqlite3` |
| macOS | `~/Library/Application Support/PromptManager/prompts.sqlite3` |
| Linux | `$XDG_DATA_HOME/prompt-manager/prompts.sqlite3`（默认 `~/.local/share/prompt-manager/prompts.sqlite3`） |

首次启动时，如果新数据库尚不存在，程序会在可执行文件目录、当前工作目录、包目录等位置查找旧版本遗留的数据库并自动迁移；原文件不会被修改。

### 配置与环境变量

| 环境变量 | 用途 | 是否必填 |
| --- | --- | --- |
| `PROMPT_MANAGER_DATA_DIR` | 覆盖默认数据目录 | 否 |
| `PROMPT_MANAGER_LEGACY_DATABASE` | 指定待迁移的旧数据库路径 | 否 |
| `OPENAI_API_KEY` | 服务商为 OpenAI 且未在设置中填写 Key 时使用 | 否 |
| `GEMINI_API_KEY` | 服务商为 Gemini 且未在设置中填写 Key 时使用 | 否 |

Agent 的 API Key 只在本次运行内保留，不会写入本地数据库。Ollama 作为本地服务不需要 Key。

### 使用方法

#### 占位符与固定预设

在提示词内容中使用两种标记：

```markdown
# 代码审查

=====REPLACE: 编程语言=====

请审查以下 ====REPLACE: 编程语言===== 代码。

=====IMPORT: 代码质量要求=====
```

- `=====REPLACE: 标题=====`：使用提示词时弹出填写窗口，输入内容按标题替换标记，并记忆到下一次。
- `=====IMPORT: 名称=====`：渲染时按名称查找 `固定预设` 类别中的条目并递归展开；检测到循环导入时会输出 `[循环导入: 名称]` 提示。

编辑器工具栏和“杂项”菜单可以插入这两种标记，输入导入标记时还会触发固定预设名称补全。

#### 使用提示词

- 点击导航栏条目右侧的复制按钮，或在列表中双击 Shift，即可打开使用窗口。
- 没有占位符的提示词会直接渲染并复制到剪贴板；有占位符时会先弹出填写窗口。
- “优化提示词”菜单会先渲染当前提示词，再拼接优化指令复制到剪贴板，可区分“无文件优化”和“有文件优化”。

#### Agent 面板

点击左下角的 `Agent` 按钮打开对话面板，在“设置 → Agent 设置”中配置服务商：

| 服务商 | 默认 API 地址 | 默认模型 |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Ollama | `http://localhost:11434/v1` | `qwen2.5:7b` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` |

选择 Ollama 时，展开模型下拉框会通过本机 `/api/tags` 获取已安装的模型列表。Agent 可以调用的工具包括：

- 列出、读取、新建、修改、删除、选中提示词
- 列出、新建分组
- 将提示词加入分组、移出分组

删除操作只有在对话中明确要求时才会被执行。Agent 面板还支持拖拽或选择本地文本文件作为附件，单个文件上限 1 MiB，附件总量上限 4 MiB。

#### 默认快捷键

| 功能 | 默认快捷键 |
| --- | --- |
| 插入替换占位符 | `Ctrl+Alt+R` |
| 插入导入占位符 | `Ctrl+Alt+I` |
| 打开设置 | `Ctrl+,` |
| 查找 | `Ctrl+F` |
| 查找和替换 | `Ctrl+R` |
| 扩展选区 | `Ctrl+W` |
| 复制整行（无选区时） | `Ctrl+C` |
| 剪切整行（无选区时） | `Ctrl+X` |
| 上移当前行 | `Alt+Shift+Up` |
| 下移当前行 | `Alt+Shift+Down` |
| 折叠当前段落 | `Ctrl+-` |
| 展开当前段落 | `Ctrl++` |
| 递归展开当前段落 | `Ctrl+Alt++` |
| 展开全部段落 | `Ctrl+Shift++` |
| 折叠全部段落 | `Ctrl+Shift+-` |

编辑器快捷键仅在内容编辑区获得焦点时生效，所有快捷键都可以在设置中重新绑定。

#### 数据备份

Agent 面板顶部的“备份数据库”按钮会在后台创建快照，保存到数据目录下以日期命名的子目录中，例如 `25-01-01/prompts.sqlite3`。同一天的重复备份会原子替换当天已有的快照。

### 项目结构

```text
prompt-manager/
├── prompt_manager/
│   ├── __init__.py           # 包版本
│   ├── __main__.py           # python -m prompt_manager 入口
│   ├── app.py                # 应用入口、命令行参数、数据库初始化
│   ├── ui.py                 # 主窗口、导航列表、分组管理、设置对话框、Agent 工具执行
│   ├── editor.py             # Markdown 编辑器：高亮、折叠、查找替换、导入补全
│   ├── agent.py              # OpenAI 兼容请求与受限工具定义
│   ├── agent_panel.py        # 内嵌 Agent 对话面板与附件处理
│   ├── service.py            # 业务用例：校验、渲染、分组、备份
│   ├── storage.py            # SQLite 仓储、结构迁移、旧库导入
│   ├── models.py             # Prompt / PromptGroup 数据模型
│   └── placeholders.py       # 占位符与导入标记的解析与渲染
├── launcher.py               # PyInstaller 打包入口
├── build.py                  # 单文件可执行程序构建脚本
└── pyproject.toml            # 项目元数据与依赖声明
```

### License

本项目基于 MIT License 发布。

---

## English

[简体中文](#简体中文) | [English](#english)

Prompt Manager is a local Markdown prompt manager with a desktop GUI. It keeps your prompts, reusable fixed presets, groups, and placeholder inputs in one window so you can edit, reuse, copy, and organize your own prompt library. Everything is stored in a local SQLite database and no external service is required.

### Features

- **Two item kinds**: `prompt` for complete prompts, `fixed` for reusable fragments referenced by other prompts.
- **Groups and pinning**: create first-level groups per kind, collapse, rename, or delete them, pin items, and reorder by drag and drop.
- **Inline renaming**: double-click a title in the navigation list to rename it in place.
- **Markdown editor**: heading highlighting, section folding by heading level, find and replace, whole-line copy and cut, line moving, selection expansion, and quote/bracket/backtick wrapping.
- **Placeholder inputs**: declare inputs with `=====REPLACE: title=====`; values are collected in a dialog and remembered for next time.
- **Fixed preset imports**: reference a fixed preset with `=====IMPORT: name=====`; imports are expanded recursively with cycle detection.
- **Import completion**: typing an import marker completes fixed preset names by name or by Chinese pinyin initials.
- **Temporary text panel**: a persistent scratch area that autosaves into the local database.
- **Built-in Agent panel**: chat with an OpenAI-compatible model that can call a bounded tool set to read and manage local prompts and groups.
- **File attachments**: drag or pick local text files in the Agent panel to send them as conversation context.
- **Database backup**: create an integrity-checked SQLite snapshot in a date-named subdirectory.
- **Configurable shortcuts**: every global and editor shortcut can be viewed and rebound in settings.

### Tech Stack

| Item | Description |
| --- | --- |
| Language | Python 3.10+ |
| GUI | PySide6 (Qt for Python) 6.6 – 6.x |
| Storage | SQLite (standard library `sqlite3`, WAL mode) |
| Packaging | setuptools + PyInstaller |
| Networking | Standard library `urllib` for OpenAI-compatible Agent requests |

### Quick Start

#### Prerequisites

- Python 3.10 or newer
- A desktop environment supported by PySide6 (Windows / macOS / Linux)

#### Install and Run

```bash
# 1. Clone the repository
git clone <repository-url>
cd prompt-manager

# 2. Create and activate a virtual environment (optional but recommended)
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
python -m pip install -e .

# 4. Start the application
python -m prompt_manager
```

Once installed as a package, the console entry point is also available:

```bash
prompt-manager
```

### Building a Single-File Executable

`build.py` wraps PyInstaller to produce a single-file windowed executable in `dist/`:

```bash
python -m pip install pyinstaller
python build.py
```

User data is never bundled into the executable; upgrades keep using `prompts.sqlite3` in the platform data directory.

### Command-Line Options

| Option | Description |
| --- | --- |
| `--data-dir PATH` | Override the persistent directory used for the SQLite database |
| `--migrate-from PATH` | Import an existing legacy database on first launch |

### Data Directory

The database file is always named `prompts.sqlite3` and defaults to:

| Platform | Path |
| --- | --- |
| Windows | `%APPDATA%\PromptManager\prompts.sqlite3` |
| macOS | `~/Library/Application Support/PromptManager/prompts.sqlite3` |
| Linux | `$XDG_DATA_HOME/prompt-manager/prompts.sqlite3` (default `~/.local/share/prompt-manager/prompts.sqlite3`) |

On first launch, if the new database does not exist yet, the application looks for databases left behind by older releases next to the executable, in the working directory, and in the package directory, then migrates the first match. The original file is left untouched.

### Configuration and Environment Variables

| Variable | Purpose | Required |
| --- | --- | --- |
| `PROMPT_MANAGER_DATA_DIR` | Override the default data directory | No |
| `PROMPT_MANAGER_LEGACY_DATABASE` | Point at a legacy database to migrate | No |
| `OPENAI_API_KEY` | Used when the provider is OpenAI and no key is entered in settings | No |
| `GEMINI_API_KEY` | Used when the provider is Gemini and no key is entered in settings | No |

The Agent API key is kept for the current run only and is never written to the local database. Ollama runs locally and needs no key.

### Usage

#### Placeholders and Fixed Presets

Use two marker forms inside prompt content:

```markdown
# Code Review

=====REPLACE: language=====

Please review the following =====REPLACE: language===== code.

=====IMPORT: code quality rules=====
```

- `=====REPLACE: title=====` opens a fill dialog when the prompt is used; the value replaces the marker and is remembered.
- `=====IMPORT: name=====` looks up a `fixed` preset by name and expands it recursively. Cyclic imports render as `[循环导入: name]`.

The editor toolbar and the “杂项” menu insert both marker types, and typing an import marker triggers fixed preset completion.

#### Using a Prompt

- Click the copy button on a list row, or press Shift twice in quick succession, to open the use dialog.
- Prompts without placeholders are rendered and copied directly; prompts with placeholders open the fill dialog first.
- The optimize menu renders the current prompt first, then prepends an optimization instruction before copying, with separate “no file” and “with file” variants.

#### Agent Panel

Open the conversation panel with the `Agent` button at the bottom left, then configure a provider under Settings → Agent 设置:

| Provider | Default API base URL | Default model |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Ollama | `http://localhost:11434/v1` | `qwen2.5:7b` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` |

With Ollama selected, opening the model dropdown fetches installed models from the local `/api/tags` endpoint. Available Agent tools:

- List, read, create, update, delete, and select prompts
- List and create groups
- Assign a prompt to a group, or clear its group

Deletion only happens when the conversation explicitly asks for it. The Agent panel also accepts local text files by drag and drop or file picker, limited to 1 MiB per file and 4 MiB in total.

#### Default Shortcuts

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
| Move line up | `Alt+Shift+Up` |
| Move line down | `Alt+Shift+Down` |
| Fold current section | `Ctrl+-` |
| Unfold current section | `Ctrl++` |
| Unfold current section recursively | `Ctrl+Alt++` |
| Expand all sections | `Ctrl+Shift++` |
| Collapse all sections | `Ctrl+Shift+-` |

Editor shortcuts only fire while the content editor has focus, and every shortcut can be rebound in settings.

#### Database Backup

The “备份数据库” button at the top of the Agent panel creates a snapshot in the background under a date-named subdirectory of the data directory, for example `25-01-01/prompts.sqlite3`. Repeated backups on the same day atomically replace that day's snapshot.

### Project Structure

```text
prompt-manager/
├── prompt_manager/
│   ├── __init__.py           # Package version
│   ├── __main__.py           # python -m prompt_manager entry point
│   ├── app.py                # Application entry, CLI options, database setup
│   ├── ui.py                 # Main window, navigation list, groups, settings, Agent tool execution
│   ├── editor.py             # Markdown editor: highlighting, folding, find/replace, import completion
│   ├── agent.py              # OpenAI-compatible requests and bounded tool definitions
│   ├── agent_panel.py        # Embedded Agent conversation panel and attachments
│   ├── service.py            # Use cases: validation, rendering, grouping, backup
│   ├── storage.py            # SQLite repository, schema migration, legacy import
│   ├── models.py             # Prompt / PromptGroup data models
│   └── placeholders.py       # Placeholder and import marker parsing and rendering
├── launcher.py               # PyInstaller entry point
├── build.py                  # Single-file executable build script
└── pyproject.toml            # Project metadata and dependencies
```

### License

This project is released under the MIT License.