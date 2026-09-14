#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert.py — 第 2 步「三语导读」：读 data/*.json 辩题 → DeepSeek 三语导读 + 翻译 → 写本地 + 思源

用法：
    python convert.py                 # 处理 data/ 下所有未处理的辩题（逐条过 LLM）
    python convert.py <文件.json>      # 只处理单个辩题

产出（每篇笔记 = 上半部分三语导读 + 下半部分英文原文 + 中文/法语翻译）：
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

MAX_POINT_CHARS = 400       # 导读里每个论点正文传给 LLM 的最大长度（只需核心逻辑）
MAX_INTRO_CHARS = 1500      # 翻译背景时传入的最大长度
MAX_BLOCK_CHARS = 1200      # 翻译单个论点（标题+正文+反驳）的最大长度


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
        "temperature": 0.2,
    }


LLM = build_llm()

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是魁北克省 Secondary 5（高中五年级）学生的英语议论文（argumentative essay）辅导老师。学生备考魁省省考，希望同时用三种语言（中文 / 英文 / 法语）理解辩题。

下面提供学生从辩论网站收集的一个英文辩题素材（含背景 + 正反论点）。

你的任务：写一段「三语导读」，帮学生快速理解辩题、掌握正反论点。每条内容都要用三种语言各写一遍，三种语言表达同一个意思。只输出导读正文的 Markdown（不含一级标题和元信息，那由脚本另加）。不要输出解释文字、不要 JSON、不要用 ``` 代码块包裹。

严格按下面的结构写。每条要点用三行（- 中 / - EN / - FR），要点之间空一行：

### 议题速览

- 中：用一句话概括这个辩题在争什么。
- EN：……
- FR：……

### 正方立场

- 中：正方要点1（概括，不逐字翻译，抓核心逻辑）。
- EN：……
- FR：……

- 中：正方要点2……
- EN：……
- FR：……

（正方概括 3~5 条）

### 反方立场

（同样 3~5 条，格式同上，每条三行 - 中 / - EN / - FR）

### 写作借鉴

- EN：原文里能直接套进议论文的英文句型1。
- 中：这个句型的用途（如「引出论点」「让步转折」「总结」）。
- FR：usage en français

- EN：英文句型2……
- 中：……
- FR：……

（给 2~3 条）

要求：
- 中文、英文、法语都要通俗，面向中学生，少堆术语。
- 「写作借鉴」里的英文句型必须来自原文论点，不编造。
- 法语句子自然即可（魁北克或法国法语均可）。
- 每个小标题与前后正文之间空一行。"""

TRANSLATE_SYSTEM = """你是翻译助手。把下面每个编号段落分别翻译成中文（简体）和法语（自然、标准）。翻译忠实、通顺，面向中学生。

严格只输出一个 JSON 对象，不要输出任何解释文字，不要用 ``` 包裹：
{"items":[{"zh":"中文翻译","fr":"traduction française"}, ...]}

