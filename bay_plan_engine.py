# ============================================================
# 🗺️ bay_plan_engine.py — Bay Plan 座標邏輯引擎
# ============================================================
#
# 2026-09 維護紀錄（見 docs/KNOWN_LIMITATIONS.md §7）：
#   1. fire_classifier.classify_fire_category() 已 fail-closed 一律回傳
#      color="grey"，先前依 fire_color 紅/黃/綠排序格子與統計分布的邏輯已
#      失去意義（見 docs/INITIAL_SAFETY_AUDIT.md C-3）。本檔改用「Class 類別
#      識別色」（IMDG_CLASS_COLORS，來源為 UN Model Regulations §5.2.2.2 /
#      IMDG Code Chapter 5.3 官方危險標誌底色）取代，並在所有顯示位置明確
#      標示「僅供視覺辨識，不代表風險等級」（規格書 3.5）。
#   2. 新增 find_nearby_dg() / get_nearby_segregation_summary()：規格書 F-004
#      要求的「鄰近危險品」功能先前並未實作。新函式為純 deterministic 幾何
#      近似（不呼叫 AI），並透過 segregation_engine.evaluate() 取得隔離狀態，
#      供 Bay Plan 頁面與 AI 事故分析頁面共用，作為「情境快照」的資料來源。

from collections import defaultdict, Counter
from vessel_profile import classify_tier
from segregation_engine import evaluate as evaluate_segregation

# ── 船舶尺寸常數（可依實際船型調整）────────────────────────
CELL_WIDTH_M  = 6.0   # 每個 Bay 寬度（公尺）
CELL_HEIGHT_M = 2.6   # 每個 Tier 高度（公尺）
CELL_ROW_M    = 2.4   # 每個 Row 寬度（公尺）


# ══════════════════════════════════════════════════════════════
# ── 危險品類別識別色（僅供視覺辨識，非風險等級／規格書 3.5）──
# ══════════════════════════════════════════════════════════════
#
# 來源：UN Model Regulations §5.2.2.2 / IMDG Code Chapter 5.3 官方危險標誌
# （placard）底色。部分類別（4.1/4.2/5.2/7/8/9）官方標誌實際為雙色或含條紋
# 圖案，此處簡化為單一辨識色以利格狀圖繪製，實際標誌樣式仍以船上核准之
# IMDG Code Chapter 5.3 為準；顏色僅用來讓使用者在 Bay Plan 上快速分辨
# 「這是哪一類危險品」，與滅火介質、風險程度或是否安全與否無關，不得作為
# 積載或應變決策依據。
IMDG_CLASS_COLORS = {
    "1":   {"hex": "#FF8C00", "text": "#111827", "note": "爆炸物 Explosives（橙色）"},
    "2.1": {"hex": "#D32F2F", "text": "#FFFFFF", "note": "易燃氣體 Flammable Gas（紅色）"},
    "2.2": {"hex": "#2E7D32", "text": "#FFFFFF", "note": "非易燃無毒氣體 Non-Flammable Gas（綠色）"},
    "2.3": {"hex": "#F5F5F5", "text": "#111827", "note": "毒性氣體 Toxic Gas（白底，官方含骷髏圖示）"},
    "3":   {"hex": "#D32F2F", "text": "#FFFFFF", "note": "易燃液體 Flammable Liquid（紅色）"},
    "4.1": {"hex": "#F5F5F5", "text": "#111827", "note": "易燃固體 Flammable Solid（白底紅條紋，簡化為白）"},
    "4.2": {"hex": "#F57C00", "text": "#111827", "note": "自燃物質 Spontaneously Combustible（白/紅雙色，簡化為橙）"},
    "4.3": {"hex": "#1565C0", "text": "#FFFFFF", "note": "遇水放氣體物質 Dangerous When Wet（藍色）"},
    "5.1": {"hex": "#FBC02D", "text": "#111827", "note": "氧化性物質 Oxidizer（黃色）"},
    "5.2": {"hex": "#F9A825", "text": "#111827", "note": "有機過氧化物 Organic Peroxide（黃/紅雙色，簡化為深黃）"},
    "6.1": {"hex": "#F5F5F5", "text": "#111827", "note": "毒性物質 Toxic（白色）"},
    "6.2": {"hex": "#F5F5F5", "text": "#111827", "note": "感染性物質 Infectious Substance（白色）"},
    "7":   {"hex": "#FDD835", "text": "#111827", "note": "放射性物質 Radioactive（黃/白雙色，簡化為黃）"},
    "8":   {"hex": "#37474F", "text": "#FFFFFF", "note": "腐蝕性物質 Corrosive（白/黑雙色，簡化為深灰）"},
    "9":   {"hex": "#CFD8DC", "text": "#111827", "note": "其他危險物質 Miscellaneous（白底黑條紋，簡化為淺灰）"},
}
_UNKNOWN_CLASS_COLOR = {"hex": "#6b7280", "text": "#FFFFFF", "note": "類別未知／未提供"}


