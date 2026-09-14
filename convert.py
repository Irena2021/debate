#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert.py — 第 2 步「中文导读」：读 data/*.json 辩题 → DeepSeek 中文导读 → 写本地 + 思源

用法：
    python convert.py                 # 处理 data/ 下所有未处理的辩题（逐条过 LLM）
    python convert.py <文件.json>      # 只处理单个辩题

产出：
    - 本地 01-Inbox/YYYY-MM-DD_[来源]_标题.md
    - 思源 独立项目区/Debate/01-Inbox/<同名>   （同步写入）
    - output/converted.json                    去重状态

LLM：DeepSeek 云端（api.deepseek.com），key 从 .env 读。依赖：仅标准库。
"""

import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# Windows 控制台默认 GBK，打印中文会崩；强制 stdout/stderr 用 UTF-8
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
INBOX_DIR = BASE / "01-Inbox"
CONVERTED_FILE = BASE / "output" / "converted.json"
ENV_FILE = BASE / ".env"

# 思源笔记：Debate 文档树在「独立项目区」笔记本下（notebook ID 复用 sec5 的）
SIYUAN_NOTEBOOK = "20260524205320-6lw22zq"
SIYUAN_TREE = "Debate"
SIYUAN_INBOX = "01-Inbox"

MAX_POINT_CHARS = 400   # 每个论点正文传给 LLM 的最大长度（导读只需抓核心逻辑）


def load_env(path):
    env = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env(ENV_FILE)
SIYUAN = {
    "base_url": ENV.get("SIYUAN_BASE_URL", "http://localhost:6806"),
    "token": ENV.get("SIYUAN_TOKEN", ""),
    "notebook": SIYUAN_NOTEBOOK,
}


def build_llm():
    env = load_env(ENV_FILE)
    return {
        "base_url": env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "api_key": env.get("DEEPSEEK_API_KEY", ""),
        "model": env.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "max_tokens": 4096,
        "temperature": 0.2,
    }


LLM = build_llm()

# ---------------------------------------------------------------------------
# 中文导读 Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是魁北克省 Secondary 5（高中五年级）学生的英语议论文（argumentative essay）辅导老师。学生备考魁省省考，需要用英语写议论文。下面提供学生从辩论网站收集的一个英文辩题素材（含背景 + 正反论点）。

你的任务：用中文写一段「中文导读」，帮学生快速理解这个辩题、掌握正反论点、并学会把这个素材用到议论文里。只输出导读正文的 Markdown（不含标题和元信息，标题/元信息由脚本另加）。不要输出解释文字、不要 JSON、不要用 ``` 代码块包裹。

严格按下面的结构写（层级不要改动）：

### 议题速览
用一句话中文概括这个辩题在争什么。

### 正方立场
把正方论点用中文简要概括成 3~5 条要点（每条一行，用 - 开头）。不要逐字翻译，抓核心逻辑即可。

### 反方立场
同样把反方论点概括成 3~5 条要点（每条一行，用 - 开头）。

### 写作借鉴
给出 2~3 条能直接套进议论文的英文句型/表达（必须从原文论点里提炼，保留英文），每条注明用途（如「引出论点」「让步转折」「总结」）。

要求：
- 中文讲解通俗，面向中学生，少堆术语。
- 英文句型必须来自原文，不编造。
- 排版：每个小标题与前后正文之间空一行。"""


