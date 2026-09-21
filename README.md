# Prompt Manager

**简体中文** · [English](#english)

Prompt Manager 是一个本地运行的桌面提示词管理工具，用于集中编写、组织和复用 Markdown 提示词与固定预设。

本项目提供可替换输入占位符和可复用固定预设。你可以将经常变化的内容定义为 `REPLACE` 占位符，将通用规则、格式要求或其他固定内容保存为独立预设并通过 `IMPORT` 引用。使用提示词时，Prompt Manager 会完成固定预设展开、变量替换，并将最终内容直接复制到剪贴板。

所有提示词、占位符历史输入和应用设置均保存在本地 SQLite 数据库中，不依赖网络服务、Web API 或外部数据库。

## 核心特性

* **本地提示词管理**：创建、编辑、删除和分类管理提示词，内容自动保存。
* **提示词与固定预设分离**：分别管理普通提示词和可被其他提示词引用的固定预设。
* **动态输入占位符**：使用 `=====REPLACE: 名称=====` 定义运行时输入。
* **固定预设复用**：使用 `=====IMPORT: 预设名称=====` 将固定预设嵌入其他提示词。
* **递归预设展开**：固定预设可以继续引用其他固定预设，并提供循环导入保护。
* **输入记忆**：自动保存每个提示词上次填写的占位符值，便于重复使用。
* **快速复制**：可以直接使用上次保存的输入渲染并复制提示词。
* **Markdown 编辑器**：提供标题、粗体、斜体、代码、引用、列表、链接和代码块等常用编辑操作。
* **Markdown 语法高亮**：对标题、占位符、行内代码和强调内容进行轻量高亮。
* **章节折叠**：基于 Markdown 标题层级折叠或展开内容。
* **编辑器快捷操作**：支持扩展选区、整行复制/剪切、移动行等编辑操作。
* **导入自动补全**：输入 `IMPORT` 标记时，可从已有固定预设中进行名称补全，并支持中文名称拼音首字母匹配。
* **临时文本区**：提供独立的持久化临时记录面板。
* **可配置快捷键**：占位符插入和设置等操作的快捷键可以在应用内修改。
* **本地 SQLite 存储**：提示词、输入历史和应用设置统一持久化到本地数据库。

## 技术栈

| 组件                 | 用途              |
| ------------------ | --------------- |
| Python 3.10+       | 应用运行环境          |
| PySide6 6.6+ / < 7 | Qt 桌面图形界面       |
| SQLite             | 本地数据持久化         |
| setuptools         | Python 包构建      |
| PyInstaller        | 可选的单文件桌面可执行程序构建 |

SQLite 通过 Python 标准库 `sqlite3` 使用，无需单独安装数据库服务。

## 项目结构

```text
.
├── build.py                 # PyInstaller 可执行程序构建脚本
├── launcher.py              # PyInstaller 启动入口
├── pyproject.toml           # 项目元数据、依赖和命令行入口
└── prompt_manager/
    ├── __init__.py          # 包信息与版本
    ├── __main__.py          # python -m prompt_manager 入口
    ├── app.py               # 应用初始化与命令行参数
    ├── editor.py            # Markdown 编辑器、语法高亮、折叠与补全
    ├── models.py            # Prompt 领域模型
    ├── placeholders.py      # REPLACE / IMPORT 标记解析与替换
    ├── service.py           # 业务逻辑、验证与提示词渲染
    ├── storage.py           # SQLite 数据访问与持久化
    └── ui.py                # PySide6 主界面与交互逻辑
```

应用采用简单的分层结构：

```text
PySide6 UI / Markdown Editor
            │
            ▼
       PromptService
      ┌─────┴─────┐
      ▼           ▼
Placeholder    PromptRepository
 Rendering          │
                    ▼
                  SQLite
```

`PromptService` 负责连接 UI 与数据层，并集中处理输入验证、占位符解析、固定预设递归展开和最终提示词渲染。

## 快速开始

### 环境要求

* Python 3.10 或更高版本
* 支持 PySide6 的桌面操作系统

### 安装

在项目根目录创建虚拟环境：

```bash
python -m venv .venv
```

激活虚拟环境。

Windows：

```powershell
.venv\Scripts\activate
```

macOS / Linux：

```bash
source .venv/bin/activate
```

然后安装项目：

```bash
python -m pip install -e .
```

`pyproject.toml` 会安装运行所需的 PySide6 依赖。

### 启动

安装完成后，可以直接使用项目提供的命令：

```bash
prompt-manager
```

也可以通过 Python 模块启动：

```bash
python -m prompt_manager
```

## 使用方法

### 1. 创建提示词

启动应用后，在 **提示词预设** 分类中点击“新建”，填写名称和 Markdown 内容。

修改内容后会自动保存，无需手动执行保存操作。

例如：

```markdown
# 代码审查

请审查下面的代码：

=====REPLACE: 代码=====

重点关注：

=====REPLACE: 审查重点=====
```

点击“使用提示词”时，应用会根据占位符生成输入框。填写内容并确认后，最终提示词会复制到系统剪贴板。

同一个提示词之前填写的值会被保存，并在下次使用时自动恢复。

### 2. 使用替换占位符

替换占位符格式为：

```text
=====REPLACE: 占位符名称=====
```

例如：

```markdown
请为以下主题生成技术方案：

=====REPLACE: 主题=====

目标用户：

=====REPLACE: 目标用户=====
```

同名占位符只需要填写一次，其值会替换该提示词中的所有对应标记。

### 3. 创建固定预设

固定预设用于保存需要在多个提示词中复用的内容，例如代码规范、输出格式或通用约束。

在 **固定预设** 分类中新建一个名为 `代码质量要求` 的预设：

```markdown
请确保：

- 代码结构清晰
- 命名具有可读性
- 避免不必要的重复
- 对关键设计决策进行说明
```

然后在普通提示词中引用：

```markdown
请实现以下需求：

=====REPLACE: 需求=====

## 代码质量

=====IMPORT: 代码质量要求=====
```

使用提示词时，`IMPORT` 标记会自动展开为对应固定预设的完整内容。

如果指定的固定预设不存在，原始 `IMPORT` 标记会保留在最终文本中。

### 4. 组合固定预设

固定预设支持递归引用，因此可以将多个小型规则组合成更大的模板。

例如：

```markdown
=====IMPORT: Python 编码规范=====

=====IMPORT: 输出格式=====
```

应用会递归解析引用。

当固定预设之间形成循环引用时，Prompt Manager 会停止继续展开，并在对应位置输出循环导入提示，避免无限递归。

### 5. 快速复制

提示词列表中的“复制”按钮会直接使用该提示词之前保存的占位符值完成渲染并复制到剪贴板。

对于不包含 `REPLACE` 占位符的提示词，使用时会直接渲染并复制，无需额外填写内容。

### 6. 临时文本

侧边栏中的“临时文本”可以打开一个独立编辑区域，用于暂存上下文、草稿或其他辅助文本。

临时文本会自动保存到本地，并在后续启动应用时恢复。

## Markdown 编辑器

内置编辑器提供常用 Markdown 操作，包括：

| 操作           | 功能                   |
| ------------ | -------------------- |
| H1 / H2 / H3 | 插入 Markdown 标题       |
| 粗体           | 使用 `**` 包裹文本         |
| 斜体           | 使用 `*` 包裹文本          |
| 代码           | 使用反引号包裹文本            |
| 引用           | 插入 `> `              |
| 列表           | 插入 `- `              |
| 链接           | 插入 Markdown 链接       |
| 代码块          | 插入 fenced code block |
| 替换占位符        | 插入 `REPLACE` 标记      |
| 导入占位符        | 插入 `IMPORT` 标记       |

编辑器还会对 Markdown 标题、占位符、行内代码和强调文本进行轻量语法高亮。

### 编辑快捷键

以下是编辑器内置操作：

| 快捷键            | 操作               |
| -------------- | ---------------- |
| `Ctrl+W`       | 逐级扩展当前选区         |
| `Ctrl+C`       | 无选区时复制当前整行       |
| `Ctrl+X`       | 无选区时剪切当前整行       |
| `Alt+Shift+↑`  | 当前行上移            |
| `Alt+Shift+↓`  | 当前行下移            |
| `Ctrl+-`       | 折叠当前 Markdown 章节 |
| `Ctrl++`       | 展开当前章节           |
| `Ctrl+Alt++`   | 递归展开当前章节         |
| `Ctrl+Shift++` | 展开全部章节           |
| `Ctrl+Shift+-` | 折叠全部章节           |

应用操作默认快捷键：

| 快捷键          | 操作               |
| ------------ | ---------------- |
| `Ctrl+Alt+R` | 插入 `REPLACE` 占位符 |
| `Ctrl+Alt+I` | 插入 `IMPORT` 占位符  |
| `Ctrl+,`     | 打开设置             |

应用操作快捷键可以在设置窗口中修改，并会持久化保存。

## 数据存储

Prompt Manager 使用 SQLite 保存数据，数据库文件名为：

```text
prompts.sqlite3
```

默认数据目录根据操作系统确定：

| 系统           | 默认目录                                                                   |
| ------------ | ---------------------------------------------------------------------- |
| Windows      | `%APPDATA%\PromptManager`                                              |
| macOS        | `~/Library/Application Support/PromptManager`                          |
| Linux / Unix | `$XDG_DATA_HOME/prompt-manager`，未设置时使用 `~/.local/share/prompt-manager` |

数据库包含三类数据：

* 提示词与固定预设
* 每个提示词已记忆的占位符输入
* 应用设置和临时文本

SQLite 使用 WAL 日志模式，并启用外键约束。

## 配置数据目录

可以通过环境变量覆盖默认数据目录：

```bash
PROMPT_MANAGER_DATA_DIR=/path/to/data
```

也可以在启动时使用 `--data-dir`：

```bash
prompt-manager --data-dir /path/to/data
```

或者：

```bash
python -m prompt_manager --data-dir /path/to/data
```

命令行参数指定的目录优先于默认平台数据目录。

## 构建桌面可执行程序

项目包含 `build.py` 和独立的 `launcher.py`，可通过 PyInstaller 构建单文件、无控制台窗口的桌面程序。

构建前需要安装 PyInstaller：

```bash
python -m pip install PyInstaller
```

然后在项目根目录运行：

```bash
python build.py
```

构建脚本等价于使用 PyInstaller 的单文件 GUI 模式，并将应用命名为 `PromptManager`。

成功后产物位于：

```text
dist/
```

具体可执行文件格式由构建所在的操作系统决定。

## License

This project is licensed under the MIT License.

---

<a id="english"></a>

# Prompt Manager

[简体中文](#prompt-manager) · **English**

Prompt Manager is a local desktop application for writing, organizing, and reusing Markdown prompts and fixed presets.

The project supports runtime replacement placeholders and reusable fixed presets. Frequently changing content can be represented with `REPLACE` markers, while shared rules, formatting requirements, or other reusable content can be stored as fixed presets and referenced through `IMPORT` markers. When a prompt is used, Prompt Manager expands its fixed presets, substitutes input values, and copies the rendered result directly to the clipboard.

Prompts, remembered placeholder values, and application settings are stored locally in SQLite. The application does not depend on network services, Web APIs, or external databases.

## Features

* **Local prompt management** — Create, edit, delete, and organize prompts with automatic saving.
* **Prompt and fixed-preset categories** — Keep regular prompts separate from reusable fixed presets.
* **Runtime placeholders** — Define user inputs with `=====REPLACE: Name=====`.
* **Reusable fixed presets** — Embed shared content with `=====IMPORT: Preset Name=====`.
* **Recursive imports** — Fixed presets can import other fixed presets, with circular-import protection.
* **Remembered inputs** — Preserve the latest placeholder values for each prompt.
* **Quick copy** — Render a prompt immediately using its previously saved values.
* **Markdown editor** — Common actions for headings, bold, italic, code, quotes, lists, links, and code blocks.
* **Markdown highlighting** — Lightweight highlighting for headings, markers, inline code, and emphasis.
* **Section folding** — Collapse and expand content according to Markdown heading hierarchy.
* **IDE-like editing shortcuts** — Expand selections, copy or cut whole lines, and move lines.
* **Import completion** — Complete fixed-preset names while entering an `IMPORT` marker, including matching Chinese names by Pinyin initials.
* **Temporary text panel** — Keep persistent scratch text next to the prompt editor.
* **Configurable shortcuts** — Customize application shortcuts from the settings dialog.
* **Local SQLite storage** — Store prompts, remembered values, and settings in a local database.

## Tech Stack

| Component          | Purpose                                       |
| ------------------ | --------------------------------------------- |
| Python 3.10+       | Application runtime                           |
| PySide6 6.6+ / < 7 | Qt desktop user interface                     |
| SQLite             | Local persistence                             |
| setuptools         | Python package build system                   |
| PyInstaller        | Optional single-file desktop executable build |

SQLite is accessed through Python's standard-library `sqlite3` module and does not require a separate database server.

## Project Structure

```text
.
├── build.py                 # PyInstaller executable build script
├── launcher.py              # PyInstaller launcher
├── pyproject.toml           # Project metadata, dependencies, and CLI entry point
└── prompt_manager/
    ├── __init__.py          # Package metadata and version
    ├── __main__.py          # python -m prompt_manager entry point
    ├── app.py               # Application bootstrap and CLI arguments
    ├── editor.py            # Markdown editor, highlighting, folding, and completion
    ├── models.py            # Prompt domain model
    ├── placeholders.py      # REPLACE / IMPORT parsing and replacement
    ├── service.py           # Business logic, validation, and prompt rendering
    ├── storage.py           # SQLite persistence layer
    └── ui.py                # PySide6 main window and interaction logic
```

The application uses a small layered architecture:

```text
PySide6 UI / Markdown Editor
            │
            ▼
       PromptService
      ┌─────┴─────┐
      ▼           ▼
Placeholder    PromptRepository
 Rendering          │
                    ▼
                  SQLite
```

`PromptService` connects the UI and persistence layer and centralizes validation, placeholder parsing, recursive preset expansion, and final prompt rendering.

## Getting Started

### Prerequisites

* Python 3.10 or later
* A desktop operating system supported by PySide6

### Installation

Create a virtual environment from the project root:

```bash
python -m venv .venv
```

Activate it.

Windows:

```powershell
.venv\Scripts\activate
```

macOS / Linux:

```bash
source .venv/bin/activate
```

Install the project:

```bash
python -m pip install -e .
```

The required PySide6 dependency is installed from `pyproject.toml`.

### Running

After installation, start the application with the installed command:

```bash
prompt-manager
```

Alternatively, run the Python module directly:

```bash
python -m prompt_manager
```

## Usage

### 1. Create a prompt

Start the application, select **提示词预设** (Prompt Presets), and create a new entry with a name and Markdown content.

Changes are saved automatically.

For example:

```markdown
# Code Review

Review the following code:

=====REPLACE: Code=====

Pay particular attention to:

=====REPLACE: Review Focus=====
```

When you use the prompt, Prompt Manager creates an input field for each placeholder. After entering the values, the rendered prompt is copied to the system clipboard.

Previously entered values are stored and restored the next time the same prompt is used.

### 2. Replacement placeholders

Use the following syntax to define an input:

```text
=====REPLACE: Placeholder Name=====
```

For example:

```markdown
Create a technical design for:

=====REPLACE: Topic=====

Target users:

=====REPLACE: Target Users=====
```

A repeated placeholder name only needs one value. That value is substituted into every matching marker in the prompt.

### 3. Fixed presets

Fixed presets contain content intended for reuse across multiple prompts, such as coding conventions, output requirements, or common instructions.

Create a fixed preset named `Code Quality Requirements`:

```markdown
Make sure that:

- The code has a clear structure
- Names are readable
- Unnecessary duplication is avoided
- Important design decisions are explained
```

Reference it from a regular prompt:

```markdown
Implement the following requirement:

=====REPLACE: Requirement=====

## Code Quality

=====IMPORT: Code Quality Requirements=====
```

When the prompt is rendered, the `IMPORT` marker is replaced with the complete contents of the matching fixed preset.

If the referenced fixed preset does not exist, the original `IMPORT` marker remains in the rendered text.

### 4. Compose fixed presets

Fixed presets can recursively import other fixed presets, allowing smaller reusable rules to be composed into larger templates.

For example:

```markdown
=====IMPORT: Python Conventions=====

=====IMPORT: Output Format=====
```

Prompt Manager recursively expands these references.

If presets form an import cycle, expansion stops at the cycle and inserts a circular-import marker instead of recursing indefinitely.

### 5. Quick copy

The **复制** (Copy) action beside a prompt renders it using its previously remembered placeholder values and immediately copies the result to the clipboard.

Prompts without `REPLACE` placeholders can be rendered and copied directly without opening an input dialog.

### 6. Temporary text

The **临时文本** (Temporary Text) button opens a persistent scratch area next to the main editor.

Its contents are automatically saved locally and restored on subsequent application launches.

## Markdown Editor

The built-in editor provides common Markdown editing actions:

| Action              | Behavior                   |
| ------------------- | -------------------------- |
| H1 / H2 / H3        | Insert a Markdown heading  |
| Bold                | Wrap text in `**`          |
| Italic              | Wrap text in `*`           |
| Code                | Wrap text in backticks     |
| Quote               | Insert `> `                |
| List                | Insert `- `                |
| Link                | Insert a Markdown link     |
| Code block          | Insert a fenced code block |
| Replace placeholder | Insert a `REPLACE` marker  |
| Import placeholder  | Insert an `IMPORT` marker  |

The editor also provides lightweight syntax highlighting for Markdown headings, placeholders, inline code, and emphasized text.

### Keyboard Shortcuts

Built-in editor shortcuts:

| Shortcut       | Action                                         |
| -------------- | ---------------------------------------------- |
| `Ctrl+W`       | Expand the current selection                   |
| `Ctrl+C`       | Copy the current line when nothing is selected |
| `Ctrl+X`       | Cut the current line when nothing is selected  |
| `Alt+Shift+↑`  | Move the current line up                       |
| `Alt+Shift+↓`  | Move the current line down                     |
| `Ctrl+-`       | Collapse the current Markdown section          |
| `Ctrl++`       | Expand the current section                     |
| `Ctrl+Alt++`   | Recursively expand the current section         |
| `Ctrl+Shift++` | Expand all sections                            |
| `Ctrl+Shift+-` | Collapse all sections                          |

Default application shortcuts:

| Shortcut     | Action                    |
| ------------ | ------------------------- |
| `Ctrl+Alt+R` | Insert a `REPLACE` marker |
| `Ctrl+Alt+I` | Insert an `IMPORT` marker |
| `Ctrl+,`     | Open settings             |

Application shortcuts can be changed from the settings dialog and are persisted locally.

## Data Storage

Prompt Manager stores its data in an SQLite database named:

```text
prompts.sqlite3
```

The default data directory depends on the operating system:

| Platform     | Default directory                                                                |
| ------------ | -------------------------------------------------------------------------------- |
| Windows      | `%APPDATA%\PromptManager`                                                        |
| macOS        | `~/Library/Application Support/PromptManager`                                    |
| Linux / Unix | `$XDG_DATA_HOME/prompt-manager`, falling back to `~/.local/share/prompt-manager` |

The database stores:

* Prompts and fixed presets
* Remembered placeholder values for each prompt
* Application settings and temporary text

SQLite runs in WAL journal mode with foreign-key enforcement enabled.

## Configuring the Data Directory

Override the default data directory with the following environment variable:

```bash
PROMPT_MANAGER_DATA_DIR=/path/to/data
```

You can also specify the directory when launching the application:

```bash
prompt-manager --data-dir /path/to/data
```

or:

```bash
python -m prompt_manager --data-dir /path/to/data
```

The command-line option takes precedence over the platform-specific default location.

## Building a Desktop Executable

The project includes `build.py` and a dedicated `launcher.py` for building a single-file, windowed desktop executable with PyInstaller.

Install PyInstaller before building:

```bash
python -m pip install PyInstaller
```

Then run:

```bash
python build.py
```

The build script uses PyInstaller's single-file windowed mode and names the application `PromptManager`.

A successful build is written to:

```text
dist/
```

The exact executable format depends on the operating system used to perform the build.

## License

This project is licensed under the MIT License.
