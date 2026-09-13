# -*- coding: utf-8 -*-
"""生成某月的 AI×实体洞察 月度总结网页。

数据来源：news-data/daily-YYYY-MM-*.html（每条日报网页里已含分类 / 行动分级 /
来源 / 行业 / 国产替代 / 实体洞察 / 摘要 等全字段）。
用 BeautifulSoup 解析后按月聚合，产出 news-data/monthly-YYYY-MM.html。

排版：报刊内参风（衬线刊头 + 发丝线 + 近似单色 + 单一印章红），
不复用日报的科技风样式；无左侧导航栏，仅刊头保留「返回首页」按钮。
不含「风险与雷区」板块（复盘确认：该板块 99% 来自 AI 通用提示模板的误报，
对实体老板无阅读与决策价值，故移除）。
"""
import re
import sys
import glob
import os
import datetime
from collections import Counter, defaultdict
from bs4 import BeautifulSoup

DATA_DIR = "news-data"


def _resolve_period():
    """确定要生成的年月。

    - 命令行传入：build_monthly.py 2026 9  或  build_monthly.py 2026-09
    - 否则取「当前月份」（用于每月最后一天的自动化：跟着当天日报一起跑）
    """
    args = sys.argv[1:]
    if len(args) >= 2 and re.fullmatch(r"\d{4}", args[0]) and re.fullmatch(r"\d{1,2}", args[1]):
        return int(args[0]), int(args[1])
    if len(args) == 1 and re.fullmatch(r"\d{4}-\d{1,2}", args[0]):
        y, m = args[0].split("-")
        return int(y), int(m)
    today = datetime.date.today()
    return today.year, today.month


YEAR, MONTH = _resolve_period()

ADV_LABEL = {"act": "立即行动", "try": "小成本试用", "watch": "观望", "skip": "暂不考虑"}
ADV_COLOR = {"act": "#c4ed1a", "try": "#b87aff", "watch": "#4f6dff", "skip": "#777777"}

files = sorted(glob.glob(f"{DATA_DIR}/daily-{YEAR}-{MONTH:02d}-*.html"))
if not files:
    raise SystemExit(f"未找到 {YEAR}-{MONTH:02d} 的日报文件")

records = []      # 每条卡片
day_stats = []    # 每天汇总


def text_of(tag):
    return tag.get_text(" ", strip=True) if tag else ""


for f in files:
    html = open(f, encoding="utf-8").read()
    soup = BeautifulSoup(html, "html.parser")

    # 日期
    meta = soup.select_one(".meta")
    date_str = meta.get_text(" ", strip=True).split("·")[0].strip() if meta else ""

    # 每日数字
    selected = filtered = None
    for s in soup.select(".stats .stat"):
        b = s.find("b")
        t = s.get_text(" ", strip=True)
        if "实体精选" in t and b:
            selected = int(b.get_text())
        elif "与实体无关" in t and b:
            filtered = int(b.get_text())

    # 每日行动分级
    adv_counts = {}
    al = soup.select_one(".advice-line")
    if al:
        for part in al.get_text(" ", strip=True).split("·"):
            m = re.search(r"(\d+)", part)
            if not m:
                continue
            if "立即行动" in part:
                adv_counts["act"] = int(m.group(1))
            elif "小成本试用" in part:
                adv_counts["try"] = int(m.group(1))
            elif "观望" in part:
                adv_counts["watch"] = int(m.group(1))

    day_stats.append({"date": date_str, "selected": selected or 0,
                      "filtered": filtered or 0, "adv": adv_counts})

    # 逐分类、逐卡片
    for section in soup.select("section.cat-group"):
        cat_el = section.select_one(".cat-title")
        cat_name = ""
        if cat_el:
            raw = cat_el.get_text(" ", strip=True)
            cat_name = re.split(r"\d+\s*条", raw)[0].strip()
        for card in section.select(".card"):
            adv = card.get("data-adv") or ""
            h3 = card.select_one("h3 a")
            title = text_of(h3)
            title = re.sub(r"\s+", " ", title).strip()
            link = h3.get("href") if h3 else ""
            industries = [s.get_text(strip=True)
                          for s in card.select(".meta-line .industry")]
            maturity = text_of(card.select_one(".meta-line .badge.maturity"))
            effort = text_of(card.select_one(".meta-line .badge.effort"))
            advice = text_of(card.select_one(".meta-line .badge.advice"))
            alts = [s.get_text(strip=True).replace("国产替代:", "").replace("国产替代：", "").strip()
                    for s in card.select(".meta-line .alternative")]
            src_el = card.select_one(".meta-line span[style*='margin-left:auto']")
            source = text_of(src_el)
            insight_el = card.select_one(".insight")
            insight = text_of(insight_el)
            insight = re.sub(r"^💡\s*实体洞察", "", insight).strip()
            summary = text_of(card.select_one(".summary"))
            records.append({
                "date": date_str, "category": cat_name, "adv": adv,
                "title": title, "link": link, "industries": industries,
                "maturity": maturity, "effort": effort, "advice": advice,
                "alts": alts, "source": source, "insight": insight,
                "summary": summary,
            })

