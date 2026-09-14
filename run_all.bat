@echo off
chcp 65001 >nul
title 辩论素材每日流程
cd /d "%~dp0"

echo [1/4] 抓取辩题 (fetch.py) ...
python fetch.py

echo [2/4] 生成中文导读 (convert.py) ...
python convert.py

echo [3/4] 渲染网页 (build_site.py) ...
python build_site.py

echo [4/4] 提交并发布到 GitHub ...
git add 01-Inbox/ docs/
git commit -m "feat: 更新辩论素材"
git push origin main

echo.
echo 全部完成！网站已推送到 GitHub，Cloudflare 会自动更新。
pause
