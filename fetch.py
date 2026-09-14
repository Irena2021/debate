#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch.py — 抓取辩论素材（Britannica ProCon + iDebate Debatabase）第 1 步

用法：
    python fetch.py                 # 按 sources.json 抓所有启用的源（每个 max_items 个）
    python fetch.py --limit 20      # 覆盖：每个源最多抓 20 个
    python fetch.py --source procon # 只抓某个源
    python fetch.py --full          # 全量抓取（不限量）

依赖（先装一次）：
    pip install requests

产出（data/<source>/<slug>.json，供 convert.py 第 2 步「中文导读」读取）：
    每个辩题一个 JSON，统一结构：
    {
      "id": "school-uniforms",        # URL 安全 slug
      "source": "procon",             # procon | idebate
      "title": "School Uniforms",     # 辩题标题
      "category": "Social Issues",    # 分类（idebate 为具体类目）
      "url": "https://...",           # 原页面链接
      "intro": "...",                 # 导语/背景（可空）
      "pro": [{"title": "...", "body": "...", "counterpoint": "..."}],
      "con": [{"title": "...", "body": "...", "counterpoint": "..."}],
      "sources": "..."                # 引用来源（可空）
    }
    去重状态存在 data/seen.json。

反爬虫策略：
    - requests.Session + 浏览器 UA，先访问首页拿 Cookie（绕过 Cloudflare）
    - 详情页之间随机静默 1~3 秒，模拟真人节奏
    - 遇到 403/429 冷却后重试一次，连续失败跳过该条