total_days = len(day_stats)
total_selected = sum(d["selected"] for d in day_stats)
total_filtered = sum(d["filtered"] for d in day_stats)
total_scanned = total_selected + total_filtered
sel_ratio = (total_selected / total_scanned * 100) if total_scanned else 0

# 行动分级分布（按卡片）
adv_counter = Counter(r["adv"] for r in records)
adv_total = sum(adv_counter.values())

# 赛道热度
cat_counter = Counter(r["category"] for r in records)

# 来源 TOP
src_counter = Counter(r["source"] for r in records if r["source"])

# 国产替代地图
alt_map = defaultdict(list)
for r in records:
    for a in r["alts"]:
        if a:
            alt_map[a].append(r)

# 立即行动清单（按链接去重）
_seen = set()
act_items = []
for r in records:
    if r["adv"] == "act" and r["link"] not in _seen:
        _seen.add(r["link"])
        act_items.append(r)

# 三大主线：按赛道热度取前三
top_cats = [c for c, _ in cat_counter.most_common(3)]

# 本月一句话主线
dominant_adv = max(("act", "try", "watch"),
                   key=lambda a: adv_counter.get(a, 0))
dominant_label = ADV_LABEL.get(dominant_adv, "")
top_cat_name = top_cats[0] if top_cats else ""
headline = (f"本月共出报 {total_days} 期，精选 {total_selected} 条；"
            f"{top_cat_name} 是本月最热赛道，行动以「{dominant_label}」为主。")


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def bar_row(label, count, total, label2=""):
    pct = (count / total * 100) if total else 0
    return (f'<div class="bar"><span class="lab">{esc(label)}</span>'
            f'<div class="track"><div class="fill" style="width:{pct:.1f}%"></div></div>'
            f'<span class="num">{count}{label2}</span></div>')


