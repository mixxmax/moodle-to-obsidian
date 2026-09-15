# Moodle → Obsidian

把 Moodle 课件按**原生目录结构**同步进 Obsidian vault。  
承诺：**课程自动落地，结构不乱，更新不漏。系统只组织，不解读。**

本仓库是给 AI agent / 本机脚本用的 **skill 包**（操作手册 + 可执行脚本），不是 Obsidian 插件本体。

## 谁适合用

- 用 Moodle 上课、用 Obsidian 记笔记的学生
- 想消灭「每周检查 → 手动下载 → 挪文件夹 → 怕漏更新」的同步仪式
- 愿意自己保管 Moodle token（每用户自持，不上传、不共用）

目前登录与取 token 流程以 **HKU Moodle（CAS-only）** 验证过；其它学校只要支持 Moodle mobile token / `moodle-dl`，镜像与伴生层可复用。

## 它做什么 / 不做什么

| 做 | 不做 |
|---|---|
| 原样镜像 Moodle 文件夹树 | 总结、打标签、判重点 |
| 增量更新；老师撤下的文件本地留底 | 替你交作业或替代 Moodle |
| 本地手改冲突时备份 `*.local-edit.bak` | 把 token 存进仓库或云端 |
| docx → md 伴生；pdf 不转；pptx 文字降级 | 后台常驻守护（定时需自建） |
| 可选：只读查 ddl / 成绩 / briefing | 在同步管道里跑 LLM |

## 架构（两份配置，不要合并）

```text
<vault>/
├── moodle-mirror.json          # mirror 用：路径、mappings、downloader
├── moodle-sync/                # moodle-dl 下载根
│   └── config.json             # moodle-dl 用：domain、course_ids、token（chmod 600）
└── <Course Folder>/
    └── 99 Moodle Mirror/       # 精确镜像 + Moodle Mirror Index.md
```

| 文件 | 所有者 | 关键键 |
|---|---|---|
| `moodle-mirror.json`（vault 根，从 `config.template.json` 复制） | `scripts/mirror.py` | `source_root`, `vault_root`, `mappings`, `downloader` |
| `moodle-sync/config.json` | `moodle-dl` | `moodle_domain`, `moodle_path`, `download_course_ids`, `token` |

## 快速开始

### 依赖

```bash
pip install moodle-dl          # 或: uv tool install moodle-dl
pip install python-docx python-pptx   # 伴生 md；缺了会写 link-only stub
```

### 配置

```bash
# 1) mirror 配置（放在 vault 根）
cp config.template.json <vault>/moodle-mirror.json
# 编辑 mappings（课号 → 课程文件夹名），确认 downloader 路径
# 只要镜像已有下载树、暂不拉取：把 downloader 设为 ""

# 2) 下载配置（moodle-dl 自己的）
mkdir -p <vault>/moodle-sync
cd <vault>/moodle-sync && moodle-dl --init
# 填 moodle_domain、download_course_ids
```

### 登录（HKU：浏览器取 token）

HKU 账号是 CAS-only，门户密码对 `/login/token.php` 无效。完整步骤见 [`references/moodle-login.md`](references/moodle-login.md)。摘要：

1. 浏览器登录 Moodle  
2. 访问 mobile launch URL（`urlscheme=moodledl`）→ 出现 `ERR_ABORTED` 即成功  
3. 在 Network 里找到 `moodledl://token=<base64>`  
4. 写入（**不会回显 token**）：

```bash
python3 scripts/save_token.py \
  --config <vault>/moodle-sync/config.json \
  --url 'moodledl://token=<base64>'
```

### 同步

```bash
python3 scripts/mirror.py --config <vault>/moodle-mirror.json doctor
python3 scripts/mirror.py --config <vault>/moodle-mirror.json run    # 拉取 + 镜像（需要 downloader）
python3 scripts/mirror.py --config <vault>/moodle-mirror.json sync   # 只镜像已有下载树
python3 scripts/mirror.py --config <vault>/moodle-mirror.json status
```

每轮会追加 changelog（默认 `Moodle Sync Updates.md`），并更新每课索引与 `.moodle-local-sync/last-run.json`。

### 伴生 Markdown

```bash
python3 scripts/to_markdown.py "<vault>/<Course Folder>"
```

- **docx**：必转（标题 / 表格 / 列表）  
- **pdf**：不转（Obsidian 原生渲染）  
- **pptx**：按 slide 抽文字，页首带降级警告  

### 可选：进度查询（moodle-mcp）

```bash
# 干跑（不调用网络）
python3 scripts/mcp_query.py --config <vault>/moodle-sync/config.json deadlines

# 实跑：需要 loyaniu/moodle-mcp checkout，并用其自带 venv 的 Python
python3 scripts/mcp_query.py --config <vault>/moodle-sync/config.json briefing \
  --mcp-dir /path/to/moodle-mcp
```

上游：[loyaniu/moodle-mcp](https://github.com/loyaniu/moodle-mcp)。只读、按需、非常驻。

### 可选：五原则凝结

镜像与伴生完成后再做。方法见 [`references/five-principles.md`](references/five-principles.md)。  
**先提案 → 你确认 → 再写入**；不进同步管道。

## Agent 用法

把本仓库当作 skill 目录加载后，按 [`SKILL.md`](SKILL.md) 的 7 步执行：检测 → 登录 → 镜像 → 伴生 → MCP → 凝结 → 结构化回报。

## 仓库结构

```text
SKILL.md                 # agent 操作手册
config.template.json     # mirror 模板（无密钥）
scripts/
  mirror.py              # 精确镜像
  to_markdown.py         # 伴生 md
  save_token.py          # token 入库（chmod 600）
  mcp_query.py           # 只读进度 shim
references/
  moodle-login.md
  companion-rules.md
  five-principles.md
  moodle-mcp.md
  troubleshooting.md
```

## 定时拉取？

本 skill **不内置** launchd / cron。需要无人值守时，用系统调度器包一层，例如：

```bash
python3 /path/to/moodle-to-obsidian-skill/scripts/mirror.py \
  --config /path/to/vault/moodle-mirror.json run
```

## 安全

- 永远不要提交 `moodle-sync/config.json` 或含 token 的文件  
- `save_token.py` 写入后 `chmod 600`，且不打印 token  
- mirror 拉取日志会脱敏 `token=` / `password=` / `cookie=`  

## License

MIT
