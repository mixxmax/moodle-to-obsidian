# Moodle → Obsidian

<p align="center">
  <img src="docs/hero.gif" alt="Moodle course files sync into an organized Obsidian vault" width="100%" />
</p>

<p align="center"><em>Moodle 课件 → 自动落进 Obsidian · 结构不乱 · 更新不漏</em></p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg" alt="Python 3.10+"></a>
  <a href="https://obsidian.md"><img src="https://img.shields.io/badge/Obsidian-Compatible-purple.svg" alt="Obsidian Compatible"></a>
  <img src="https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey.svg" alt="Platform">
</p>

把 Moodle 上的课件，按原来的文件夹样子，原样镜像放进你的 Obsidian 库。  
系统**只负责搬运和组织**，不替你总结重点、不篡改你的个人笔记。

需要查作业 ddl / 成绩 / 简报时，可**可选对接**开源项目 [loyaniu/moodle-mcp](https://github.com/loyaniu/moodle-mcp)（共用同一登录，本仓库只提供薄封装，不是自研 MCP 服务）。

目前登录流程以 **HKU Moodle（CAS 统一身份认证）** 深度验证过；其它高校只要支持 Moodle 移动端 token 或 `moodle-dl`，课件镜像与伴生层同样通用可用。

---

## 全景架构与数据流向

```text
       [HKU Moodle (CAS 网页认证)]
                   │ (增量下载 / 移动端 Token 授权)
                   ▼
       ┌───────────────────────┐
       │   ① 本地拉取缓存区     │  moodle-sync/ (moodle-dl 增量同步)
       │  (moodle_state.db)    │  保存原始文件，离线随时可用
       └───────────┬───────────┘
                   │ (同构映射 / 覆盖前备份 .local-edit.bak)
                   ▼
       ┌───────────────────────┐
       │   ② Obsidian 镜像区   │  <Vault>/<Course>/99 Moodle Mirror/
       │  (Moodle Mirror Index)│  100% 还原 Moodle 目录树 + 自动索引
       └───────────┬───────────┘
                   │
         ┌─────────┴───────────────┬────────────────────────┐
         ▼                         ▼                        ▼
 ┌───────────────┐         ┌───────────────┐        ┌───────────────┐
 │ 伴生 Markdown │         │ 可选：对接    │        │  五原则凝结   │
 │ docx/pptx可搜 │         │ loyaniu/      │        │ 第一性/控制论 │
 │               │         │ moodle-mcp    │        │               │
 └───────────────┘         └───────────────┘        └───────────────┘
```

---

## 30 秒极速上手

### 1. 安装核心依赖
```bash
pip install moodle-dl python-docx python-pptx
```

### 2. 初始化配置与浏览器一次性登录
```bash
# 复制映射配置文件到你的 Obsidian 库根目录
cp config.template.json /path/to/your/vault/moodle-mirror.json

# 在浏览器中登录 Moodle 完成 CAS 认证后保存 Token（以 HKU 为例）
python3 scripts/save_token.py --config /path/to/your/vault/moodle-sync/config.json --url 'moodledl://token=...'

# 自检环境配置与路径连通性
python3 scripts/mirror.py --config /path/to/your/vault/moodle-mirror.json doctor
```

### 3. 一键同步进 Obsidian
```bash
# 全流程：拉取最新课件 + 原生映射进 Obsidian 库
python3 scripts/mirror.py --config /path/to/your/vault/moodle-mirror.json run

# 为各课程生成伴生 Markdown（使 Word/PPT 在 Obsidian 内支持全文搜索）
python3 scripts/to_markdown.py "/path/to/your/vault/<Course Folder>"
```

---

## 产品能力一览

| 能力 | 一句话说明 | 要不要你盯着 | 对应命令 / 工具 |
|---|---|---|---|
| **① 拉取 / 更新** | 从 Moodle 把课件增量下载到本机缓存 | 登录一次后，系统自动完成 | `moodle-dl` 写入 `moodle-sync/` |
| **② 映射进 Obsidian** | 把下载树原样放进各课 `99 Moodle Mirror/` | 系统自动完成（可完全离线） | `python3 scripts/mirror.py sync` |
| **①+② 完整同步** | 先联网拉取最新更新，再立即镜像映射进库 | 一键完成 | `python3 scripts/mirror.py run` |
| **伴生 Markdown** | docx 必转结构化 md；pdf 不动；pptx 抽文字与备注 | 按需运行 | `python3 scripts/to_markdown.py` |
| **五原则知识凝结** | 镜像就绪后，基于第一性原理与控制论整理笔记 | 需你确认后再写入 | 通用五原则方法论 |
| **可选：moodle-mcp** | 对接上游只读查 ddl / 成绩 / briefing（非本仓库自研） | 需另装上游；未装不影响①② | `scripts/mcp_query.py` 薄封装 |

---

## 核心两段论（先分清）

整套系统的核心设计理念是将**网络传输**与**笔记库映射**彻底解耦：

```text
① 拉取 / 更新          从 Moodle 把课件增量下载到本机缓存（moodle-sync/）
② 映射进 Obsidian      把缓存里的目录树，原样放进各课的「99 Moodle Mirror」
```

- **不是**「说一句就永远全自动后台偷跑」
- **是**：你在浏览器里**登录一次**；之后按需下达指令——只要①拉取缓存、只要②映射进库，或①+②一键跑完。

### 你 vs 系统的职责边界

| 操作项目 | 谁来做 |
|---|---|
| 浏览器里登录 Moodle 完成授权（通常只需一次） | **你** |
| ① 从 Moodle 增量下载课件至本机缓存 | **系统** |
| ② 按原结构映射进 Obsidian，生成更新日志与文件索引 | **系统** |
| 决定本次只要①、只要②，还是一体运行 | **你**（或吩咐 AI Agent） |
| 整理后的知识凝结笔记是否写入 Vault | **你确认后**系统才写入 |
| （可选）查 ddl / 成绩 / 简报 | 若已安装上游 moodle-mcp，由封装脚本只读查询 |

---

## 可选集成：loyaniu/moodle-mcp

**①② 镜像是本产品的主业。** 作业 ddl、成绩、每日 briefing 来自开源上游 [loyaniu/moodle-mcp](https://github.com/loyaniu/moodle-mcp)，本仓库只提供 `scripts/mcp_query.py` 做**同凭证、按需调用**的薄封装——未安装上游时，**不影响拉取与映射**。

- 与下载器共用 `moodle-sync/config.json` 里的 token，不另开账号  
- 只读、按需、非常驻；结果默认是快照说明，不自动写进 vault  
- 实跑需本地 checkout 上游，并用其可用的 Python 环境（详见上游文档）

```bash
# 干跑：确认有 token，不真正请求
python3 scripts/mcp_query.py --config <vault>/moodle-sync/config.json deadlines

# 实跑：指向本地 moodle-mcp 仓库
python3 scripts/mcp_query.py --config <vault>/moodle-sync/config.json briefing \
  --mcp-dir /path/to/moodle-mcp
```

工具名与约定见 [`references/moodle-mcp.md`](references/moodle-mcp.md)。

---

## 伴生 Markdown（让课件在库内可全文搜索）

Word / PPT 在 Obsidian 库内通常无法被全局检索。通过伴生转换引擎可一键生成轻量伴生 `.md`：

```bash
python3 scripts/to_markdown.py "<vault>/<Course Folder>"
```

| 格式 | 转换策略 | 呈现效果 |
|---|---|---|
| **.docx** | **必转** | 标题层级、Markdown 表格、列表完整保留，顶部提供原件双向回链 |
| **.pdf** | **不转** | Obsidian 原生完美渲染，保留原始法律/学术版式 |
| **.pptx** | **抽取文字** | 按幻灯片抽取文字与讲者备注（Speaker Notes），标明抽取自原件 |

- **安全原则**：原始二进制文件永不修改；已有 `.md` 默认不覆盖；每个伴生文件均附带返回原件的标准链接。
- 详见 [`references/companion-rules.md`](references/companion-rules.md)。

---

## 五原则凝结层（高阶知识沉淀）

在镜像与伴生文件齐全后，可用**通用五原则**将庞杂课件提炼为实战专题卡片：

| 原则 | 核心方法 | 解决的痛点 |
|---|---|---|
| **1. 第一性原理** | 拆解为不可再拆的底层需求（告知 / 界定 / 证明 / 效率与代价） | 遇到陌生法条也能推出底层法理与目的 |
| **2. 工程控制论** | 建立状态机模型（S1–S5 状态变量、G1–G5 不可逆闸门、三大反馈回路） | 明确当前诉讼/业务所处阶段与下一步合法动作 |
| **3. 顺向主干** | 是什么 ➔ 核心流程 ➔ 精确时限与起算点 | 建立自顶向下的标准实务执行主干 |
| **4. 横向耦合** | 跨制度联动关系与时点错位表（如法院暑期八月冻结期） | 杜绝单点知识盲区与连锁计算错误 |
| **5. 逆向目的** | 目的 ➔ 工具 ➔ 代价（根据诉讼目标选择最佳程序工具） | 直击实务决策与考场案情应对 |

- **操作纪律**：**先给提案 ➔ 你确认 ➔ 系统才写入**，严禁未经确认污染笔记库。
- 详见 [`references/five-principles.md`](references/five-principles.md)。

---

## 安全与隐私承诺

| 系统保证做到的 | 系统绝对不碰的 |
|---|---|
| 100% 保持 Moodle 原始文件夹结构 | 绝不替你主观删改内容或代写作业 |
| 增量更新；线上撤回的文件本地始终安全留底 | 绝不把你的登录凭证上传至第三方服务器 |
| 遇到冲突时自动先将本地修改备份为 `*.local-edit.bak` | 绝不常驻后台偷跑占用资源 |
| 凭证权限收紧为 `chmod 600` 且终端输出严格脱敏 | 绝不在同步管道中擅自调用 LLM 改名重组 |

---

## 库内目录推荐布局

```text
<你的 Obsidian Vault>/
├── moodle-mirror.json              # 映射配置（路径、课程对应、下载器配置）
├── moodle-sync/                    # ① 拉取缓存区（moodle-dl 专用工作目录）
│   └── config.json                 # 登录凭证与 Token（chmod 600，严禁提交）
├── Moodle Sync Updates.md          # 自动生成的每轮更新日志
└── <某门课程目录>/
    ├── 01 SG / Exercises/          # 你的个人练习与演练剧本
    ├── 03 Condensation/            # 五原则专题凝结卡片
    └── 99 Moodle Mirror/           # ② 映射结果：与 Moodle 100% 同构
        ├── Moodle Mirror Index.md  # 自动生成的课件导航索引（手写区不会被覆盖）
        └── ...
```

两份配置**不要合并**：

| 文件 | 所有者 | 关键键 |
|---|---|---|
| `<vault>/moodle-mirror.json`（从 `config.template.json` 复制） | `scripts/mirror.py` | `source_root`, `vault_root`, `mappings`, `downloader`, `mirror_folder` |
| `<vault>/moodle-sync/config.json`（`chmod 600`） | `moodle-dl` | `moodle_domain`, `moodle_path`, `download_course_ids`, `token` |

首次初始化请先 `mkdir -p <vault>/moodle-sync`，再在该目录运行 `moodle-dl --init`。

---

## 常用命令速查表

| 使用场景 | 终端命令 |
|---|---|
| **自检配置与依赖** | `python3 scripts/mirror.py --config <vault>/moodle-mirror.json doctor` |
| **全流程同步 (①+②)** | `python3 scripts/mirror.py --config <vault>/moodle-mirror.json run` |
| **仅镜像到库 (仅②)** | `python3 scripts/mirror.py --config <vault>/moodle-mirror.json sync` |
| **查看上轮更新状态** | `python3 scripts/mirror.py --config <vault>/moodle-mirror.json status` |
| **生成伴生 Markdown** | `python3 scripts/to_markdown.py "<vault>/<Course Folder>"` |
| **（可选）mcp 干跑** | `python3 scripts/mcp_query.py --config <vault>/moodle-sync/config.json deadlines` |
| **（可选）mcp 实跑** | `… briefing --mcp-dir /path/to/moodle-mcp`（需已安装上游） |

- 登录与 Token 获取指南：[`references/moodle-login.md`](references/moodle-login.md)
- 常见问题与排障指南：[`references/troubleshooting.md`](references/troubleshooting.md)

---

## 仓库文件导航

```text
SKILL.md                 # Agent 完整标准化操作手册（7 步流程）
config.template.json     # 映射配置模板（安全无密钥）
scripts/
  mirror.py              # ①+② 同步与映射核心脚本
  to_markdown.py         # 伴生 Markdown 转换工具
  save_token.py          # 登录凭证安全写入工具（无回显）
  mcp_query.py           # 可选：对接 loyaniu/moodle-mcp 的薄封装
references/              # 登录 · 伴生 · mcp 集成说明 · 五原则 · 排障
docs/hero.gif            # README 演示头图
```

---

## License

[MIT](LICENSE)