def get_class_color(hazard_class: str) -> dict:
    """
    依危險品 Class 回傳「類別識別色」（非風險等級，見上方模組註解）。
    找不到對應子類別時退回大類（例如 "2.1" 找不到就用 "2"，反之亦然）。
    """
    if not hazard_class:
        return dict(_UNKNOWN_CLASS_COLOR)
    key = hazard_class.strip()
    if key in IMDG_CLASS_COLORS:
        return dict(IMDG_CLASS_COLORS[key])
    major = key.split(".")[0]
    if major in IMDG_CLASS_COLORS:
        return dict(IMDG_CLASS_COLORS[major])
    return dict(_UNKNOWN_CLASS_COLOR)


def get_class_color_legend() -> list[dict]:
    """回傳目前使用的類別識別色圖例（用於畫面上的色標說明），依類別順序排列。"""
    return [{"class": cls, **info} for cls, info in IMDG_CLASS_COLORS.items()]


# ══════════════════════════════════════════════════════════════
# ── EmS Fire Code 識別色（僅供視覺辨識，非滅火介質／風險等級）──
# ══════════════════════════════════════════════════════════════
#
# 2026-09 新增（回應使用者需求：「Bay plan 請幫我根據 EMS 處理方式進行顏色的
# 區隔」）。EmS Fire Code（F-A ~ F-J）本身是 imdg_database.json 已核對來源
# 的公開資料（見 source.verified_scope 內的 "ems"），只是「代碼」，不是
# 「這個代碼實際該用什麼滅火介質」——後者才是 fire_classifier.py 明確 fail
# -closed、不顯示的內容（docs/INITIAL_SAFETY_AUDIT.md C-3）。依代碼字母分組
# 上色，只是讓使用者能在 Bay Plan 上一眼看出「哪些貨櫃屬於同一個 EmS Fire
# Code 分組」，方便對照船上 EmS Guide 查閱對應章節，不透露、也不代表任何
# 具體滅火介質或危險程度。
EMS_FIRE_COLORS = {
    "F-A": {"hex": "#3B82F6", "text": "#FFFFFF"},
    "F-B": {"hex": "#8B5CF6", "text": "#FFFFFF"},
    "F-C": {"hex": "#EC4899", "text": "#FFFFFF"},
    "F-D": {"hex": "#F59E0B", "text": "#111827"},
    "F-E": {"hex": "#10B981", "text": "#FFFFFF"},
    "F-F": {"hex": "#06B6D4", "text": "#111827"},
    "F-G": {"hex": "#84CC16", "text": "#111827"},
    "F-H": {"hex": "#F43F5E", "text": "#FFFFFF"},
    "F-I": {"hex": "#A855F7", "text": "#FFFFFF"},
    "F-J": {"hex": "#0EA5E9", "text": "#FFFFFF"},
}
_UNKNOWN_EMS_COLOR = {"hex": "#6b7280", "text": "#FFFFFF"}


def get_ems_fire_color(fire_code: str) -> dict:
    """依 EmS Fire Code（如 "F-A"）回傳識別色（非滅火介質、非風險等級，見上方註解）。"""
    if not fire_code:
        return dict(_UNKNOWN_EMS_COLOR)
    code = fire_code.strip().upper()
    if code in EMS_FIRE_COLORS:
        return dict(EMS_FIRE_COLORS[code])
    return dict(_UNKNOWN_EMS_COLOR)


def get_ems_fire_color_legend() -> list[dict]:
    """回傳目前使用的 EmS Fire Code 識別色圖例，依代碼順序排列。"""
    return [{"code": code, **info} for code, info in EMS_FIRE_COLORS.items()]


