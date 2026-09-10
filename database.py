# ============================================================
# 📦 database.py — IMDG 危險品資料庫讀取模組（強化版）
# ============================================================

import json
import os
import re
from typing import Optional

# ── 資料庫路徑 ───────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "imdg_database.json")


# ══════════════════════════════════════════════════════════════
# 📂 資料庫載入（加入快取避免重複 I/O）
# ══════════════════════════════════════════════════════════════
_db_cache: Optional[dict] = None

def load_database(force_reload: bool = False) -> dict:
    """
    載入 IMDG 資料庫，回傳完整字典。
    使用記憶體快取，避免每次查詢都重新讀取檔案。

    Args:
        force_reload: 強制重新載入（資料庫更新時使用）
    """
    global _db_cache
    if _db_cache is not None and not force_reload:
        return _db_cache

    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            _db_cache = json.load(f)
            print(f"✅ 資料庫載入成功，共 {len(_db_cache)} 筆資料")
            return _db_cache
    except FileNotFoundError:
        print(f"❌ 找不到資料庫檔案：{DB_PATH}")
        _db_cache = {}
        return {}
    except json.JSONDecodeError as e:
        print(f"❌ 資料庫格式錯誤：{e}")
        _db_cache = {}
        return {}


def reload_database() -> dict:
    """強制重新載入資料庫（供外部呼叫）"""
    return load_database(force_reload=True)


# ══════════════════════════════════════════════════════════════
# 🔧 UN 號碼標準化工具
# ══════════════════════════════════════════════════════════════
def normalize_un_number(un_number: str) -> str:
    """
    標準化 UN 號碼輸入格式為 "UN1234"

    支援輸入格式：
    - "1203"、"UN1203"、"un1203"、" UN1203 "
    - "UN 1203"（含空格）

    Returns:
        標準化後的 UN 號碼字串，例如 "UN1203"
    """
    un = un_number.strip().upper().replace(" ", "")
    if not un.startswith("UN"):
        un = f"UN{un}"
    # 驗證格式：UN + 4位數字
    if not re.match(r"^UN\d{4}$", un):
        raise ValueError(f"無效的 UN 號碼格式：{un_number}（應為4位數字，例如 UN1203）")
    return un


def is_valid_un_number(un_number: str) -> bool:
    """快速驗證 UN 號碼格式是否合法"""
    try:
        normalize_un_number(un_number)
        return True
    except ValueError:
        return False


# ══════════════════════════════════════════════════════════════
# 🔍 依 UN 號碼查詢
# ══════════════════════════════════════════════════════════════
def get_by_un_number(un_number: str) -> Optional[dict]:
    """
    依 UN 號碼查詢危險品完整資料。

    Args:
        un_number: UN 號碼，支援 "1203" 或 "UN1203" 格式

    Returns:
        危險品資料字典（含 un_number 欄位），找不到則回傳 None
    """
    try:
        normalized = normalize_un_number(un_number)
    except ValueError as e:
        print(f"⚠️ {e}")
        return None

    db = load_database()
    result = db.get(normalized)

    if result:
        entry = result.copy()
        entry["un_number"] = normalized
        entry = _fill_missing_fields(entry)
        return entry

    return None


def get_by_un_number_fuzzy(un_number: str) -> list:
    """
    模糊查詢 UN 號碼（部分匹配）。
    例如輸入 "12" 會回傳所有 UN12xx 的結果。

    Args:
        un_number: 部分 UN 號碼字串

    Returns:
        符合條件的危險品列表
    """
    db = load_database()
    keyword = un_number.strip().upper().replace("UN", "")
    results = []

    for un_num, data in db.items():
        if keyword in un_num.replace("UN", ""):
            entry = data.copy()
            entry["un_number"] = un_num
            entry = _fill_missing_fields(entry)
            results.append(entry)

    return sorted(results, key=lambda x: x["un_number"])


# ══════════════════════════════════════════════════════════════
# 🏷️ 依危險品類別查詢
# ══════════════════════════════════════════════════════════════
def get_by_class(dg_class: str) -> list:
    """
    依危險品類別查詢所有符合的危險品。

    Args:
        dg_class: 危險品類別，例如 "3"、"6.1"、"9"
                  也支援子類別，例如 "1.1"、"1.2"

    Returns:
        符合條件的危險品列表，依 UN 號碼排序
    """
    db = load_database()
    dg_class = dg_class.strip()
    results = []

    for un_num, data in db.items():
        item_class = data.get("class", "")
        # 精確匹配或前綴匹配（例如 "1" 可匹配 "1.1D"）
        if item_class == dg_class or item_class.startswith(dg_class + ".") or item_class.startswith(dg_class + " "):
            entry = data.copy()
            entry["un_number"] = un_num
            entry = _fill_missing_fields(entry)
            results.append(entry)

    return sorted(results, key=lambda x: x["un_number"])


