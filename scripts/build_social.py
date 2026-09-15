"""日报 → 社媒内容生成器（含抖音合规审核）

从 news-data/daily-YYYY-MM-DD.html 二次加工出两样东西：

1. 抖音图文：封面 + 内容卡（N 张）+ 结尾卡，每张 1080×1440，
   生成卡片网页后用本地浏览器（Edge/Chrome）无头模式截图成 PNG。
2. 公众号文章：把当天日报重新组织成一篇可读的文章 HTML。

合规审核（防限流）分两关，都在出图之前跑：
  第一关 源头净化 —— 引用来的新闻标题/判断/建议，清掉「放哪都不能有」的硬违禁词；
  第二关 固定文案 —— 我们自己写的页脚/引导/落款，按抖音规则全量审。
  产出 news-data/social/<日期>/审核报告-抖音.md（含未处理项与发布前自检清单）。

用法：
    python scripts/build_social.py                 # 用最新一期日报
    python scripts/build_social.py 2026-09-12      # 指定日期
    python scripts/build_social.py 2026-09-12 --top 3
    python scripts/build_social.py 2026-09-12 --no-shot   # 只出 HTML 不截图
    python scripts/build_social.py --self-test     # 只跑规则自检，确认审核机制没失效
    python scripts/build_social.py 2026-09-12 --strict    # 有高危项就中止（适合挂自动化）
    python scripts/build_social.py 2026-09-12 --allow-contact  # 硬要放微信号（高风险）
"""
from __future__ import annotations

import argparse
import html as html_mod
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from bs4 import BeautifulSoup

DATA_DIR = Path("news-data")
SOCIAL_DIR = DATA_DIR / "social"
WORK_DIR = DATA_DIR / ".social-work"

CARD_W, CARD_H = 1080, 1440

# ---------- 主题：近黑底 + 暖白字 + 单一印章红（现代简约） ----------
C_INK = "#F2F0EA"
C_MUTED = "#8A8880"
C_RED = "#C0392B"
C_RED_TXT = "#E4634F"
C_AMBER = "#D9A441"
C_PANEL = "#1E1E1C"
C_HAIR = "#302F2C"

ADV_CLS = {"立即行动": "act", "小成本试用": "try", "观望": "watch", "暂不跟进": "skip"}
ADV_ORDER = {"act": 0, "try": 1, "watch": 2, "skip": 3}
ADV_HEAD = {
    "act": "立即行动",
    "try": "小成本试用",
    "watch": "观望",
    "skip": "暂不跟进",
}
ADV_NOTE = {
    "act": "成熟、低门槛、强相关，现在就能用起来",
    "try": "可低成本试错，验证是否适合自己",
    "watch": "有前景但不成熟，先跟踪",
    "skip": "与本地实体无关，暂不跟进",
}

# 字体：Windows / macOS 的名字在前，服务器(Linux)的名字在后。
# 云端机器默认不带中文字体，缺了就会截出满屏方框，所以 Noto CJK / 文泉驿 必须列进来。
SERIF = ('"Source Han Serif SC","Noto Serif SC","Noto Serif CJK SC",'
         '"Songti SC","SimSun","AR PL UMing CN",serif')
SANS = ('"Microsoft YaHei","PingFang SC","Hiragino Sans GB",'
        '"Noto Sans SC","Noto Sans CJK SC","WenQuanYi Zen Hei","DejaVu Sans",sans-serif')

CARD_CSS = f"""
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{CARD_W}px;height:{CARD_H}px;overflow:hidden}}
body{{
  background:#141413;color:{C_INK};
  font-family:{SANS};
  padding:84px 84px 72px;display:flex;flex-direction:column;
}}
.serif{{font-family:{SERIF};font-weight:700}}
.topbar{{font-size:24px;letter-spacing:2px;color:{C_MUTED}}}
.rule{{width:132px;height:6px;background:{C_RED};margin-top:34px;flex:none}}
.body-title{{margin-top:60px;font-size:88px;line-height:1.24;letter-spacing:1px}}
.meta{{display:flex;align-items:center;justify-content:space-between;margin-top:36px}}
.tag{{font-size:28px;letter-spacing:2px;padding:6px 24px;border:2px solid {C_RED};
  color:{C_RED_TXT};border-radius:4px;white-space:nowrap}}
.tag.try{{border-color:#B98A2E;color:{C_AMBER}}}
.tag.watch{{border-color:#5A5852;color:{C_MUTED}}}
.idx{{font-size:26px;letter-spacing:3px;color:#6E6C66}}
.judge{{margin-top:56px;border-left:5px solid {C_RED};padding:4px 0 4px 36px}}
.judge .label{{font-size:26px;letter-spacing:2px;color:{C_MUTED}}}
.judge p{{margin-top:16px;font-size:44px;line-height:1.6;color:#EDEBE4}}
.action{{margin-top:44px;background:{C_PANEL};border-radius:6px;padding:34px 38px}}
.action .label{{font-size:26px;letter-spacing:2px;color:{C_MUTED}}}
.action p{{margin-top:14px;font-size:40px;line-height:1.6;color:{C_AMBER}}}
.action .more{{margin-top:16px;padding-top:14px;border-top:1px dashed #4A4740;
  font-size:24px;color:{C_MUTED};letter-spacing:1px}}
.bottom{{margin-top:auto;padding-top:28px;border-top:1px solid {C_HAIR};
  font-size:26px;color:{C_MUTED};display:flex;justify-content:space-between;gap:24px}}
.cover-kicker{{font-size:28px;letter-spacing:4px;color:{C_MUTED}}}
.cover-title{{margin-top:28px;font-size:80px;line-height:1.28}}
.cover-sub{{margin-top:32px;font-size:32px;color:#B9B6AC;line-height:1.7}}
.cover-tl{{margin-top:42px;padding-top:26px;border-top:1px solid {C_HAIR};
  font-size:26px;color:{C_MUTED};line-height:1.7}}
.cover-stats{{margin-top:58px;display:flex;gap:72px}}
.cover-stats .n{{font-size:60px;color:{C_RED_TXT};font-family:{SERIF};font-weight:700;line-height:1}}
.cover-stats .t{{margin-top:12px;font-size:23px;color:{C_MUTED};letter-spacing:1px}}
.mid{{flex:1;display:flex;flex-direction:column;justify-content:center}}
.end-wrap{{flex:1;display:flex;flex-direction:column;justify-content:center;text-align:center}}
.end-wrap h1{{font-size:92px;line-height:1.3}}
.end-wrap .sub{{margin-top:38px;font-size:32px;color:#B9B6AC;line-height:1.75}}
.end-wrap .cta{{margin-top:52px;font-size:38px;font-weight:600;color:{C_INK};line-height:1.7}}
.end-wrap .acct{{margin-top:44px;font-size:32px;color:{C_RED_TXT};line-height:2.1}}
.end-wrap .note{{margin-top:48px;font-size:26px;color:{C_MUTED};line-height:1.8}}
"""


# ============================ 工具 ============================

def _char_w(ch: str) -> float:
    """中文/全角按 1 个字宽，ASCII 按 0.5。中文标点（破折号/引号/省略号）同样算全角。"""
    o = ord(ch)
    if 0x2010 <= o <= 0x205E or o >= 0x2E80:
        return 1.0
    return 0.5


# 不能出现在行首的收尾标点
_CLOSERS = "。，、；：！？）〕】》」』”’…·,.!?;:%)]}"