# ══════════════════════════════════════════════════════════════
# ── 滅火介質通則／高風險類別標示（2026-09 新增，回應使用者需求）──
# ══════════════════════════════════════════════════════════════
#
# 使用者需求原文：「貨櫃 Bay Plan 應該要區分 像是可用水 / CO2滅火，甚至高危險的
# 類別要特別標示」。
#
# 【與 fire_classifier.py fail-closed 決策的關係，務必先讀】
# fire_classifier.py 先前因為把 F-A~F-J 對應到「具體滅火介質／PPE／冷卻時間／
# do & dont」等逐物質戰術建議，但該對應表沒有文件名稱、版本、章節頁碼、生效
# 日期與公司核准紀錄，屬於未經核准的安全關鍵判斷，已於 Phase-1 安全稽核
# （docs/INITIAL_SAFETY_AUDIT.md C-3）fail-closed 停用，且該決策維持不變——
# fire_classifier.py 本身未被修改，AI/EMS 頁面也不會因本模組而重新出現逐物質
# 戰術建議。
#
# 本模組不同：不對應「逐物質戰術細節」，而是採用 IMO EmS Guide（MSC.1/Circ.1025）
# 總則（General Introduction）中對 F-A ~ F-J 十個「Fire Schedule」代碼本身的
# 官方通則定義（哪一組代碼原則上可用水／不可用水／需特別注意)，這是 EmS Guide
# 架構本身公開、穩定、可查證的通則分類，不是逐物質的公司 SOP 戰術指示。
# 來源：imorules.com 對 IMO EmS Guide 總則 Fire Schedules 的整理（見
# EMS_EXTINGUISH_SOURCE），僅反映「這一組代碼原則上屬於哪種滅火通則」，
# 不含冷卻時間、PPE、確切用量等逐物質戰術細節。
#
# 【嚴格範圍限制，畫面上須明確標示】
#   - 僅為「代碼分組通則」，不是本船／本公司核准之逐物質應變 SOP。
#   - 實際處置仍須查閱船上最新版 EmS Guide 該貨物對應章節，並依船長／
#     大副現場判斷，不得僅依本模組顏色或標籤直接執行滅火作業。
#   - high_risk 標示僅代表「此類 EmS 通則本身含有容易誤判的滅火陷阱
#     （例如誤用水/ 誤撲滅氣體火焰）」，不代表該貨物一定比其他類別危險，
#     也不是 IMDG Code 官方風險分級。
EMS_EXTINGUISH_SOURCE = (
    "IMO EmS Guide（MSC.1/Circ.1025）總則 Fire Schedules F-A~F-J 官方通則定義"
    "（參考 imorules.com 整理版），非本船／本公司核准逐物質 SOP"
)

# medium_hint 意義：
#   "water"          可用水（水霧／水柱）為主要滅火介質
#   "water_caution"  可用水，但需額外持續監控／降溫，並有配載限制（不得艙下）
#   "no_water"       禁止使用水或泡沫，須用乾燥惰性粉末等特殊介質
#   "flame_caution"  以水霧冷卻鄰近容器為主，除非確定氣源已關閉，否則不可逕自
#                     撲滅正在燃燒的氣體火焰（撲滅後未燃氣體外洩恐更危險）
EMS_EXTINGUISH_GUIDANCE = {
    "F-A": {"medium_hint": "water",         "high_risk": False,
            "note_cn": "一般滅火程序，可用水霧／水柱"},
    "F-B": {"medium_hint": "water",         "high_risk": True,
            "note_cn": "爆炸品，可用大量水，但需高度警戒殉爆（火勢蔓延引爆其他爆炸品）風險"},
    "F-C": {"medium_hint": "water_caution", "high_risk": True,
            "note_cn": "非易燃氣體，以水霧冷卻容器為主，注意容器過熱破裂（BLEVE）風險"},
    "F-D": {"medium_hint": "flame_caution", "high_risk": True,
            "note_cn": "易燃氣體，以水霧冷卻鄰近容器，除非確定氣源已關閉，勿逕自撲滅正在燃燒的氣體火焰"},
    "F-E": {"medium_hint": "water",         "high_risk": False,
            "note_cn": "非遇水反應之易燃液體，可用水霧、泡沫、乾粉或 CO2"},
    "F-F": {"medium_hint": "water_caution", "high_risk": True,
            "note_cn": "溫控自反應物質／有機過氧化物，可用大量水但須持續監控降溫，且不得配載於甲板下"},
    "F-G": {"medium_hint": "no_water",      "high_risk": True,
            "note_cn": "遇水反應物質，禁止使用水或泡沫，須用乾燥惰性粉末等特殊滅火介質"},
    "F-H": {"medium_hint": "water",         "high_risk": False,
            "note_cn": "氧化性物質，可用大量水並加強通風"},
    "F-I": {"medium_hint": "water",         "high_risk": False,
            "note_cn": "放射性物質，可用水滅火，但滅火後需留意除污（decontamination）程序"},
    "F-J": {"medium_hint": "water_caution", "high_risk": True,
            "note_cn": "非溫控自反應物質／有機過氧化物，可用水，但不得配載於甲板下"},
}
_UNKNOWN_EXTINGUISH_GUIDANCE = {
    "medium_hint": "unknown", "high_risk": False,
    "note_cn": "查無對應 EmS Fire Code 通則資料，請逕查船上最新版 EmS Guide",
}

# medium_hint → 顯示色（僅供快速辨識滅火介質通則，非風險分級；來源見上方註解）
_EXTINGUISH_MEDIUM_COLOR = {
    "water":         {"hex": "#2E7D32", "text": "#FFFFFF", "label": "🌊 可用水"},
    "water_caution": {"hex": "#F9A825", "text": "#111827", "label": "🌊⚠️ 可用水，需監控／限制配載"},
    "no_water":      {"hex": "#D32F2F", "text": "#FFFFFF", "label": "🚫💧 禁水，需特殊介質（如乾粉）"},
    "flame_caution": {"hex": "#F57C00", "text": "#111827", "label": "🔥⚠️ 冷卻為主，勿逕自撲滅氣體火焰"},
    "unknown":       {"hex": "#6b7280", "text": "#FFFFFF", "label": "⚫ 未知／查無資料"},
}
_HIGH_RISK_BORDER = {"hex": "#DC2626", "width": 4}