# ---------------------------------------------------------------------------
# LLM 调用（OpenAI 兼容，纯标准库）
# ---------------------------------------------------------------------------
def _post(url, payload, headers, timeout=600):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def chat(system, user):
    url = LLM["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": LLM["model"],
        "temperature": LLM["temperature"],
        "max_tokens": LLM["max_tokens"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    out = _post(url, payload, {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {LLM['api_key']}",
    })
    msg = out["choices"][0]["message"]
    return msg.get("content") or msg.get("reasoning_content") or ""


def extract_markdown(text):
    text = text.strip()
    m = re.search(r"```(?:markdown|md)?\s*\n(.*?)\n```", text, re.S)
    if m:
        return m.group(1).strip()
    return text


# ---------------------------------------------------------------------------
# 读取 / 构建 markdown
# ---------------------------------------------------------------------------
def slugify(s):
    s = re.sub(r'[\\/:*?"<>|]+', "_", s).strip()[:80]
    return s or "untitled"


def fmt_point(p):
    """把一个论点渲染成 markdown（含可选反驳）。"""
    lines = [f"### {p.get('title', '').strip()}"]
    if p.get("body"):
        lines.append("")
        lines.append(p["body"].strip())
    if p.get("counterpoint"):
        lines.append("")
        lines.append(f"**反驳 Counterpoint**：{p['counterpoint'].strip()}")
    return "\n".join(lines)


def build_note(item, guide_md):
    title = item.get("title", "").strip()
    source_name = "Britannica ProCon" if item.get("source") == "procon" else "iDebate Debatabase"
    url = item.get("url", "")
    date = datetime.now().strftime("%Y-%m-%d")

    L = [f"# {title}", ""]
    category = item.get("category", "其他")
    L.append(f"> **元信息**：英语 | 来源：{source_name} | 分类：{category} | [原文]({url}) | {date}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 🎯 中文导读")
    L.append("")
    L.append(guide_md)
    L.append("")

    if item.get("intro"):
        L.append("## 📖 背景 Background")
        L.append("")
        L.append(item["intro"].strip())
        L.append("")

    if item.get("pro"):
        L.append("## ✅ 正方论点 Pros")
        L.append("")
        for p in item["pro"]:
            L.append(fmt_point(p))
            L.append("")

    if item.get("con"):
        L.append("## ❌ 反方论点 Cons")
        L.append("")
        for p in item["con"]:
            L.append(fmt_point(p))
            L.append("")

    if item.get("sources"):
        L.append("## 📚 引用来源 Sources")
        L.append("")
        L.append(item["sources"].strip())
        L.append("")

    return "\n".join(L)


def build_user_prompt(item):
    """把辩题精简后拼给 LLM（每个论点截断）。"""
    parts = [f"辩题：{item.get('title', '').strip()}"]
    if item.get("intro"):
        parts.append(f"\n背景：{item['intro'][:600]}")
    if item.get("pro"):
        parts.append("\n【正方论点】")
        for p in item["pro"]:
            parts.append(f"- {p.get('title', '').strip()}：{p.get('body', '')[:MAX_POINT_CHARS]}")
    if item.get("con"):
        parts.append("\n【反方论点】")
        for p in item["con"]:
            parts.append(f"- {p.get('title', '').strip()}：{p.get('body', '')[:MAX_POINT_CHARS]}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 思源写入
# ---------------------------------------------------------------------------
def siyuan_api(path, payload):
    url = SIYUAN["base_url"] + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Token {SIYUAN['token']}",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def siyuan_create(path, title, markdown):
    return siyuan_api("/api/filetree/createDocWithMd", {
        "notebook": SIYUAN["notebook"],
        "path": path,
        "title": title,
        "markdown": markdown,
    })


def doc_stem(item):
    src = item.get("source", "topic")
    title = item.get("title", "")
    return f"{datetime.now():%Y-%m-%d}_{src}_{slugify(title)}"


def save_local(item, md):
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    fname = doc_stem(item) + ".md"
    (INBOX_DIR / fname).write_text(md, encoding="utf-8")
    return fname


def save_siyuan(item, md):
    stem = doc_stem(item)
    try:
        r = siyuan_create(f"/{SIYUAN_TREE}/{SIYUAN_INBOX}/{stem}", item.get("title", ""), md)
        return r.get("code") == 0, r.get("msg", "")
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# 处理单个辩题
# ---------------------------------------------------------------------------
def process_item(path):
    item = json.loads(path.read_text(encoding="utf-8"))
    title = item.get("title", "").strip()
    print(f"[导读] {item.get('source')} / {title or path.stem}")
    if not item.get("pro") and not item.get("con"):
        print("  无论点，跳过。")
        return False

    try:
        raw = chat(SYSTEM_PROMPT, build_user_prompt(item))
    except Exception as e:
        print(f"  LLM 调用失败：{e}")
        print("  请检查 .env 里的 DEEPSEEK_API_KEY 是否已填、网络是否可访问 api.deepseek.com。")
        return False

    guide_md = extract_markdown(raw)
    if not guide_md.strip():
        print("  模型返回为空。")
        return False

    md = build_note(item, guide_md)
    fname = save_local(item, md)
    print(f"  [本地] 01-Inbox/{fname}")
    ok, msg = save_siyuan(item, md)
    print(f"  [思源] Debate/01-Inbox {'OK' if ok else 'ERR: ' + msg}")
    return True


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def load_converted():
    if CONVERTED_FILE.exists():
        return set(json.loads(CONVERTED_FILE.read_text(encoding="utf-8")))
    return set()


def save_converted(s):
    CONVERTED_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONVERTED_FILE.write_text(json.dumps(sorted(s), ensure_ascii=False), encoding="utf-8")


def main():
    if len(sys.argv) > 1:
        files = [Path(sys.argv[1])]
    else:
        files = sorted(DATA_DIR.glob("*/*.json")) if DATA_DIR.exists() else []

    if not files:
        print("没有待处理的辩题。先跑 `python fetch.py` 抓取。")
        return

    if not LLM.get("api_key"):
        print("未配置 DEEPSEEK_API_KEY。请编辑 .env 填入你的 DeepSeek API key 后再运行。")
        return

    converted = load_converted()
    n = 0
    for f in files:
        if str(f) in converted:
            print(f"[跳过] {f}")
            continue
        try:
            if process_item(f):
                converted.add(str(f))
                n += 1
        except Exception as e:
            print(f"  [出错] {f}: {e}")
    save_converted(converted)
    print(f"完成：新生成中文导读 {n} 份。")


if __name__ == "__main__":
    main()