"""

import html
import json
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

# Windows 控制台默认 GBK，打印中文会崩；强制 stdout/stderr 用 UTF-8
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

try:
    import requests
except ImportError:
    print("缺少依赖 requests，请先运行：pip install requests")
    sys.exit(1)

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
SEEN_FILE = DATA_DIR / "seen.json"
SOURCES_FILE = BASE / "sources.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

DELAY_BETWEEN_ITEMS = (1, 3)   # 详情页之间的随机静默（秒）
DELAY_ON_BLOCK = (30, 60)      # 403/429 后的冷却（秒）


def load_sources():
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    return data.get("sources", [])


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def save_seen(seen):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding="utf-8")


def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def polite_get(session, url):
    """带 403/429 冷却重试的 GET，返回 Response 或 None。"""
    for attempt in (1, 2):
        try:
            r = session.get(url, timeout=40)
            if r.status_code == 200:
                return r
            if r.status_code in (403, 429):
                wait = random.uniform(*DELAY_ON_BLOCK)
                print(f"    [限流] {r.status_code}，冷却 {wait:.0f} 秒（第 {attempt} 次）")
                time.sleep(wait)
                continue
            print(f"    [跳过] {url} 状态码 {r.status_code}")
            return None
        except Exception as e:
            print(f"    [网络] {url} 请求失败: {e}")
            if attempt == 1:
                time.sleep(random.uniform(*DELAY_ON_BLOCK))
            else:
                return None
    return None


# ---------------------------------------------------------------------------
# 通用文本处理
# ---------------------------------------------------------------------------
def clean(html_frag):
    """去标签 + 去脚本样式 + 转实体 + 压缩空白。"""
    s = re.sub(r"<script[\s\S]*?</script>", " ", html_frag)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def slugify(s):
    s = re.sub(r"[^\w-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-").lower() or "topic"


def paras(html_frag):
    """提取 <p> 段落纯文本，排除脚注段（以 [n] 开头）并去掉内嵌引用标记 [n]。"""
    out = []
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", html_frag, re.S):
        t = clean(m.group(1))
        if not t:
            continue
        if re.match(r"^\[\d+\]", t):  # 脚注段落
            continue
        t = re.sub(r"\[\d+\]", "", t)  # 去掉内嵌引用编号
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            out.append(t)
    return out


# ---------------------------------------------------------------------------
# Britannica ProCon
# ---------------------------------------------------------------------------
def procon_topics(session):
    """主页提取主题链接（-debate / -explainer 结尾）。"""
    session.get("https://www.britannica.com/", timeout=40)  # 拿 Cookie 绕过 Cloudflare
    r = polite_get(session, "https://www.britannica.com/procon")
    if r is None:
        return []
    links = set()
    for m in re.finditer(r'href="(https?://www\.britannica\.com/procon/[^"]+)"', r.text):
        url = m.group(1)
        if url.endswith(("-debate", "-explainer")):
            links.add(url)
    return sorted(links)


def _procon_argument(block_html):
    """解析一个 <section class='pro'|'con'> 论点块。"""
    m = re.search(r"<h2[^>]*>(.*?)</h2>", block_html, re.S)
    title = clean(m.group(1)) if m else ""
    body = " ".join(paras(block_html))
    return {"title": title, "body": body, "counterpoint": ""}


def fetch_procon_item(session, url, seen):
    """抓一个 ProCon 主题（主页面 + /Cons 页面）。"""
    if url in seen:
        return None
    slug = slugify(url.rstrip("/").split("/")[-1].replace("-debate", "").replace("-explainer", ""))
    main = polite_get(session, url)
    if main is None:
        return None
    cons_url = url.rstrip("/") + "/Cons"
    cons = polite_get(session, cons_url)

    m = re.search(r"<h1[^>]*>(.*?)</h1>", main.text, re.S)
    title = clean(m.group(1)) if m else slug

    intro = ""
    m = re.search(r'<p class="topic-paragraph">(.*?)</p>', main.text, re.S)
    if m:
        intro = re.sub(r"\[\d+\]", "", clean(m.group(1)))

    pro = [_procon_argument(b) for b in re.findall(r'<section class="pro"[^>]*>(.*?)</section>', main.text, re.S)]
    con = []
    sources = ""
    if cons is not None:
        con = [_procon_argument(b) for b in re.findall(r'<section class="con"[^>]*>(.*?)</section>', cons.text, re.S)]
        m = re.search(r'<section class="sources"[^>]*>(.*?)</section>', cons.text, re.S)
        if m:
            sources = clean(m.group(1))

    return {
        "id": slug,
        "source": "procon",
        "title": title,
        "category": "Social Issues",
        "url": url,
        "intro": intro,
        "pro": pro,
        "con": con,
        "sources": sources,
    }


# ---------------------------------------------------------------------------
# iDebate Debatabase
# ---------------------------------------------------------------------------
def idebate_categories(session):
    """主页提取分类链接（/debatabase/xxx~c数字/）。"""
    session.get("https://idebate.net/", timeout=40)
    r = polite_get(session, "https://idebate.net/resources/debatabase")
    if r is None:
        return []
    cats = []
    for m in re.finditer(r'href="((?:https://idebate\.net)?/debatabase/[^"]+~c\d+/)"', r.text):
        url = m.group(1)
        if url.startswith("/"):
            url = "https://idebate.net" + url
        if url not in cats:
            cats.append(url)
    return cats


def idebate_motions(session, cat_url):
    """一个分类页 + 分页，返回 [(动议URL, 分类名)]。"""
    cat_name = unquote(cat_url.rstrip("/").split("/")[-1].split("~")[0])
    motions = []
    page = 0
    while True:
        url = cat_url if page == 0 else f"{cat_url}?page={page}"
        r = polite_get(session, url)
        if r is None:
            break
        found = False
        for m in re.finditer(r'href="((?:https://idebate\.net)?/(?:this-house|thw)[^"]*~b\d+/)"', r.text):
            murl = m.group(1)
            if murl.startswith("/"):
                murl = "https://idebate.net" + murl
            if (murl, cat_name) not in motions:
                motions.append((murl, cat_name))
                found = True
        # 还有下一页吗？
        if not found or f"?page={page + 1}" not in r.text:
            break
        page += 1
    return motions


def _split_items(html_frag):
    """把 HTML 里所有 accordion__item 块切出来，返回 [(起始位置, 块HTML)]。

    边界取「下一个 accordion__item 的起始位置」，可容忍内部嵌套 div。
    """
    starts = [m.start() for m in re.finditer(r'<div class="accordion__item">', html_frag)]
    items = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(html_frag)
        items.append((s, html_frag[s:e]))
    return items


def _idebate_item(item_html):
    """解析一个 accordion__item 论点（含 POINT + COUNTERPOINT）。"""
    m = re.search(r'accordion__subtitle">(.*?)</h4>', item_html, re.S)
    title = clean(m.group(1)) if m else ""
    cp_idx = item_html.find("COUNTERPOINT")
    point_html = item_html[:cp_idx] if cp_idx != -1 else item_html
    counter_html = item_html[cp_idx:] if cp_idx != -1 else ""
    body = " ".join(paras(point_html))
    counterpoint = " ".join(paras(counter_html))
    return {"title": title, "body": body, "counterpoint": counterpoint}


def fetch_idebate_item(session, url, category, seen):
    """抓一个 idebate 辩论动议详情页。"""
    if url in seen:
        return None
    r = polite_get(session, url)
    if r is None:
        return None
    raw = r.text

    m = re.search(r"<h1[^>]*>(.*?)</h1>", raw, re.S)
    title = clean(m.group(1)) if m else url

    slug = slugify(url.rstrip("/").split("/")[-1].split("~")[0])

    # intro：h1 后第一个非空 <p>
    intro = ""
    i = raw.find("<h1")
    seg = raw[i:] if i != -1 else ""
    for pm in re.finditer(r"<p[^>]*>(.*?)</p>", seg, re.S):
        t = clean(pm.group(1))
        if t:
            intro = t
            break

    # 论点：提取所有 accordion__item，用 "Points Against" 位置切分正/反
    pa = raw.find("Points Against")
    pro, con = [], []
    for start, it_html in _split_items(raw):
        item = _idebate_item(it_html)
        if not item["title"]:
            continue
        if pa != -1 and start > pa:
            con.append(item)
        else:
            pro.append(item)
    # 去重：反方区会原样重复渲染正方前几条（标题+正文完全一致），按标题去掉
    pro_titles = {p["title"] for p in pro}
    con = [c for c in con if c["title"] not in pro_titles]

    return {
        "id": slug,
        "source": "idebate",
        "title": title,
        "category": category,
        "url": url,
        "intro": intro,
        "pro": pro,
        "con": con,
        "sources": "",
    }


# ---------------------------------------------------------------------------
# 落盘 / 主流程
# ---------------------------------------------------------------------------
def save_item(item):
    src_dir = DATA_DIR / item["source"]
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / (item["id"] + ".json")).write_text(
        json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"    [保存] {item['source']}/{item['id']}.json  ({len(item['pro'])} 正 / {len(item['con'])} 反)")


def run_source(src, limit, seen):
    session = make_session()
    print(f"\n=== 抓取 {src['name']} ({src['id']}) ===")
    n = 0

    if src["id"] == "procon":
        topics = procon_topics(session)
        print(f"  发现 {len(topics)} 个主题")
        for url in topics:
            if n >= limit:
                break
            if url in seen:
                continue
            time.sleep(random.uniform(*DELAY_BETWEEN_ITEMS))
            item = fetch_procon_item(session, url, seen)
            if item and item["pro"] and item["con"]:
                save_item(item)
                seen.add(url)
                n += 1
            elif item:
                print(f"    [跳过] {url} 论点不完整")
                seen.add(url)

    elif src["id"] == "idebate":
        cats = idebate_categories(session)
        print(f"  发现 {len(cats)} 个分类")
        for cat in cats:
            if n >= limit:
                break
            motions = idebate_motions(session, cat)
            for url, cat_name in motions:
                if n >= limit:
                    break
                if url in seen:
                    continue
                time.sleep(random.uniform(*DELAY_BETWEEN_ITEMS))
                item = fetch_idebate_item(session, url, cat_name, seen)
                if item and item["pro"] and item["con"]:
                    save_item(item)
                    seen.add(url)
                    n += 1
                elif item:
                    print(f"    [跳过] {url} 论点不完整")
                    seen.add(url)

    print(f"  {src['name']} 完成：新抓 {n} 个")


def main():
    args = sys.argv[1:]
    limit = None
    only_source = None
    full = "--full" in args

    for a in args:
        if a.startswith("--limit"):
            limit = int(a.split("=", 1)[1]) if "=" in a else int(args[args.index(a) + 1])
        elif a.startswith("--source"):
            only_source = a.split("=", 1)[1] if "=" in a else args[args.index(a) + 1]

    if not SOURCES_FILE.exists():
        print("找不到 sources.json，请先准备数据源配置。")
        return

    sources = load_sources()
    seen = load_seen()

    for src in sources:
        if not src.get("enabled", True):
            continue
        if only_source and src["id"] != only_source:
            continue
        lim = limit if limit is not None else (None if full else src.get("max_items", 20))
        if lim is None:
            lim = 10 ** 9
        run_source(src, lim, seen)

    save_seen(seen)
    print("\n完成。")


if __name__ == "__main__":
    main()