def get_ems_extinguish_guidance(fire_code: str) -> dict:
    """
    依 EmS Fire Code 回傳滅火介質通則與高風險標示（見上方模組註解的來源與
    範圍限制；僅為 F-A~F-J 代碼本身的官方通則分類，非逐物質 SOP）。
    """
    if not fire_code:
        return dict(_UNKNOWN_EXTINGUISH_GUIDANCE)
    code = fire_code.strip().upper()
    return dict(EMS_EXTINGUISH_GUIDANCE.get(code, _UNKNOWN_EXTINGUISH_GUIDANCE))


def get_ems_extinguish_legend() -> list[dict]:
    """回傳「滅火介質通則」色標圖例（medium_hint → 顏色／說明），供畫面顯示。"""
    return [
        {"medium_hint": key, **info}
        for key, info in _EXTINGUISH_MEDIUM_COLOR.items()
        if key != "unknown"
    ] + [{"medium_hint": "unknown", **_EXTINGUISH_MEDIUM_COLOR["unknown"]}]


# ══════════════════════════════════════════════════════════════
# ── 「三秒判斷卡」應做／禁止／後續風險（2026-09 第五輪新增）──
# ══════════════════════════════════════════════════════════════
#
# 使用者提供 Bay Plan 視覺化參考圖，圖中有一張「三秒判斷卡：應做／禁止／
# 後續風險」的摘要卡片。務必先讀上方 EMS_EXTINGUISH_GUIDANCE 模組註解的
# 範圍限制說明——本表**不是**新的逐物質戰術資料來源，而是把同一份已核對
# 來源（EMS_EXTINGUISH_SOURCE：IMO EmS Guide 總則 F-A~F-J 官方通則定義）
# 依 medium_hint（僅 5 種分組，非逐物質）拆成「應做／禁止／後續風險」三行，
# 純粹是既有 note_cn 內容的顯示重組，不新增、不臆測任何滅火介質或戰術判斷
# ——刻意避免重蹈 fire_classifier.py 被 fail-closed 停用的錯誤（逐物質、無
# 版本來源的戰術建議，見 docs/INITIAL_SAFETY_AUDIT.md C-3）。
# 三行文字皆維持與 EMS_EXTINGUISH_GUIDANCE.note_cn 一致的保守用語，且畫面
# 上必須與既有免責聲明（EMS_EXTINGUISH_SOURCE、「非本船／本公司核准之逐
# 物質 SOP」）一併顯示，不得單獨呈現本表內容。
_ACTION_CARD_GUIDANCE = {
    "water": {
        "do":    "可用水霧或水柱直接滅火，依一般滅火程序處置",
        "avoid": "無特別禁止項目（仍請確認貨物本身無其他 IMDG 特殊規定）",
        "risk":  "依一般火災程序處置，EmS 通則未特別標示額外風險",
    },
    "water_caution": {
        "do":    "可用大量水滅火，但須持續監控、降溫，並加強現場觀察",
        "avoid": "不得視為一般火災處置後即撤離，須持續監控至完全降溫",
        "risk":  "容器可能因高溫或反應持續發熱，降溫不足恐有復燃或破裂風險",
    },
    "no_water": {
        "do":    "使用乾燥惰性粉末等特殊滅火介質",
        "avoid": "禁止使用水或泡沫滅火",
        "risk":  "使用水或泡沫可能引發劇烈反應，使火勢或危害範圍擴大",
    },
    "flame_caution": {
        "do":    "以水霧冷卻鄰近容器為主，確認氣源已關閉後再處置火勢本身",
        "avoid": "除非確定氣源已關閉，否則勿逕自撲滅正在燃燒的氣體火焰",
        "risk":  "氣源未關閉即撲滅火焰時，外洩氣體可能持續累積，恐有二次爆炸或中毒風險",
    },
    "unknown": {
        "do":    "請逕查船上最新版 EmS Guide 該代碼對應章節",
        "avoid": "查無通則資料前，避免逕自假設可套用一般滅火程序",
        "risk":  "資料不完整，實際風險未知，須由船長／大副依現場狀況判斷",
    },
}


def get_action_card_guidance(fire_code: str) -> dict:
    """
    供畫面「三秒判斷卡」使用：依 EmS Fire Code 回傳
    {"do", "avoid", "risk", "medium_hint", "high_risk", "note_cn"}。
    純粹組合 get_ems_extinguish_guidance() 既有資料，不做任何新判斷
    （見上方模組註解的嚴格範圍限制）。
    """
    guidance = get_ems_extinguish_guidance(fire_code)
    action = _ACTION_CARD_GUIDANCE.get(guidance["medium_hint"], _ACTION_CARD_GUIDANCE["unknown"])
    return {**guidance, **action}