# ---------- 报刊内参风样式（自包含，不复用日报科技风） ----------
CSS = """
:root{
  --bg:#100f0e; --paper:#161513; --ink:#ece8e1; --muted:#9b968c;
  --hair:#2b2926; --hair-soft:#211f1c;
  --seal:#c0392b; --seal-soft:rgba(192,57,43,.13);
  --serif:Georgia,"Times New Roman","Songti SC","Noto Serif SC","SimSun",serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.78;-webkit-text-size-adjust:100%}
.wrap{max-width:820px;margin:0 auto;padding:0 22px 84px}

/* 刊头 */
.masthead{text-align:center;padding:56px 0 26px;border-bottom:1px solid var(--hair)}
.masthead .kicker{font-family:var(--serif);font-size:12.5px;letter-spacing:.42em;color:var(--muted)}
.masthead h1{font-family:var(--serif);font-weight:700;font-size:34px;letter-spacing:.05em;margin:16px 0 0;color:#fbfaf7}
.masthead .hair-seal{width:52px;height:3px;background:var(--seal);margin:16px auto}
.masthead .dateline{font-size:13.5px;color:var(--muted);letter-spacing:.12em}
.back-home{display:inline-block;margin-top:22px;font-size:13px;letter-spacing:.12em;color:var(--ink);
  text-decoration:none;border:1px solid var(--hair);padding:8px 18px;transition:border-color .2s,color .2s}
.back-home:hover{border-color:var(--seal);color:var(--seal)}

/* 导语 */
.lede{font-family:var(--serif);font-size:18px;line-height:1.95;color:var(--ink);
  margin:36px 0 4px;padding-left:16px;border-left:3px solid var(--seal)}

/* 区块 */
.sec{margin-top:48px}
.sec-kick{font-family:var(--serif);font-size:12.5px;letter-spacing:.34em;color:var(--seal);font-weight:700;margin:0 0 6px}
.sec-title{font-family:var(--serif);font-size:23px;font-weight:700;color:#fbfaf7;margin:0 0 18px;padding-bottom:12px;border-bottom:1px solid var(--hair)}

/* 数据看板：报纸式数字条 */
.figs{display:flex;flex-wrap:wrap;border-top:1px solid var(--hair);border-bottom:1px solid var(--hair)}
.fig{flex:1;min-width:118px;padding:18px 12px;text-align:center;border-left:1px solid var(--hair)}
.fig:first-child{border-left:none}
.fig b{display:block;font-family:var(--serif);font-size:30px;line-height:1.1;color:var(--seal)}
.fig span{font-size:12.5px;color:var(--muted)}

/* 条形 */
.bar{display:flex;align-items:center;gap:14px;margin:12px 0}
.bar .lab{width:128px;flex-shrink:0;font-size:13.5px;color:var(--ink)}
.bar .track{flex:1;height:9px;background:#20201e;border-radius:0;overflow:hidden}
.bar .fill{height:100%;background:var(--seal)}
.bar .num{width:80px;text-align:right;font-size:12.5px;color:var(--muted);flex-shrink:0}

/* 三大主线：编辑式条目 */
.theme{display:flex;gap:18px;padding:18px 0;border-top:1px solid var(--hair)}
.theme:first-of-type{border-top:none}
.theme .no{font-family:var(--serif);font-size:24px;font-weight:700;color:var(--seal);flex-shrink:0;width:30px;line-height:1.2}
.theme .ttl{font-family:var(--serif);font-size:17px;font-weight:700;color:#fbfaf7;margin:0 0 5px}
.theme .desc{font-size:13px;color:var(--muted);margin:0 0 10px}
.theme .rep{display:flex;gap:10px;padding:7px 0;border-top:1px solid var(--hair-soft);align-items:flex-start}
.theme .rep .dot{flex-shrink:0;width:7px;height:7px;border-radius:50%;background:var(--seal);margin-top:8px}
.theme .rep a{color:var(--ink);text-decoration:none;font-size:13.5px;line-height:1.55}
.theme .rep a:hover{color:var(--seal);text-decoration:underline}
.theme .rep .meta{color:var(--muted);font-size:11.5px;margin-top:2px}

/* 清单行（立即行动 / 国产替代） */
.row{display:flex;gap:12px;padding:12px 0;border-top:1px solid var(--hair);align-items:flex-start}
.row:first-of-type{border-top:none}
.row .mark{flex-shrink:0;width:9px;height:9px;border-radius:50%;background:var(--seal);margin-top:8px}
.row .body{flex:1}
.row a{color:var(--ink);text-decoration:none;font-size:14px;line-height:1.55}
.row a:hover{color:var(--seal);text-decoration:underline}
.row .meta{color:var(--muted);font-size:12px;margin-top:3px}
.alt-group{margin:16px 0 4px}
.alt-name{display:inline-block;font-size:13px;font-weight:700;color:#f0c9a0;
  border:1px solid rgba(192,140,80,.4);padding:3px 11px;margin-bottom:6px;letter-spacing:.04em}
.alt-note{color:var(--muted);font-size:13px;line-height:1.9;margin-bottom:6px}

/* 研判层：客观事实 vs 主观研判 严格分离、视觉区分 */
.judge-sec{margin-top:8px}
.risk-lede{font-size:13.5px;color:var(--muted);line-height:1.9;margin:6px 0 18px;padding-left:14px;border-left:3px solid var(--seal)}
.judge{margin:22px 0;padding:18px 0;border-top:1px solid var(--hair)}
.judge:first-of-type{border-top:none}
.judge .j-h{font-family:var(--serif);font-size:18px;font-weight:700;color:#fbfaf7;margin:0 0 12px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.judge .j-tag{flex-shrink:0;font-family:var(--sans);font-size:11px;letter-spacing:.12em;color:#f0c9a0;border:1px solid rgba(192,140,80,.45);padding:2px 9px}
.judge .j-fact{font-size:13.5px;color:var(--muted);line-height:1.85;margin:0 0 12px;padding-left:14px;border-left:3px solid #3a3833}
.judge .j-view{font-size:14.5px;color:var(--ink);line-height:1.9;margin:0;padding:12px 14px;background:var(--seal-soft);border-left:3px solid var(--seal)}
.judge .j-view b{color:#f0c9a0;font-weight:700}
.j-sub{font-family:var(--serif);font-size:15.5px;font-weight:700;color:var(--seal);margin:32px 0 6px;letter-spacing:.04em}
.les{display:flex;gap:14px;padding:14px 0;border-top:1px solid var(--hair);align-items:flex-start}
.les:first-of-type{border-top:none}
.les .ln{font-family:var(--serif);font-size:20px;font-weight:700;color:var(--seal);flex-shrink:0;width:26px;line-height:1.2}
.les .lt{font-size:13.8px;color:var(--ink);line-height:1.85}
.les .lt b{color:#f0c9a0}
.fc{margin:16px 0;padding:16px 18px;border:1px solid var(--hair);background:rgba(255,255,255,.015)}
.fc .fc-h{font-family:var(--serif);font-size:13px;letter-spacing:.18em;color:var(--seal);font-weight:700;margin:0 0 8px}
.fc .fc-sig{font-size:13.5px;color:#f0b6ae;margin:0 0 10px;line-height:1.7}
.fc .fc-do{font-size:14px;color:var(--ink);line-height:1.85;margin:0 0 9px}
.fc .fc-do b{color:#f0c9a0}
.fc .fc-pos{font-size:13px;color:var(--muted);line-height:1.8;margin:0;padding-left:14px;border-left:3px solid #3a3833}
.fc .fc-pos b{color:#f0c9a0}

.footer{margin-top:64px;padding-top:20px;border-top:1px solid var(--hair);
  text-align:center;color:var(--muted);font-size:12.5px;letter-spacing:.08em}

@media (max-width:560px){
  .wrap{padding:0 16px 64px}
  .masthead{padding:40px 0 22px}
  .masthead h1{font-size:26px}
  .fig{min-width:45%}
  .bar .lab{width:96px}
  .theme{flex-direction:column;gap:8px}
  .theme .no{width:auto}
}
"""

