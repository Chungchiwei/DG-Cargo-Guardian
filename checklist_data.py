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
INCIDENT_TYPE_TO_CODE = {
    "engine_room_fire":    "1-5",
    "deck_container_fire": "3-3",
    "hold_container_fire": "3-4",
    "cargo_leakage":       "3-5",
    "dg_fire_leakage":     "3-5-1",
    "container_overboard": "3-2",
}

# ── 自由問答關鍵字 → 檢查表編號（簡單比對，非 AI，找不到就不注入任何檢查表全文）──
KEYWORD_TO_CODE = [
    (("機艙失火", "機艙", "engine room fire"), "1-5"),
    (("甲板貨櫃失火", "甲板失火", "deck container"), "3-3"),
    (("貨艙貨櫃失火", "貨艙失火", "hold container"), "3-4"),
    (("危險貨櫃事故", "危險貨櫃失火", "危險貨櫃洩漏", "dangerous cargo"), "3-5-1"),
    (("貨櫃洩漏", "洩漏", "leakage"), "3-5"),
    (("貨櫃落海", "貨櫃傾倒", "container overboard"), "3-2"),
    (("人員落水", "man overboard", "mob"), "2-1"),
    (("人員受傷", "crew injured"), "2-2"),
    (("貨艙浸水", "flooding"), "3-1"),
    (("碰撞", "collision"), "1-2"),
    (("擱淺", "grounding"), "1-3"),
    (("電力故障", "black out", "blackout"), "1-8"),
    (("主機故障", "main engine breakdown"), "1-7"),
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