def wrap_cjk(text: str, per_line: float, max_lines: int | None = None) -> list[str]:
    """按字宽折行，并做均衡处理（避免末行只剩一两个字）。
    超出 max_lines 时按容量截断并在末尾加省略号。
    """
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []

    widths = [_char_w(c) for c in text]
    total = sum(widths)
    need = max(1, math.ceil(total / per_line - 1e-9))

    if max_lines and need > max_lines:
        cap = per_line * max_lines - 1.0          # 预留 1 字宽给省略号
        acc, cut = 0.0, len(text)
        for i, w in enumerate(widths):
            if acc + w > cap:
                cut = i
                break
            acc += w
        text = text[:cut].rstrip("，。、；：,.;:·— ") + "…"
        widths = [_char_w(c) for c in text]
        total = sum(widths)
        need = max_lines

    n = min(need, max_lines) if max_lines else need
    per = min(total / n, per_line) if n else per_line

    lines: list[str] = []
    cur, line_w = "", 0.0
    i, L = 0, len(text)
    while i < L:
        if cur and len(lines) < n - 1 and line_w + widths[i] > per + 1e-9:
            # 行首禁则：结尾标点（。，、）跟随上一行，不单独掉行
            nxt = i
            while nxt < L and text[nxt] in _CLOSERS:
                nxt += 1
            cur += text[i:nxt]
            i = nxt
            lines.append(cur)
            cur, line_w = "", 0.0
            continue
        cur += text[i]
        line_w += widths[i]
        i += 1
    if cur:
        lines.append(cur)
    return lines


# 内容区可用宽度（1080 - 左右各 84）
TITLE_INNER = 912
TITLE_SIZE_MAX = 88
TITLE_SIZE_MIN = 54


def title_block(title: str, max_lines: int = 2) -> tuple[str, int]:
    """标题自动配字号 + 折行：短标题字大，长标题自动缩小以塞进 max_lines 行。"""
    t = re.sub(r"\s+", " ", (title or "").strip())
    if not t:
        return "—", TITLE_SIZE_MAX
    units = sum(_char_w(c) for c in t) or 1.0
    size = int(min(TITLE_SIZE_MAX, max(TITLE_SIZE_MIN, TITLE_INNER * max_lines / units)))
    lines = wrap_cjk(t, TITLE_INNER / size, max_lines)
    return "<br>".join(esc(x) for x in lines), size


def esc(s: str) -> str:
    return html_mod.escape(s or "")


# 链接在图文里既放不下，又正好是平台认定的站外导流信号 —— 一律剥掉
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)


def clean(s: str) -> str:
    s = (s or "").replace("\u200b", "")
    s = _URL_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" -—|·、,，")


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u2B00-\u2BFF\u2190-\u21FF]"
)


def _strip_emoji(s: str) -> str:
    return _EMOJI_RE.sub("", s)


def strip_lead(s: str) -> str:
    """去掉字段开头的前导 emoji 与标签词。"""
    s = clean(s)
    for _ in range(3):
        s2 = _strip_emoji(s).strip()
        s2 = re.sub(r"^(实体洞察|一句话核心判断|一句话决策建议|顾问备忘录)"
                    r"\s*[:：]?\s*", "", s2).strip()
        if s2 == s:
            break
        s = s2
    return s


def tidy_title(s: str) -> str:
    """新闻标题上屏前收拾干净：去链接、去 emoji、去开头的列表序号（如「10. 」）。"""
    s = strip_lead(s)
    s = re.sub(r"^\d{1,2}\s*[.、]\s*(?=[\u4e00-\u9fffA-Za-z])", "", s)
    return clean(s)


# ============================ 抖音合规审核 ============================
# 依据：抖音社区自律公约（站外导流 / 绝对化承诺 / 诱导互动 / 低质内容）
#       + 《广告法》第九条（极限词）
#
# 三级判定：
#   P0 必改   —— 直发会被限流/下架（站外导流、绝对化承诺、诱导互动、招商加盟）
#   P1 建议改 —— 可能降权（极限词、标题党、恐吓式表达）
#   P2 提示   —— 需自查（敏感品类、无来源数字）
#
# 两条决定「这套机制准不准」的认知：
#   ① 图文是「字」不是「话」。平台对图片文字 / 标题 / 字幕的识别比语音更严，
#      口播能含糊带过去的，写在图上就是硬命中 —— 审核必须在出图之前，不是发出去之后。
#   ② 判「导流」不能只看词，要看它是不是「指向我们自己的联系方式」。
#      新闻正文里出现「微信」「抖音」「美团」是正常引用，不算导流；
#      所以拆两层审：我们自己写的固定文案走全规则，引用来的新闻内容只查硬违禁。
#
# 规则字段：(类别, 级别, 仅抖音, 引用层也查, 为什么, 正则列表, 改写映射)

PLATFORM = "douyin"          # douyin | wechat

