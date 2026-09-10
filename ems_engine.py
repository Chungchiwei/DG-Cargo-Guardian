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
from variant_resolver import resolve_variant, VariantStatus


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

    # ── 正式品名選列狀態（規格書 3.2 / VariantResolver）───────────
    # requires_variant_selection=true 且尚未選列時，不得顯示確定的 Packing Group /
    # Stowage（這些欄位在不同 official_variants 間可能不同），必須 fail closed 為
    # AMBIGUOUS 並要求人工從 official_variants 選列。
    variant_resolution = resolve_variant(un_number)
    is_ambiguous = variant_resolution.status == VariantStatus.AMBIGUOUS

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

    # ── 隔離代碼／來源資料（規格書強化：使用資料庫已有、已核對頁碼的真實欄位，──
    #    不新增任何未經來源的判斷。requires_variant_selection 且尚未選列時，
    #    與 packing_group／stowage 相同，一律 fail closed 留空。）──────────
    selected_variant = variant_resolution.selected_variant if not is_ambiguous else None
    segregation_codes = []
    if not is_ambiguous:
        if selected_variant and selected_variant.get("segregation_codes"):
            segregation_codes = selected_variant["segregation_codes"]
        elif result.get("segregation_codes"):
            segregation_codes = result["segregation_codes"]
    source_meta = result.get("source", {}) or {}

    # ── 舊版（未經 2024 Supplement 核對）應急處置自由文字 ──────────────
    # 使用者已明確確認：於畫面上以顯眼警示標示「未經驗證」後仍要顯示，讓船員
    # 免翻書即可看到重點，同時清楚知道這不是已核對的官方逐字條文（見
    # docs/KNOWN_LIMITATIONS.md §7.6）。資料本身不做任何修改／推測，原樣帶出
    # imdg_database.json 既有的 legacy_unverified.emergency_action 欄位。
    legacy = result.get("legacy_unverified") or {}
    legacy_emergency_action = legacy.get("emergency_action") or {}

    return {
        "found":                     True,
        "un_number":                 result.get("un_number"),
        "proper_shipping_name":      result.get("proper_shipping_name", "Unknown"),
        "hazard_class":              result.get("class", "Unknown"),
        "subsidiary_risk":           sub_risk,
        # Packing Group / Stowage 在 requires_variant_selection=true 且尚未選列時
        # 一律 fail closed 為空字串，不得顯示可能錯誤的「代表值」（規格書 3.2 / C-4）。
        "packing_group":             "" if is_ambiguous else result.get("packing_group", ""),
        "ems":                       ems,
        "mfag":                      result.get("mfag", ""),
        "stowage":                   "" if is_ambiguous else (result.get("stowage") or result.get("stowage_segregation", "")),
        "description":               result.get("description", ""),
        "flashpoint":                flashpoint,
        "flashpoint_raw":            flashpoint_raw,
        "emergency_action":          result.get("emergency_action", {}),
        # 2026-09 新增（見 docs/KNOWN_LIMITATIONS.md §7.12）：上面 emergency_action
        # 內容的來源標示（ERG2024 Guide 對照與免責聲明），供 UI／報告顯示於內容
        # 旁，讓使用者清楚這不是 IMO EmS Guide 逐字條文。
        "emergency_action_source":   result.get("emergency_action_source", {}),
        # 舊版未核對自由文字（供 UI 以顯眼警示顯示，見上方註解）；沒有的項目為空字典。
        "legacy_emergency_action":   legacy_emergency_action,
        "legacy_emergency_action_available": bool(legacy_emergency_action),
        "special_provisions":        special_provisions,
        # 隔離代碼（segregation codes，例如 SG2/SG9…）：資料庫本身已核對來源頁碼的
        # 客觀資料，僅供人工對照船上 IMDG Code Segregation Table 使用；不構成
        # 「合規／違規」判定，判定仍完全由 segregation_engine（deterministic）負責。
        "segregation_codes":         "" if is_ambiguous else segregation_codes,
        # 資料來源／版本資訊：讓查詢結果附上可稽核的出處，而非「已驗證」的空泛宣告。
        "source_edition":            source_meta.get("imdg_edition", ""),
        "source_amendment":          source_meta.get("amendment", ""),
        "source_resolution":         source_meta.get("resolution", ""),
        "source_effective_from":     source_meta.get("effective_from", ""),
        "source_pdf_pages":          source_meta.get("dangerous_goods_list_pdf_pages", []),
        "source_verified_scope":     source_meta.get("verified_scope", []),
        "source_not_verified_scope": source_meta.get("not_verified_without_2024_supplement_or_sds", []),
        # variant 選列狀態（規格書 3.2）：AMBIGUOUS 時 UI 必須要求人工選列，
        # 不得顯示或使用上面被清空的 packing_group / stowage。
        "variant_status":            variant_resolution.status.value,
        "requires_variant_selection": is_ambiguous,
        "variant_candidates":        variant_resolution.candidates if is_ambiguous else [],
        "variant_message":           variant_resolution.message if is_ambiguous else "",
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
    ea_src   = data.get("emergency_action_source", {})
    ems_source_line = (
        f"\n  來源：{ea_src['reference']}，Guide {ea_src.get('guide_number','')}"
        f"（{ea_src.get('guide_title_en','')}）——非 IMO EmS Guide 逐字條文，"
        "亦非本船／本公司核准之正式 SOP，僅供快速參考\n"
    ) if ea_src.get("reference") else ""
    ems      = data.get("ems", {})
    sub_risk = "、".join(data["subsidiary_risk"]) if data["subsidiary_risk"] else "無"
    sp       = "、".join(data["special_provisions"]) if data["special_provisions"] else "無"
    seg_codes = data.get("segregation_codes") or []
    seg_codes_str = "、".join(seg_codes) if seg_codes else (
        "待選列" if data.get("requires_variant_selection") else "無登記代碼"
    )

    if data.get("source_edition"):
        pages = data.get("source_pdf_pages") or []
        pages_str = "、".join(str(p) for p in pages) if pages else "N/A"
        source_line = (
            f"IMDG Code {data['source_edition']} Edition"
            + (f"，Amendment {data['source_amendment']}" if data.get("source_amendment") else "")
            + (f"（{data['source_resolution']}）" if data.get("source_resolution") else "")
            + (f"，生效日 {data['source_effective_from']}" if data.get("source_effective_from") else "")
            + f"｜Dangerous Goods List 頁碼：{pages_str}"
        )
    else:
        source_line = "本筆資料未附版本／頁碼來源，請以船上最新版 IMDG Code 為準"

    # AMBIGUOUS：requires_variant_selection=true 且尚未選列，PG/Stowage 已被 query_ems()
    # 清空，此處明確標示狀態，禁止顯示確定的積載/隔離資訊（規格書 3.2）。
    variant_banner = ""
    if data.get("requires_variant_selection"):
        variant_banner = (
            "\n📝  【正式品名尚未選列 / 待確認品名】\n"
            f"  {data.get('variant_message', '')}\n"
            f"  候選項目數：{len(data.get('variant_candidates', []))}\n"
            "  下方包裝等級／積載類別欄位在選列前一律留空，禁止依此做出積載決策。\n"
        )

    report = f"""
╔══════════════════════════════════════════════╗
║         IMDG 危險品應急資料（EMS Report）         ║
╚══════════════════════════════════════════════╝
{variant_banner}
【基本資料】
  UN 號碼        : {data['un_number']}
  正式運輸名稱   : {data['proper_shipping_name']}
  危險品類別     : Class {data['hazard_class']}  {_class_label(data['hazard_class'])}
  附屬危險       : {sub_risk}
  包裝等級       : {data['packing_group'] or ('待選列' if data.get('requires_variant_selection') else 'N/A')}
  閃點           : {data['flashpoint']}

【物質描述】
  {data['description'] or '無描述資料'}

【EMS 應急程序代碼】
  🔥 火災代碼    : {ems.get('fire_code', 'N/A')}
     狀態        : {ems.get('fire_summary', 'N/A')}

  💧 洩漏代碼    : {ems.get('spillage_code', 'N/A')}
     狀態        : {ems.get('spillage_summary', 'N/A')}

  🏥 MFAG 號碼   : {data['mfag'] or 'N/A'}

【積載與隔離】
  積載類別       : {data['stowage'] or ('待選列' if data.get('requires_variant_selection') else 'N/A')}
  特殊規定       : {sp}
  隔離代碼       : {seg_codes_str}（僅供對照船上 IMDG Code Segregation Table，非合規判定）

【資料來源與版本】
  {source_line}

【應急處置指引】{ems_source_line}
  🔥 火災處置    :
  {_indent(ea.get('fire', '請參閱船上最新版 IMDG EmS Guide'))}

  💧 洩漏處置    :
  {_indent(ea.get('spillage', '請參閱船上最新版 IMDG EmS Guide'))}

  🏥 急救處置    :
  {_indent(ea.get('first_aid', '請參閱船上最新版 MFAG'))}

══════════════════════════════════════════════
⚠️  本系統為決策支援工具，不取代 IMDG Code、EmS Guide、MFAG、船舶 SMS、
    公司核准程序及船長決定。緊急情況請依船上核准之應急聯絡清單聯繫。
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
    if data.get("requires_variant_selection"):
        pg_str = " | 📝 待確認品名"
    else:
        pg_str = f" | PG {pg}" if pg else ""

    return (
        f"{data['un_number']} | {data['proper_shipping_name']} | "
        f"Class {data['hazard_class']}{pg_str} | "
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
