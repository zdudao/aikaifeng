#!/usr/bin/env python
"""本机一键：同步最新日报 → 生成抖音图文 / 公众号文章 → 打开取图页。

分工（2026-09-15 定）：
  云端只出「当天日报 + 月末月报」并直接上线；
  抖音图文 / 公众号文章 / 发布文案 / 合规报告一律在本机生成 ——
  卡片截图依赖中文字体与浏览器，本机环境可控，不必再去赌云端那台 Linux。

入口是项目根目录的「生成今日素材.bat」，双击即可，无需任何参数。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "news-data"
SOCIAL_DIR = DATA_DIR / "social"
SITE = "https://zdudao.github.io/aikaifeng/news-data"
BJ = timezone(timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0 (local-build)"}
KEEP_DAYS = 60          # 本机素材保留天数，超期自动清掉
LOOKBACK = 8            # 线上往前找几天的日报


def log(m: str = "") -> None:
    print(m, flush=True)


# ============================ ① 同步最新日报 ============================

def _day_file(day: str) -> Path:
    return DATA_DIR / f"daily-{day}.html"


def _local_days() -> list[str]:
    days = []
    if DATA_DIR.exists():
        for f in DATA_DIR.glob("daily-*.html"):
            m = re.search(r"daily-(\d{4}-\d{2}-\d{2})\.html$", f.name)
            if m:
                days.append(m.group(1))
    return sorted(days)


def _download(day: str) -> bool:
    """从网站把某一天的日报拉下来。本地已有则跳过。"""
    dst = _day_file(day)
    if dst.exists() and dst.stat().st_size > 5000:
        return False
    try:
        req = urllib.request.Request(f"{SITE}/daily-{day}.html", headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            blob = r.read()
    except Exception as e:
        log(f"   · {day} 线上还没有（{type(e).__name__}）")
        return False
    if len(blob) < 5000:
        log(f"   · {day} 拿到的内容不完整，跳过")
        return False
    dst.write_bytes(blob)
    log(f"   ✓ 已下载 {day} 的日报（{len(blob) // 1024} KB）")
    return True


def sync() -> str:
    """返回接下来要用的日期：优先今天，没有就往前找。"""
    log("① 从网站同步最新日报")
    today = datetime.now(BJ).date()
    day = ""
    for back in range(LOOKBACK):
        cand = (today - timedelta(days=back)).isoformat()
        if _day_file(cand).exists():
            log(f"   · {cand} 本地已有")
            day = cand
            break
        if _download(cand):
            day = cand
            break
    if not day:
        days = _local_days()
        if not days:
            log("   ❌ 本地没有任何日报，也没能从网站拉到。")
            log("      先确认网站能正常打开，或者这台电脑能不能上网。")
            sys.exit(1)
        day = days[-1]
        log(f"   ⚠️ 线上最近一周都没出新日报，改用本地最新的一份：{day}")
    if day != today.isoformat():
        log(f"   ℹ️ 今天（{today.isoformat()}）这期还没出，本次生成的是 {day} 的。")
        log("      云端实测要到傍晚才跑完，晚点再点一次就能拿到当天的。")
    return day


# ============================ ② 生成素材 ============================

def run_build(day: str) -> None:
    log(f"② 生成 {day} 的素材（抖音图文 + 公众号文章 + 发布文案 + 合规体检）")
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_social.py"), day],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        log()
        log("❌ 生成过程出错，把上面的提示截图发出来。")
        sys.exit(r.returncode)


def prune() -> None:
    """清掉超过 KEEP_DAYS 天的素材：图片很占地方，本机也别无限堆。"""
    if not SOCIAL_DIR.exists():
        return
    cut = (datetime.now(BJ).date() - timedelta(days=KEEP_DAYS)).isoformat()
    gone = []
    for d in sorted(SOCIAL_DIR.iterdir()):
        if not d.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name):
            continue
        if d.name < cut:
            shutil.rmtree(d, ignore_errors=True)
            for extra in (DATA_DIR / f"social-{d.name}.html",
                          DATA_DIR / f"wechat-{d.name}.html"):
                extra.unlink(missing_ok=True)
            gone.append(d.name)
    if gone:
        log(f"   · 顺手清掉 {len(gone)} 天前的旧素材（{gone[0]} 及更早）")


# ============================ ③ 打开结果 ============================

def open_path(p: Path) -> None:
    if not p.exists():
        return
    try:
        if os.name == "nt":
            os.startfile(str(p))                      # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(p)], check=False)
        else:
            subprocess.run(["xdg-open", str(p)], check=False)
    except Exception as e:
        log(f"   · 自动打开失败（{e}），你可以手动打开：{p}")


def main() -> None:
    os.chdir(ROOT)
    log("=" * 48)
    log("  老许聊实体 · 今日抖音图文 / 公众号文章")
    log("=" * 48)

    if not DATA_DIR.exists():
        log("❌ 找不到 news-data 目录，确认这个脚本在项目的 scripts 文件夹里。")
        sys.exit(1)

    day = sync()
    log()
    run_build(day)
    prune()

    out_dir = SOCIAL_DIR / day
    log()
    if "--no-open" in sys.argv:          # 只想生成、不想弹窗口时用
        log("③ 跳过自动打开（--no-open）")
    else:
        log("③ 打开取图页和图片文件夹")
        open_path(DATA_DIR / f"social-{day}.html")
        open_path(out_dir)

    log()
    log("-" * 48)
    log(f"✅ 完成。{day} 的图片在：")
    log(f"   {out_dir}")
    log("   浏览器里打开的页面可以复制抖音发布文案；")
    log("   图片拖进微信「文件传输助手」就能发到手机。")
    log("-" * 48)


if __name__ == "__main__":
    main()