COMPLIANCE_RULES: list[tuple] = [
    (
        "站外导流", "P0", True, False,
        "抖音明确治理把用户导去站外（微信/公众号/电话/链接），是限流第一大原因",
        [r"微信号?", r"weixin", r"(?<![A-Za-z])[Vv][Xx](?![A-Za-z])", r"\bwx\b",
         r"Q{2}\s*号?", r"扣扣", r"加\s*我", r"私\s*信\s*我", r"私\s*我",
         r"扫码", r"二维码", r"长按识别", r"手机号", r"联系电话", r"电话\s*[:：]",
         r"公众号", r"网址", r"https?://", r"www\."],
        [("见公众号日报", "完整内容见主页合集"),
         ("公众号", "主页"), ("扫码", "在主页查看"), ("二维码", "主页入口"),
         ("加我", "在评论区聊"), ("私信我", "在评论区聊")],
    ),
    (
        "翻墙/境外网络", "P0", True, True,
        "抖音对「翻墙」「科学上网」类表述零容忍，出现在图文文案里极易被判违规限流",
        [r"翻墙", r"科学上网", r"(?<![A-Za-z])[Vv][Pp][Nn](?![A-Za-z])",
         r"机场订阅", r"订阅节点"],
        [("翻墙", "访问境外服务"), ("科学上网", "访问境外服务"),
         ("VPN", "境外网络服务"), ("vpn", "境外网络服务"),
         ("机场订阅", "订阅服务"), ("订阅节点", "订阅服务")],
    ),
    (
        "绝对化承诺", "P0", False, True,
        "《广告法》第九条 + 抖音虚假宣传治理：保证类、收益承诺类一票否决",
        [r"保证[^，。；]{0,6}(成功|拿下|通过|赚|涨|有效)",
         r"一定能", r"必然会", r"百分百", r"100\s*%", r"零风险",
         r"稳赚", r"必赚", r"(?<!外)包(你)?(赚|过|成)(?!本)", r"躺赚",
         r"月入\s*\d+\s*万", r"日入\s*\d+", r"永久有效", r"绝对(有效|安全|可靠)"],
        [("零风险", "风险可控"), ("稳赚", "相对稳"), ("必赚", "有机会"),
         ("包赚", "看经营"), ("躺赚", "省人力"), ("百分百", "大概率"),
         ("100%", "大概率"), ("一定能", "更有可能"), ("永久有效", "长期可用"),
         ("绝对有效", "更有效"), ("绝对安全", "相对安全")],
    ),
    (
        "诱导互动", "P0", True, True,
        "抖音禁止用命令式或利益诱导点赞/关注/转发",
        [r"关注\s*我", r"双击", r"扣\s*1", r"评论区扣", r"转发本文",
         r"求(关注|转发|点赞)", r"点赞关注", r"点个赞"],
        [("关注我", "想看就留着"), ("双击", "收藏"), ("扣1", "在评论区说"),
         ("点赞关注", "收藏留着"), ("求关注", "合你口味就留下"),
         ("求转发", "觉得有用再说")],
    ),
    (
        "招商加盟引流", "P0", True, False,
        "招商加盟类内容需资质，普通账号发布易被判定违规引流"
        "（只查我们自己的文案——新闻里出现「招商/加盟」是正常行业词，不算引流）",
        [r"招(商|募)", r"加盟", r"招(代理|分销)", r"代理商招募", r"带你(做|赚)",
         r"报名(学习|课程|培训)", r"拉你进群"],
        [("加盟", "合作")],
    ),
    (
        "极限词", "P1", False, False,
        "广告法极限词会降权；没有数据支撑的「最」尤其危险",
        [r"最(好|强|快|便宜|大|小|高|低|新|先进|领先|赚钱)",
         r"第一(名|品牌|选择)", r"唯一", r"史上最", r"国家级", r"顶级",
         r"极致", r"绝无仅有", r"空前绝后", r"独家(秘籍|配方)"],
        [("最好", "更好"), ("最强", "更强"), ("最快", "更快"), ("最高", "更高"),
         ("唯一", "少有"), ("史上最", "很"), ("顶级", "优质"), ("极致", "很"),
         ("国家级", "行业级"), ("独家", "少见"), ("第一品牌", "领先品牌")],
    ),
    (
        "标题党/低质", "P1", False, False,
        "抖音低质内容治理：夸张标题会被压流量，也会伤你的专业人设",
        [r"震惊", r"惊呆", r"速看", r"必看", r"不看后悔", r"错过就没了",
         r"火(爆|了)", r"炸(了|裂)", r"秘(密|诀)曝光", r"内幕曝光"],
        [("震惊", "值得注意"), ("速看", "可以看看"), ("必看", "值得一看"),
         ("不看后悔", "错过可惜"), ("火爆炸", "热度很高")],
    ),
    (
        "恐吓式表达", "P1", False, False,
        "恐吓/焦虑营销会被判低质，也与你「第三方研判」的人设相悖",
        [r"血亏", r"完蛋", r"死路", r"必死", r"倒闭潮", r"末日", r"噩梦",
         r"全军覆没", r"颗粒无收"],
        [("血亏", "亏了"), ("完蛋", "很难办"), ("死路", "走不通")],
    ),
    (
        "敏感品类", "P2", False, False,
        "医疗/金融/投资类表述需谨慎，不要给出效果或收益承诺",
        [r"治疗", r"治愈", r"疗效", r"投资回报", r"收益率", r"保本",
         r"理财产品", r"荐股", r"包批"],
        [],
    ),
]

_LEVEL_ICON = {"P0": "⛔", "P1": "⚠️", "P2": "·"}


def _rules_for(platform: str, quote_layer: bool):
    """取适用规则。quote_layer=True 表示在审「引用来的新闻内容」，跳过品牌词类规则。"""
    for cat, lvl, dy_only, q_check, why, pats, fix in COMPLIANCE_RULES:
        if dy_only and platform != "douyin":
            continue
        if quote_layer and not q_check:
            continue
        yield cat, lvl, why, pats, fix


def scan_text(text: str, platform: str = "douyin",
              quote_layer: bool = False) -> list[dict]:
    """扫描一段文字，返回命中项列表。"""
    text = text or ""
    hits: list[dict] = []
    for cat, lvl, why, pats, _fix in _rules_for(platform, quote_layer):
        for p in pats:
            for m in re.finditer(p, text, re.I):
                hits.append({
                    "cat": cat, "lvl": lvl, "why": why, "word": m.group(0),
                    "ctx": re.sub(r"\s+", " ", text[max(0, m.start() - 14):m.end() + 14]),
                })
    return hits


def sanitize_text(text: str, platform: str = "douyin",
                  quote_layer: bool = False) -> tuple[str, list[dict]]:
    """自动改写（只改有映射的词）。返回 (新文本, 命中列表)。

    改写按「规则」触发，不按「词」——只有这条规则真的命中了才动它，
    否则替换表会到处乱改（例如正文里正常的「点赞」被顺手改成「收藏」）。
    """
    text = text or ""
    hits = scan_text(text, platform, quote_layer)
    hit_cats = {h["cat"] for h in hits}
    new = text
    for cat, _lvl, _why, _pats, fix in _rules_for(platform, quote_layer):
        if cat not in hit_cats:
            continue
        for old, rep in fix:
            if old in new:
                new = new.replace(old, rep)
    return new, hits


def compliance_pass(data: dict, platform: str = "douyin") -> tuple[list[dict], list[dict]]:
    """源头净化：把引用来的新闻标题/判断/建议里的硬违禁词改掉。

    返回 (已自动改写, 未改写需人工)。
    「未改写」这一份不能藏起来——那恰恰是最该让人亲眼看一眼的地方，
    自动改写报“已处理”却没改干净，比不报更危险。
    """
    fixed: list[dict] = []
    manual: list[dict] = []
    for r in data["items"]:
        for k in ("title", "judgement", "decision", "insight", "summary", "memo"):
            v = r.get(k) or ""
            if not v:
                continue
            nv, hits = sanitize_text(v, platform, quote_layer=True)
            if nv != v:
                r[k] = nv
            where = f'{(r.get("title") or "")[:16]} · {k}'
            for h in hits:
                item = dict(h, where=where, before=v[:70], after=nv[:70])
                (manual if h["word"] in nv else fixed).append(item)
    return fixed, manual


# ---- 我们自己写的固定文案：卡片与审核共用同一份，避免「改了卡片忘了审」 ----

def copy_set(platform: str = "douyin", allow_contact: bool = False) -> dict:
    if platform == "wechat":
        return {
            "cover_foot": "公众号 · 老许聊实体",
            "end_acct": "抖音 @老许聊实体<br>微信 xuyang2946",
            "end_cta": "你店里想用 AI 做点什么？<br>留言聊聊，我挑着答",
            "end_note": "完整日报（含每条行动建议）<br>每天在公众号更新",
            "item_foot": "@老许聊实体",
            "more": "完整建议 · 见公众号日报",
        }
    c = {
        "cover_foot": "主页 · 老许聊实体",
        "end_acct": "抖音 @老许聊实体",
        "end_cta": "你店里想用 AI 做点什么？<br>评论区聊聊，我挑着答",
        "end_note": "完整日报（含每条行动建议）<br>每天更新，主页合集可回看",
        "item_foot": "@老许聊实体",
        "more": "完整建议 · 见主页合集",
    }
    if allow_contact:                     # 用户手动硬开，风险自负（审核会标红）
        c["end_acct"] += "<br>微信 xuyang2946"
    return c


def audit_copy(copies: dict, platform: str = "douyin") -> list[dict]:
    """审我们自己写的固定文案，走全规则。"""
    labels = {
        "cover_foot": "封面·页脚", "end_acct": "结尾卡·账号",
        "end_cta": "结尾卡·互动引导", "end_note": "结尾卡·说明",
        "item_foot": "内容卡·账号", "more": "内容卡·延伸提示",
    }
    out: list[dict] = []
    for k, t in copies.items():
        for h in scan_text(t, platform, quote_layer=False):
            h["where"] = labels.get(k, k)
            out.append(h)
    return out


