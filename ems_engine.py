# ============================================================
# 🔍 ems_engine.py — EMS 查詢引擎（強化版）
# ============================================================

from database import (
    get_by_un_number,
    get_by_un_number_fuzzy,
    get_ems_description,
    normalize_un_number,
    is_valid_un_number,
    get_dangerous_goods_summary,
)


# ══════════════════════════════════════════════════════════════
# 🔍 主查詢函數
# ══════════════════════════════════════════════════════════════
def query_ems(un_number: str) -> dict:
    """
    查詢指定 UN 號碼的完整 EMS 應急資訊。

    功能強化：
    - 輸入格式容錯（自動標準化）
    - 查無結果時提供模糊建議
    - EMS 代碼結構化輸出（含 agents / notes）
    - 自動補全缺失欄位，避免下游 KeyError

    Args:
        un_number: UN 號碼，支援 "1203" / "UN1203" / "un 1203"

    Returns:
        完整應急資料字典，found=False 時含錯誤訊息與建議
    """
    # ── 格式驗證 ──────────────────────────────────────────────
    if not un_number or not un_number.strip():
        return _not_found_response(
            un_number="",
            message="UN 號碼不可為空白",
            suggestions=[]
        )

    if not is_valid_un_number(un_number):
        return _not_found_response(
            un_number=un_number.strip().upper(),
            message=f"「{un_number.strip()}」格式無效，UN 號碼應為4位數字（例如：UN1203）",
            suggestions=[]
        )

    # ── 精確查詢 ──────────────────────────────────────────────
    result = get_by_un_number(un_number)

    if not result:
        # 嘗試模糊查詢，提供建議
        try:
            normalized = normalize_un_number(un_number)
        except ValueError:
            normalized = un_number.strip().upper()

        fuzzy_results = get_by_un_number_fuzzy(un_number)
        suggestions = [
            get_dangerous_goods_summary(r["un_number"])
            for r in fuzzy_results[:5]
            if r.get("un_number")
        ]

        return _not_found_response(
            un_number=normalized,
            message=f"查無 {normalized} 的資料，請確認 UN 號碼是否正確",
            suggestions=[s for s in suggestions if s]
        )

    # ── 組合 EMS 資料 ─────────────────────────────────────────
    ems = get_ems_description(
        result.get("ems_fire", ""),
        result.get("ems_spillage", "")
    )

    # ── 附屬危險與特殊規定格式化 ──────────────────────────────
    sub_risk = result.get("subsidiary_risk", [])
    if isinstance(sub_risk, str):
        sub_risk = [sub_risk] if sub_risk else []

    special_provisions = result.get("special_provisions", [])
    if isinstance(special_provisions, str):
        special_provisions = [special_provisions] if special_provisions else []

    # ── 閃點標準化 ────────────────────────────────────────────
    flashpoint_raw = result.get("flashpoint", None)
    flashpoint = _format_flashpoint(flashpoint_raw)

    # ── 危險等級評估 ──────────────────────────────────────────
    risk_level = _assess_risk_level(
        hazard_class=result.get("class", ""),
        packing_group=result.get("packing_group", ""),
        ems_fire=result.get("ems_fire", ""),
    )

    return {
        "found":                True,
        "un_number":            result.get("un_number"),
        "proper_shipping_name": result.get("proper_shipping_name", "Unknown"),
        "hazard_class":         result.get("class", "Unknown"),
        "subsidiary_risk":      sub_risk,
        "packing_group":        result.get("packing_group", ""),
        "ems":                  ems,
        "mfag":                 result.get("mfag", ""),
        "stowage":              result.get("stowage") or result.get("stowage_segregation", ""),
        "description":          result.get("description", ""),
        "flashpoint":           flashpoint,
        "flashpoint_raw":       flashpoint_raw,
        "emergency_action":     result.get("emergency_action", {}),
        "special_provisions":   special_provisions,
        "risk_level":           risk_level,
    }