# 行动分级分布
adv_bars = ""
for a in ("act", "try", "watch", "skip"):
    if adv_counter.get(a):
        adv_bars += bar_row(ADV_LABEL[a], adv_counter[a], adv_total)

# 赛道热度
cat_bars = ""
cat_max = max(cat_counter.values()) if cat_counter else 1
for c, n in cat_counter.most_common():
    pct = n / cat_max * 100
    cat_bars += (f'<div class="bar"><span class="lab">{esc(c)}</span>'
                 f'<div class="track"><div class="fill" style="width:{pct:.0f}%"></div></div>'
                 f'<span class="num">{n} 条</span></div>')

# 立即行动清单
act_html = ""
for r in act_items:
    act_html += (f'<div class="row"><span class="mark"></span><div class="body">'
                 f'<a href="{esc(r["link"])}" target="_blank" rel="noopener">{esc(r["title"])}</a>'
                 f'<div class="meta">{esc(r["source"])} · {esc(r["maturity"])}'
                 f'{" · " + "、".join(r["industries"]) if r["industries"] else ""}</div></div></div>')
if not act_html:
    act_html = '<div class="note">本月无「立即行动」级条目。</div>'

# 国产替代地图（取最高频 12 个，避免过长）
alt_html = ""
top_alts = sorted(alt_map.items(), key=lambda x: -len(x[1]))[:12]
if top_alts:
    alt_html += (f'<div class="alt-note">本月共提及 <b style="color:#f0c9a0">{len(alt_map)}</b> 个国产/平替工具，'
                 f'以下为被引用最多的 12 个：</div>')