# ══════════════════════════════════════════════════════════════
# ── 位置距離工具（純幾何近似，供「鄰近 DG 貨物」等 deterministic 功能使用）──
# ══════════════════════════════════════════════════════════════

def calc_distance_m(pos_a: str, pos_b: str) -> float | None:
    """
    計算兩個 BBRRTT 位置之間的近似距離（公尺）。以 CELL_WIDTH_M /
    CELL_ROW_M / CELL_HEIGHT_M 做簡化的三維歐氏距離估算，非官方配載圖
    精確距離，僅供快速篩選鄰近貨物參考，不得作為隔離間距合規依據
    （合規判定一律由 segregation_engine.evaluate() 負責）。
    """
    if not (pos_a and pos_b and len(pos_a) == 6 and pos_a.isdigit()
            and len(pos_b) == 6 and pos_b.isdigit()):
        return None
    bay_a, row_a, tier_a = int(pos_a[0:2]), int(pos_a[2:4]), int(pos_a[4:6])
    bay_b, row_b, tier_b = int(pos_b[0:2]), int(pos_b[2:4]), int(pos_b[4:6])
    bay_dist  = abs(bay_a - bay_b)   * CELL_WIDTH_M
    row_dist  = abs(row_a - row_b)   * CELL_ROW_M
    tier_dist = abs(tier_a - tier_b) * CELL_HEIGHT_M
    return (bay_dist ** 2 + row_dist ** 2 + tier_dist ** 2) ** 0.5


def describe_distance(meters: float | None) -> str:
    """把距離（公尺）轉為簡短可讀描述，供 UI 與 AI 情境快照共用。"""
    if meters is None:
        return "未知"
    if meters == 0:
        return "同一位置"
    if meters < 3:
        return f"約 {meters:.1f}m（緊鄰）"
    if meters < 12:
        return f"約 {meters:.1f}m（近距）"
    return f"約 {meters:.1f}m"


def find_nearby_dg(
    cargo_list: list[dict],
    target_position: str,
    radius_m: float = 15.0,
    exclude_container: str | None = None,
) -> list[dict]:
    """
    在目前艙單中，找出目標位置（BBRRTT）指定半徑內的其他 DG 貨物
    （規格書 F-004）。純 deterministic 幾何近似，不涉及任何 AI 判斷。

    Returns:
        依距離由近到遠排序的清單，每筆為
        {"cargo": <原始貨物 dict>, "distance_m": float, "distance_label": str}
    """
    if not target_position or len(target_position) != 6 or not target_position.isdigit():
        return []

    nearby = []
    for c in cargo_list:
        if exclude_container and c.get("container_no") == exclude_container:
            continue
        dist = calc_distance_m(target_position, c.get("position", ""))
        if dist is not None and dist <= radius_m:
            nearby.append({
                "cargo":          c,
                "distance_m":     dist,
                "distance_label": describe_distance(dist),
            })

    nearby.sort(key=lambda x: x["distance_m"])
    return nearby


def get_nearby_segregation_summary(target_cargo: dict, nearby: list[dict]) -> dict:
    """
    針對目標貨物與其鄰近 DG 清單，逐一呼叫 deterministic SegregationEngine
    （segregation_engine.evaluate()）取得隔離狀態。不呼叫任何 LLM，本函式
    本身也不做任何合規判斷——結果一律直接反映 engine 回傳的 status/message
    （目前正式操作模式下一律為 NOT_VERIFIED，見 segregation_engine.py 註解）。

    Returns:
        {
            "checked": [
                {"container_no", "un_number", "hazard_class", "distance_label",
                 "status", "message"}, ...
            ],
            "not_verified": N, "compliant": N, "violation": N,
            "general_ok": N, "general_caution": N,
        }
    """
    un_a    = target_cargo.get("un_number", "")
    class_a = target_cargo.get("hazard_class", "")

    checked = []
    counts  = {"not_verified": 0, "compliant": 0, "violation": 0,
               "general_ok": 0, "general_caution": 0}

    for item in nearby:
        c      = item["cargo"]
        result = evaluate_segregation(
            un_a, class_a, c.get("un_number", ""), c.get("hazard_class", ""),
            distance_m=item.get("distance_m"),
        )
        checked.append({
            "container_no":   c.get("container_no", ""),
            "un_number":      c.get("un_number", ""),
            "hazard_class":   c.get("hazard_class", ""),
            "distance_label": item["distance_label"],
            "status":         result.status.value,
            "message":        result.message,
        })
        if result.status.value == "COMPLIANT":
            counts["compliant"] += 1
        elif result.status.value == "VIOLATION":
            counts["violation"] += 1
        elif result.status.value == "GENERAL_TABLE_OK":
            counts["general_ok"] += 1
        elif result.status.value == "GENERAL_TABLE_CAUTION":
            counts["general_caution"] += 1
        else:
            counts["not_verified"] += 1

    return {"checked": checked, **counts}


