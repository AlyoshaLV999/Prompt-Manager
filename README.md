# Prompt Manager

[简体中文](#简体中文) | [English](#english)

---

## 简体中文

### 项目简介

Prompt Manager 是一个面向本地使用的桌面提示词管理器。它把提示词、可复用的固定预设、分组、占位符输入以及临时文本记录统一保存在本机的 SQLite 数据库中，并提供接近 IDE 的 Markdown 编辑器体验。项目内置一个由 OpenAI 兼容接口驱动的 Agent 对话面板，可以直接读取、创建、更新、组织本地提示词，并在改动前自动生成可回滚的数据库快照。

所有数据都存储在用户数据目录，替换可执行文件不会影响提示词、设置或已记忆的占位符输入。

### 核心特性

- **本地优先**：提示词、分组、设置与占位符输入均保存在本地 SQLite 文件中，程序本身不依赖云服务或外部数据库。
- **提示词与固定预设**：两个独立类别，各自维护命名条目；固定预设可通过 `=====IMPORT: 名称=====` 被其他提示词递归引用。
- **分组与置顶**：条目可归入一级分组，也可置顶；支持拖拽排序、拖入分组、取消分组。
- **Markdown 编辑器**：语法高亮、标题折叠、查找/替换、扩展选区、整行复制/剪切、行移动、成对符号包裹、导入名称补全。
- **占位符**：`=====REPLACE: 标题=====` 标记在渲染时被用户输入替换，输入值会被自动记忆。
- **临时文本面板**：一个持久化的 Markdown 草稿区，内容写入设置表，重启后保留。
- **内置 Agent**：支持 OpenAI、Ollama、Gemini、GLM 四类 OpenAI 兼容服务商，可流式输出、调用工具、引用本地附件文件。
- **数据库备份与恢复**：按日期命名的 SQLite 快照，可在设置界面一键备份与恢复；Agent 生成回复前会自动创建安全快照，并在程序关闭时清理。
- **可定制快捷键**：设置对话框中列出全部编辑器与窗口级快捷键，可自由绑定并检测冲突。
- **数据目录可迁移**：通过 `--migrate-from` 或 `PROMPT_MANAGER_LEGACY_DATABASE` 在首次启动时导入旧数据库。

### 技术栈

| 组件 | 版本 / 说明 |
| --- | --- |
| Python | >= 3.10 |
| GUI 框架 | PySide6 >= 6.6, < 7 |
| 持久化 | SQLite（Python 标准库 `sqlite3`） |
| 打包 | setuptools（PEP 621）+ PyInstaller（可选，用于生成单文件可执行程序） |

### 项目结构

```text
prompt-manager/
├── prompt_manager/
│   ├── __init__.py            # 包版本号
│   ├── __main__.py            # python -m prompt_manager 入口
│   ├── app.py                 # 应用入口、CLI 参数解析、任务栏身份
│   ├── ui.py                  # 主窗口、导航、设置对话框
│   ├── editor.py              # Markdown 编辑器、语法高亮、查找替换
│   ├── agent.py               # OpenAI 兼容传输层与工具定义
│   ├── agent_panel.py         # 嵌入式 Agent 对话面板
│   ├── service.py             # 业务用例与输入校验
│   ├── storage.py             # SQLite 仓储、备份与迁移
│   ├── models.py              # Prompt / PromptGroup 数据类
│   ├── placeholders.py        # REPLACE / IMPORT 标记解析
│   ├── database_maintenance.py# 备份线程、恢复对话框、Agent 快照会话
│   └── icon.py                # 程序化绘制的应用图标
├── launcher.py                # PyInstaller 入口脚本
├── build.py                   # 单文件可执行程序构建脚本
└── pyproject.toml             # 项目元数据与依赖
```

### 快速开始

#### 环境要求

- Python 3.10 或更高版本
- 支持 PySide6 的桌面操作系统（Windows / macOS / Linux）
- 可选：本机运行的 Ollama，或一个 OpenAI 兼容服务商的 API Key

#### 安装

```bash
# 1. 克隆仓库
git clone <repository-url>
cd prompt-manager

# 2. 创建并激活虚拟环境
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

# 3. 以可编辑模式安装
pip install -e .
```

#### 启动

任选一种方式启动：

```bash
# 方式一：模块方式
python -m prompt_manager

# 方式二：控制台脚本（由 pip install 提供）
prompt-manager

# 方式三：直接运行入口脚本
python launcher.py
```

#### 指定数据目录或迁移旧数据库

```bash
python -m prompt_manager --data-dir /path/to/data
python -m prompt_manager --migrate-from /path/to/old/prompts.sqlite3
```

### 使用说明

#### 提示词与固定预设

- 左侧导航顶部的“提示词预设 / 固定预设”按钮切换当前类别。
- “新建”按钮创建条目，条目名称可在列表中双击直接重命名。
- 编辑器内容修改后自动保存（约 650 ms 防抖），状态栏会给出提示。
- 点击条目右侧的复制按钮（或双击 Shift）可以渲染并复制提示词到剪贴板。

#### 占位符

在提示词内容中使用如下标记：

```markdown
=====REPLACE: 主题=====
=====IMPORT: 代码质量要求=====
```

- `REPLACE` 标记会在“使用提示词”时弹出填写对话框，输入值会被记忆。
- `IMPORT` 标记会递归展开同类别下同名的固定预设；检测到循环导入时会输出 `[循环导入: 名称]`。

#### 分组与置顶

- 点击“新建分组”创建一级分组，分组行支持展开/收起、重命名和删除。
- 条目行上的 📌 按钮切换置顶状态；☰ 按钮弹出分组菜单。
- 也可以直接把条目拖到分组行上完成分组分配。

#### 临时文本

点击左下角“临时文本”按钮展开草稿面板。内容会自动保存到设置表，重新启动后仍然存在。

#### 内置 Agent

- 点击左侧“Agent”按钮展开对话面板。
- 在“设置 → Agent 设置”中选择服务商并填写模型和 API Key。
- Ollama 和 GLM 会主动获取模型列表；GLM 的 API Key 留空时会展示内置的推荐模型。
- 输入框支持将本地文本文件拖入作为附件，附件内容会作为用户数据追加到请求中。
- Agent 可以调用的工具包括：`list_prompts`、`read_prompt`、`create_prompt`、`update_prompt`、`delete_prompt`、`select_prompt`、`list_groups`、`create_group`、`set_prompt_group`、`clear_prompt_group`。
- 删除操作仅在用户明确要求时执行。

#### 备份与恢复

- Agent 面板右上角的“备份数据库”会创建一份当日快照；“恢复数据库”会列出所有可用快照。
- 每次 Agent 生成回复前会自动生成一份带 `agent-` 前缀的快照，程序退出时会清理。

### 配置

#### 应用设置

打开“设置”（快捷键默认 `Ctrl+,`）：

- **快捷键**：编辑所有窗口级和编辑器级快捷键，包括查找/替换、折叠、整行操作、插入占位符等。
- **名称显示长度**：控制左侧导航中条目与分组名称的省略长度。
- **Agent 设置**：服务商、API 地址、模型、本次运行使用的 API Key。

#### Agent 服务商默认值

| 服务商 | 默认 API 地址 | 默认模型 |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Ollama | `http://localhost:11434/v1` | `qwen2.5:7b` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` |
| GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |

#### 环境变量

| 变量 | 用途 |
| --- | --- |
| `PROMPT_MANAGER_DATA_DIR` | 覆盖默认的数据目录位置。 |
| `PROMPT_MANAGER_LEGACY_DATABASE` | 在首次启动时指定要迁移的旧数据库路径。 |
| `OPENAI_API_KEY` | OpenAI 服务商的默认 API Key。 |
| `GEMINI_API_KEY` | Gemini 服务商的默认 API Key。 |
| `GLM_API_KEY` | GLM 服务商的默认 API Key。 |

Ollama 为本地服务，不需要 API Key。

#### 数据目录

默认位置随操作系统而定：

| 平台 | 默认路径 |
| --- | --- |
| Windows | `%APPDATA%\PromptManager` |
| macOS | `~/Library/Application Support/PromptManager` |
| Linux | `$XDG_DATA_HOME/prompt-manager` 或 `~/.local/share/prompt-manager` |

数据库文件为 `prompts.sqlite3`；自动备份位于其同级的 `YY-MM-DD` 目录下。

### 构建单文件可执行程序

`build.py` 使用 PyInstaller 将项目打包为单文件窗口程序，并在 Windows 上生成 ICO、在 macOS 上生成 ICNS，作为可执行文件图标。

```bash
pip install pyinstaller
python build.py
```

构建产物位于 `dist/PromptManager`（Windows 下为 `PromptManager.exe`）。用户数据仍保存在平台数据目录中，不会被打包进可执行文件。

### 许可证

本项目采用 MIT License。

---

## English

### Overview

Prompt Manager is a local-first desktop prompt manager. It stores prompts, reusable fixed presets, groups, remembered placeholder values, and a scratch Markdown note in a single SQLite database on your machine, and ships an IDE-like Markdown editor. A built-in Agent panel — powered by any OpenAI-compatible endpoint — can read, create, update, and organize your prompts, and takes an automatic database snapshot before each reply so any Agent change can be rolled back.

Replacing the executable does not affect your prompts, settings, or remembered placeholder values.

### Features

- **Local-first**: prompts, groups, settings, and placeholder values all live in a local SQLite file; the application itself does not rely on cloud services or an external database.
- **Prompts and fixed presets**: two independent categories, each with named entries; fixed presets can be pulled into other prompts with `=====IMPORT: name=====`.
- **Groups and pinning**: entries can be placed in a first-level group or pinned to the top; drag-and-drop reordering, group assignment, and ungrouping are supported.
- **Markdown editor**: syntax highlighting, heading folding, find/replace, selection expansion, whole-line copy/cut, line moving, paired-symbol wrapping, and import-name completion.
- **Placeholders**: `=====REPLACE: title=====` markers are substituted with your input at render time, and the values are remembered.
- **Scratch text panel**: a persistent Markdown scratchpad whose contents are written to the settings table.
- **Built-in Agent**: works with OpenAI, Ollama, Gemini, and GLM; supports streaming output, tool calls, and local file attachments.
- **Database backup and restore**: date-named SQLite snapshots you can create and restore from the UI; Agent safety snapshots are created before each reply and cleaned up when the program exits.
- **Customizable shortcuts**: every window- and editor-level shortcut is listed in the settings dialog, rebindable, and checked for conflicts.
- **Portable data directory**: migrate a legacy database on first launch with `--migrate-from` or `PROMPT_MANAGER_LEGACY_DATABASE`.

### Tech Stack

| Component | Version / Notes |
| --- | --- |
| Python | >= 3.10 |
| GUI | PySide6 >= 6.6, < 7 |
| Persistence | SQLite (Python standard library `sqlite3`) |
| Packaging | setuptools (PEP 621) + PyInstaller (optional, for single-file builds) |

### Project Structure

```text
prompt-manager/
├── prompt_manager/
│   ├── __init__.py            # Package version
│   ├── __main__.py            # python -m prompt_manager entry point
│   ├── app.py                 # Application entry, CLI parsing, taskbar identity
│   ├── ui.py                  # Main window, navigation, settings dialog
│   ├── editor.py              # Markdown editor, highlighter, find/replace
│   ├── agent.py               # OpenAI-compatible transport and tool definitions
│   ├── agent_panel.py         # Embedded Agent conversation panel
│   ├── service.py             # Use cases and validation
│   ├── storage.py             # SQLite repository, backups, migration
│   ├── models.py              # Prompt / PromptGroup data classes
│   ├── placeholders.py        # REPLACE / IMPORT marker parsing
│   ├── database_maintenance.py# Backup worker, restore dialog, Agent session
│   └── icon.py                # Programmatically drawn application icon
├── launcher.py                # PyInstaller entry script
├── build.py                   # Single-file build script
└── pyproject.toml             # Project metadata and dependencies
```

### Getting Started

#### Prerequisites

- Python 3.10 or later
- A desktop OS supported by PySide6 (Windows / macOS / Linux)
- Optional: a local Ollama server, or an API key for an OpenAI-compatible provider

#### Installation

```bash
# 1. Clone the repository
git clone <repository-url>
cd prompt-manager

# 2. Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

# 3. Install in editable mode
pip install -e .
```

#### Running

Any of the following starts the application:

```bash
# Module form
python -m prompt_manager

# Console script (installed by pip)
prompt-manager

# Direct entry script
python launcher.py
```

#### Custom data directory or legacy migration

```bash
python -m prompt_manager --data-dir /path/to/data
python -m prompt_manager --migrate-from /path/to/old/prompts.sqlite3
```

### Usage

#### Prompts and fixed presets

- The "Prompts / Fixed presets" buttons at the top of the left navigation switch the active category.
- "New" creates an entry; double-click a row's name to rename it inline.
- Edits to the editor content are autosaved (about 650 ms debounce); the status bar reports each save.
- The copy button on each row (or a double press of Shift) renders and copies the prompt to the clipboard.

#### Placeholders

Use the following markers inside a prompt:

```markdown
=====REPLACE: topic=====
=====IMPORT: code quality rules=====
```

- `REPLACE` markers open a fill dialog when the prompt is used; entered values are remembered.
- `IMPORT` markers recursively expand a fixed preset with the same name; circular imports render as `[循环导入: name]`.

#### Groups and pinning

- "New group" creates a first-level group; a group row supports collapse/expand, rename, and delete.
- The 📌 button on each entry toggles pinning; the ☰ button opens the group menu.
- Dragging an entry onto a group row assigns it to that group.

#### Scratch text

Click "临时文本" in the lower-left corner to open the scratch panel. Its content is autosaved to the settings table and survives restarts.

#### Built-in Agent

- Click "Agent" on the left to open the conversation panel.
- Configure the provider, model, and API key under "Settings → Agent".
- Ollama and GLM fetch the model list automatically; GLM falls back to built-in suggestions when no key is provided.
- The input box accepts local text files by drag-and-drop; their contents are appended to the request as user data.
- Tools the Agent can call: `list_prompts`, `read_prompt`, `create_prompt`, `update_prompt`, `delete_prompt`, `select_prompt`, `list_groups`, `create_group`, `set_prompt_group`, `clear_prompt_group`.
- Deletion is only performed when you explicitly ask for it.

#### Backup and restore

- The "备份数据库" (Back up) and "恢复数据库" (Restore) buttons in the Agent panel header create and list date-named snapshots.
- Before each Agent reply, an `agent-`-prefixed snapshot is taken automatically and removed when the program exits.

### Configuration

#### Application settings

Open "Settings" (default shortcut `Ctrl+,`):

- **Shortcuts**: rebind every window- and editor-level shortcut, including find/replace, folding, whole-line operations, and marker insertion.
- **Name display length**: controls how entry and group names are elided in the left navigation.
- **Agent settings**: provider, base URL, model, and the API key used for this run.

#### Agent provider defaults

| Provider | Default base URL | Default model |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Ollama | `http://localhost:11434/v1` | `qwen2.5:7b` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` |
| GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |

#### Environment variables

| Variable | Purpose |
| --- | --- |
| `PROMPT_MANAGER_DATA_DIR` | Overrides the default data directory. |
| `PROMPT_MANAGER_LEGACY_DATABASE` | Path to a legacy database to migrate on first launch. |
| `OPENAI_API_KEY` | Default API key for the OpenAI provider. |
| `GEMINI_API_KEY` | Default API key for the Gemini provider. |
| `GLM_API_KEY` | Default API key for the GLM provider. |

Ollama runs locally and does not need an API key.

#### Data directory

Default locations by platform:

| Platform | Default path |
| --- | --- |
| Windows | `%APPDATA%\PromptManager` |
| macOS | `~/Library/Application Support/PromptManager` |
| Linux | `$XDG_DATA_HOME/prompt-manager` or `~/.local/share/prompt-manager` |

The database file is `prompts.sqlite3`; automatic backups live in `YY-MM-DD` folders next to it.

### Building a Single-File Executable

`build.py` uses PyInstaller to package the project as a single-file windowed application, and generates an ICO on Windows and an ICNS on macOS for the executable icon.

```bash
pip install pyinstaller
python build.py
```

The output is written to `dist/PromptManager` (or `PromptManager.exe` on Windows). User data still lives in the platform data directory and is never bundled into the executable.

### License

This project is released under the MIT License.