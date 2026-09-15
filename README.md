# Moodle → Obsidian

<p align="center">
  <img src="docs/hero.gif" alt="Moodle course files sync into an organized Obsidian vault" width="100%" />
</p>

<p align="center"><em>Moodle 课件 → 自动落进 Obsidian · 结构不乱 · 更新不漏</em></p>

把 Moodle 上的课件，按原来的文件夹样子，自动放进你的 Obsidian 库。  
系统**只负责搬运和组织**，不替你总结、不改你的笔记习惯。

---

## 你要做什么（很短）

核心就一件事：**第一次打开浏览器，登录一次港大 Moodle。**  
登录成功后，凭证保存在你自己电脑上；之后下载、更新、放进课程文件夹，都由系统做。

```text
你：浏览器里登录一次 Moodle
        ↓
系统：记住登录 → 下载课件 → 按原结构放进 Obsidian
        ↓
你：打开 Obsidian，直接看到各课「99 Moodle Mirror」
```

| | 谁做 |
|---|---|
| 浏览器里登录 Moodle（通常只需一次） | **你** |
| 下载课件、对照课程、写入 Obsidian、记更新日志 | **系统** |
| 以后想再同步 | 跑一下同步（或让 agent / 定时任务代跑）——**一般不用再登录** |

密码改了、或很久以后同步报登录失败时，再登录一次即可。

---

## 第一次怎么用

如果你是把这个仓库交给 AI agent（或按 `SKILL.md` 操作），对你来说体验接近：

1. **说一声**「帮我把 Moodle 同步到 Obsidian」  
2. Agent / 脚本会准备好本机环境  
3. **系统打开浏览器** → 你用港大账号**登录一次**（按页面提示完成即可）  
4. 登录完成后，其余步骤交给系统：拉取课件 → 镜像进库 → 写更新记录  
5. 打开 Obsidian，在对应课程下看到 `99 Moodle Mirror/`，结构和 Moodle 上一样  

成功时你会看到：

- 各门课里多了 `99 Moodle Mirror/`（里面是原样课件树）  
- 库里有一份更新记录（这轮新增了什么、更新了什么）  
- 之后再同步：有新文件会进来；老师撤掉的文件本地仍保留  

---

## 同步之后还可以（可选）

- **伴生笔记**：把 docx 转成可搜索的 `.md`（pdf 不转；pptx 只抽文字并标明「以原件为准」）  
- **查作业 / ddl / 成绩**：按需查询，不常驻后台  
- **定时同步**：本仓库不自带闹钟；需要的话用系统定时任务每天跑一次同步即可  

---

## 它保证什么 / 不碰什么

| 会 | 不会 |
|---|---|
| 按 Moodle 原文件夹结构落地 | 替你总结重点、打标签 |
| 增量更新；撤下的文件本地留底 | 替你交作业、替代 Moodle 网站 |
| 你改过的文件若与网上冲突，先备份再更新 | 把登录凭证上传到别人的服务器 |

登录凭证只存在你自己的电脑里，且不会打印到终端。

---

## 给 agent / 开发者

配置细节、双配置文件、命令行与排障见：

- [`SKILL.md`](SKILL.md) — 完整操作步骤  
- [`references/moodle-login.md`](references/moodle-login.md) — 登录与 token  
- [`references/troubleshooting.md`](references/troubleshooting.md) — 常见问题  

```text
SKILL.md · config.template.json · scripts/ · references/ · docs/hero.gif
```

## License

MIT