def parse_position(pos: str, vessel_id: str | None = None) -> dict | None:
    """
    解析 BBRRTT 位置代碼

    Args:
        pos: 6位數字字串，例如 "010472"
        vessel_id: 選填，指定船舶 ID 以套用該船的 VesselProfile（規格書 3.4）

    Returns:
        {"bay": 1, "row": 4, "tier": 72, "on_deck": True, "on_deck_verified": False,
         "on_deck_message": "..."}
        或 None（格式錯誤）

    甲板／艙內判定：不再使用本模組寫死的門檻（先前為 tier>=70，與 app.py 的
    tier>=80 互相矛盾，見 docs/INITIAL_SAFETY_AUDIT.md C-5），改由
    vessel_profile.classify_tier() 統一判定。找不到該船正式 VesselProfile 時，
    判定結果的 on_deck_verified 為 False，呼叫端必須顯示「未經驗證」提示。
    """
    if not pos or not pos.isdigit() or len(pos) != 6:
        return None
    bay  = int(pos[0:2])
    row  = int(pos[2:4])
    tier = int(pos[4:6])
    deck = classify_tier(tier, vessel_id=vessel_id)
    return {
        "bay":              bay,
        "row":              row,
        "tier":             tier,
        "on_deck":          deck.on_deck,
        "on_deck_verified": deck.verified,
        "on_deck_message":  deck.message,
    }



def get_row_label(row: int) -> str:
    """
    Row 號碼轉可讀標籤（2026-09 第五輪回饋：使用者提供 Bay Plan 視覺化參考
    圖，欄位標題改用簡潔的 P2／P1／CL／S1／S2 樣式，不含原始 Row 數字或
    換行，見 docs/KNOWN_LIMITATIONS.md §7.11.1）。
    00=中心線，奇數=左舷，偶數=右舷。完整數字仍保留在格子 hover tooltip
    與貨物清單「位置」欄位中，僅此處的座標軸標籤簡化。
    """
    if row == 0:
        return "CL"
    elif row % 2 == 1:
        return f"P{(row + 1) // 2}"   # Port 左舷
    else:
        return f"S{row // 2}"          # Starboard 右舷


def get_tier_label(tier: int) -> str:
    """
    Tier 號碼轉可讀標籤（2026-09 第五輪回饋：改為顯示原始 Tier 數字本身，
    不含 D/H 換算層級或換行，對齊使用者提供之參考圖樣式——甲板／艙內已由
    圖表標題與區塊分開顯示，此處座標軸僅需 Tier 原始數字，見
    docs/KNOWN_LIMITATIONS.md §7.11.1）。
    """
    return f"{tier:02d}"



def build_bay_plan(cargo_list: list[dict]) -> dict:
    """
    將貨物清單轉換為 Bay Plan 資料結構

    Args:
        cargo_list: manifest_parser 輸出的標準貨物清單

    Returns:
        {
            3: {                          ← bay number (int)
                "on_deck": {
                    (row, tier): [cargo, ...]   ← 同格子可能多個貨物
                },
                "in_hold": {
                    (row, tier): [cargo, ...]
                }
            },
            ...
        }
    """
    plan = defaultdict(lambda: {"on_deck": defaultdict(list), "in_hold": defaultdict(list)})

    for cargo in cargo_list:
        pos = parse_position(cargo.get("position", ""))
        if pos is None:
            continue

        section = "on_deck" if pos["on_deck"] else "in_hold"
        key     = (pos["row"], pos["tier"])
        plan[pos["bay"]][section][key].append(cargo)

    # 轉為普通 dict（方便序列化）
    return {
        bay: {
            "on_deck": dict(data["on_deck"]),
            "in_hold": dict(data["in_hold"]),
        }
        for bay, data in sorted(plan.items())
    }