# ---- 发布前 60 秒自检（每次跟着报告一起打印）----
SELF_CHECK = [
    "图片里没有任何微信号 / 二维码 / 手机号 / 其他平台名",
    "没有「保证 / 稳赚 / 100% / 第一 / 唯一 / 国家级」这类词",
    "没有「点赞 / 关注我 / 扣1」这类命令式诱导",
    "标题不夸张、不恐吓（震惊 / 必看 / 血亏 / 完蛋）",
    "点名的品牌是客观引用，没有贬损或替你下结论",
    "评论区自己置顶一条问题，且不夹带任何联系方式",
    "发布满 2 小时看一眼：播放极低且完播差 → 大概率被限流，删掉改后再发",
]


def render_audit_md(date_str: str, platform: str, copy_hits: list[dict],
                    fixed_log: list[dict], manual_log: list[dict],
                    allow_contact: bool) -> tuple[str, bool]:
    """生成体检报告 Markdown。返回 (正文, 是否可直接发布)。"""
    p0_copy = [h for h in copy_hits if h["lvl"] == "P0"]
    p0_manual = [h for h in manual_log if h["lvl"] == "P0"]
    ok = not p0_copy and not p0_manual
    name = "抖音图文" if platform == "douyin" else "公众号文章"

    L = [f"# {name} · 发布前合规体检", "",
         f"**日期**：{date_str}　**平台**：{name}", "",
         ("**结论：✅ 可以发布**" if ok else
          "**结论：⛔ 有未处理的高危项，先改再发**"), "",
         "---", "",
         "## 一、我们自己写的文案（页脚 / 引导 / 落款）", ""]
    if not copy_hits:
        L += ["逐条扫过，**无命中**。", ""]
    else:
        L += ["| 位置 | 级别 | 类别 | 命中 | 说明 |", "|---|---|---|---|---|"]
        for h in copy_hits:
            L.append(f'| {h["where"]} | {_LEVEL_ICON[h["lvl"]]} {h["lvl"]} | '
                     f'{h["cat"]} | `{h["word"]}` | {h["why"]} |')
        L.append("")

    L += ["## 二、引用内容（新闻标题 / 判断 / 行动建议）", "",
          f"### 2.1 已自动改写（{len(fixed_log)} 处）", ""]
    if not fixed_log:
        L += ["无需改写。", ""]
    else:
        L += ["| 级别 | 类别 | 命中 | 位置 | 改法 |", "|---|---|---|---|---|"]
        for h in fixed_log:
            L.append(f'| {_LEVEL_ICON[h["lvl"]]} {h["lvl"]} | {h["cat"]} | '
                     f'`{h["word"]}` | {h["where"]} | {h["before"][:30]} → {h["after"][:30]} |')
        L.append("")

    L += [f"### 2.2 未能自动改写，需你亲自看一眼（{len(manual_log)} 处）", ""]
    if not manual_log:
        L += ["无。", ""]
    else:
        L += ["这些词没有现成的安全替换写法，硬换会改变原意，所以没有动它。",
              "**建议**：把图上对应那句删掉，或改成你自己的说法。", "",
              "| 级别 | 类别 | 命中 | 位置 | 它出现的那句 |", "|---|---|---|---|---|"]
        for h in manual_log:
            L.append(f'| {_LEVEL_ICON[h["lvl"]]} {h["lvl"]} | {h["cat"]} | '
                     f'`{h["word"]}` | {h["where"]} | …{h.get("ctx", "")}… |')
        L.append("")

    L += ["## 三、发布前 60 秒自检", ""]
    L += [f"- [ ] {s}" for s in SELF_CHECK]
    L += ["", "---", "", "> 说明：本报告的规则来自抖音社区自律公约与《广告法》第九条，",
          "> 属于**发布前自查**，不构成平台判定结果的承诺。文中点名品牌的引用不带定性结论。",
          ""]
    if allow_contact:
        L += ["", "> ⚠️ 你开启了 `--allow-contact`，抖音卡片会展示微信号。",
              "> 这是平台明确的站外导流高危项，发布后限流风险由你自己承担。", ""]
    return "\n".join(L), ok


# ============================ 解析日报 ============================

def latest_daily() -> Path:
    files = sorted(DATA_DIR.glob("daily-*.html"))
    if not files:
        sys.exit("❌ news-data/ 下没有找到任何 daily-*.html")
    return files[-1]


def _step_text(card, label: str) -> str:
    for d in card.select(".d-step"):
        t = d.select_one(".d-step-title")
        if t and label in t.get_text():
            body = t.find_next_sibling()
            if body is not None:
                return strip_lead(body.get_text(" ", strip=True))
    return ""


def parse_daily(path: Path) -> dict:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    date_str = ""
    m = re.search(r"daily-(\d{4}-\d{2}-\d{2})\.html$", str(path))
    if m:
        date_str = m.group(1)

    items = []
    for card in soup.select(".card"):
        h3 = card.select_one("h3")
        a = card.select_one("h3 a")
        title = tidy_title(h3.get_text(" ", strip=True)) if h3 else ""
        link = (a.get("href") if a else "") or ""
        adv = "观望"
        adv_el = card.select_one(".badge.advice")
        if adv_el:
            adv = clean(adv_el.get_text(strip=True)) or "观望"
        src_el = card.select_one(".meta-line span[style]")
        source = clean(src_el.get_text(strip=True)) if src_el else ""
        ins_el = card.select_one(".insight")
        insight = strip_lead(ins_el.get_text(" ", strip=True)) if ins_el else ""
        sum_el = card.select_one(".summary")
        summary = clean(sum_el.get_text(" ", strip=True)) if sum_el else ""
        industries = [clean(x.get_text(strip=True)) for x in card.select(".industry")]
        memos = [d for d in card.select(".d-kaifeng")]
        memo = strip_lead(memos[0].get_text(" ", strip=True)) if memos else ""

        items.append({
            "title": title,
            "link": link,
            "adv": adv,
            "cls": ADV_CLS.get(adv, "watch"),
            "source": source,
            "insight": insight,
            "summary": summary,
            "judgement": _step_text(card, "一句话核心判断"),
            "decision": _step_text(card, "一句话决策建议"),
            "memo": memo,
            "industries": industries,
        })

    items.sort(key=lambda r: ADV_ORDER.get(r["cls"], 9))
    counts = {"act": 0, "try": 0, "watch": 0, "skip": 0}
    for r in items:
        counts[r["cls"]] = counts.get(r["cls"], 0) + 1
    return {"date": date_str, "items": items, "counts": counts}


# ============================ 抖音卡片 ============================

def _page(inner: str) -> str:
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
        f"<style>{CARD_CSS}</style></head><body>{inner}</body></html>"
    )


def _topbar(date_str: str) -> str:
    return (f'<div class="topbar serif">老许聊实体 · AI×实体洞察日报</div>'
            f'<div class="rule"></div>')


