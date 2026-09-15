# Moodle → Obsidian

<p align="center">
  <img src="docs/hero.gif" alt="Moodle course files sync into an organized Obsidian vault" width="100%" />
</p>

<p align="center"><em>Moodle 课件 → 自动落进 Obsidian · 结构不乱 · 更新不漏</em></p>

把 Moodle 上的课件，按原来的文件夹样子，放进你的 Obsidian 库。  
系统**只负责搬运和组织**，不替你总结、不改你的笔记习惯。

---

## 产品就两段（先分清）

整件事可以想成流水线的两步，**可以一起跑，也可以分开跑**：

```text
① 拉取 / 更新          从 Moodle 把课件下载到本机缓存
② 映射进 Obsidian      把缓存里的树，原样放进各课的「99 Moodle Mirror」
```

| 段 | 干什么 | 你怎么叫它 | 系统命令（给 agent / 自己跑） |
|---|---|---|---|
| **① 拉取** | 联网，把 Moodle 上的新文件/更新拉下来 | 「帮我拉取 / 更新 Moodle」 | 下载器工作；结果在本机 `moodle-sync/` |
| **② 映射** | 不必须联网，把已下载的内容写进 Obsidian | 「帮我映射进 Obsidian / 同步进库」 | `mirror.py sync` |
| **①+② 一次做完** | 先拉再映射 | 「拉取并同步到 Obsidian」 | `mirror.py run` |

所以：**不是“说一句就永远全自动了”。**  
更准确的是——

- **你**：第一次（或凭证失效时）在浏览器里**登录一次** Moodle  
- **之后**：按需要下指令——可以只要①、只要②，或①+②一起  

登录是一次性验证；**拉取**和**映射**是两个可分开的动作。

---

## 你要做什么 vs 系统做什么

| | 谁做 |
|---|---|
| 浏览器里登录 Moodle（通常只需一次） | **你** |
| ① 从 Moodle 下载 / 增量更新课件 | **系统** |
| ② 按原结构映射进 Obsidian，写更新日志 | **系统** |
| 决定这次只要拉取、只要映射，还是两段一起 | **你**（或你吩咐 agent） |

密码改了、或同步提示登录失败时，再登录一次即可。

---

## 第一次怎么用

1. 让 agent（或按 `SKILL.md`）准备好本机环境  
2. **系统打开浏览器** → 你用港大账号**登录一次**  
3. 登录完成后，选一种跑法：  
   - **只要更新课件缓存**：做 ①  
   - **缓存已有、只要进 Obsidian**：做 ②  
   - **从头到尾一次做完**：①+②（`run`）  
4. 打开 Obsidian：对应课程下出现 `99 Moodle Mirror/`，结构和 Moodle 上一样  

成功时你会看到：

- 本机有一份 Moodle 下载缓存（① 的结果）  
- 各课里有 `99 Moodle Mirror/`（② 的结果）  
- 一份更新记录（这轮新增 / 更新 / 撤回留底了什么）  

老师后来撤掉的文件，本地仍会保留；你改过镜像里的文件又碰上网上更新时，系统会先备份你的版本再覆盖。

---

## 同步之后还可以（可选）

- **伴生笔记**：docx → 可搜索的 `.md`（pdf 不转；pptx 只抽文字并标明「以原件为准」）  
- **查作业 / ddl / 成绩**：按需查询，不常驻后台  
- **定时**：本仓库不自带闹钟；需要的话用系统定时任务分别或一起跑 ① / ②  

---

## 它保证什么 / 不碰什么

| 会 | 不会 |
|---|---|
| 按 Moodle 原文件夹结构落地 | 替你总结重点、打标签 |
| 增量更新；撤下的文件本地留底 | 替你交作业、替代 Moodle 网站 |
| 冲突时先备份你的本地修改 | 把登录凭证上传到别人的服务器 |

登录凭证只存在你自己的电脑里，且不会打印到终端。

---

## 给 agent / 开发者

| 意图 | 命令 |
|---|---|
| 自检 | `python3 scripts/mirror.py --config <vault>/moodle-mirror.json doctor` |
| ①+② | `… run` |
| 仅 ② | `… sync` |
| 看上轮结果 | `… status` |

配置、登录细节与排障：[`SKILL.md`](SKILL.md) · [`references/moodle-login.md`](references/moodle-login.md) · [`references/troubleshooting.md`](references/troubleshooting.md)

## License

MIT