# ══════════════════════════════════════════════════════════════
# 🔎 關鍵字搜尋（強化版）
# ══════════════════════════════════════════════════════════════
def search_by_keyword(keyword: str, limit: int = 50) -> list:
    """
    依關鍵字搜尋危險品，支援中英文、UN 號碼、EMS 代碼。

    搜尋範圍：
    - proper_shipping_name（英文名稱）
    - description（描述）
    - UN 號碼
    - EMS 代碼（例如 "F-E"）
    - 危險品類別

    Args:
        keyword: 搜尋關鍵字
        limit  : 最多回傳筆數（預設 50）

    Returns:
        符合條件的危險品列表，依相關性排序
    """
    db = load_database()
    keyword = keyword.strip().lower()
    results = []

    for un_num, data in db.items():
        score = 0
        name = data.get("proper_shipping_name", "").lower()
        desc = data.get("description", "").lower()
        un_lower = un_num.lower()
        ems_fire = data.get("ems_fire", "").lower()
        ems_spill = data.get("ems_spillage", "").lower()
        dg_class = data.get("class", "").lower()

        # 計算相關性分數
        if keyword in un_lower:
            score += 10          # UN 號碼完全匹配優先
        if name.startswith(keyword):
            score += 8           # 名稱開頭匹配
        elif keyword in name:
            score += 5           # 名稱包含
        if keyword in desc:
            score += 3
        if keyword in ems_fire or keyword in ems_spill:
            score += 4
        if keyword in dg_class:
            score += 2

        if score > 0:
            entry = data.copy()
            entry["un_number"] = un_num
            entry["_score"] = score
            entry = _fill_missing_fields(entry)
            results.append(entry)

    # 依相關性分數排序，再依 UN 號碼排序
    results.sort(key=lambda x: (-x["_score"], x["un_number"]))

    # 移除內部分數欄位
    for r in results:
        r.pop("_score", None)

    return results[:limit]


# ══════════════════════════════════════════════════════════════
# 🔥 EMS 代碼 — fail-closed 顯示（規格書 3.1 / docs/INITIAL_SAFETY_AUDIT.md C-3）
# ══════════════════════════════════════════════════════════════
#
# 原本這裡有一份手寫的 EMS_FIRE_CODES / EMS_SPILLAGE_CODES 對照表，內含具體滅火劑、
# 處置行動與注意事項，但沒有任何文件名稱、版本、章節頁碼、生效日期、公司核准日期與
# SHA-256，屬於未經核准的安全關鍵判斷，已全面停用並移除內容。
#
# 在公司匯入經核准的 2024 EmS Supplement 結構化資料（含上述版本／來源欄位）之前，
# 本模組僅回傳原始 F-code / S-code 與統一的「未經驗證」提示，不再產生任何滅火介質、
# PPE、冷卻時間、撤離距離或處置行動等內容。與 fire_classifier.py 的 fail-closed
# 行為保持一致。
#
# 2026-09 更新（見 docs/KNOWN_LIMITATIONS.md §7.12）：本函式僅收到 F-code／S-code
# 兩個代碼本身，並未收到 UN 號碼，因此**結構上就無法**做到逐物質內容——同一個
# IMDG EmS 代碼（如 F-A）可能對應到多個完全不同的美國 ERG2024 Guide Number（ERG
# 與 IMDG 是兩套不同分類系統，不是一對一映射），勉強在這裡填入某個具體 ERG 內容
# 反而會造成「同代碼不同物質顯示相同內容」的誤導。真正逐物質、已依 UN 號碼對應
# 正確 ERG2024 Guide 的完整內容，改放在 imdg_database.json 每筆記錄的
# emergency_action／emergency_action_source 欄位（ems_engine.query_ems() 已回傳，
# app.py 的「應急處置指引」區塊已顯示），此函式的訊息文字僅更新為指向該區塊。

EMS_NOT_VERIFIED_MESSAGE = "本代碼本身無逐物質內容，詳細應急處置請見下方「應急處置指引」（ERG2024 對照）及船上最新版 EmS Guide。"


