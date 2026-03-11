# ============================================================
# 🔥 fire_classifier.py — EMS 滅火介質分類引擎
# ============================================================

# ── EMS Fire Code 對應分類表 ─────────────────────────────────
# 來源：IMDG Code EMS Guide（F-A 至 F-J）
# 顏色語意：
#   green  → 可用大量水
#   yellow → 非水介質（乾粉/CO2/泡沫）
#   red    → 禁水 / 高危
#   grey   → 查無資料

FIRE_CATEGORY_MAP = {
    "F-A": {
        "color":       "green",
        "color_hex":   "#22c55e",
        "label":       "可用水",
        "media":       "大量水 (Copious quantities of water)",
        "do":          "使用水霧或水柱直接滅火，大量冷卻鄰近容器",
        "dont":        "避免在密閉空間內使用，注意蒸氣燙傷",
        "risk_after":  "燃燒產物可能含有毒煙霧，保持上風處",
    },
    "F-B": {
        "color":       "yellow",
        "color_hex":   "#eab308",
        "label":       "非水介質",
        "media":       "乾粉 / CO2 / 抗溶性泡沫 (Dry chemical / CO2 / AR-AFFF)",
        "do":          "使用乾粉、CO2 或抗溶性泡沫，冷卻鄰近容器",
        "dont":        "避免直射水流，可能導致液體飛濺擴大污染範圍",
        "risk_after":  "注意殘餘蒸氣，保持通風",
    },
    "F-C": {
        "color":       "green",
        "color_hex":   "#22c55e",
        "label":       "可用水",
        "media":       "大量水 (Copious quantities of water) / 泡沫",
        "do":          "大量水冷卻，可使用泡沫輔助",
        "dont":        "避免人員進入濃煙區域",
        "risk_after":  "注意燃燒後殘留物的毒性",
    },
    "F-D": {
        "color":       "yellow",
        "color_hex":   "#eab308",
        "label":       "非水介質",
        "media":       "乾粉 / CO2 (Dry chemical / CO2)",
        "do":          "使用乾粉或 CO2，從上風側接近",
        "dont":        "禁止直射水，可能引起劇烈反應",
        "risk_after":  "確認無復燃風險後方可撤離",
    },
    "F-E": {
        "color":       "green",
        "color_hex":   "#22c55e",
        "label":       "可用水",
        "media":       "大量水 / 泡沫 (Water / Foam)",
        "do":          "大量水冷卻容器，防止 BLEVE",
        "dont":        "避免在無防護情況下接近高溫容器",
        "risk_after":  "容器冷卻後仍需持續監控",
    },
    "F-G": {
        "color":       "yellow",
        "color_hex":   "#eab308",
        "label":       "非水介質",
        "media":       "乾粉 / CO2 / 惰性氣體 (Dry chemical / CO2 / Inert gas)",
        "do":          "使用乾粉或惰性氣體，隔絕氧氣",
        "dont":        "禁止用水，可能產生有毒或易燃氣體",
        "risk_after":  "保持密封，防止空氣進入引發復燃",
    },
    "F-H": {
        "color":       "yellow",
        "color_hex":   "#eab308",
        "label":       "非水介質",
        "media":       "乾粉 / CO2 (Dry chemical / CO2)",
        "do":          "使用乾粉或 CO2，控制燃燒範圍",
        "dont":        "禁止使用泡沫或水，可能加劇反應",
        "risk_after":  "注意有毒燃燒產物，佩戴 CABA",
    },
    "F-I": {
        "color":       "red",
        "color_hex":   "#ef4444",
        "label":       "⛔ 禁水",
        "media":       "乾砂 / 特殊乾粉 (Dry sand / Special dry powder)",
        "do":          "使用乾砂或特殊乾粉覆蓋，隔離熱源",
        "dont":        "⛔ 嚴禁用水！遇水產生易燃/有毒氣體",
        "risk_after":  "確保完全冷卻，防止復燃，通知岸上專業人員",
    },
    "F-J": {
        "color":       "red",
        "color_hex":   "#ef4444",
        "label":       "⛔ 禁水/高危",
        "media":       "隔離疏散，禁止滅火 (Evacuate / Do not fight fire)",
        "do":          "立即疏散所有人員，隔離區域，冷卻鄰近容器",
        "dont":        "⛔ 禁止任何人員接近！可能爆炸或釋放劇毒氣體",
        "risk_after":  "請求岸上 HAZMAT 專業支援，不得自行處置",
    },
    "F-F": {
        "color":       "red",
        "color_hex":   "#ef4444",
        "label":       "⛔ 禁水",
        "media":       "乾砂 / 乾粉 (Dry sand / Dry powder)",
        "do":          "使用乾砂覆蓋，防止擴散",
        "dont":        "⛔ 嚴禁用水！可能引發爆炸性反應",
        "risk_after":  "保持現場乾燥，等待專業處置",
    },
}

# ── 顏色顯示優先順序（用於多貨混合格子）────────────────────
COLOR_PRIORITY = {"red": 0, "yellow": 1, "green": 2, "grey": 3}


def classify_fire_category(fire_ems_code: str) -> dict:
    """
    輸入 EMS Fire Code（如 "F-A"），回傳完整分類資訊

    Returns:
        dict with keys: color, color_hex, label, media, do, dont, risk_after
    """
    code = fire_ems_code.strip().upper() if fire_ems_code else "UNKNOWN"
    return FIRE_CATEGORY_MAP.get(code, {
        "color":       "grey",
        "color_hex":   "#6b7280",
        "label":       "未知",
        "media":       f"查無 {code} 對應資料，請查閱 IMDG EMS 手冊",
        "do":          "依 IMDG EMS 手冊操作",
        "dont":        "不確定時，切勿貿然行動",
        "risk_after":  "聯繫 CHEMTREC (+1-703-527-3887) 取得專業建議",
    })


def get_dominant_color(fire_codes: list[str]) -> dict:
    """
    多個 EMS Code 共存時，取最高風險顏色
    例如：["F-A", "F-I"] → 回傳 red（F-I 優先）

    Args:
        fire_codes: EMS Fire Code 清單

    Returns:
        最高風險的分類 dict
    """
    if not fire_codes:
        return classify_fire_category("UNKNOWN")

    best = None
    best_priority = 999

    for code in fire_codes:
        cat = classify_fire_category(code)
        p   = COLOR_PRIORITY.get(cat["color"], 999)
        if p < best_priority:
            best_priority = p
            best = cat

    return best


def get_color_legend() -> list[dict]:
    """
    回傳圖例資料，供 UI 顯示色標說明

    Returns:
        [{"color_hex": ..., "label": ..., "media": ...}, ...]
    """
    return [
        {
            "color_hex": "#22c55e",
            "label":     "🟢 可用水",
            "media":     "大量水 / 水霧 / 泡沫",
            "example":   "F-A, F-C, F-E",
        },
        {
            "color_hex": "#eab308",
            "label":     "🟡 非水介質",
            "media":     "乾粉 / CO2 / 抗溶性泡沫",
            "example":   "F-B, F-D, F-G, F-H",
        },
        {
            "color_hex": "#ef4444",
            "label":     "🔴 禁水 / 高危",
            "media":     "乾砂 / 特殊粉末 / 疏散",
            "example":   "F-F, F-I, F-J",
        },
        {
            "color_hex": "#6b7280",
            "label":     "⚫ 未知",
            "media":     "請查閱 IMDG EMS 手冊",
            "example":   "查無資料",
        },
    ]