# ══════════════════════════════════════════════════════════════
# 📄 格式化報告（純文字，供 AI 分析）
# ══════════════════════════════════════════════════════════════
def format_ems_report(data: dict) -> str:
    """
    將 EMS 查詢結果格式化為結構化純文字報告。
    主要供 AI 分析模組使用，資訊盡量完整詳細。

    Args:
        data: query_ems() 的回傳值

    Returns:
        格式化純文字報告字串
    """
    if not data.get("found"):
        lines = [f"❌ {data.get('message', '查詢失敗')}"]
        suggestions = data.get("suggestions", [])
        if suggestions:
            lines.append("\n💡 您是否要查詢以下 UN 號碼？")
            for s in suggestions:
                lines.append(f"   • {s}")
        return "\n".join(lines)

    ea       = data.get("emergency_action", {})
    ems      = data.get("ems", {})
    sub_risk = "、".join(data["subsidiary_risk"]) if data["subsidiary_risk"] else "無"
    sp       = "、".join(data["special_provisions"]) if data["special_provisions"] else "無"
    risk_lv  = data.get("risk_level", {})

    report = f"""
╔══════════════════════════════════════════════╗
║         IMDG 危險品應急資料（EMS Report）         ║
╚══════════════════════════════════════════════╝

【基本資料】
  UN 號碼        : {data['un_number']}
  正式運輸名稱   : {data['proper_shipping_name']}
  危險品類別     : Class {data['hazard_class']}  {_class_label(data['hazard_class'])}
  附屬危險       : {sub_risk}
  包裝等級       : {data['packing_group'] or 'N/A'}
  閃點           : {data['flashpoint']}
  危險等級評估   : {risk_lv.get('label', 'N/A')}  （{risk_lv.get('reason', '')}）

【物質描述】
  {data['description'] or '無描述資料'}

【EMS 應急程序代碼】
  🔥 火災代碼    : {ems.get('fire_code', 'N/A')}
     類型        : {ems.get('fire_summary', 'N/A')}
     建議滅火劑  : {ems.get('fire_agents', 'N/A')}
     注意事項    : {ems.get('fire_notes', 'N/A')}

  💧 洩漏代碼    : {ems.get('spillage_code', 'N/A')}
     類型        : {ems.get('spillage_summary', 'N/A')}
     處置行動    : {ems.get('spillage_action', 'N/A')}
     注意事項    : {ems.get('spillage_notes', 'N/A')}

  🏥 MFAG 號碼   : {data['mfag'] or 'N/A'}

【積載與隔離】
  積載類別       : {data['stowage'] or 'N/A'}
  特殊規定       : {sp}

【應急處置指引】
  🔥 火災處置    :
  {_indent(ea.get('fire', '請參閱 IMDG EMS 手冊'))}

  💧 洩漏處置    :
  {_indent(ea.get('spillage', '請參閱 IMDG EMS 手冊'))}

  🏥 急救處置    :
  {_indent(ea.get('first_aid', '請參閱 IMDG EMS 手冊'))}

══════════════════════════════════════════════
⚠️  本資料依據 IMDG Code，僅供參考。
    緊急情況請聯繫 CHEMTREC：+1-703-527-3887
══════════════════════════════════════════════
"""
    return report.strip()


# ══════════════════════════════════════════════════════════════
# 📊 格式化摘要（供 UI 快速顯示）
# ══════════════════════════════════════════════════════════════
def format_ems_summary(data: dict) -> str:
    """
    產生單行摘要，適合 UI 列表或 sidebar 快速顯示。

    Returns:
        例如：「UN1203 | GASOLINE | Class 3 🔴 極高風險 | PG II | F-E / S-E」
    """
    if not data.get("found"):
        return f"❌ {data.get('un_number', '?')} — 查無資料"

    ems     = data.get("ems", {})
    pg      = data.get("packing_group", "")
    pg_str  = f" | PG {pg}" if pg else ""
    risk    = data.get("risk_level", {}).get("label", "")
    risk_str = f" {risk}" if risk else ""

    return (
        f"{data['un_number']} | {data['proper_shipping_name']} | "
        f"Class {data['hazard_class']}{risk_str}{pg_str} | "
        f"{ems.get('fire_code', '?')} / {ems.get('spillage_code', '?')}"
    )


# ══════════════════════════════════════════════════════════════
# 🔁 批次查詢
# ══════════════════════════════════════════════════════════════
def query_ems_batch(un_numbers: list) -> list:
    """
    批次查詢多個 UN 號碼的 EMS 資料。

    Args:
        un_numbers: UN 號碼字串列表

    Returns:
        query_ems() 結果的列表，順序與輸入一致
    """
    return [query_ems(un) for un in un_numbers]


# ══════════════════════════════════════════════════════════════
# 🛠️ 內部工具函數
# ══════════════════════════════════════════════════════════════
def _not_found_response(un_number: str, message: str, suggestions: list) -> dict:
    """統一的查無結果回傳格式"""
    return {
        "found":       False,
        "un_number":   un_number,
        "message":     message,
        "suggestions": suggestions,
    }


