# Moodle to Obsidian (for HKU)

<p align="center">
  <img src="docs/hero.gif" alt="Moodle course files sync into an organized Obsidian vault" width="100%" />
</p>

<p align="center"><em>Moodle 课件云 → 精确镜像（只增不删）→ Obsidian 知识库</em></p>

把 Moodle 课件按**原生目录结构**同步进 Obsidian vault。  
承诺：**课程自动落地，结构不乱，更新不漏。系统只组织，不解读。**

本仓库提供操作手册（`SKILL.md`）+ 本机脚本，方便人或 AI agent 完成配置与同步；不是 Obsidian 插件本体。

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

## 拉取怎么成功：谁做什么、系统做什么、最后长什么样

整条链路只有两段，顺序不能反：

```text
① 拉取（moodle-dl）     用户配好凭证与课表 → 系统从 Moodle 下载到 moodle-sync/
② 镜像（mirror.py）     用户下一条命令     → 系统把下载树原样拷进各课 99 Moodle Mirror/
```

`run` = ① + ② 连着做。`sync` = 只做 ②（已经有下载树时）。  
**拉取成败取决于 ①；镜像成败取决于 mappings 是否对上课号。**

### 总览：用户 vs 系统

| 阶段 | 你（用户）要做的 | 系统会做的 | 成功时你看到的 |
|---|---|---|---|
| A. 装工具 | 安装 `moodle-dl`，记下它的路径（`command -v moodle-dl`） | — | 终端能跑 `moodle-dl --help` |
| B. 两份配置 | 在 vault 根写 `moodle-mirror.json`；在 `moodle-sync/` 里 `moodle-dl --init` | — | 两文件都在，且**不要合并** |
| C. 登录取 token | 浏览器登录 Moodle，按下面「取 token」步骤拿到 `moodledl://token=…`，交给 `save_token.py` | 把 token 写入 `moodle-sync/config.json`（`chmod 600`，不回显） | 打印 `saved … Token NOT printed.` |
| D. 自检 | 跑 `doctor` | 检查路径、mappings、downloader、锁文件 | 全是 `OK`（不要有 `ISSUE`） |
| E. 拉取+镜像 | 跑 `run` | 调 moodle-dl 增量下载 → 再按课号镜像进 vault；写 changelog / index / last-run | `moodle-sync/` 出现课程树；各课下有 `99 Moodle Mirror/`；changelog 有 Added/Updated… |
| F.（可选）伴生 md | 对某课跑 `to_markdown.py` | docx→md；pdf 不动；pptx 抽文字并标降级 | 原件旁多出同名 `.md` |

缺任何一环（没 token、没 `download_course_ids`、`downloader` 空、mappings 对不上），**拉取或镜像就会停**；系统宁可大声失败，也不静默假装成功。

---

### 逐步操作（HKU 已验证路径）

下面默认你的 Obsidian 库路径是 `<vault>`，本仓库克隆在旁可引用 `scripts/`。

#### 1）安装依赖

```bash
pip install moodle-dl                 # 或: uv tool install moodle-dl
command -v moodle-dl                  # 记下绝对路径，稍后填进 downloader
pip install python-docx python-pptx   # 伴生 md 用；缺了会写 link-only stub，不影响拉取
```

#### 2）准备两份配置（不要合成一个文件）

**Mirror 配置（管「拷到哪」）——必须在 vault 根：**

```bash
cp config.template.json <vault>/moodle-mirror.json
```

打开编辑：

- `downloader`：填上一步的 moodle-dl 路径，例如 `~/.local/bin/moodle-dl`  
  - 若暂时只想镜像已有下载、不联网拉取：设为 `""`，之后用 `sync` 而不是 `run`
- `mappings`：Moodle 课号 → vault 里课程文件夹名，例如  
  `"PCLL8010": "Civil Litigation (PCLL8010)"`  
  课号要能从下载文件夹名里匹配到（通用形态如 `PCLL8010`、`LAWS1234`）
- `source_root` / `vault_root` 保持相对 vault 根即可（模板默认 `./moodle-sync` 与 `.`）

**Download 配置（管「从哪拉、拉哪几门」）——属于 moodle-dl：**

```bash
mkdir -p <vault>/moodle-sync
cd <vault>/moodle-sync && moodle-dl --init
```

按向导填写（或事后编辑 `moodle-sync/config.json`）：

- `moodle_domain`：如 `moodle.hku.hk`
- `download_course_ids`：**数字课号列表**（来自课程页 URL 里的 `id=`，不是 `PCLL8010` 这种代码）
- `token`：下一步写入，这里可先空着

> 为什么是两份？moodle-dl 只认 domain / course_ids / token；mirror 只认 paths / mappings / downloader。揉在一起会配错且难排障。

#### 3）取 token（HKU：CAS-only，密码直登无效）