def card_cover(data: dict, top_item: dict | None, cp: dict) -> str:
    c = data["counts"]
    n = len(data["items"])
    act = c.get("act", 0)
    if act:
        lead = f"今天 {n} 条 AI 新闻<br>能立刻动手的只有 {act} 条"
        sub = f"其余 {n - act} 条，看一眼、先记着就够了"
    else:
        lead = f"今天 {n} 条 AI 新闻<br>没有一条值得你立刻动手"
        sub = "今天适合看，不适合动"
    tl = top_item["title"] if top_item else ""
    tl_html = (f'<div class="cover-tl">今日头条 · {esc(tl)}</div>' if tl else "")
    y, mo, d = (data["date"].split("-") + ["", "", ""])[:3]
    stats = (
        f'<div class="cover-stats">'
        f'<div><div class="n">{act}</div><div class="t">立即行动</div></div>'
        f'<div><div class="n">{c.get("try", 0)}</div><div class="t">小成本试用</div></div>'
        f'<div><div class="n">{c.get("watch", 0)}</div><div class="t">观望</div></div>'
        f'</div>'
    )
    inner = (
        _topbar(data["date"])
        + '<div class="mid">'
        + f'<div class="cover-kicker">{y} / {mo} / {d}</div>'
        + f'<div class="cover-title serif">{lead}</div>'
        + f'<div class="cover-sub">{esc(sub)}</div>'
        + tl_html
        + stats
        + "</div>"
        + f'<div class="bottom"><span>完整日报每天更新</span>'
          f'<span>{esc(cp["cover_foot"])}</span></div>'
    )
    return _page(inner)


def card_item(item: dict, idx: int, total: int, date_str: str, cp: dict) -> str:
    title_html, title_size = title_block(item["title"], 2)

    judge = item["judgement"] or item["insight"] or item["summary"]
    judge_html = ""
    if judge:
        body = "<br>".join(esc(x) for x in wrap_cjk(judge, 19.0, 3))
        judge_html = (f'<div class="judge"><div class="label">这条跟你有什么关系</div>'
                      f"<p>{body}</p></div>")

    action = item["decision"] or item["memo"]
    action_html = ""
    if action:
        lines = wrap_cjk(action, 20.0, 3)
        body = "<br>".join(esc(x) for x in lines)
        more = ""
        if lines and lines[-1].endswith("…"):
            more = f'<div class="more">{esc(cp["more"])}</div>'
        action_html = (f'<div class="action"><div class="label">可以怎么做</div>'
                       f"<p>{body}</p>{more}</div>")

    cls = item["cls"]
    inner = (
        _topbar(date_str)
        + f'<div class="meta"><span class="tag {cls}">{esc(item["adv"])}</span>'
          f'<span class="idx">{idx:02d} / {total:02d}</span></div>'
        + f'<h1 class="body-title serif" style="font-size:{title_size}px">{title_html}</h1>'
        + judge_html
        + action_html
        + f'<div class="bottom"><span>来源 · {esc(item["source"] or "网络")}</span>'
          f'<span>{esc(cp["item_foot"])}</span></div>'
    )
    return _page(inner)


def card_end(data: dict, cp: dict) -> str:
    inner = (
        _topbar(data["date"])
        + '<div class="end-wrap">'
        + f'<h1 class="serif">今天这 {len(data["items"])} 条<br>就说到这</h1>'
        + '<div class="sub">AI 每天在变，<br>但能落到你店里的，一天就一两条。</div>'
        + f'<div class="cta">{cp["end_cta"]}</div>'
        + f'<div class="acct">{cp["end_acct"]}</div>'
        + f'<div class="note">{cp["end_note"]}</div>'
        + "</div>"
    )
    return _page(inner)


# ============================ 截图 ============================

def find_browser() -> str | None:
    cands = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    for n in ("msedge", "chrome", "google-chrome", "chromium"):
        p = shutil.which(n)
        if p:
            return p
    return None