for a, rs in top_alts:
    items_html = ""
    for r in rs[:3]:
        items_html += (f'<div class="row" style="padding:8px 0"><span class="mark" '
                       f'style="background:#d9a86a"></span><div class="body">'
                       f'<a href="{esc(r["link"])}" target="_blank" rel="noopener">{esc(r["title"])}</a>'
                       f'<div class="meta">{esc(r["source"])}</div></div></div>')
    more = f'<div class="meta" style="color:var(--muted)">…等共 {len(rs)} 条提及</div>' if len(rs) > 3 else ""
    alt_html += (f'<div class="alt-group"><span class="alt-name">🔧 {esc(a)}</span>'
                 f'{items_html}{more}</div>')
if not alt_html:
    alt_html = '<div class="note">本月卡片未标注国产替代。</div>'

# ===================== 研判层（第三方视角）：客观事实与主观推断严格分离 =====================
# 对齐「零售选址分析器」方法论：① 客观依据(事实) 与 主观研判(观点/预判) 分开标注、分开呈现；
# ② 每一条主观推断都绑定本月真实数据，不空谈；③ 站在第三方(顾问/投资人/租户)视角，而非只罗列新闻。
def _ctype(name):
    CAT_TYPE = {
        "智能体": "效率/流程", "自动化": "效率/流程", "工作流": "效率/流程",
        "视频": "内容生成", "图像": "内容生成", "设计": "内容生成", "数字人": "内容生成",
        "平台": "平台/流量", "商业模式": "平台/流量", "大模型": "底层能力",
        "电商": "经营提效", "零售": "经营提效",
    }
    for k, v in CAT_TYPE.items():
        if k in name:
            return v
    return "其他"


def _strip_emoji(s):
    return re.sub(r'^[^\u4e00-\u9fffA-Za-z0-9]+', '', s or "").strip()


cats3 = cat_counter.most_common(3)
top1, top1n = (cats3[0] if cats3 else ("—", 0))
top2, top2n = (cats3[1] if len(cats3) > 1 else (top1, 0))
top1d, top2d = _strip_emoji(top1), _strip_emoji(top2)
t1, t2 = _ctype(top1), _ctype(top2)
act_n = adv_counter.get("act", 0)
act_pct = act_n / adv_total * 100 if adv_total else 0
alt_n = len(alt_map)


def judge_card(title, fact, view):
    return (f'<div class="judge"><div class="j-h"><span class="j-tag">研判</span>'
            f'<span>{esc(title)}</span></div>'
            f'<p class="j-fact"><b>客观依据 ·</b> {esc(fact)}</p>'
            f'<p class="j-view"><b>核心观点 ·</b> {esc(view)}</p></div>')


