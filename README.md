# Debate 辩论素材库

给魁北克 Secondary 5 学生准备的英语议论文（argumentative essay）辩论素材系统：自动抓取两个权威辩论网站的辩题（正反论点）→ 用 DeepSeek 生成三语导读 → 同步到思源笔记 → 发布成静态网站。

---

## 一、项目介绍

**目标**：帮学生备考魁省省考议论文写作，积累大量英文正反论点素材，快速理解议题、掌握论证思路、学会套用英文句型。

**数据来源（两个）**：

| 来源 | 说明 | 规模 |
|---|---|---|
| Britannica ProCon | 美国社会议题，正反论点各 3~5 条，带引用 | 约 113 个主题 |
| iDebate Debatabase | 「This House believes…」辩论动议，更学术，每个论点自带反驳 | 15 个分类、数百个辩题 |

**核心能力**：
- 自动抓取两个网站的辩题（背景 + 正方论点 + 反方论点 + 引用来源）
- 用 DeepSeek 生成三语导读（议题速览 + 正反立场概括 + 英文写作句型）
- 笔记同时存本地和思源笔记（独立项目区 / Debate）
- 自动构建成静态网站，发布到 Cloudflare Pages

**整体流水线（三步）**：

```
fetch.py       抓取辩题            → data/<来源>/*.json
convert.py     DeepSeek 三语导读    → 01-Inbox/*.md + 思源
build_site.py  渲染成静态网站      → docs/（供 Cloudflare 发布）
```

---

## 二、目录结构

| 路径 | 作用 |
|---|---|
| `fetch.py` | 第 1 步：抓 ProCon + iDebate 辩题 |
| `convert.py` | 第 2 步：调 DeepSeek 生成三语导读 |
| `build_site.py` | 第 3 步：把笔记渲染成静态网站 |
| `sources.json` | **数据源配置（两个网站）** |
| `.env` | 密钥配置（DeepSeek key、思源 token 等，勿提交） |
| `run_all.bat` | 双击运行：fetch + convert + build + git push |
| `data/` | 抓到的原始辩题 JSON（可再生成，已 gitignore） |
| `01-Inbox/` | 生成好的笔记（本地副本，**会提交 git**） |
| `output/` | 运行产物、去重状态（已 gitignore） |
| `docs/` | **静态网站产物，直接发布** |

---

## 三、环境准备（只做一次）

1. **Python 3.14**（本机已装，PowerShell 里可直接用 `python`）。

2. **安装依赖**（在项目目录打开 PowerShell 执行）：

```powershell
pip install requests      # 抓取网页必需
pip install markdown      # 建站必需（否则笔记正文变成纯文本）
```

3. **配置 `.env`**（已从 sec5 复制，改这里就行，**不要把真实内容提交到公开仓库**）：

| 变量 | 作用 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 密钥（复用 sec5 的） |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | `deepseek-chat` |
| `SIYUAN_BASE_URL` | 默认 `http://localhost:6806` |
| `SIYUAN_TOKEN` | 思源令牌（复用 sec5 的） |
| `SIYUAN_NOTEBOOK` | 思源「独立项目区」笔记本 ID |

> 思源笔记需在本地运行（localhost:6806）。如果没开思源，笔记仍会存本地 `01-Inbox/`，只是不同步到思源。

---

## 四、日常使用方法

**最简单：双击 `run_all.bat`**，自动执行 fetch → convert → build → git push 全流程。

**手动分步跑**（PowerShell，逐条执行）：

```powershell
cd E:\Projects\debate
python fetch.py          # 抓辩题（每个来源默认 20 个）
python convert.py        # 调 DeepSeek 生成三语导读
python build_site.py     # 重新生成 docs/
git add 01-Inbox/ docs/
git commit -m "feat: 更新辩论素材"
git push origin main
```

### 抓取更多 / 全量

`fetch.py` 默认按 `sources.json` 里 `max_items`（当前 20）抓取。想抓全量：

```powershell
python fetch.py --full            # 不限量，抓完两个网站全部辩题
python fetch.py --source procon   # 只抓 ProCon
python fetch.py --source idebate  # 只抓 iDebate
python fetch.py --limit 50        # 每个来源抓 50 个
```

### 更新网站（发布到线上）

每次生成新笔记后，网站需要重新构建并推送（`run_all.bat` 已包含这一步）。推送后 Cloudflare Pages 会自动重新部署。

---

## 五、各脚本用法速查

```powershell
python fetch.py                  # 抓所有启用的源（每个 max_items 个）
python fetch.py --full           # 全量抓取
python fetch.py --source procon  # 只抓某个源
python fetch.py --limit 30       # 每个源抓 30 个

python convert.py                # 处理 data/ 下所有未处理辩题
python convert.py <文件.json>     # 只处理单个辩题

python build_site.py             # 把 01-Inbox/*.md 渲染成 docs/
```

---

## 六、修改的方法

### 1. 改抓取数量 / 启用禁用来源

改 `sources.json` 里的 `max_items`（抓取上限）或 `enabled`（true/false）。

### 2. 改三语导读的结构 / 提示词

改 `convert.py` 里的 `SYSTEM_PROMPT`。这是发给 DeepSeek 的提示词，定义了「议题速览 → 正方立场 → 反方立场 → 写作借鉴」的结构。

### 3. 改网站样式 / 布局

改 `build_site.py` 里的 `CSS` 字符串（约第 58 行开始）。

### 4. 改 slug 生成规则（辩题网址）

改 `build_site.py` 里的 `slugify()` 函数。注意保留特殊字符会破坏链接。

---

## 七、常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `fetch.py` 抓到 0 个或大量「论点不完整」 | 网站结构变了或被限流；等一会儿再试，或用 `--source` 单独试 |
| `fetch.py` 报「缺少依赖 requests」 | `pip install requests` |
| `convert.py` 报 LLM 调用失败 | 检查 `.env` 的 `DEEPSEEK_API_KEY` 是否填了 |
| 笔记没同步到思源 | 思源没开（localhost:6806 连不上）；本地 `01-Inbox/` 仍有副本 |
| `build_site.py` 报「缺少依赖 markdown」 | `pip install markdown` |
| PowerShell 报错 `&&` | PowerShell 5.1 不支持 `&&`，命令分两行执行 |

---

## 八、重要提醒

1. **`.env` 里有真实密钥**（DeepSeek key、思源 token），已在 `.gitignore` 里，**切勿提交到 GitHub**。
2. **提交 git 用 `git add 01-Inbox/ docs/`**，别用 `git add .`（会误提交 `.claude/`、密钥等）。
3. `data/`、`output/`、`__pycache__/` 都是可再生或缓存，已 gitignore，不用管。
4. 网站是纯静态的（`docs/`），改了笔记或配置后一定要跑 `build_site.py` 再 push，否则线上看不到变化。