items 的数量必须与输入段落数量一致、顺序一致。空段落也要输出 {"zh":"","fr":""} 占位。"""


# ---------------------------------------------------------------------------
# LLM 调用（OpenAI 兼容，纯标准库）
# ---------------------------------------------------------------------------
def _post(url, payload, headers, timeout=600):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def chat(system, user, max_tokens=4096):
    url = LLM["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": LLM["model"],
        "temperature": LLM["temperature"],
        "max_tokens": max_tokens,
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


def extract_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.S)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("模型未返回 JSON")
    return json.loads(text[start:end + 1])


# ---------------------------------------------------------------------------
# 读取 / 翻译 / 构建 markdown
# ---------------------------------------------------------------------------
def slugify(s):
    s = re.sub(r'[\\/:*?"<>|]+', "_", s).strip()[:80]
    return s or "untitled"


def point_text(p):
    """把一个论点拼成一段英文（标题 + 正文 + 反驳），供翻译。"""
    parts = []
    if p.get("title"):
        parts.append(p["title"].strip())
    if p.get("body"):
        parts.append(p["body"].strip())
    if p.get("counterpoint"):
        parts.append("Counterpoint: " + p["counterpoint"].strip())
    txt = "\n\n".join(parts)
    if len(txt) > MAX_BLOCK_CHARS:
        txt = txt[:MAX_BLOCK_CHARS].rstrip() + " …"
    return txt


def translate_blocks(blocks):
    """把若干英文段落批量翻译成 [{zh, fr}]，顺序与输入一致。

    批量翻译偶尔会丢 zh 或 fr（模型偶发返回空值）；对缺失的段落逐个重译兜底。
    """
    if not blocks:
        return []
    out = [{"zh": "", "fr": ""} for _ in blocks]
    try:
        user = "\n\n".join(f"【{i}】\n{b.strip()}" for i, b in enumerate(blocks, 1))
        raw = chat(TRANSLATE_SYSTEM, user, max_tokens=8192)
        items = extract_json(raw).get("items", [])
        for i in range(len(blocks)):
            it = items[i] if i < len(items) else {}
            out[i] = {
                "zh": (it.get("zh") or "").strip(),
                "fr": (it.get("fr") or "").strip(),
            }
    except Exception:
        pass

    for i, b in enumerate(blocks):
        if out[i]["zh"] and out[i]["fr"]:
            continue
        for _ in range(2):
            try:
                raw = chat(TRANSLATE_SYSTEM, f"【1】\n{b.strip()}", max_tokens=4096)
                items = extract_json(raw).get("items", [])
                it = items[0] if items else {}
                zh = (it.get("zh") or "").strip()
                fr = (it.get("fr") or "").strip()
                if zh:
                    out[i]["zh"] = zh
                if fr:
                    out[i]["fr"] = fr
                if out[i]["zh"] and out[i]["fr"]:
                    break
            except Exception:
                continue
    return out


def fmt_intro(intro_en, tr):
    lines = ["## 📖 背景 Background", "", "**English**", "", intro_en.strip()]
    if tr.get("zh"):
        lines += ["", "**中文**", "", tr["zh"].strip()]
    if tr.get("fr"):
        lines += ["", "**Français**", "", tr["fr"].strip()]
    return "\n".join(lines)


def fmt_point(p, tr):
    """渲染一个论点：英文原文 + 中文 + 法语翻译。tr = {'zh','fr'}。"""
    lines = [f"### {p.get('title', '').strip()}", "", "**English**"]
    if p.get("body"):
        lines += ["", p["body"].strip()]
    if p.get("counterpoint"):
        lines += ["", f"**反驳 Counterpoint**：{p['counterpoint'].strip()}"]
    if tr.get("zh"):
        lines += ["", "**中文**", "", tr["zh"].strip()]
    if tr.get("fr"):
        lines += ["", "**Français**", "", tr["fr"].strip()]
    return "\n".join(lines)


def build_note(item, guide_md, intro_tr, pro_trs, con_trs):
    title = item.get("title", "").strip()
    source_name = "Britannica ProCon" if item.get("source") == "procon" else "iDebate Debatabase"
    url = item.get("url", "")
    date = datetime.now().strftime("%Y-%m-%d")
    category = item.get("category", "其他")

    L = [f"# {title}", ""]
    L.append(f"> **元信息**：英·中·法 | 来源：{source_name} | 分类：{category} | [原文]({url}) | {date}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 🎯 三语导读")
    L.append("")
    L.append(guide_md)
    L.append("")

    if item.get("intro"):
        L.append(fmt_intro(item["intro"].strip(), intro_tr))
        L.append("")

    if item.get("pro"):
        L.append("## ✅ 正方论点 Pros")
        L.append("")
        for i, p in enumerate(item["pro"]):
            tr = pro_trs[i] if i < len(pro_trs) else {}
            L.append(fmt_point(p, tr))
            L.append("")

    if item.get("con"):
        L.append("## ❌ 反方论点 Cons")
        L.append("")
        for i, p in enumerate(item["con"]):
            tr = con_trs[i] if i < len(con_trs) else {}
            L.append(fmt_point(p, tr))
            L.append("")

    if item.get("sources"):
        L.append("## 📚 引用来源 Sources")
        L.append("")
        L.append(item["sources"].strip())
        L.append("")

    return "\n".join(L)


def build_user_prompt(item):
    """把辩题精简后拼给 LLM 生成导读（每个论点截断）。"""
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
def process_item(path, local_only=False):
    item = json.loads(path.read_text(encoding="utf-8"))
    title = item.get("title", "").strip()
    print(f"[导读] {item.get('source')} / {title or path.stem}")
    if not item.get("pro") and not item.get("con"):
        print("  无论点，跳过。")
        return False

    # 1. 三语导读
    try:
        raw = chat(SYSTEM_PROMPT, build_user_prompt(item), max_tokens=4096)
    except Exception as e:
        print(f"  导读调用失败：{e}")
        print("  请检查 .env 里的 DEEPSEEK_API_KEY 是否已填、网络是否可访问 api.deepseek.com。")
        return False
    guide_md = extract_markdown(raw)
    if not guide_md.strip():
        print("  导读返回为空。")
        return False

    # 2. 翻译：背景 + 正方
    blocks = []
    has_intro = bool(item.get("intro"))
    if has_intro:
        blocks.append(item["intro"][:MAX_INTRO_CHARS])
    for p in item.get("pro", []):
        blocks.append(point_text(p))
    try:
        pro_res = translate_blocks(blocks)
    except Exception as e:
        print(f"  翻译(背景+正方)失败：{e}")
        return False
    if has_intro:
        intro_tr, pro_trs = pro_res[0], pro_res[1:]
    else:
        intro_tr, pro_trs = {}, pro_res

    # 3. 翻译：反方
    con_trs = []
    if item.get("con"):
        try:
            con_trs = translate_blocks([point_text(p) for p in item["con"]])
        except Exception as e:
            print(f"  翻译(反方)失败：{e}")
            return False

    md = build_note(item, guide_md, intro_tr, pro_trs, con_trs)
    fname = save_local(item, md)
    print(f"  [本地] 01-Inbox/{fname}")
    if local_only:
        return True
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
    args = sys.argv[1:]
    local_only = "--local-only" in args
    paths = [a for a in args if not a.startswith("--")]

    if paths:
        files = [Path(p) for p in paths]
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
            if process_item(f, local_only=local_only):
                converted.add(str(f))
                n += 1
        except Exception as e:
            print(f"  [出错] {f}: {e}")
    save_converted(converted)
    print(f"完成：新生成三语导读 {n} 份。")


if __name__ == "__main__":
    main()