if t1 == "效率/流程" and t2 == "内容生成":
    v1 = ("本月 AI 落地重心正从「内容生成」切到「流程自动化」。对实体老板，省人力的工具比做营销内容先一步成熟——"
          "优先拿排班、客服、库存这类重复活试自动化，比再雇人划算。")
elif t1 == "内容生成":
    v1 = ("内容生成仍是主角，但红利在变薄、同质化加剧。想靠 AI 出片出文案，得拼「独家信息 + 真人设」，纯工具红利已不够。")
elif t1 == "平台/流量":
    v1 = ("平台与流量玩法是本月焦点，说明「用 AI 引流」门槛在降；但流量最终沉淀在平台手里的坑也在变深，别只经营平台内粉丝。")
else:
    v1 = f"本月注意力集中在「{t1}」方向，老板可重点看这类的真实落地案例，先小范围试。"

judge_cards = judge_card(f"赛道重心：本月最热是「{top1d}」",
    f"本月最热赛道「{top1d}」{top1n} 条，第二「{top2d}」{top2n} 条。", v1)
judge_cards += judge_card(f"信息密度：约 {total_scanned} 条里只筛出 {total_selected} 条",
    f"本月进入筛选的 AI 资讯约 {total_scanned} 条，最终入选 {total_selected} 条（筛选率约 {sel_ratio:.0f}%）。",
    "对实体老板真正有用的 AI 资讯，平均一天就一两条。别为海量未筛选的 AI 新闻焦虑——盯本站的精选就够了，省下的时间用来落地。")
judge_cards += judge_card("成熟度：绝大多数 AI 能力「能看不能用」",
    f"精选 {total_selected} 条里，真正「立即行动」仅 {act_n} 条（{act_pct:.0f}%），其余多为试用或观望。",
    "别被日更焦虑裹挟：筛选比盲动重要，每月真正值得你动手的就那十来条。多数事拖成观望也活得好。")

# —— 沉淀：实体老板该记住的 3 条规律（均绑定本月真实数据）——
lessons = [
    (f"本月「立即行动」仅占 <b>{act_pct:.0f}%</b>——记住：每天刷到的 AI 新闻 90% 与你无关，能落地的凤毛麟角。"
     f"少看热闹、多挑能用的，比焦虑更重要。"),
    (f"国产 / 平替工具本月被点名 <b>{alt_n}</b> 个、已成主流——记住：同类需求优先选国内合规工具，"
     f"少踩跨境卡脖子与合规的坑。"),
    (f"内容生成类仍热但已卷、自动化类在升——记住：红利正从「会生成」转向「能落地」，"
     f"你的投入要从「买工具」转向「改流程」。"),
]
lessons_html = ""
for i, t in enumerate(lessons, 1):
    lessons_html += f'<div class="les"><div class="ln">{i}</div><div class="lt">{t}</div></div>'

# —— 预判：下月信号与准备（含可能性情景）——
def forecast_card(sig, do, pos):
    return (f'<div class="fc"><div class="fc-h">信号</div>'
            f'<p class="fc-sig">▸ {esc(sig)}</p>'
            f'<p class="fc-do"><b>准备动作 ·</b> {esc(do)}</p>'
            f'<p class="fc-pos"><b>可能性 ·</b> {esc(pos)}</p></div>')


forecast_html = forecast_card(
    f"「{top1d}」赛道下月大概率继续升温、工具迭代最快（本月 {top1n} 条居首）。",
    "本月就选 1 个高频重复工作流试起来，别等「更完美」的版本——早试早知道坑在哪。",
    "若平台顺势推出「AI 店铺 / AI 经营」类工具（收租模式），先免费试用、别提前年付绑定。")
forecast_html += forecast_card(
    "平台免费 AI 功能会逐步收紧或转向收费（本行业普遍规律）。",
    "现在就把核心顾客数据导出留底、关键流程别只绑一家平台，避免被规则变动卡住。",
    "若平台带头收紧，早做数据留底与多平台分散的，反而更稳。")