def get_ems_description(ems_fire: str, ems_spillage: str) -> dict:
    """
    取得 EMS 代碼的 fail-closed 顯示資訊（不含未經核准的具體處置內容）。

    Args:
        ems_fire    : 火災 EMS 代碼，例如 "F-E"
        ems_spillage: 洩漏 EMS 代碼，例如 "S-E"

    Returns:
        僅包含原始代碼與統一提示；不含滅火劑／處置行動等內容——這兩個代碼本身
        無法對應到特定 UN 號碼的 ERG2024 Guide（見上方模組註解），逐物質內容
        改由 imdg_database.json 的 emergency_action 欄位提供。
    """
    fire_code = (ems_fire or "").strip().upper()
    spill_code = (ems_spillage or "").strip().upper()

    return {
        "fire_code":            fire_code,
        "fire_summary":         EMS_NOT_VERIFIED_MESSAGE if fire_code else "查無資料",
        "fire_agents":          "",
        "fire_notes":           "",
        "fire_description":     f"EmS {fire_code}" if fire_code else "查無資料",
        "spillage_code":        spill_code,
        "spillage_summary":     EMS_NOT_VERIFIED_MESSAGE if spill_code else "查無資料",
        "spillage_action":      "",
        "spillage_notes":       "",
        "spillage_description": f"EmS {spill_code}" if spill_code else "查無資料",
    }


# ══════════════════════════════════════════════════════════════
# 🧩 資料補全工具（確保欄位完整性）
# ══════════════════════════════════════════════════════════════
def _fill_missing_fields(entry: dict) -> dict:
    """
    補全缺少的欄位，確保下游模組不會因 KeyError 崩潰。
    所有欄位若缺失則填入空字串或空列表。
    """
    defaults = {
        "proper_shipping_name": "Unknown",
        "class":                "Unknown",
        "packing_group":        "",
        "description":          "",
        "ems_fire":             "",
        "ems_spillage":         "",
        "mfag":                 "",
        "stowage":              "",
        "special_provisions":   [],
        "emergency_action": {
            "fire":       "",
            "spillage":   "",
            "first_aid":  "",
        },
        # 2026-09 新增（見 docs/KNOWN_LIMITATIONS.md §7.12）：emergency_action
        # 內容來源標示，防禦性預設值（正常情況下 198 筆資料應皆已補齊，此處僅
        # 避免缺漏欄位時下游 KeyError）。
        "emergency_action_source": {},
    }
    for key, default in defaults.items():
        if key not in entry:
            entry[key] = default
    return entry


def validate_entry(entry: dict) -> tuple[bool, list]:
    """
    驗證單筆危險品資料的完整性。

    Returns:
        (is_valid, missing_fields) — 是否有效 + 缺失欄位清單
    """
    required_fields = [
        "proper_shipping_name",
        "class",
        "ems_fire",
        "ems_spillage",
    ]
    missing = [f for f in required_fields if not entry.get(f)]
    return (len(missing) == 0, missing)


# ══════════════════════════════════════════════════════════════
# 📊 資料庫統計與工具函數
# ══════════════════════════════════════════════════════════════
def get_all_un_numbers() -> list:
    """回傳資料庫中所有 UN 號碼的排序清單"""
    db = load_database()
    return sorted(db.keys())


def get_database_stats() -> dict:
    """
    回傳資料庫完整統計資訊。

    Returns:
        包含總筆數、各類別數量、資料完整性統計的字典
    """
    db = load_database()
    class_count    = {}
    pg_count       = {"I": 0, "II": 0, "III": 0, "N/A": 0}
    incomplete     = []

    for un_num, data in db.items():
        # 類別統計
        dg_class   = data.get("class", "Unknown")
        main_class = dg_class.split(".")[0]
        class_count[main_class] = class_count.get(main_class, 0) + 1

        # 包裝等級統計
        pg = data.get("packing_group", "") or "N/A"
        if pg in pg_count:
            pg_count[pg] += 1
        else:
            pg_count["N/A"] += 1

        # 資料完整性檢查
        entry = data.copy()
        entry["un_number"] = un_num
        is_valid, missing = validate_entry(entry)
        if not is_valid:
            incomplete.append({"un": un_num, "missing": missing})

    return {
        "total":            len(db),
        "by_class":         dict(sorted(class_count.items())),
        "by_packing_group": pg_count,
        "incomplete_count": len(incomplete),
        "incomplete_items": incomplete[:10],   # 最多顯示前10筆
    }


def get_dangerous_goods_summary(un_number: str) -> Optional[str]:
    """
    取得危險品的一行摘要文字，方便 UI 快速顯示。

    Returns:
        格式：「UN1203 | GASOLINE | Class 3 | PG II」
        找不到則回傳 None
    """
    entry = get_by_un_number(un_number)
    if not entry:
        return None

    un  = entry.get("un_number", "")
    name = entry.get("proper_shipping_name", "Unknown")
    cls  = entry.get("class", "?")
    pg   = entry.get("packing_group", "")
    pg_str = f" | PG {pg}" if pg else ""

    return f"{un} | {name} | Class {cls}{pg_str}"