def get_cell_display(cargos: list[dict], color_mode: str = "ems") -> dict:
    """
    計算單一格子的顯示資訊（可能有多個貨物共用格子）。

    主要貨物排序邏輯：待選列（AMBIGUOUS，requires_variant_selection=true）
    優先顯示，因為這類貨物的 Packing Group／積載類別尚未確定，最需要人工
    優先處理；同狀態則依 Class 字串排序，確保多次渲染結果穩定一致。
    （先前依 fire_color 紅/黃/綠排序：fire_classifier 現一律 fail-closed
    回傳 grey，該排序已無意義，已移除，見 docs/INITIAL_SAFETY_AUDIT.md C-3）

    color_mode:
        "ems"        （預設）依 EmS Fire Code（F-A ~ F-J）上色，回應使用者需求
                     「Bay plan 請根據 EMS 處理方式進行顏色的區隔」（見
                     get_ems_fire_color() 註解：僅依代碼分組視覺辨識，不透露
                     滅火介質，也不代表風險等級）。
        "class"      依危險品 Class 上色（見 get_class_color()），沿用先前版本。
        "extinguish" 2026-09 新增：依「滅火介質通則」（可用水／需監控／禁水／
                     勿逕自撲滅氣體火焰）上色，回應使用者需求「應該要區分像是
                     可用水 / CO2滅火，甚至高危險的類別要特別標示」；來源與
                     嚴格範圍限制見 get_ems_extinguish_guidance() 模組註解
                     （僅 F-A~F-J 代碼通則，非逐物質 SOP，仍須查閱船上 EmS
                     Guide 及船長判斷）。
    格內含待選列貨物時，以橘色粗邊框標示（不使用紅色，避免與「高風險」混淆）；
    color_mode="extinguish" 時，若主要貨物屬於 high_risk 通則分組，改以紅色
    粗邊框特別標示（見 get_ems_extinguish_guidance()），優先於待選列邊框顯示。
    """
    if not cargos:
        return None

    primary = min(
        cargos,
        key=lambda c: (0 if c.get("requires_variant_selection") else 1,
                       c.get("hazard_class", "") or "")
    )
    has_ambiguous = any(c.get("requires_variant_selection") for c in cargos)
    extinguish_guidance = None
    if color_mode == "class":
        color = get_class_color(primary.get("hazard_class", ""))
    elif color_mode == "extinguish":
        extinguish_guidance = get_ems_extinguish_guidance(primary.get("fire_ems", ""))
        color = _EXTINGUISH_MEDIUM_COLOR[extinguish_guidance["medium_hint"]]
    else:
        color = get_ems_fire_color(primary.get("fire_ems", ""))

    is_high_risk = bool(extinguish_guidance and extinguish_guidance["high_risk"])

    # ── 格子內文字：貨櫃號碼後7碼 + 位置碼 + UN ──────────────
    # 取主要貨物完整顯示，多筆時加 +N more；含待選列貨物時額外標示
    pos = primary.get("position", "")

    if len(cargos) == 1:
        label = (
            f"{primary['container_no'][-7:]}\n"   # 貨櫃號後7碼
            f"{pos}\n"                              # 位置碼 BBRRTT
            f"UN{primary['un_number']}"             # UN號
        )
    else:
        label = (
            f"{primary['container_no'][-7:]}\n"
            f"{pos}\n"
            f"UN{primary['un_number']}\n"
            f"+{len(cargos)-1} more"
        )
    if color_mode == "ems" and primary.get("fire_ems"):
        label += f"\n{primary['fire_ems']}"
    if color_mode == "extinguish" and primary.get("fire_ems"):
        label += f"\n{primary['fire_ems']}"
        if is_high_risk:
            label += " ⚠️高風險"
    if has_ambiguous:
        label += "\n📝 待確認品名"

    # ── Hover Tooltip：完整資訊（含 Fire／Spill EmS Code，先前遺漏 Spill）──
    tooltip_parts = []
    for c in cargos:
        c_pos    = c.get("position", "—")
        amb_flag = " 📝待確認品名" if c.get("requires_variant_selection") else ""
        tooltip_parts.append(
            f"📦 {c['container_no']}<br>"
            f"位置：{c_pos}<br>"
            f"UN{c['un_number']} | Class {c['hazard_class']}{amb_flag}<br>"
            f"EmS：Fire {c.get('fire_ems') or '—'} / Spill {c.get('spill_ems') or '—'}<br>"
            f"品名：{c['description'][:30] if c['description'] else '—'}"
        )
    tooltip = "<br>─────<br>".join(tooltip_parts)
    if is_high_risk:
        tooltip += (
            f"<br>─────<br>⚠️ <b>高風險 EmS 通則分組</b>："
            f"{extinguish_guidance['note_cn']}"
        )

    if is_high_risk:
        border_hex, border_width = _HIGH_RISK_BORDER["hex"], _HIGH_RISK_BORDER["width"]
    elif has_ambiguous:
        border_hex, border_width = "#f59e0b", 3
    else:
        border_hex, border_width = "#334155", 1

    return {
        "color_hex":     color["hex"],
        "text_color":    color["text"],
        "border_hex":    border_hex,
        "border_width":  border_width,
        "has_ambiguous": has_ambiguous,
        "is_high_risk":  is_high_risk,
        "label":         label,
        "tooltip":       tooltip,
        "count":         len(cargos),
        "cargos":        cargos,
        # 2026-09 第五輪新增（見 docs/KNOWN_LIMITATIONS.md §7.11.2）：暴露
        # 主要貨物本身，供 app.py 需要「僅顯示 UN 號碼」等更精簡格內文字
        # 樣式時直接取用，不需重新實作一次「同格多貨物選主要貨物」的排序
        # 邏輯；既有的 "label"／"tooltip" 完整格式維持不變，向下相容。
        "primary":       primary,
    }



