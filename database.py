# ============================================================
# 📦 database.py — IMDG 危險品資料庫讀取模組（強化版）
# ============================================================

import json
import os
import re
from typing import Optional
from functools import lru_cache

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
# 🔥 EMS 代碼完整對照表
# ══════════════════════════════════════════════════════════════

EMS_FIRE_CODES = {
    "F-A": {
        "summary": "一般可燃物火災",
        "agents":  "水、CO₂、乾粉、泡沫",
        "notes":   "適用大多數固體可燃物，可直接用水撲滅",
    },
    "F-B": {
        "summary": "爆炸物火災",
        "agents":  "大量水霧",
        "notes":   "⛔ 禁止使用 CO₂；火勢無法控制時立即撤離至安全距離",
    },
    "F-C": {
        "summary": "壓縮/液化氣體火災",
        "agents":  "水霧冷卻容器",
        "notes":   "優先關閉氣源閥門；容器過熱有爆炸風險",
    },
    "F-D": {
        "summary": "易燃氣體火災",
        "agents":  "水霧、乾粉",
        "notes":   "⛔ 禁止使用 CO₂；防止氣體積聚於低窪處",
    },
    "F-E": {
        "summary": "易燃液體火災",
        "agents":  "泡沫、乾粉、CO₂",
        "notes":   "⛔ 禁止直射水流（可能擴散火勢）；使用水霧冷卻周圍容器",
    },
    "F-F": {
        "summary": "自燃物質火災",
        "agents":  "大量水",
        "notes":   "⛔ 禁止使用 CO₂；保持物質濕潤防止復燃",
    },
    "F-G": {
        "summary": "遇水反應物火災",
        "agents":  "乾沙、D 類乾粉",
        "notes":   "⛔ 嚴禁使用水、泡沫、CO₂；接觸水會產生可燃/有毒氣體",
    },
    "F-H": {
        "summary": "氧化劑火災",
        "agents":  "大量水霧",
        "notes":   "⛔ 禁止使用 CO₂ 及可燃性滅火劑；氧化劑會助燃",
    },
    "F-J": {
        "summary": "有機過氧化物火災",
        "agents":  "大量水霧",
        "notes":   "持續冷卻容器防止爆炸；有自加速分解風險",
    },
    "F-S": {
        "summary": "固體危險品火災",
        "agents":  "水、乾粉",
        "notes":   "依物質特性選擇滅火劑，注意燃燒產物毒性",
    },
}

EMS_SPILLAGE_CODES = {
    "S-A": {
        "summary": "一般固體洩漏",
        "action":  "掃除收集，放入密封容器",
        "notes":   "通風，防止粉塵吸入；防止進入排水系統",
    },
    "S-B": {
        "summary": "腐蝕性液體洩漏",
        "action":  "中和後大量清水沖洗",
        "notes":   "穿戴耐酸鹼防護；酸鹼中和時注意放熱反應",
    },
    "S-C": {
        "summary": "感染性物質洩漏",
        "action":  "消毒液覆蓋，隔離現場",
        "notes":   "立即通報衛生機關；處置人員需穿戴生物防護裝備",
    },
    "S-D": {
        "summary": "毒性液體洩漏",
        "action":  "吸附材料收集，密封廢棄",
        "notes":   "穿戴全套化學防護；防止皮膚及吸入暴露",
    },
    "S-E": {
        "summary": "易燃液體洩漏",
        "action":  "消除所有火源，吸附材料收集",
        "notes":   "⛔ 禁止使用電動工具；防止蒸氣積聚",
    },
    "S-F": {
        "summary": "環境危害物洩漏",
        "action":  "圍堵防止擴散，收集廢液",
        "notes":   "依 MARPOL 規定通報；防止進入海洋",
    },
    "S-G": {
        "summary": "自燃物洩漏",
        "action":  "保持濕潤或隔絕空氣",
        "notes":   "⛔ 禁止暴露於空氣中；立即用濕沙覆蓋",
    },
    "S-I": {
        "summary": "鋰電池洩漏/熱失控",
        "action":  "隔離，大量水冷卻",
        "notes":   "注意熱失控連鎖反應；通風排除有毒氣體",
    },
    "S-P": {
        "summary": "遇水反應物洩漏",
        "action":  "乾燥覆蓋，隔絕水分",
        "notes":   "⛔ 嚴禁使用水；保持乾燥環境",
    },
    "S-Q": {
        "summary": "氧化劑洩漏",
        "action":  "大量清水稀釋沖洗",
        "notes":   "⛔ 禁止接觸可燃物；防止氧化反應",
    },
    "S-U": {
        "summary": "有毒/易燃氣體洩漏",
        "action":  "疏散，水霧稀釋，消除火源",
        "notes":   "從上風處接近；確認氣體濃度低於爆炸下限後方可進入",
    },
    "S-V": {
        "summary": "冷凍液化氣體洩漏",
        "action":  "通風，保持距離",
        "notes":   "注意窒息風險（密閉空間）及低溫凍傷",
    },
    "S-W": {
        "summary": "放射性物質洩漏",
        "action":  "隔離，通報輻射防護機關",
        "notes":   "⛔ 禁止未授權人員接近；啟動船上輻射應急程序",
    },
    "S-X": {
        "summary": "腐蝕性固體洩漏",
        "action":  "乾式清掃，避免揚塵",
        "notes":   "穿戴耐腐蝕防護；防止粉塵吸入",
    },
    "S-Y": {
        "summary": "爆炸物洩漏",
        "action":  "禁止接觸，隔離現場",
        "notes":   "⛔ 禁止任何撞擊、摩擦或加熱；立即通知爆炸物處置專家",
    },
    "S-Z": {
        "summary": "磁性物質洩漏",
        "action":  "保持與電子設備距離",
        "notes":   "通知航行設備檢查；可能影響羅盤及導航系統",
    },
}


def get_ems_description(ems_fire: str, ems_spillage: str) -> dict:
    """
    取得 EMS 代碼的完整中文說明（強化版）。

    Args:
        ems_fire    : 火災 EMS 代碼，例如 "F-E"
        ems_spillage: 洩漏 EMS 代碼，例如 "S-E"

    Returns:
        包含火災與洩漏完整說明的字典
    """
    fire_info  = EMS_FIRE_CODES.get(ems_fire.upper(), {})
    spill_info = EMS_SPILLAGE_CODES.get(ems_spillage.upper(), {})

    return {
        "fire_code":              ems_fire,
        "fire_summary":           fire_info.get("summary", "請參閱 IMDG EMS 手冊"),
        "fire_agents":            fire_info.get("agents",  "請參閱 IMDG EMS 手冊"),
        "fire_notes":             fire_info.get("notes",   ""),
        "fire_description":       f"{fire_info.get('summary', '')} — 使用：{fire_info.get('agents', '')}",
        "spillage_code":          ems_spillage,
        "spillage_summary":       spill_info.get("summary", "請參閱 IMDG EMS 手冊"),
        "spillage_action":        spill_info.get("action",  "請參閱 IMDG EMS 手冊"),
        "spillage_notes":         spill_info.get("notes",   ""),
        "spillage_description":   f"{spill_info.get('summary', '')} — {spill_info.get('action', '')}",
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