def shoot(browser: str, html_path: Path, png_path: Path, scale: int = 1) -> bool:
    base = [
        browser,
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        f"--force-device-scale-factor={scale}",
        f"--window-size={CARD_W},{CARD_H}",
    ]
    if os.name != "nt":
        # 云端/容器里跑必须关沙箱，否则浏览器直接起不来
        base += ["--no-sandbox", "--disable-dev-shm-usage"]
    uri = html_path.resolve().as_uri()
    # 新版 headless 参数在个别浏览器版本上不认，失败就退回旧写法
    for mode in ("--headless=new", "--headless"):
        cmd = [base[0], mode] + base[1:] + [
            f"--screenshot={os.path.abspath(png_path)}", uri,
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            continue
        if png_path.exists() and png_path.stat().st_size > 1000:
            return True
        if png_path.exists():
            png_path.unlink()
    return False


# ============================ 公众号文章 ============================

ART_CSS = f"""
body{{margin:0;background:#F5F4F0;font-family:{SANS};color:#22221F;
  line-height:1.75;font-size:16px}}
.wrap{{max-width:700px;margin:0 auto;padding:40px 26px 72px}}
.masthead{{border-bottom:2px solid #22221F;padding-bottom:14px;margin-bottom:8px;
  display:flex;justify-content:space-between;align-items:baseline;gap:12px}}
.masthead .b{{font-family:{SERIF};font-weight:700;font-size:19px;letter-spacing:.5px}}
.masthead .d{{font-size:13px;color:#7C7A73;letter-spacing:2px}}
h1.art{{font-family:{SERIF};font-weight:700;font-size:34px;line-height:1.35;
  margin:30px 0 18px}}
.lede{{font-size:16px;color:#4A4944;border-left:4px solid {C_RED};
  padding:4px 0 4px 16px;margin:22px 0 8px}}
.stats{{display:flex;gap:22px;margin:26px 0 8px;padding:18px 0;
  border-top:1px solid #DEDCD5;border-bottom:1px solid #DEDCD5}}
.stats .n{{font-family:{SERIF};font-weight:700;font-size:26px;color:{C_RED};line-height:1.1}}
.stats .t{{font-size:12.5px;color:#7C7A73;margin-top:4px}}
h2.grp{{font-family:{SERIF};font-weight:700;font-size:22px;margin:44px 0 6px;
  padding-left:12px;border-left:4px solid {C_RED}}}
.grp-note{{font-size:13px;color:#7C7A73;margin-bottom:18px;padding-left:16px}}
.item{{padding:20px 0;border-bottom:1px solid #E6E4DE}}
.item:last-child{{border-bottom:none}}
.item h3{{font-family:{SERIF};font-weight:700;font-size:18.5px;line-height:1.5;margin:0 0 8px}}
.item h3 a{{color:#22221F;text-decoration:none}}
.meta{{font-size:13px;color:#7C7A73;margin-bottom:12px}}
.meta .pill{{display:inline-block;border:1px solid #C0392B;color:{C_RED};
  border-radius:3px;padding:1px 8px;margin-right:8px;font-size:12px}}
.meta .pill.try{{border-color:#B98A2E;color:#9A6E1C}}
.meta .pill.watch{{border-color:#B4B2AB;color:#7C7A73}}
.line{{margin:8px 0;font-size:15.5px}}
.line b{{color:{C_RED};font-weight:700}}
.line.act b{{color:#9A6E1C}}
.ins{{background:#EFEEE8;border-radius:6px;padding:12px 16px;margin:12px 0;
  font-size:15px;color:#3A3934}}
.ins b{{color:#22221F}}
.zero{{padding:16px 0;font-size:14.5px;color:#7C7A73}}
.foot{{margin-top:50px;padding-top:24px;border-top:2px solid #22221F;
  font-size:14px;color:#4A4944;line-height:2}}
.foot b{{color:#22221F}}
"""


# 抖音图文发布时直接粘贴的标题 + 正文（人工发布，所以给一份现成的，省得再想）
CAP_TAGS = "#AI工具 #实体店 #开店 #小生意"


def douyin_caption(data: dict, picks: list[dict]) -> str:
    d = data["date"]
    mo, dy = d[5:7], d[8:10]
    n = len(data["items"])
    act = data["counts"].get("act", 0)
    if act:
        title = f"{int(mo)}月{int(dy)}日｜{n} 条 AI 新闻，实体店能立刻上手的只有 {act} 条"
    else:
        title = f"{int(mo)}月{int(dy)}日｜今天 {n} 条 AI 新闻，没有一条值得立刻动手"
    body: list[str] = []
    if act:
        body.append(f"今天筛了 {n} 条，真正能马上用的只有 {act} 条：")
    else:
        body.append(f"今天筛了 {n} 条，能马上用的暂时没有，下面这 {len(picks)} 条值得先看一眼：")
    for i, r in enumerate(picks, 1):
        jd = clean(r.get("judgement") or r.get("summary") or "")
        if len(jd) > 44:
            jd = jd[:43].rstrip("，。、；： ") + "…"
        body.append(f"{i}、{clean(r['title'])}")
        if jd:
            body.append(f"　　{jd}")
    body.append("")
    body.append("每条怎么落地、值不值得做，完整版每天更新，主页可回看。")
    body.append(CAP_TAGS)
    return f"【标题】\n{title}\n\n【正文】\n" + "\n".join(body)


def build_article(data: dict) -> str:
    items = data["items"]
    counts = data["counts"]
    date_str = data["date"]
    head = next((r for r in items if r["cls"] == "act"), items[0] if items else None)

    n = len(items)
    act = counts.get("act", 0)
    mo, dy = (date_str[5:7] or "", date_str[8:10] or "")
    if act:
        art_title = f"AI×实体日报 · {mo}/{dy}｜{n} 条里，能立刻动手的只有 {act} 条"
    else:
        art_title = f"AI×实体日报 · {mo}/{dy}｜今天 {n} 条，没有一条值得你立刻动手"

    lede_html = ""
    if head:
        lede_html = (f'<div class="lede"><b>今日头条 · </b>{esc(head["title"])}</div>')

    stats = (
        f'<div class="stats">'
        f'<div><div class="n">{len(items)}</div><div class="t">今日精选</div></div>'
        f'<div><div class="n">{counts.get("act", 0)}</div><div class="t">立即行动</div></div>'
        f'<div><div class="n">{counts.get("try", 0)}</div><div class="t">小成本试用</div></div>'
        f'<div><div class="n">{counts.get("watch", 0)}</div><div class="t">观望</div></div>'
        f'</div>'
    )

    groups = ""
    for cls in ("act", "try", "watch", "skip"):
        group = [r for r in items if r["cls"] == cls]
        if not group:
            continue
        groups += (f'<h2 class="grp">{esc(ADV_HEAD[cls])} · {len(group)} 条</h2>'
                   f'<div class="grp-note">{esc(ADV_NOTE[cls])}</div>')
        for r in group:
            # 标题不做外链：公众号正文只认站内跳转，外部链接到了编辑器里也点不动，
            # 留下一堆域名反倒容易被判「导流」，不如干净地只放文字。
            title = esc(r["title"])
            t_html = title
            meta = (f'<div class="meta"><span class="pill {cls}">{esc(r["adv"])}</span>'
                    f'{esc(r["source"] or "网络")}'
                    + ("　·　" + "、".join(esc(x) for x in r["industries"]) if r["industries"] else "")
                    + "</div>")
            body = ""
            if r["judgement"]:
                body += (f'<div class="line"><b>一句话判断：</b>'
                         f'{esc(r["judgement"])}</div>')
            if r["decision"] and cls in ("act", "try"):
                body += (f'<div class="line act"><b>可以怎么做：</b>'
                         f'{esc(r["decision"])}</div>')
            if r["insight"] and cls in ("act", "try"):
                body += f'<div class="ins"><b>实体洞察：</b>{esc(r["insight"])}</div>'
            if not body:
                body = f'<div class="line">{esc(r["summary"] or "—")}</div>'
            groups += (f'<div class="item"><h3>{t_html}</h3>{meta}{body}</div>')

    if not groups:
        groups = '<div class="zero">今日无精选内容。</div>'

    # 「复制全文」按钮刻意放在 .wrap 之外：复制选区时不会把按钮自己也带上
    btn = """
<button id="cpall" onclick="cpAll(this)">📋 复制全文 → 粘贴到公众号编辑器</button>
<a id="back" href="../index.html">← 返回首页</a>
<script>
function cpAll(btn){
  var w = document.querySelector('.wrap');
  var r = document.createRange(); r.selectNodeContents(w);
  var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
  var ok = false;
  try { ok = document.execCommand('copy'); } catch(e) { ok = false; }
  s.removeAllRanges();
  var old = btn.textContent;
  btn.textContent = ok ? '✅ 已复制，去公众号编辑器粘贴' : '⚠️ 复制失败，请手动全选复制';
  setTimeout(function(){ btn.textContent = old; }, 2600);
}
</script>
<style>
#cpall{position:fixed;right:18px;bottom:18px;z-index:99;font-family:inherit;
  font-size:14px;padding:11px 18px;border:0;border-radius:8px;cursor:pointer;
  background:#C0392B;color:#fff;box-shadow:0 6px 18px rgba(0,0,0,.18)}
#back{position:fixed;right:18px;bottom:62px;z-index:99;font-size:13px;
  color:#7C7A73;background:#fff;border:1px solid #DDD9D0;border-radius:8px;
  padding:7px 14px;text-decoration:none}
@media (max-width:760px){
  #cpall{right:12px;bottom:12px;font-size:13px;padding:10px 14px}
  #back{right:12px;bottom:56px}
}
</style>
"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(art_title)}</title>
<style>{ART_CSS}</style></head>
<body>{btn}<div class="wrap">
  <div class="masthead">
    <span class="b">老许聊实体 · AI×实体洞察日报</span>
    <span class="d">{date_str}</span>
  </div>
  <h1 class="art">{esc(art_title)}</h1>
  {lede_html}
  {stats}
  {groups}
  <div class="foot">
    <b>完整日报每天更新</b>，按「立即行动 / 小成本试用 / 观望」分档，
    每条都带一句判断和一句行动建议。<br>
    抖音：<b>@老许聊实体</b>　｜　微信：<b>xuyang2946</b>
  </div>
</div></body></html>"""


# ---- 机制自检：拿「该抓的」和「故意不该抓的」样本验证规则还有没有用 ----
SELF_TEST_CASES = [
    # (样本, 类别, 应该命中?, 检查层：fixed=我们写的文案 / quote=引用的新闻内容)
    ("加我微信 vx123 领资料", "站外导流", True, "fixed"),
    ("详情见公众号日报", "站外导流", True, "fixed"),
    ("保证一个月回本，稳赚不赔", "绝对化承诺", True, "fixed"),
    ("点赞关注我，扣1领名单", "诱导互动", True, "fixed"),
    ("加盟我们的品牌，带你做", "招商加盟引流", True, "fixed"),
    ("全网最好的选址方法", "极限词", True, "fixed"),
    ("震惊！不看后悔的真相", "标题党/低质", True, "fixed"),
    ("再不改就血亏，等着完蛋", "恐吓式表达", True, "fixed"),
    ("不翻墙就用不了这个工具", "翻墙/境外网络", True, "quote"),
    # ---- 以下都是「不该抓」：中文没有词边界，这些正是最容易误伤的写法 ----
    ("订阅制软件又涨价了", "翻墙/境外网络", False, "quote"),
    ("外包成本降了三成", "绝对化承诺", False, "fixed"),
    ("这条新闻的点赞数很高", "诱导互动", False, "fixed"),
    ("替巨头交学费", "招商加盟引流", False, "quote"),
    ("开封商场招商政策有新变化", "招商加盟引流", False, "quote"),
    ("微信发布新版本", "站外导流", False, "quote"),
    ("抖音上线了新功能", "站外导流", False, "quote"),
]


def self_test(platform: str = "douyin", quiet: bool = False) -> int:
    """规则自检：区分「内容真干净」和「规则坏了」。返回失败条数。"""
    fails = 0
    lines: list[str] = []
    for sample, cat, should_hit, layer in SELF_TEST_CASES:
        hits = scan_text(sample, platform, quote_layer=(layer == "quote"))
        got = cat in {h["cat"] for h in hits}
        ok = got == should_hit
        fails += 0 if ok else 1
        lines.append(f"  {'✓' if ok else '✗'} [{'该抓' if should_hit else '不该抓'}] "
                     f"{cat:<8} {sample}")
    if not quiet or fails:
        print("─" * 48)
        print("规则自检（✗ 表示规则需要修）")
        for ln in lines:
            print(ln)
        print("─" * 48)
        print("✅ 规则自检全部通过" if not fails else f"⛔ 自检失败 {fails} 条，规则需修")
    return fails


# ============================ 主流程 ============================

def build(date_str: str | None, top: int, do_shot: bool, scale: int,
          allow_contact: bool = False, strict: bool = False) -> None:
    # 先给审核机制自己做体检：规则坏了要立刻知道，否则它会一直「报平安」
    if self_test(quiet=True):
        sys.exit("⛔ 规则自检未通过，审核机制可能已失效，先修规则再出内容。")

    src = None
    if date_str:
        cand = DATA_DIR / f"daily-{date_str}.html"
        if not cand.exists():
            sys.exit(f"❌ 未找到 {cand}")
        src = cand
    else:
        src = latest_daily()

    data = parse_daily(src)
    if not data["items"]:
        sys.exit(f"❌ {src.name} 里没有解析到任何卡片")

    d = data["date"]
    print(f"📄 数据源：{src.name}")
    print(f"📊 精选 {len(data['items'])} 条 · "
          f"立即行动 {data['counts'].get('act', 0)} / "
          f"小成本试用 {data['counts'].get('try', 0)} / "
          f"观望 {data['counts'].get('watch', 0)}")

    # ---------- 合规第一关：源头净化 ----------
    # 新闻标题/判断/建议是引用来的，只清「放哪都不能有」的硬违禁词
    quote_fixed, quote_manual = compliance_pass(data, "douyin")
    if quote_fixed:
        print(f"\n🩹 引用内容自动改写 {len(quote_fixed)} 处：")
        for h in quote_fixed:
            print(f"   {_LEVEL_ICON[h['lvl']]} [{h['cat']}] 「{h['word']}」 {h['where']}")
    if quote_manual:
        print(f"\n🔎 有 {len(quote_manual)} 处没有现成替换、保持原样，发布前记得看一眼：")
        for h in quote_manual:
            print(f"   {_LEVEL_ICON[h['lvl']]} [{h['cat']}] 「{h['word']}」 {h['where']}")

    # ---------- 合规第二关：审我们自己写的固定文案 ----------
    cp_dy = copy_set("douyin", allow_contact)
    cp_wx = copy_set("wechat")
    hits_dy = audit_copy(cp_dy, "douyin")
    hits_wx = audit_copy(cp_wx, "wechat")
    p0_dy = ([h for h in hits_dy if h["lvl"] == "P0"]
             + [h for h in quote_manual if h["lvl"] == "P0"])

    out_dir = SOCIAL_DIR / d
    out_dir.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    # 挑图口径必须和日报的推荐档一致，否则会出现"封面写能立刻动手 N 条、
    # 翻进去一条都不是"的矛盾。双键排序：先按行动档
    # （立即行动→小成本→观望→暂不跟进），同一档里再优先中文标题。
    # —— 英文标题卡在抖音图文上观感很差，但绝不该为了中文标题把"立即行动"挤掉。
    def _zh_n(t: str) -> int:
        return sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")

    picks = sorted(
        data["items"],
        key=lambda r: (ADV_ORDER.get(r["cls"], 9),
                       0 if _zh_n(r["title"]) >= 6 else 1),
    )
    picks = picks[:max(1, top)]

    pages: list[tuple[str, str]] = [
        ("01-cover.png", card_cover(data, picks[0] if picks else None, cp_dy))]
    for i, item in enumerate(picks, 1):
        pages.append((f"{i + 1:02d}-content-{i}.png",
                      card_item(item, i, len(picks), d, cp_dy)))
    pages.append((f"{len(pages) + 1:02d}-end.png", card_end(data, cp_dy)))

    # 写卡片网页（中间产物）
    html_files = []
    for name, markup in pages:
        p = WORK_DIR / (name.replace(".png", ".html"))
        p.write_text(markup, encoding="utf-8")
        html_files.append((p, out_dir / name))

    # 公众号文章
    art = build_article(data)
    art_path = DATA_DIR / f"wechat-{d}.html"
    art_path.write_text(art, encoding="utf-8")
    print(f"📝 公众号文章：{art_path}")

    if do_shot:
        browser = find_browser()
        if not browser:
            print("⚠️  未找到 Chrome/Edge，跳过截图（卡片 HTML 已生成）")
        else:
            print(f"🖼  使用浏览器截图：{os.path.basename(browser)}")
            ok = 0
            for hp, png in html_files:
                if shoot(browser, hp, png, scale):
                    ok += 1
                    print(f"   ✓ {png.name}")
                else:
                    print(f"   ✗ {png.name} 截图失败")
            print(f"🖼  抖音图文：{ok}/{len(html_files)} 张 → {out_dir}")

    # ---------- 合规体检报告 ----------
    md_dy, ok_dy = render_audit_md(d, "douyin", hits_dy,
                                   quote_fixed, quote_manual, allow_contact)
    rpt_dy = out_dir / "审核报告-抖音.md"
    rpt_dy.write_text(md_dy, encoding="utf-8")

    md_wx, _ = render_audit_md(d, "wechat", hits_wx, [], [], False)
    rpt_wx = out_dir / "审核报告-公众号.md"
    rpt_wx.write_text(md_wx, encoding="utf-8")

    # 体检结论放在整段输出的最后压轴，并尽量醒目：
    # 这是整屏信息里唯一"看到就该停下手"的内容，不能被上面的进度日志淹没。
    print("\n" + "!" * 52)
    print("  体检结果（发布前请看这一段）")
    print("-" * 52)
    if p0_dy:
        print(f"⛔ 抖音：发现 {len(p0_dy)} 项高危，建议先别发")
        for h in p0_dy:
            print(f"   · {h['where']} 命中「{h['word']}」")
            print(f"     为什么：{h['why']}")
    else:
        print("✅ 抖音：通过（可直接发布）")
    if quote_manual:
        print(f"⚠️ 有 {len(quote_manual)} 处没有现成替换、保持原样，发布前扫一眼：")
        for h in quote_manual[:5]:
            print(f"   · {h['where']}：{h['word']}")
    print(f"   固定文案命中 {len(hits_dy)} 处｜自动改写 {len(quote_fixed)} 处"
          f"｜需人工看 {len(quote_manual)} 处")
    print(f"   完整报告：{rpt_dy}")
    print(f"             {rpt_wx}")
    print("!" * 52)

    # 抖音发布文案：人工发布时直接粘贴（标题 + 正文，省得再想）
    cap = douyin_caption(data, picks)
    (out_dir / "发布文案-抖音.txt").write_text(cap, encoding="utf-8")

    # 预览页（图片 + 一键复制文案 + 体检条）：发布的人从这里取素材
    labels = ["封面"] + [f"内容 {i}" for i in range(1, len(picks) + 1)] + ["结尾"]
    imgs = "".join(
        f'<div class="cell"><a href="social/{d}/{name}" download>'
        f'<img src="social/{d}/{name}" alt="{name}"></a>'
        f'<span>{labels[i] if i < len(labels) else name}</span></div>'
        for i, (name, _) in enumerate(pages)
    )
    if p0_dy:
        badge = (f'<div class="audit bad">⛔ 抖音合规体检未通过（{len(p0_dy)} 项高危）'
                 + "".join(f'<span>· {esc(h["where"])}：{esc(h["word"])}</span>' for h in p0_dy)
                 + "</div>")
    else:
        badge = (f'<div class="audit ok">✅ 抖音合规体检通过　'
                 f'<span>固定文案 0 高危｜自动改写 {len(quote_fixed)} 处</span></div>')
    if quote_manual:
        badge += ('<div class="audit warn">⚠️ 这几处没有现成替换、保持原样，发布前看一眼'
                  + "".join(f'<span>· {esc(h["where"])}：{esc(h["word"])}</span>'
                            for h in quote_manual[:8])
                  + "</div>")

    # 复制按钮的脚本单独放，避免在 f-string 里跟大括号打架
    copy_js = """
<script>
function cpCap(btn){
  var t = document.getElementById('cap').innerText;
  function done(ok){
    var o = btn.textContent;
    btn.textContent = ok ? '✅ 已复制' : '⚠️ 请手动选中复制';
    setTimeout(function(){ btn.textContent = o; }, 2400);
  }
  function fb(){
    var a = document.createElement('textarea');
    a.value = t; document.body.appendChild(a); a.select();
    var ok = false; try { ok = document.execCommand('copy'); } catch(e) { ok = false; }
    a.remove(); done(ok);
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(t).then(function(){ done(true); }).catch(fb);
  } else { fb(); }
}
</script>
"""

    preview = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>社媒素材 · {d}</title>
<style>
body{{margin:0;background:#0E0E0D;padding:30px 20px 70px;font-family:{SANS};color:{C_INK}}}
h1{{font-size:19px;font-weight:600;margin:0 0 8px}}
p.hint{{color:{C_MUTED};font-size:13.5px;margin:0 0 20px;line-height:2}}
.audit{{border:1px solid #2E7D5B;border-left-width:5px;border-radius:6px;
  padding:12px 16px;margin:0 0 12px;font-size:14px;display:flex;
  flex-wrap:wrap;gap:6px 18px;align-items:baseline}}
.audit.ok{{border-color:#2E7D5B;color:#7FD1A6}}
.audit.bad{{border-color:{C_RED};color:#F0A79C}}
.audit.warn{{border-color:#B98A2E;color:#E0BC72}}
.audit span{{color:{C_MUTED};font-size:13px}}
.row{{display:flex;gap:18px;overflow-x:auto;padding:6px 0 22px;align-items:flex-start}}
.cell{{width:300px;flex:none}}
.cell img{{width:100%;border-radius:10px;display:block;border:1px solid #2A2A28}}
.cell span{{display:block;margin-top:8px;color:{C_MUTED};font-size:12.5px;
  letter-spacing:1px;text-align:center}}
.capwrap{{max-width:780px;background:#171716;border:1px solid #2A2A28;
  border-radius:10px;padding:18px 20px}}
.caphead{{display:flex;justify-content:space-between;align-items:center;gap:12px;
  color:{C_MUTED};font-size:13px;margin-bottom:12px}}
#cap{{white-space:pre-wrap;word-break:break-word;font-family:{SANS};
  font-size:14.5px;line-height:1.95;color:{C_INK};margin:0}}
.btn{{font-family:inherit;font-size:13.5px;padding:8px 16px;border-radius:7px;
  border:1px solid {C_RED};background:{C_RED};color:#fff;cursor:pointer;white-space:nowrap}}
.btn.ghost{{background:transparent;border-color:#4A4740;color:{C_INK};
  text-decoration:none;display:inline-block;padding:9px 16px}}
.links{{display:flex;gap:10px;flex-wrap:wrap;margin:22px 0 0}}
.back{{display:inline-block;margin-top:26px;color:{C_RED_TXT};font-size:14px;
  text-decoration:none;border:1px solid #5A5852;border-radius:6px;padding:8px 16px}}
@media (max-width:760px){{
  body{{padding:22px 14px 60px}}
  .cell{{width:74vw}}
}}
</style></head><body>
<h1>今日社媒素材 · {d}（共 {len(pages)} 张）</h1>
<p class="hint">图片从左到右就是发布顺序。<b>手机长按图片存相册，电脑点图直接下载。</b><br>
文案点右侧「复制文案」，到抖音图文里粘贴即可。</p>
{badge}
<div class="row">{imgs}</div>
<div class="capwrap">
  <div class="caphead"><span>抖音发布文案（标题 + 正文）</span>
    <button class="btn" onclick="cpCap(this)">📋 复制文案</button></div>
  <pre id="cap">{esc(cap)}</pre>
</div>
<div class="links">
  <a class="btn ghost" href="wechat-{d}.html" target="_blank" rel="noopener">📄 公众号文章（点开 → 复制全文）</a>
  <a class="btn ghost" href="social/{d}/审核报告-抖音.md" target="_blank" rel="noopener">🛡 抖音合规体检</a>
  <a class="btn ghost" href="social/{d}/审核报告-公众号.md" target="_blank" rel="noopener">🛡 公众号体检</a>
</div>
<a class="back" href="../index.html">← 返回首页</a>
{copy_js}</body></html>"""
    prev_path = DATA_DIR / f"social-{d}.html"
    prev_path.write_text(preview, encoding="utf-8")
    print(f"👀 素材页（取图/复制文案）：{prev_path}")

    if strict and p0_dy:
        sys.exit("⛔ --strict 模式：存在未处理高危项，已中止。")

    # 非 strict 模式：不改内容、照常出图（发不发由人决定），但用退出码 3 告诉外面
    # "有高危项"——好让一键脚本把窗口停住。这条最该看的提醒不能被倒计时吃掉。
    if p0_dy:
        sys.exit(3)


def main() -> None:
    ap = argparse.ArgumentParser(description="日报 → 抖音图文 + 公众号文章（含合规审核）")
    ap.add_argument("date", nargs="?", default=None,
                    help="日期 YYYY-MM-DD，缺省取最新一期")
    ap.add_argument("--top", type=int, default=3, help="内容卡条数（默认 3）")
    ap.add_argument("--no-shot", action="store_true", help="只生成 HTML，不截图")
    ap.add_argument("--scale", type=int, default=1, help="截图倍率（2 为高清）")
    ap.add_argument("--allow-contact", action="store_true",
                    help="抖音卡片也展示微信号（高风险，默认关闭）")
    ap.add_argument("--strict", action="store_true",
                    help="存在未处理的高危项时直接中止（适合挂自动化）")
    ap.add_argument("--self-test", action="store_true",
                    help="只跑规则自检（确认审核机制没失效）")
    args = ap.parse_args()
    os.chdir(Path(__file__).resolve().parent.parent)
    if args.self_test:
        sys.exit(1 if self_test() else 0)
    build(args.date, args.top, not args.no_shot, args.scale,
          allow_contact=args.allow_contact, strict=args.strict)


if __name__ == "__main__":
    main()