def _format_flashpoint(flashpoint_raw) -> str:
    """
    將閃點資料標準化為可讀字串。
    支援數字（°C）、字串、None 等輸入。
    """
    if flashpoint_raw is None:
        return "N/A"
    if isinstance(flashpoint_raw, (int, float)):
        return f"{flashpoint_raw} °C"
    val = str(flashpoint_raw).strip()
    if not val:
        return "N/A"
    # 若已含單位則直接回傳，否則補上 °C
    if "°" in val or "c" in val.lower() or "n/a" in val.lower():
        return val
    return f"{val} °C"


def _assess_risk_level(hazard_class: str, packing_group: str, ems_fire: str) -> dict:
    """
    依危險品類別、包裝等級、EMS 代碼評估整體危險等級。

    Returns:
        {"label": "🔴 極高風險", "reason": "..."}
    """
    cls = hazard_class.split(".")[0] if hazard_class else ""
    pg  = packing_group.upper() if packing_group else ""

    # 極高風險：爆炸物、劇毒 PG I、遇水反應 PG I
    if cls == "1" or ems_fire == "F-B" or ems_fire == "F-G":
        return {"label": "🔴 極高風險", "reason": "爆炸物或遇水反應危險品"}
    if cls in ("2",) and ems_fire in ("F-D", "F-C"):
        return {"label": "🔴 極高風險", "reason": "易燃/毒性壓縮氣體"}
    if cls in ("6", "6.1") and pg == "I":
        return {"label": "🔴 極高風險", "reason": "劇毒物質 PG I"}
    if cls == "7":
        return {"label": "🔴 極高風險", "reason": "放射性物質"}

    # 高風險：易燃液體/固體 PG I~II、氧化劑、有機過氧化物
    if cls == "3" and pg in ("I", "II"):
        return {"label": "🟠 高風險", "reason": "易燃液體 PG I/II"}
    if cls in ("4", "4.1", "4.2", "4.3"):
        return {"label": "🟠 高風險", "reason": "易燃固體/自燃/遇水反應物質"}
    if cls in ("5", "5.1", "5.2"):
        return {"label": "🟠 高風險", "reason": "氧化劑或有機過氧化物"}
    if cls in ("6", "6.1") and pg == "II":
        return {"label": "🟠 高風險", "reason": "毒性物質 PG II"}
    if cls == "8" and pg == "I":
        return {"label": "🟠 高風險", "reason": "強腐蝕性物質 PG I"}

    # 中風險
    if cls == "3" and pg == "III":
        return {"label": "🟡 中風險", "reason": "易燃液體 PG III"}
    if cls in ("6", "6.1") and pg == "III":
        return {"label": "🟡 中風險", "reason": "毒性物質 PG III"}
    if cls == "8":
        return {"label": "🟡 中風險", "reason": "腐蝕性物質"}
    if cls == "6.2":
        return {"label": "🟡 中風險", "reason": "感染性物質"}

    # 低風險
    if cls == "9":
        return {"label": "🟢 低風險", "reason": "雜項危險品"}

    return {"label": "⚪ 未分類", "reason": "請參閱 IMDG Code"}


def _class_label(hazard_class: str) -> str:
    """回傳危險品類別的中文標籤"""
    labels = {
        "1":   "💥 爆炸物",
        "1.1": "💥 爆炸物（整體爆炸危險）",
        "1.2": "💥 爆炸物（拋射危險）",
        "1.3": "💥 爆炸物（火災危險）",
        "1.4": "💥 爆炸物（輕微危險）",
        "1.5": "💥 爆炸物（極不敏感）",
        "1.6": "💥 爆炸物（極不敏感物品）",
        "2.1": "🔥 易燃氣體",
        "2.2": "🫧 非易燃非毒性氣體",
        "2.3": "☠️ 毒性氣體",
        "3":   "🔥 易燃液體",
        "4.1": "🔥 易燃固體",
        "4.2": "🔥 自燃物質",
        "4.3": "💧 遇水反應物質",
        "5.1": "⚗️ 氧化劑",
        "5.2": "⚗️ 有機過氧化物",
        "6.1": "☠️ 毒性物質",
        "6.2": "🦠 感染性物質",
        "7":   "☢️ 放射性物質",
        "8":   "🧪 腐蝕性物質",
        "9":   "📦 雜項危險品",
    }
    cls = hazard_class.strip() if hazard_class else ""
    return labels.get(cls, labels.get(cls.split(".")[0], ""))


def _indent(text: str, spaces: int = 4) -> str:
    """
    將多行文字每行加上縮排，讓純文字報告更易閱讀。
    """
    if not text:
        return ""
    prefix = " " * spaces
    return ("\n" + prefix).join(str(text).splitlines())
