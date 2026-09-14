# ============================================================
# 📋 checklist_data.py — 萬海航運官方緊急事故處理程序檢查表載入器
# ============================================================
#
# 資料來源與授權（見 docs/KNOWN_LIMITATIONS.md §7.7／§7.8）：
#   data/emergency_checklists.json 為使用者於 2026-09 直接提供的 17 份萬海航運
#   （WHL）官方緊急事故處理程序檢查表全文（.docx 原始檔逐字擷取，僅整理表格
#   結構，未改寫任何內容），涵蓋編號 1-1 ~ 3-6。這些屬公司內部程序文件，
#   使用者已明確確認可將內容送往外部 LLM 供應商（Perplexity）供 AI 自由問答／
#   事故分析引用（即明確同意作為先前 docs/INITIAL_SAFETY_AUDIT.md C-2 發現的
#   例外情形，僅限這 17 份检查表，不擴及公司其他未經同意的機密文件）。
#
#   2026-09 第二輪回饋：使用者原本也同意可在系統內建「緊急程序書」頁面本地
#   顯示全文，但後續改為「不用顯示出來，是要餵給AI判斷的時候會從裡面找資料，
#   船上直接看紙本就好了」——故該頁面已從 app.py 移除，本模組僅供 AI 背景
#   資料使用，不再對使用者介面顯示全文。
#   本模組僅負責讀取／查詢，不做任何內容改寫或判斷。

import json
import os

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "emergency_checklists.json")

_cache = None


def load_checklists() -> dict:
    """載入全部檢查表資料（含快取）。Returns: {code: {code, title_cn, title_en, source_file, sections}}"""
    global _cache
    if _cache is None:
        try:
            with open(_DATA_PATH, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _cache = {}
    return _cache


def get_checklist(code: str) -> dict | None:
    """依編號（例如 "3-3"）取得單一檢查表，查無則回傳 None。"""
    return load_checklists().get(code)


def list_checklist_options() -> list[tuple[str, str]]:
    """回傳 [(code, "編號 中文標題 English Title"), ...]，依編號排序，供 UI 選單使用。"""
    data = load_checklists()

    def _sort_key(code: str):
        parts = code.split("-")
        return tuple(int(p) for p in parts)

    out = []
    for code in sorted(data.keys(), key=_sort_key):
        c = data[code]
        out.append((code, f"{code}　{c['title_cn']} {c['title_en']}"))
    return out


def format_checklist_markdown(code: str) -> str:
    """將指定檢查表格式化為 Markdown 全文（供頁面顯示或 AI context 使用）。"""
    c = get_checklist(code)
    if not c:
        return f"（查無編號 {code} 的檢查表資料）"

    lines = [f"## {code} {c['title_cn']} / {c['title_en']}", ""]
    for section in c.get("sections", []):
        header = section.get("header", "").strip()
        if header:
            lines.append(f"**{header}**")
            lines.append("")
        for item in section.get("items", []):
            no = item.get("no", "").strip()
            text = item.get("text", "").strip()
            prefix = f"{no} " if no and no not in ("", "-") else ""
            lines.append(f"- {prefix}{text}")
        lines.append("")
    return "\n".join(lines)


# ── 事故類型 → 檢查表編號對照（供 AI 事故分析頁選單與自由問答關鍵字比對使用）──
#
# 2026-09 第十輪回饋（見 docs/KNOWN_LIMITATIONS.md §7.16）：使用者重新上傳
# 同一批 17 份官方檢查表後，要求「確定這幾個程序書都有被加進去幫助AI判斷
# 事故」。審查發現 data/emergency_checklists.json 雖已有全部 17 個編號的
# 完整內容，但本對照表先前只涵蓋其中 6 個（皆為危險品貨櫃相關類型），其餘
# 11 個編號（1-1／1-2／1-3／1-4／1-6／1-7／1-8／2-1／2-2／3-1／3-6）完全
# 沒有對應的 incident_type，導致「AI 事故分析」頁面的事故類型下拉選單無法
# 選取這些檢查表，即使資料本身早已存在。現已補齊全部 17 個編號的對照，
# 讓「AI 事故分析」頁面能真正涵蓋全部 17 份已授權檢查表（見 §7.16.1）。
INCIDENT_TYPE_TO_CODE = {
    "hull_damage":           "1-1",
    "collision":             "1-2",
    "grounding":             "1-3",
    "touch_bottom":          "1-4",
    "engine_room_fire":      "1-5",
    "mooring_rope_fouling":  "1-6",
    "main_engine_breakdown": "1-7",
    "blackout":              "1-8",
    "man_overboard":         "2-1",
    "crew_injured":          "2-2",
    "flooding_cargo_hold":   "3-1",
    "container_overboard":   "3-2",
    "deck_container_fire":   "3-3",
    "hold_container_fire":   "3-4",
    "cargo_leakage":         "3-5",
    "dg_fire_leakage":       "3-5-1",
    "gantry_crane_damage":   "3-6",
}

# ── 自由問答關鍵字 → 檢查表編號（簡單比對，非 AI，找不到就不注入任何檢查表全文）──
#
# 2026-09 第十輪回饋：原本缺少 1-1（船殼受損）、1-4（觸底）、1-6（纜繩事故）
# 三個編號的關鍵字項目，導致這 3 份檢查表連「自由問答」的關鍵字比對都完全
# 抓不到（其餘 14 份原本就可透過關鍵字比對找到）。現已補齊，17 份檢查表
# 全部都能被自由問答的關鍵字比對找到（見 §7.16.1）。
KEYWORD_TO_CODE = [
    (("船殼受損", "船體受損", "hull damage"), "1-1"),
    (("碰撞", "collision"), "1-2"),
    (("擱淺", "grounding"), "1-3"),
    (("觸底", "touch bottom"), "1-4"),
    (("機艙失火", "機艙", "engine room fire"), "1-5"),
    (("纜繩", "螺旋槳纏繞", "mooring rope", "rope fouling"), "1-6"),
    (("主機故障", "main engine breakdown"), "1-7"),
    (("電力故障", "black out", "blackout"), "1-8"),
    (("人員落水", "man overboard", "mob"), "2-1"),
    (("人員受傷", "crew injured"), "2-2"),
    (("貨艙浸水", "flooding"), "3-1"),
    (("貨櫃落海", "貨櫃傾倒", "container overboard"), "3-2"),
    (("甲板貨櫃失火", "甲板失火", "deck container"), "3-3"),
    (("貨艙貨櫃失火", "貨艙失火", "hold container"), "3-4"),
    (("貨櫃洩漏", "洩漏", "leakage"), "3-5"),
    (("危險貨櫃事故", "危險貨櫃失火", "危險貨櫃洩漏", "dangerous cargo"), "3-5-1"),
    (("吊車", "gantry crane"), "3-6"),
]


def match_checklist_code_by_text(text: str) -> str | None:
    """依自由文字關鍵字比對可能相關的檢查表編號（純字串比對，非 AI，找不到回傳 None）。"""
    if not text:
        return None
    t = text.lower()
    for keywords, code in KEYWORD_TO_CODE:
        for kw in keywords:
            if kw.lower() in t:
                return code
    return None