HKU 门户密码对 `/login/token.php` 会 `invalidlogin`。用官方 App 同款 launch 流程（细节见 [`references/moodle-login.md`](references/moodle-login.md)）：

1. 用**干净/可控**的 Chrome 登录 `https://moodle.hku.hk`
2. 地址栏打开：  
   `https://moodle.hku.hk/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=12345&urlscheme=moodledl`
3. 页面报 `ERR_ABORTED` / 打不开自定义协议 —— **这就是成功信号**
4. DevTools → Network，找到 `moodledl://token=<base64>` 请求
5. 写入（脚本**不会**把 token 打到终端）：

```bash
python3 scripts/save_token.py \
  --config <vault>/moodle-sync/config.json \
  --url 'moodledl://token=<base64>'
```

系统效果：只更新该文件里的 `token` 字段，保留 domain / course_ids，并 `chmod 600`。

#### 4）自检（不过关不要 run）

```bash
python3 scripts/mirror.py --config <vault>/moodle-mirror.json doctor
```

期望：`source_root` / `vault_root` / `mappings` / `downloader` / download lock 均为 `OK`。  
有 `ISSUE` 先修配置；不要跳过。

#### 5）一键拉取 + 镜像

```bash
python3 scripts/mirror.py --config <vault>/moodle-mirror.json run
```

**系统实际顺序：**

1. 在 `moodle-sync/` 工作目录调用 `moodle-dl -q`（按你的 `download_course_ids` **增量**拉文件）
2. 若拉取失败 → 打印错误并退出，**不改动** vault 里的镜像（失败可见）
3. 拉取成功 → 扫描 `moodle-sync/` 下课程文件夹，用课号对照 `mappings`
4. 把文件原子拷贝进 `<课程夹>/99 Moodle Mirror/`（原生相对路径不变）
5. 更新每课 `Moodle Mirror Index.md`、追加 `Moodle Sync Updates.md`、写入 `.moodle-local-sync/last-run.json`

**成功时磁盘上应有：**

```text
<vault>/moodle-sync/<Moodle课程名>/…原样树…
<vault>/<你的课程夹>/99 Moodle Mirror/…同一相对路径…
<vault>/<你的课程夹>/99 Moodle Mirror/Moodle Mirror Index.md
<vault>/Moodle Sync Updates.md          # 本轮 Added/Updated/Withdrawn/Conflicted
```

再看状态：

```bash
python3 scripts/mirror.py --config <vault>/moodle-mirror.json status
```

### 常见分叉

| 你的情况 | 该跑什么 | 说明 |
|---|---|---|
| 第一次 / 想从 Moodle 拉新文件 | `run` | 需要 `downloader` + 有效 token + `download_course_ids` |
| 文件已经在 `moodle-sync/`，只想进 vault | `sync` | 不联网；`downloader` 可为空 |
| `run` 提示 no downloader | 填 `downloader` 或改用 `sync` | 空 downloader = 同步专用模式 |
| changelog 出现 `UNMAPPED` | 把该课号加进 `mappings` 再 `sync` | 已下载但还没映射进 vault |
| 本地改过镜像文件又碰上远程更新 | 会生成 `*.local-edit.bak` | 你的版本在 bak，镜像更新为 Moodle 版 |

排障表见 [`references/troubleshooting.md`](references/troubleshooting.md)。

---

## 拉取成功之后（可选）

### 伴生 Markdown（让 docx/pptx 在库内可搜）

```bash
python3 scripts/to_markdown.py "<vault>/<Course Folder>"
```

- **docx**：必转（标题 / 表格 / 列表）  
- **pdf**：不转（Obsidian 原生渲染）  
- **pptx**：按 slide 抽文字，页首带降级警告  

### 进度查询（moodle-mcp，可选）

```bash
# 干跑（不调用网络）
python3 scripts/mcp_query.py --config <vault>/moodle-sync/config.json deadlines

# 实跑：需要 loyaniu/moodle-mcp checkout，并用其自带 venv 的 Python
python3 scripts/mcp_query.py --config <vault>/moodle-sync/config.json briefing \
  --mcp-dir /path/to/moodle-mcp
```

上游：[loyaniu/moodle-mcp](https://github.com/loyaniu/moodle-mcp)。只读、按需、非常驻。

### 五原则凝结（可选，不进同步管道）

镜像与伴生完成后再做。方法见 [`references/five-principles.md`](references/five-principles.md)。  
**先提案 → 你确认 → 再写入。**

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
python3 /path/to/moodle-to-obsidian/scripts/mirror.py \
  --config /path/to/vault/moodle-mirror.json run
```

## 安全

- 永远不要提交 `moodle-sync/config.json` 或含 token 的文件  
- `save_token.py` 写入后 `chmod 600`，且不打印 token  
- mirror 拉取日志会脱敏 `token=` / `password=` / `cookie=`  

## License

MIT
