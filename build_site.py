#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_site.py — 把 01-Inbox/*.md 辩题笔记渲染成静态站点（docs/），供 Cloudflare Pages 发布。

用法：
    python build_site.py

产出：
    docs/index.html           目录页（卡片网格 + 来源/分类筛选 + 搜索）
    docs/topic/<slug>.html    每个辩题一页（含中文导读 + 正反论点）
    docs/style.css            共享样式
    docs/data.js              辩题元数据（供前端筛选/左边栏用）
    docs/app.js               前端交互（筛选、渲染、左边栏开关）
    docs/.nojekyll            告诉 GitHub Pages 原样发布

依赖：markdown（pip install markdown）
"""
import html
import json
import re
import shutil
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
INBOX = BASE / "01-Inbox"
OUT = BASE / "docs"
TOPIC_DIR = OUT / "topic"

try:
    import markdown as md_lib
except ImportError:
    md_lib = None

SOURCE_LABEL = {"procon": "ProCon", "idebate": "iDebate"}


# ---------------------------------------------------------------------------
# 样式
# ---------------------------------------------------------------------------
CSS = """\
:root {
  --maxw: 880px;
  --bg: #f6f7f9;
  --card: #ffffff;
  --border: #e5e7eb;
  --text: #1f2328;
  --muted: #6b7280;
  --accent: #7c3aed;
  --accent-strong: #6d28d9;
  --accent-soft: #f3e8ff;
  --pro: #16a34a;
  --con: #dc2626;
  --radius: 12px;
  --radius-sm: 9px;
  --shadow: 0 1px 2px rgba(16,24,40,.05), 0 1px 3px rgba(16,24,40,.07);
  --shadow-md: 0 6px 16px rgba(16,24,40,.10);
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", sans-serif;
  line-height: 1.75;
  color: var(--text);
  background: var(--bg);
  -webkit-font-smoothing: antialiased;
}
::selection { background: #e0d4ff; }
a { color: var(--accent); text-decoration: none; }
a:hover { color: var(--accent-strong); text-decoration: underline; }

header.top {
  position: sticky; top: 0; z-index: 10;
  background: rgba(255,255,255,.9);
  -webkit-backdrop-filter: saturate(180%) blur(10px);
  backdrop-filter: saturate(180%) blur(10px);
  border-bottom: 1px solid var(--border);
  box-shadow: 0 1px 6px rgba(16,24,40,.04);
}
.wrap { max-width: var(--maxw); margin: 0 auto; padding: 0 20px; }
header.top .wrap { display: flex; align-items: center; gap: 12px; height: 56px; }
header.top h1 { font-size: 1.05rem; margin: 0; font-weight: 700; }
header.top h1 a { color: var(--text); }
header.top h1 a:hover { text-decoration: none; color: var(--accent-strong); }
header.top .sub { color: var(--muted); font-size: 0.82rem; }

main.wrap { padding: 28px 20px 64px; }
.back { display: inline-block; margin: 0 0 16px; font-size: 0.9rem; font-weight: 500; }
h1.page-title { font-size: 1.7rem; line-height: 1.35; margin: 0 0 10px; font-weight: 800; letter-spacing: -0.02em; }

.meta { color: var(--muted); font-size: 0.88rem; margin-bottom: 22px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.badge { display: inline-block; font-size: 0.7rem; font-weight: 700; padding: 3px 9px; border-radius: 999px; color: #fff; letter-spacing: 0.03em; }
.badge.procon { background: #0e7490; }
.badge.idebate { background: var(--accent); }

table { width: 100%; table-layout: fixed; border-collapse: separate; border-spacing: 0; margin: 1.3em 0; font-size: 0.94rem; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); }
th, td { padding: 11px 13px; border-bottom: 1px solid var(--border); border-right: 1px solid var(--border); vertical-align: top; word-break: break-word; overflow-wrap: break-word; text-align: left; }
th { background: #f4f6f8; font-weight: 600; color: #334155; }
tbody tr:nth-child(even) { background: #fafbfc; }
tr:last-child td { border-bottom: none; }
th:last-child, td:last-child { border-right: none; }
thead th:first-child { border-top-left-radius: calc(var(--radius) - 1px); }
thead th:last-child { border-top-right-radius: calc(var(--radius) - 1px); }
tbody tr:last-child td:first-child { border-bottom-left-radius: calc(var(--radius) - 1px); }
tbody tr:last-child td:last-child { border-bottom-right-radius: calc(var(--radius) - 1px); }

h2 { font-size: 1.35rem; margin: 2em 0 0.8em; font-weight: 700; }
h3 { font-size: 1.18rem; margin: 1.9em 0 0.7em; padding-bottom: 7px; border-bottom: 2px solid var(--accent-soft); font-weight: 700; }
h4 { font-size: 1rem; margin: 1.5em 0 0.5em; font-weight: 700; color: #5b21b6; }
blockquote { margin: 1em 0; padding: 10px 16px; border-left: 3px solid var(--accent); color: var(--muted); background: var(--card); border-radius: 0 var(--radius-sm) var(--radius-sm) 0; box-shadow: var(--shadow); }

/* 正/反论点标题着色 */
h3:has(+ p) { border-bottom-color: transparent; }

.filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 14px; }
.src-group { display: inline-flex; border: 1px solid var(--border); border-radius: 999px; overflow: hidden; background: var(--card); }
.src-btn { border: 0; background: transparent; color: var(--muted); padding: 7px 16px; font-size: 0.9rem; cursor: pointer; font-weight: 600; }
.src-btn.active { background: var(--accent); color: #fff; }
#search { flex: 1; min-width: 180px; padding: 8px 14px; font-size: 0.92rem; border: 1px solid var(--border); border-radius: 999px; background: var(--card); color: var(--text); outline: none; }
#search:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }

.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }
.chip { border: 1px solid var(--border); background: var(--card); color: var(--muted); padding: 5px 12px; border-radius: 999px; font-size: 0.82rem; cursor: pointer; white-space: nowrap; }
.chip:hover { border-color: #d8c9f0; }
.chip.active { background: var(--accent-soft); border-color: var(--accent); color: var(--accent-strong); font-weight: 600; }

.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 14px; }
.card { display: flex; flex-direction: column; gap: 10px; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; box-shadow: var(--shadow); transition: border-color .15s, box-shadow .15s, transform .15s; }
.card:hover { border-color: #d8c9f0; box-shadow: var(--shadow-md); transform: translateY(-2px); }
.card-top { display: flex; align-items: center; gap: 8px; }
.tag { font-size: 0.72rem; color: var(--muted); background: #f0f2f5; padding: 2px 8px; border-radius: 6px; }
.card-title { font-size: 0.98rem; font-weight: 600; color: var(--text); line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card-title:hover { color: var(--accent-strong); text-decoration: none; }
.card-meta { margin-top: auto; display: flex; justify-content: space-between; gap: 8px; font-size: 0.78rem; color: var(--muted); }
.card-cat { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-date { white-space: nowrap; }
.empty { color: var(--muted); text-align: center; padding: 40px 0; }

.layout { max-width: 1200px; margin: 0 auto; display: flex; align-items: flex-start; }
.sidebar { width: 280px; flex-shrink: 0; position: sticky; top: 56px; height: calc(100vh - 56px); overflow-y: auto; padding: 18px 10px 40px; border-right: 1px solid var(--border); }
.sidebar .back { display: block; margin: 0 0 12px 6px; }
#sideSearch { width: 100%; padding: 8px 12px; font-size: 0.9rem; margin-bottom: 8px; border: 1px solid var(--border); border-radius: 8px; background: var(--card); color: var(--text); outline: none; }
#sideSearch:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.side-group { font-size: 0.75rem; font-weight: 700; color: var(--muted); padding: 14px 6px 6px; border-bottom: 1px solid var(--border); margin-bottom: 4px; }
.nav-link { display: flex; align-items: center; gap: 8px; padding: 7px 8px; border-radius: 8px; color: var(--text); font-size: 0.88rem; line-height: 1.4; }
.nav-link .badge { flex-shrink: 0; }
.nav-link span { overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.nav-link:hover { background: var(--accent-soft); color: var(--text); text-decoration: none; }
.nav-link.active { background: var(--accent-soft); color: var(--accent-strong); font-weight: 600; }

.content { flex: 1 1 auto; min-width: 0; padding: 28px 32px 64px; }
.nav-toggle { display: none; border: 0; background: transparent; color: var(--text); font-size: 1.3rem; cursor: pointer; padding: 4px 8px; border-radius: 8px; line-height: 1; }
.nav-toggle:hover { background: #f0f2f5; }

@media (max-width: 900px) {
  .layout { display: block; }
  .sidebar { position: fixed; top: 0; left: 0; bottom: 0; height: 100vh; width: 280px; transform: translateX(-100%); transition: transform .25s ease; z-index: 60; background: var(--card); box-shadow: var(--shadow-md); border-right: 1px solid var(--border); }
  .sidebar.open { transform: translateX(0); }
  .overlay { position: fixed; inset: 0; background: rgba(15,23,42,.4); opacity: 0; pointer-events: none; transition: opacity .25s; z-index: 50; }
  body.nav-open .overlay { opacity: 1; pointer-events: auto; }
  .nav-toggle { display: inline-block; }
  .content { padding: 20px 16px 56px; }
}
@media (min-width: 901px) { .overlay { display: none; } }
"""


PAGE_TEMPLATE = """\
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="../style.css">
</head>
<body>
<header class="top"><div class="wrap">
  <button id="navToggle" class="nav-toggle" aria-label="打开目录">☰</button>
  <h1><a href="../index.html">Debate 辩论素材库</a></h1>
  <span class="sub">{category}</span>
</div></header>
<div id="overlay" class="overlay"></div>
<div class="layout">
  <aside id="sidebar" class="sidebar">
    <a class="back" href="../index.html">← 首页</a>
    <input id="sideSearch" type="search" placeholder="搜索辩题…">
    <nav id="sidebarNav" data-current="{slug}"></nav>
  </aside>
  <main class="content">
    <h1 class="page-title">{title}</h1>
    <div class="meta">{badge}{category_html}{date_html}{url_html}</div>
    {body_html}
  </main>
</div>
<script src="../data.js"></script>
<script src="../app.js"></script>
</body>
</html>
"""

INDEX_TEMPLATE = """\
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Debate 辩论素材库</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header class="top"><div class="wrap">
  <h1>Debate 辩论素材库</h1>
  <span class="sub">议论文正反论点 · <span id="count">{total}</span> 个辩题</span>
</div></header>
<main class="wrap">
  <div class="filters">
    <div class="src-group">
      <button class="src-btn active" data-src="all">全部</button>
      <button class="src-btn" data-src="procon">ProCon</button>
      <button class="src-btn" data-src="idebate">iDebate</button>
    </div>
    <input id="search" type="search" placeholder="搜索辩题 / 分类…">
  </div>
  <div id="cats" class="chips"></div>
  <div id="cards" class="cards"></div>
</main>
<script src="data.js"></script>
<script src="app.js"></script>
</body>
</html>
"""

APP_JS = """\
(function () {
  var NOTES = window.NOTES || [];
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function badge(n) {
    var id = n.source === 'idebate' ? 'idebate' : 'procon';
    var label = n.source === 'idebate' ? 'iDebate' : 'ProCon';
    return '<span class="badge ' + id + '">' + label + '</span>';
  }

  function initIndex() {
    var grid = document.getElementById('cards');
    if (!grid) return;
    var state = { src: 'all', cat: 'all', q: '' };
    var search = document.getElementById('search');
    var catRow = document.getElementById('cats');

    var counts = {};
    NOTES.forEach(function (n) { counts[n.category] = (counts[n.category] || 0) + 1; });
    var catNames = Object.keys(counts).sort();
    if (catRow) {
      catRow.innerHTML = '';
      var all = document.createElement('button');
      all.className = 'chip active'; all.dataset.cat = 'all'; all.textContent = '全部';
      catRow.appendChild(all);
      catNames.forEach(function (c) {
        var b = document.createElement('button');
        b.className = 'chip'; b.dataset.cat = c;
        b.textContent = c + ' · ' + counts[c];
        catRow.appendChild(b);
      });
    }

    function render() {
      var q = state.q.trim().toLowerCase();
      var html = '', shown = 0;
      NOTES.forEach(function (n) {
        if (state.src !== 'all' && n.source !== state.src) return;
        if (state.cat !== 'all' && n.category !== state.cat) return;
        if (q && (n.title + ' ' + n.category).toLowerCase().indexOf(q) < 0) return;
        shown++;
        html += '<article class="card">'
          + '<div class="card-top">' + badge(n) + '<span class="tag">' + esc(n.category) + '</span></div>'
          + '<a class="card-title" href="/topic/' + esc(n.slug) + '.html">' + esc(n.title) + '</a>'
          + '<div class="card-meta"><span class="card-cat">' + esc(n.category) + '</span><span class="card-date">' + esc(n.date) + '</span></div>'
          + '</article>';
      });
      grid.innerHTML = html || '<p class="empty">没有匹配的辩题</p>';
      var countEl = document.getElementById('count');
      if (countEl) countEl.textContent = shown;
    }

    if (search) search.addEventListener('input', function () { state.q = this.value; render(); });
    document.querySelectorAll('.src-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        document.querySelectorAll('.src-btn').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
        state.src = b.dataset.src;
        render();
      });
    });
    if (catRow) catRow.addEventListener('click', function (e) {
      var chip = e.target.closest('.chip');
      if (!chip) return;
      document.querySelectorAll('.chip').forEach(function (x) { x.classList.remove('active'); });
      chip.classList.add('active');
      state.cat = chip.dataset.cat;
      render();
    });
    render();
  }

  function initSidebar() {
    var nav = document.getElementById('sidebarNav');
    if (!nav) return;
    var current = nav.getAttribute('data-current') || '';
    var search = document.getElementById('sideSearch');
    function render() {
      var q = (search ? search.value : '').trim().toLowerCase();
      var groups = {};
      NOTES.forEach(function (n) {
        if (q && (n.title + ' ' + n.category).toLowerCase().indexOf(q) < 0) return;
        (groups[n.category] = groups[n.category] || []).push(n);
      });
      var cats = Object.keys(groups).sort();
      var html = '';
      if (!cats.length) { nav.innerHTML = '<p class="empty">无匹配</p>'; return; }
      cats.forEach(function (cat) {
        html += '<div class="side-group">' + esc(cat) + '</div>';
        groups[cat].forEach(function (n) {
          html += '<a class="nav-link' + (n.slug === current ? ' active' : '') + '" href="/topic/' + esc(n.slug) + '.html">'
            + badge(n) + '<span>' + esc(n.title) + '</span></a>';
        });
      });
      nav.innerHTML = html;
    }
    if (search) search.addEventListener('input', render);
    render();
  }

  function initToggle() {
    var btn = document.getElementById('navToggle');
    var sb = document.getElementById('sidebar');
    var ov = document.getElementById('overlay');
    function close() { if (sb) sb.classList.remove('open'); document.body.classList.remove('nav-open'); }
    if (btn && sb) btn.addEventListener('click', function () {
      var open = sb.classList.toggle('open');
      document.body.classList.toggle('nav-open', open);
    });
    if (ov) ov.addEventListener('click', close);
    if (sb) sb.addEventListener('click', function (e) { if (e.target.closest('a')) close(); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initIndex();
    initSidebar();
    initToggle();
  });
})();
"""


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def slugify(s):
    s = re.sub(r"[^\w-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


def parse_note(path):
    text = path.read_text(encoding="utf-8")

    title = ""
    for ln in text.splitlines():
        if ln.startswith("# "):
            title = ln[2:].strip()
            break

    meta_line = ""
    for ln in text.splitlines():
        if ln.startswith("> **元信息**"):
            meta_line = ln
            break

    source = "procon"
    if "iDebate" in meta_line or "idebate" in meta_line.lower():
        source = "idebate"

    category = "其他"
    m = re.search(r"分类：([^|]+)", meta_line)
    if m:
        category = m.group(1).strip()

    url = ""
    m = re.search(r"\[原文\]\((\S+)\)", meta_line)
    if m:
        url = m.group(1)

    date = ""
    m = re.search(r"\|\s*(\d{4}-\d{2}-\d{2})\s*$", meta_line)
    if m:
        date = m.group(1)

    # body：从第一个 ## 标题开始
    idx = text.find("\n## ")
    body_md = text[idx + 1:].strip() if idx != -1 else ""

    return {
        "title": title,
        "source": source,
        "category": category,
        "url": url,
        "date": date,
        "body_md": body_md,
        "slug": slugify(path.stem),
    }


def render_body(body_md):
    if md_lib is None:
        return "<pre>" + html.escape(body_md) + "</pre>"
    return md_lib.markdown(body_md, extensions=["tables", "fenced_code"], output_format="html5")


# ---------------------------------------------------------------------------
# 构建
# ---------------------------------------------------------------------------
def build_page(note):
    title_esc = html.escape(note["title"])
    sid = "idebate" if note["source"] == "idebate" else "procon"
    badge = f'<span class="badge {sid}">{SOURCE_LABEL.get(note["source"], note["source"])}</span>'
    category_html = f'<span>{html.escape(note["category"])}</span>' if note["category"] else ""
    date_html = f'<span>{html.escape(note["date"])}</span>' if note["date"] else ""
    url_html = (
        f'<a href="{html.escape(note["url"])}" target="_blank" rel="noopener">↗ 原文</a>'
        if note["url"] else ""
    )
    body_html = render_body(note["body_md"])
    return PAGE_TEMPLATE.format(
        title=title_esc,
        category=html.escape(note["category"]),
        slug=html.escape(note["slug"]),
        badge=badge,
        category_html=category_html,
        date_html=date_html,
        url_html=url_html,
        body_html=body_html,
    )


def build_index(notes):
    return INDEX_TEMPLATE.format(total=len(notes))


def build_data_js(notes):
    data = [
        {
            "slug": n["slug"],
            "title": n["title"],
            "date": n["date"],
            "source": n["source"],
            "category": n["category"],
        }
        for n in notes
    ]
    return "window.NOTES = " + json.dumps(data, ensure_ascii=False) + ";"


def main():
    files = sorted(INBOX.glob("*.md")) if INBOX.exists() else []
    if not files:
        print("01-Inbox 里没有笔记，先跑 `python convert.py`。")
        return

    if TOPIC_DIR.exists():
        shutil.rmtree(TOPIC_DIR)
    TOPIC_DIR.mkdir(parents=True, exist_ok=True)

    notes = []
    for f in files:
        try:
            n = parse_note(f)
        except Exception as e:
            print(f"[跳过] {f.name}: {e}")
            continue
        if not n["title"]:
            print(f"[跳过] {f.name}: 无标题")
            continue
        notes.append(n)
        (TOPIC_DIR / (n["slug"] + ".html")).write_text(build_page(n), encoding="utf-8")

    notes.sort(key=lambda x: (x["date"] or ""), reverse=True)

    (OUT / "index.html").write_text(build_index(notes), encoding="utf-8")
    (OUT / "style.css").write_text(CSS, encoding="utf-8")
    (OUT / "data.js").write_text(build_data_js(notes), encoding="utf-8")
    (OUT / "app.js").write_text(APP_JS, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    print(f"完成：{len(notes)} 个辩题 → docs/（index + topic/ + style.css + data.js + app.js）")


if __name__ == "__main__":
    main()
