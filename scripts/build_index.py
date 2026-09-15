"""生成 GitHub Pages 首页 + 历史日报侧边导航 + 行动分级导航

- 扫描 news-data/daily-*.html，最新一份作为首页 index.html
- 每份日报侧栏注入"📅 历史日报"导航：
  - 按月分组（如 2026年8月）
  - 默认显示最近 6 条，更早的折叠在"更早日报 ▾"
  - 顶部"🏠 返回首页"按钮
- 每份日报侧栏注入"⚡ 行动分级"导航（旧版 HTML 无此功能时补注入）：
  - 按 立即行动/小成本试用/观望/暂不跟进 分组，点击直达该分级第一张新闻卡片
  - 新版 HTML 由 html_render.py 生成自带，此处检测到即跳过（幂等）
- 幂等：历史导航带 <!--ARC_NAV--> 标记，行动分级带 class="adv-nav"，均不重复注入

用法: uv run python scripts/build_index.py
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.html_render import _ADVICE_EMOJI, adv_nav_html  # noqa: E402

INDEX = "index.html"
MAX_VISIBLE = 6  # 默认直接显示的最近日报条数，其余折叠

NAV_BEGIN = "<!--ARC_NAV-->"
NAV_END = "<!--/ARC_NAV-->"

ADV_CLS_TO_NAME = {
    "act": "立即行动",
    "try": "小成本试用",
    "watch": "观望",
    "skip": "暂不跟进",
}

NAV_STYLE = """
<style>
.arc-nav{margin:18px 4px 0;padding:10px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px}
.arc-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;gap:8px}
.arc-title{color:#c4ed1a;font-size:12.5px;font-weight:600;letter-spacing:.5px;white-space:nowrap}
.arc-home{color:#8fa6ff;font-size:12px;text-decoration:none;border:1px solid rgba(79,109,255,.5);border-radius:6px;padding:2px 8px;transition:all .15s;white-space:nowrap}
.arc-home:hover{background:rgba(79,109,255,.15);color:#fff}
.arc-month-label{color:#6b6f7a;font-size:11px;margin:9px 0 4px;letter-spacing:.5px}
.arc-list{display:flex;flex-direction:column;gap:4px}
.arc-link{color:#9aa7c7;font-size:13px;text-decoration:none;padding:4px 10px;border-radius:6px;border:1px solid transparent;transition:all .15s}
.arc-link:hover{background:rgba(79,109,255,.12);color:#fff}
.arc-link.active{color:#fff;background:rgba(79,109,255,.18);border-color:rgba(79,109,255,.55);border-left:3px solid #4f6dff}
.arc-more{margin-top:6px;border:none;background:none;padding:0}
.arc-more summary{cursor:pointer;color:#888;font-size:12px;padding:4px 10px;list-style:none;border-radius:6px;transition:all .15s}
.arc-more summary::-webkit-details-marker{display:none}
.arc-more summary:hover{color:#fff}
@media (max-width:860px){
  .arc-nav{margin:8px 4px 0}
  .arc-head{flex-wrap:wrap}
  .arc-list{flex-direction:row;overflow-x:auto;padding-bottom:4px}
  .arc-month-label{flex-shrink:0;margin:2px 6px 0 0}
  .arc-link{flex-shrink:0;border:1px solid #2a2a2a}
}
</style>
"""


def parse_date(path: str):
    m = re.search(r"daily-(\d{4})-(\d{2})-(\d{2})\.html$", path.replace("\\", "/"))
    return m.groups() if m else None


def parse_monthly(path: str):
    m = re.search(r"monthly-(\d{4})-(\d{2})\.html$", path.replace("\\", "/"))
    return m.groups() if m else None


# 月度总结入口：扫描 news-data/monthly-*.html，作为「历史日报」导航下方的补充区块
# 月报页面自身不带侧栏，所以这里同时给首页与所有日报注入入口，方便读者发现
MONTHLY_STYLE = """
<style>
.mm-nav{margin:14px 4px 0;padding:10px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px}
.mm-title{color:#c0392b;font-size:12.5px;font-weight:600;letter-spacing:.5px;margin-bottom:6px;display:block}
.mm-list{display:flex;flex-direction:column;gap:4px}
.mm-link{color:#9aa7c7;font-size:13px;text-decoration:none;padding:4px 10px;border-radius:6px;border:1px solid transparent;transition:all .15s}
.mm-link:hover{background:rgba(192,57,43,.12);color:#fff}
@media (max-width:860px){
  .mm-list{flex-direction:row;overflow-x:auto;padding-bottom:4px}
  .mm-link{flex-shrink:0;border:1px solid #2a2a2a}
}
</style>
"""


def parse_social(path: str):
    m = re.search(r"social-(\d{4})-(\d{2})-(\d{2})\.html$", path.replace("\\", "/"))
    return m.groups() if m else None


# 图文素材入口：扫描 news-data/social-*.html（抖音图文预览页）
# 这条通道是给「发布的人」用的，读者不关心，所以放侧栏最底部、只列最近几期
SOCIAL_STYLE = """
<style>
.sc-nav{margin:10px 4px 0;padding:10px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px}
.sc-title{color:#8a8880;font-size:12.5px;font-weight:600;letter-spacing:.5px;margin-bottom:6px;display:block}
.sc-list{display:flex;flex-direction:column;gap:4px}
.sc-link{color:#8a8880;font-size:13px;text-decoration:none;padding:4px 10px;border-radius:6px;transition:all .15s}
.sc-link:hover{background:rgba(192,57,43,.12);color:#fff}
.sc-new{color:#c0392b;font-size:11px;margin-left:6px}
@media (max-width:860px){
  .sc-list{flex-direction:row;overflow-x:auto;padding-bottom:4px}
  .sc-link{flex-shrink:0;border:1px solid #2a2a2a}
}
</style>
"""


def social_block(prefix: str, limit: int = 5) -> str:
    """生成「📱 图文素材」侧栏区块。prefix 与 arc-nav 一致：首页 'news-data/'，日报 ''。"""
    files = sorted(glob.glob("news-data/social-*.html"), reverse=True)[:limit]
    items = []
    for f in files:
        d = parse_social(f)
        if d:
            items.append((f"{d[0]}-{d[1]}-{d[2]}",
                          f"{int(d[1])}/{int(d[2])}",
                          os.path.basename(f).replace("\\", "/")))
    if not items:
        return ""
    newest = items[0][0]
    links = "".join(
        f'<a class="sc-link" href="{prefix}{fn}">{label} 图文'
        + ('<span class="sc-new">最新</span>' if key == newest else "")
        + "</a>"
        for key, label, fn in items
    )
    return SOCIAL_STYLE + (
        f'<div class="sc-nav" id="sc-nav">'
        f'<span class="sc-title">📱 图文素材（发布取图用）</span>'
        f'<div class="sc-list">{links}</div></div>'
    )


def monthly_block(prefix: str) -> str:
    """生成「📊 月度总结」侧栏区块。prefix 与 arc-nav 一致：首页用 'news-data/'，日报用 ''。"""
    items = []
    for f in sorted(glob.glob("news-data/monthly-*.html"), reverse=True):
        d = parse_monthly(f)
        if d:
            items.append((d[0], d[1], os.path.basename(f).replace("\\", "/")))
    if not items:
        return ""
    links = "".join(
        f'<a class="mm-link" href="{prefix}{fn}">{y}年{int(mo)}月 月报</a>'
        for y, mo, fn in items
    )
    return MONTHLY_STYLE + (
        f'<div class="mm-nav" id="mm-nav">'
        f'<span class="mm-title">📊 月度总结</span>'
        f'<div class="mm-list">{links}</div></div>'
    )


# 旧版日报补注入"行动分级"导航时附带的样式与脚本（与 html_render.py 一致）
ADV_STYLE = """
<style>
.adv-nav { display: flex; flex-direction: column; gap: 4px; margin-top: 14px; padding-top: 14px; border-top: 1px solid #2a2a2a; }
.adv-label { color: #666666; font-size: 11px; letter-spacing: 1.5px; padding: 0 12px 4px; }
.adv-chip {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; border-radius: 8px;
  background: transparent; border: 1px solid transparent; border-left: 3px solid transparent;
  color: #666666; font-size: 13px; text-decoration: none; transition: all .15s;
}
.adv-chip:hover { background: rgba(255,255,255,.04); color: #cccccc; }
.adv-chip.act { border-left-color: rgba(196,237,26,.6); }
.adv-chip.try { border-left-color: rgba(184,122,255,.6); }
.adv-chip.watch { border-left-color: rgba(79,109,255,.7); }
.adv-chip.skip { border-left-color: rgba(119,119,119,.6); }
.adv-chip.active { background: rgba(255,255,255,.06); color: #ffffff; font-weight: 700; }
.adv-chip .adv-n {
  color: #888888; background: rgba(255,255,255,.08); border-radius: 20px;
  padding: 0 8px; font-size: 12px; font-weight: 600; min-width: 22px; text-align: center;
}
.adv-chip.act .adv-n { color: #c4ed1a; background: rgba(196,237,26,.1); }
.adv-chip.try .adv-n { color: #d8c4f5; background: rgba(184,122,255,.12); }
.adv-chip.watch .adv-n { color: #8fa6ff; background: rgba(79,109,255,.12); }
.adv-chip.skip .adv-n { color: #9a9a9a; background: rgba(119,119,119,.1); }
.adv-chip.active .adv-n { background: rgba(255,255,255,.16); }
.card { scroll-margin-top: 18px; }
@media (max-width:860px){
  .adv-nav { flex-direction: row; flex-wrap: wrap; align-items: center; }
  .adv-label { width: 100%; }
}
</style>
"""

# 完整页面脚本（copyWx + 分类高亮 + 行动分级过滤）。必须放 body 末尾执行。
# 因清理旧版日报的注入脚本时会整块移除原 <script>（含 copyWx），这里一次性补齐完整功能。
ADV_SCRIPT = """
<script>
function copyWx(el){
  var text = "xuyang2946";
  var tip = el.querySelector(".tip");
  var ok = function(){ if (tip){ tip.textContent = "已复制 ✓"; setTimeout(function(){ tip.textContent = "点击复制"; }, 2000); } };
  var fail = function(){ if (tip) tip.textContent = "复制失败，请手动添加"; };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(ok).catch(fail);
  } else {
    var ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); ok(); } catch (e) { fail(); }
    document.body.removeChild(ta);
  }
}
(function(){
  var chips = document.querySelectorAll(".cat-chip");
  function setActive(hash){ chips.forEach(function(c){ c.classList.toggle("active", c.getAttribute("href") === hash); }); }
  chips.forEach(function(c){
    c.addEventListener("click", function(){
      setActive(c.getAttribute("href"));
      if (window.__advApply) window.__advApply("all");  // 点分类时恢复全部分级，避免看到空分类
      document.querySelectorAll(".adv-chip").forEach(function(x){ x.classList.toggle("active", x.getAttribute("data-cls") === "all"); });
    });
  });
  window.addEventListener("hashchange", function(){ setActive(location.hash); });
  setActive(location.hash);
})();
(function(){
  var chips = document.querySelectorAll(".adv-chip");
  var cards = document.querySelectorAll(".card[data-adv]");
  var groups = document.querySelectorAll(".cat-group");
  function apply(cls){
    cards.forEach(function(c){ c.style.display = (cls === "all" || c.getAttribute("data-adv") === cls) ? "" : "none"; });
    groups.forEach(function(s){
      var any = false;
      s.querySelectorAll(".card").forEach(function(c){ if (c.style.display !== "none") any = true; });
      s.style.display = any ? "" : "none";
    });
  }
  window.__advApply = apply;
  chips.forEach(function(c){
    c.addEventListener("click", function(){
      chips.forEach(function(x){ x.classList.toggle("active", x === c); });
      apply(c.getAttribute("data-cls"));
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });
  apply("all");
  chips.forEach(function(c){ c.classList.toggle("active", c.getAttribute("data-cls") === "all"); });
})();
</script>
"""


ADV_BEGIN = "<!--ADV_NAV-->"
ADV_END = "<!--/ADV_NAV-->"

# 打赏：右侧独立大卡片（桌面端）+ 侧栏小卡片（移动端），图片按目录区分前缀
DONATE_STYLE = """
<style>
.page { max-width: 1400px; }
/* 右侧打赏列（桌面端独立一列，sticky 固定） */
.donate-panel {
  position: sticky; top: 0;
  flex-shrink: 0; width: 260px;
  height: 100vh; box-sizing: border-box;
  padding: 28px 8px 24px;
  overflow-y: auto;
}
.donate-panel .donate {
  margin: 0 4px; padding: 22px 14px;
  background: #1a1a1a;
  border: 1px solid rgba(196,237,26,.15);
  border-radius: 14px; text-align: center;
}
.donate-panel .donate-title { font-size: 16px; font-weight: 700; margin: 0 0 12px; }
.donate-panel .donate-desc { font-size: 13.5px; line-height: 1.7; margin: 0 0 16px; text-align: left; }
.donate-panel .donate-qr {
  display: block; width: 200px; height: 200px;
  margin: 0 auto; padding: 6px;
  border: 1px solid #3a3a3a; border-radius: 10px;
  background: #fff; box-sizing: border-box; object-fit: contain;
}
.donate-panel .donate-tip { font-size: 13px; margin: 12px 0 0; }
/* 侧栏小卡片（不再注入，保留样式兜底） */
.donate{margin:18px 4px 0;padding:14px;background:#1a1a1a;border:1px solid rgba(196,237,26,.15);border-radius:12px;text-align:center}
.donate-title{color:#c4ed1a;font-size:14px;font-weight:700;letter-spacing:.5px;margin:0 0 8px}
.donate-desc{color:#888;font-size:12.5px;line-height:1.7;margin:0 0 12px;text-align:left}
.donate-qr{display:block;width:118px;height:118px;margin:0 auto;border-radius:8px;border:1px solid #2a2a2a;object-fit:contain;background:#fff;padding:4px;box-sizing:border-box}
.donate-tip{color:#6b6f7a;font-size:12px;margin:10px 0 0;letter-spacing:.5px}
/* 移动端浮动打赏按钮 + 二维码弹窗 */
.donate-fab,.donate-modal{display:none}
@media (max-width:860px){
  .donate-fab{
    display:flex;position:fixed;right:14px;bottom:18px;z-index:998;
    align-items:center;gap:6px;
    background:linear-gradient(135deg,#c4ed1a,#9cc70f);
    color:#121212;font-weight:700;font-size:14px;
    padding:12px 18px;border:none;border-radius:50px;
    box-shadow:0 6px 20px rgba(0,0,0,.45);cursor:pointer;
  }
  .donate-modal{
    display:none;position:fixed;inset:0;z-index:1000;
    background:rgba(0,0,0,.72);
    align-items:center;justify-content:center;padding:24px;
  }
  .donate-modal.open{display:flex}
  .donate-modal-box{background:#1a1a1a;border:1px solid rgba(196,237,26,.2);border-radius:16px;padding:24px 20px;text-align:center;position:relative;max-width:320px;width:100%}
  .donate-modal-close{position:absolute;top:10px;right:12px;background:none;border:none;color:#888;font-size:18px;cursor:pointer;padding:4px}
  .donate-modal-box .donate-title{font-size:16px;margin:0 0 10px}
  .donate-modal-box .donate-desc{font-size:13px;line-height:1.7;margin:0 0 12px;text-align:left}
  .donate-modal-box .donate-qr{width:200px;height:200px;margin:0 auto;display:block;border-radius:10px;border:1px solid #3a3a3a;background:#fff;padding:6px;box-sizing:border-box;object-fit:contain}
  .donate-modal-box .donate-tip{font-size:12px;margin:10px 0 0}
}
/* 桌面端（≥1101px）只显示右侧大卡片 */
@media (min-width:1101px){ .donate-inner{ display:none !important; } }
@media (max-width:1100px){ .donate-panel{ display:none !important; } }
@media (max-width:860px){
  .donate{margin:8px 4px 0}
  .donate-qr{width:92px;height:92px}
}
</style>
"""


DONATE_BEGIN = "<!--DONATE-->"
DONATE_END = "<!--/DONATE-->"

# 移动端导航抽屉：顶栏收成一条细栏（品牌 + ☰ 按钮），点击展开全屏导航
MENU_BTN_BEGIN = "<!--MENU_BTN-->"
MENU_BTN_END = "<!--/MENU_BTN-->"
MENU_JS_BEGIN = "<!--MENU_JS-->"
MENU_JS_END = "<!--/MENU_JS-->"

MENU_BTN = (
    MENU_BTN_BEGIN
    + '<button class="menu-toggle" aria-label="菜单">☰</button>'
    + MENU_BTN_END
)

MENU_JS = (
    MENU_JS_BEGIN
    + """
<style>
.menu-toggle{display:none}
@media (max-width:860px){
  .sidebar{padding:6px 12px !important;display:flex !important;flex-direction:row !important;align-items:center;gap:10px;background:var(--bg,#121212);z-index:20}
  .brand{display:flex !important;align-items:baseline;gap:8px;margin:0 !important;padding:0 !important;font-size:16px;line-height:1;white-space:nowrap}
  .brand .brand-sub{font-size:11px;margin:0}
  .menu-toggle{display:block;margin-left:auto;background:rgba(255,255,255,.04);border:1px solid #2a2a2a;border-radius:8px;color:#e0e0e0;font-size:17px;line-height:1;padding:6px 12px;cursor:pointer;flex-shrink:0}
  .cat-nav,.adv-nav,.arc-nav,.donate.donate-inner{display:none !important}
  .sidebar.menu-open{
    position:fixed;inset:0;width:100%;height:100%;z-index:999;
    display:flex !important;flex-direction:column !important;align-items:stretch;
    padding:16px 12px 30px;overflow-y:auto;background:#121212;gap:0;
  }
  .sidebar.menu-open .brand{display:flex !important;align-items:center;width:100%;margin:0 0 12px !important}
  .sidebar.menu-open .menu-toggle{position:fixed;top:12px;right:12px;margin:0}
  .sidebar.menu-open .cat-nav{display:flex !important;flex-direction:column;align-items:stretch;overflow:visible}
  .sidebar.menu-open .adv-nav{display:flex !important;flex-direction:column;align-items:stretch}
  .sidebar.menu-open .arc-nav{display:block !important}
  .sidebar.menu-open .donate.donate-inner{display:block !important;margin:16px 4px 0}
  .sidebar.menu-open .arc-list{flex-direction:column;overflow:visible}
  .sidebar.menu-open .arc-month-label{flex-shrink:1;margin:9px 0 4px}
  .sidebar.menu-open .adv-label{width:auto}
}
</style>
<script>
(function(){
  var btn=document.querySelector(".menu-toggle"), side=document.querySelector(".sidebar");
  if(!btn||!side)return;
  function close(){ side.classList.remove("menu-open"); btn.textContent="☰"; document.body.style.overflow=""; }
  btn.addEventListener("click",function(){
    var open=side.classList.toggle("menu-open");
    btn.textContent=open?"✕":"☰";
    document.body.style.overflow=open?"hidden":"";
  });
  document.querySelectorAll(".adv-chip,.cat-chip,.arc-link").forEach(function(c){
    c.addEventListener("click",close);
  });
  window.addEventListener("resize",function(){
    if(window.innerWidth>860&&side.classList.contains("menu-open")){ close(); }
  });
})();
</script>
"""
    + MENU_JS_END
)


def inject_menu(html: str) -> str:
    """移动端导航抽屉：细顶栏 + ☰ 按钮 + 全屏菜单。幂等。"""
    # 清理旧注入
    html = re.sub(re.escape(MENU_BTN_BEGIN) + r".*?" + re.escape(MENU_BTN_END), "", html, flags=re.S)
    html = re.sub(re.escape(MENU_JS_BEGIN) + r".*?" + re.escape(MENU_JS_END), "", html, flags=re.S)
    # ☰ 按钮插到品牌 div 之后（兄弟元素，才能靠 margin-left:auto 推到顶栏右侧）
    m = re.search(r'<div class="brand">.*?</div>', html, flags=re.S)
    if m:
        html = html[: m.end()] + MENU_BTN + html[m.end():]
    # 样式 + 脚本插到 </body> 前
    bidx = html.rfind("</body>")
    if bidx != -1:
        html = html[:bidx] + MENU_JS + html[bidx:]
    return html

DONATE_PANEL_BEGIN = "<!--DONATE_PANEL-->"
DONATE_PANEL_END = "<!--/DONATE_PANEL-->"


def _donate_card(prefix: str, extra_cls: str) -> str:
    return (
        '<div class="donate ' + extra_cls + '">'
        + '<p class="donate-title">这碗胡辣汤，老许请客，你买单</p>'
        + '<p class="donate-desc">日报每天人工+AI 逐条研判几百条资讯，免费送到你手里。'
          '觉得值，一碗胡辣汤就是最大的支持——明天老许接着干。</p>'
        + f'<img class="donate-qr" src="{prefix}donate.png" alt="打赏二维码">'
        + '<p class="donate-tip">微信 / 支付宝 扫码支持</p>'
        + "</div>"
    )


def inject_donate(html: str, prefix: str) -> str:
    """注入打赏入口：桌面端右侧大卡片（sticky）+ 移动端浮动打赏按钮与二维码弹窗。"""
    # 清理旧注入（含历史残缺块）
    html = re.sub(r"</div>\s*<!--DONATE-->", "<!--DONATE-->", html)
    html = re.sub(re.escape(DONATE_BEGIN) + r".*?" + re.escape(DONATE_END), "", html, flags=re.S)
    html = re.sub(re.escape(DONATE_PANEL_BEGIN) + r".*?" + re.escape(DONATE_PANEL_END), "", html, flags=re.S)
    html = re.sub(r'<aside class="donate-panel">.*?</aside>', "", html, flags=re.S)
    html = re.sub(r'<button class="donate-fab".*?</button>', "", html, flags=re.S)
    html = re.sub(r'<div class="donate-modal">.*?</div>\s*(?=</body>)', "", html, flags=re.S)
    html = re.sub(r'<div class="donate donate-inner">.*?</div>', "", html, flags=re.S)
    html = re.sub(r'<div class="donate">.*?</div>', "", html, flags=re.S)
    html = re.sub(r'<div class="donate-(?:title|desc|tip)">.*?</div>', "", html, flags=re.S)
    html = re.sub(r'<img class="donate-qr"[^>]*>', "", html)
    html = re.sub(r"<style>.*?\.donate-panel.*?</style>", "", html, flags=re.S)
    html = re.sub(r"<style>.*?\.donate\s*\{.*?</style>", "", html, flags=re.S)

    panel = (
        DONATE_PANEL_BEGIN
        + DONATE_STYLE
        + '<aside class="donate-panel">'
        + _donate_card(prefix, "")
        + "</aside>"
        + DONATE_PANEL_END
    )
    fab = (
        DONATE_BEGIN
        + '<button class="donate-fab" aria-label="打赏">☕ 请老许喝碗胡辣汤</button>'
        + '<div class="donate-modal">'
        + '<div class="donate-modal-box">'
        + '<button class="donate-modal-close" aria-label="关闭">✕</button>'
        + '<p class="donate-title">这碗胡辣汤，老许请客，你买单</p>'
        + '<p class="donate-desc">日报每天人工+AI 逐条研判几百条资讯，免费送到你手里。'
          '觉得值，一碗胡辣汤就是最大的支持——明天老许接着干。</p>'
        + f'<img class="donate-qr" src="{prefix}donate.png" alt="打赏二维码">'
        + '<p class="donate-tip">微信 / 支付宝 扫码支持</p>'
        + "</div></div>"
        + '<script>'
        + '(function(){var f=document.querySelector(".donate-fab"),m=document.querySelector(".donate-modal");'
        + 'if(!f||!m)return;'
        + 'f.addEventListener("click",function(){m.classList.add("open");});'
        + 'var c=m.querySelector(".donate-modal-close");'
        + 'if(c)c.addEventListener("click",function(){m.classList.remove("open");});'
        + 'm.addEventListener("click",function(e){if(e.target===m)m.classList.remove("open");});'
        + '})();'
        + "</script>"
        + DONATE_END
    )

    # 右侧大卡片（含样式）：插到 </main> 后（.page 闭合 </div> 前）
    midx = html.rfind("</main>")
    if midx == -1:
        return html
    html = html[: midx + len("</main>")] + panel + html[midx + len("</main>"):]
    # 浮动按钮 + 弹窗 + 脚本：插到 </body> 前
    bidx = html.rfind("</body>")
    if bidx != -1:
        html = html[:bidx] + fab + html[bidx:]
    return html


def inject_adv(html: str) -> str:
    """给日报补注入/重建"行动分级"导航（过滤 + 分级图标）。

    - 给每张卡片加锚点 id + data-adv（用于点击过滤）
    - 评分数字替换为行动分级图标
    - 侧栏插入行动分级导航（含"全部新闻"），脚本放 body 末尾
    - 幂等/可升级：先清理旧注入（标记块/旧样式/旧脚本/卡片旧属性）再重建
    """
    # --- 1) 清理旧注入，保证可重复运行且能升级旧版本 ---
    html = re.sub(re.escape(ADV_BEGIN) + r".*?" + re.escape(ADV_END), "", html, flags=re.S)
    # 移除所有已存在的行动分级导航块（新版 html_render 自带/旧版注入均无标记，按结构特征清）
    html = re.sub(r'<nav class="adv-nav">.*?</nav>', "", html, flags=re.S)
    html = re.sub(r"<style>\s*\.adv-nav\s*\{.*?</style>", "", html, flags=re.S)
    # 只删除"行动分级"脚本块（特征：包含 .adv-chip 选择器），不影响页面原有脚本
    html = re.sub(
        r"<script>(?:(?!</script>).)*\.adv-chip(?:(?!</script>).)*</script>",
        "",
        html,
        flags=re.S,
    )
    # 还原所有卡片为干净开标签（去掉旧 id/data-adv 属性）
    html = re.sub(r'<div class="card"[^>]*>', '<div class="card">', html)

    # --- 2) 卡片加锚点 id + data-adv ---
    starts = [m.end() for m in re.finditer(r'<div class="card">', html)]
    if not starts:
        return html

    ids: dict = {}
    counts: dict = {}
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(html)
        m = re.search(r'<span class="badge advice (act|try|watch|skip)">', html[s:e])
        if not m:
            continue
        cls = m.group(1)
        counts[cls] = counts.get(cls, 0) + 1
        ids[i] = f'id="adv-{cls}-{counts[cls]}" data-adv="{cls}"'
    # 从后往前应用替换，避免索引偏移
    for i in range(len(starts) - 1, -1, -1):
        if i not in ids:
            continue
        html = html[: starts[i] - 18] + f'<div class="card" {ids[i]}>' + html[starts[i]:]

    # --- 3) 评分数字 → 行动分级图标（评分保留在数据层，页面不显示分数） ---
    html = re.sub(
        r'<span class="score (act|try|watch|skip)">\d+</span>',
        lambda m: (
            f'<span class="score {m.group(1)}" title="行动分级">'
            f"{_ADVICE_EMOJI[m.group(1)]}</span>"
        ),
        html,
    )

    # --- 4) 插入导航（含样式）与脚本 ---
    advice_cnt = {
        name: counts[cls]
        for cls, name in ADV_CLS_TO_NAME.items()
        if counts.get(cls)
    }
    nav = adv_nav_html(advice_cnt)
    if not nav:
        return html

    block = ADV_BEGIN + ADV_STYLE + nav + ADV_END
    idx = html.find("</nav>")
    if idx == -1:
        return html
    html = html[: idx + 6] + block + html[idx + 6:]
    bidx = html.rfind("</body>")
    if bidx != -1:
        html = html[:bidx] + ADV_SCRIPT + html[bidx:]
    return html


def nav_html(prefix: str, home: str, files: list[str], current: str) -> str:
    """生成历史导航。prefix: 链接前缀(index 用 news-data/，日报用空)；home: 返回首页链接"""
    items = []
    for f in reversed(files):
        d = parse_date(f)
        if not d:
            continue
        y, mo, day = d
        href = prefix + os.path.basename(f).replace("\\", "/")
        active = " active" if f == current else ""
        items.append((y, mo, day, href, active))

    if not items:
        return ""

    def render(rows) -> str:
        parts, last = [], None
        for y, mo, day, href, active in rows:
            key = f"{y}-{mo}"
            if key != last:
                parts.append(f'<div class="arc-month-label">{y}年{int(mo)}月</div>')
                last = key
            parts.append(f'<a class="arc-link{active}" href="{href}">{mo}/{day}</a>')
        return "".join(parts)

    body = (
        f'<div class="arc-nav" id="arc-nav">'
        f'<div class="arc-head"><span class="arc-title">📅 历史日报</span>'
        f'<a class="arc-home" href="{home}">🏠 返回首页</a></div>'
        f'<div class="arc-list">{render(items[:MAX_VISIBLE])}</div>'
    )
    if len(items) > MAX_VISIBLE:
        body += (
            f'<details class="arc-more"><summary>更早日报 ▾</summary>'
            f'<div class="arc-list">{render(items[MAX_VISIBLE:])}</div>'
            f"</details>"
        )
    body += "</div>"
    body += monthly_block(prefix)
    body += social_block(prefix)
    return NAV_STYLE + body


def inject(html: str, prefix: str, home: str, files: list[str], current: str) -> str:
    nav = NAV_BEGIN + nav_html(prefix, home, files, current) + NAV_END
    if NAV_BEGIN in html:
        # 已注入过：整体替换（幂等）
        return re.sub(re.escape(NAV_BEGIN) + r".*?" + re.escape(NAV_END),
                      lambda _: nav, html, flags=re.S)
    # 首次注入：放到侧栏分类导航之后
    for marker in ("</nav>", "</aside>"):
        idx = html.find(marker)
        if idx != -1:
            return html[: idx + len(marker)] + nav + html[idx + len(marker):]
    return html  # 找不到注入点，原样返回


def main() -> int:
    files = sorted(glob.glob("news-data/daily-*.html"))
    if not files:
        print("❌ 未找到日报文件 news-data/daily-*.html")
        return 1

    latest = files[-1]

    # 1) 所有日报注入侧栏导航（含最新一份，保证任意日期页都能返回首页/切换日期）
    for f in files:
        html = open(f, encoding="utf-8").read()
        new = inject(html, prefix="", home="../index.html", files=files, current=f)
        new = inject_adv(new)
        new = inject_donate(new, "../")
        new = inject_menu(new)
        if new != html:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(new)
            print(f"↪ 已注入导航: {f}")

    # 2) 最新日报 -> 首页 index.html（index 版导航：链接带 news-data/ 前缀，返回首页指向自身）
    html = open(latest, encoding="utf-8").read()
    html = inject(html, prefix="news-data/", home="index.html", files=files, current=latest)
    html = inject_adv(html)
    html = inject_donate(html, "")
    html = inject_menu(html)
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ 首页已生成: {INDEX}（最新日报 {latest}，历史 {len(files) - 1} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