def _row_physical_sort_key(row: int) -> int:
    """
    依「離中心線的實際左右位置」排序 Row，而非原始 Row 編號本身
    （00=CL, 奇數=左舷 Port, 偶數=右舷 Starboard——原始編號本身不會照
    實際左右順序排列，例如 01(P1)/02(S1)/03(P2)/04(S2) 若直接依數字排序
    會得到 CL, P1, S1, P2, S2，物理上錯亂）。

    2026-09 第五輪回饋（見 docs/KNOWN_LIMITATIONS.md §7.11.1）：使用者
    提供的 Bay Plan 視覺化參考圖，欄位由左至右為 P2, P1, CL, S1, S2，
    即「左舷由外而內、中心線、右舷由內而外」的實際物理順序，本函式回傳
    可用於排序的整數 key（左舷為負、中心線為 0、右舷為正，依離中心線
    格數遞增）以重現此順序，供 get_bay_dimensions() 使用。
    """
    if row == 0:
        return 0
    elif row % 2 == 1:
        return -((row + 1) // 2)   # Port 左舷：負值，離中心線越遠越小
    else:
        return row // 2            # Starboard 右舷：正值，離中心線越遠越大


def get_bay_dimensions(bay_data: dict) -> dict:
    """
    計算單一 Bay 的格子範圍（用於繪圖座標）

    Returns:
        {
            "rows":  依實際左右物理順序排列的 row 清單（左舷→中心線→右舷，
                     見 _row_physical_sort_key()，非原始 Row 編號大小）,
            "tiers_deck": 排序後的甲板 tier 清單（由下到上）,
            "tiers_hold": 排序後的艙內 tier 清單（由下到上）,
        }
    """
    all_rows        = set()
    tiers_deck      = set()
    tiers_hold      = set()

    for (row, tier) in bay_data["on_deck"]:
        all_rows.add(row)
        tiers_deck.add(tier)
    for (row, tier) in bay_data["in_hold"]:
        all_rows.add(row)
        tiers_hold.add(tier)

    return {
        "rows":        sorted(all_rows, key=_row_physical_sort_key),
        "tiers_deck":  sorted(tiers_deck),        # 甲板由低到高
        "tiers_hold":  sorted(tiers_hold),         # 艙內由低到高
    }


def get_plan_statistics(bay_plan: dict) -> dict:
    """
    統計 Bay Plan 中的類別分布、待選列數量與甲板／艙內分布。

    先前依 fire_color（紅/黃/綠/灰）統計：fire_classifier 現一律 fail-closed
    回傳 grey，該統計已無意義，已改為依「危險品類別（Class）」與「待選列
    （AMBIGUOUS）」統計，較貼近實際使用情境——大副／船副想快速掌握的是
    「這艘船裝了哪些類別、各幾櫃、有幾櫃還沒選列正式品名」，而非早已停用
    的滅火色碼分布（見 docs/INITIAL_SAFETY_AUDIT.md C-3）。

    2026-09 新增 high_risk 統計：依 get_ems_extinguish_guidance() 之官方
    F-A~F-J 通則分組計算，僅代表「該 EmS 通則本身含有容易誤判的滅火陷阱」，
    範圍限制與來源見該函式模組註解，非逐物質風險分級。

    Returns:
        {"total_bays": N, "total_cargo": N, "by_class": {class: count, ...}
         （依數量由多到少排序）, "ambiguous": N, "on_deck": N, "in_hold": N,
         "high_risk_extinguish": N}
    """
    class_counter = Counter()
    fire_counter  = Counter()
    ambiguous     = 0
    on_deck_count = 0
    in_hold_count = 0
    total_cargo   = 0
    high_risk     = 0

    for bay_data in bay_plan.values():
        for section in ("on_deck", "in_hold"):
            for cargos in bay_data[section].values():
                for cargo in cargos:
                    total_cargo += 1
                    class_counter[cargo.get("hazard_class") or "未知"] += 1
                    fire_counter[cargo.get("fire_ems") or "未知"] += 1
                    if cargo.get("requires_variant_selection"):
                        ambiguous += 1
                    if get_ems_extinguish_guidance(cargo.get("fire_ems", ""))["high_risk"]:
                        high_risk += 1
                    if section == "on_deck":
                        on_deck_count += 1
                    else:
                        in_hold_count += 1

    return {
        "total_bays":           len(bay_plan),
        "total_cargo":          total_cargo,
        "by_class":             dict(class_counter.most_common()),
        "by_fire_code":         dict(fire_counter.most_common()),
        "ambiguous":            ambiguous,
        "on_deck":              on_deck_count,
        "in_hold":              in_hold_count,
        "high_risk_extinguish": high_risk,
    }