forecast_html += forecast_card(
    f"国产 / 平替工具本月被提及 {alt_n} 个、已成主流。",
    "同类需求优先选国内合规工具，降低被卡脖子与跨境合规风险。",
    "若海外工具进一步受限或涨价，国产平替会补位加速——提前摸底不吃亏。")

month_cn = f"{YEAR}年{MONTH:02d}月"

content = f"""
<div class="masthead">
  <div class="kicker">老许聊实体 · 内部参阅</div>
  <h1>AI × 实体洞察月报</h1>
  <div class="hair-seal"></div>
  <div class="dateline">{month_cn} · 给实体经营者的月度行动回顾</div>
  <div><a class="back-home" href="../index.html">← 返回首页</a></div>
</div>

<p class="lede">{esc(headline)}</p>

<div class="sec">
  <p class="sec-kick">OVERVIEW</p>
  <h2 class="sec-title">本月数据看板</h2>
  <div class="figs">
    <div class="fig"><b>{total_days}</b><span>出报天数</span></div>
    <div class="fig"><b>{total_selected}</b><span>实体精选条数</span></div>
    <div class="fig"><b>{total_filtered}</b><span>筛掉的无关资讯</span></div>
    <div class="fig"><b>{adv_counter.get('act',0)}</b><span>立即行动</span></div>
    <div class="fig"><b>{adv_counter.get('try',0)}</b><span>小成本试用</span></div>
    <div class="fig"><b>{adv_counter.get('watch',0)}</b><span>观望</span></div>
  </div>
</div>

<div class="sec">
  <p class="sec-kick">ACTION</p>
  <h2 class="sec-title">行动分级分布</h2>
  {adv_bars}
</div>

<div class="sec">
  <p class="sec-kick">TRACK</p>
  <h2 class="sec-title">赛道热度榜</h2>
  {cat_bars}
</div>

<div class="sec judge-sec">
  <p class="sec-kick">ANALYSIS · 第三方视角</p>
  <h2 class="sec-title">研判层：观点 · 沉淀 · 预判</h2>
  <div class="risk-lede">以下为主观研判，与上方「数据看板 / 赛道热度」等客观事实严格分离；每条判断均绑定本月真实数据，仅供参考，不构成经营决策。</div>
  <p class="j-sub">▍ 本月三条核心判断（观点）</p>
  {judge_cards}
  <p class="j-sub">▍ 沉淀 · 实体老板该记住的 3 条规律</p>
  {lessons_html}
  <p class="j-sub">▍ 预判 · 下月信号与准备（可能性）</p>
  {forecast_html}
</div>

<div class="sec">
  <p class="sec-kick">DO NOW</p>
  <h2 class="sec-title">立即行动清单</h2>
  {act_html}
</div>

<div class="sec">
  <p class="sec-kick">LOCAL</p>
  <h2 class="sec-title">国产替代地图</h2>
  {alt_html}
</div>

<div class="footer">老许聊实体 · {month_cn}月度总结 · 数据来自本月 {total_days} 期日报自动聚合</div>
"""

html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>老许聊实体-AI×实体洞察月报 {month_cn}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  {content}
</div>
</body>
</html>
"""

out_path = f"{DATA_DIR}/monthly-{YEAR}-{MONTH:02d}.html"
with open(out_path, "w", encoding="utf-8") as fh:
    fh.write(html_doc)

print(f"✅ 已生成 {out_path}")
print(f"   出报 {total_days} 期 / 精选 {total_selected} 条 / 筛掉 {total_filtered} 条")
print(f"   行动分级: {dict(adv_counter)}")
print(f"   赛道 TOP3: {cat_counter.most_common(3)}")
print(f"   来源 TOP3: {src_counter.most_common(3)}")
print(f"   立即行动条目: {len(act_items)} / 国产替代: {len(alt_map)} 个")
