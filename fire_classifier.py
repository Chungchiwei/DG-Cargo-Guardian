# ============================================================
# 🔥 fire_classifier.py — EmS Fire Code 顯示模組（fail-closed 版）
# ============================================================
#
# 安全變更紀錄（見 docs/INITIAL_SAFETY_AUDIT.md C-3，規格書 3.1）：
#   本模組原本把 EmS Fire Code（F-A ~ F-J）直接對應到「顏色 / 滅火介質 / do&dont /
#   冷卻時間」等具體操作建議，但這些內容並非官方 EmS Guide 原文，沒有文件名稱、版本、
#   章節頁碼、生效日期、公司核准日期與 SHA-256，屬於未經核准的安全關鍵判斷，已全面停用。
#
#   在公司匯入經核准的 2024 EmS Supplement 結構化資料（含上述版本／來源欄位）之前，
#   本模組僅保留並顯示原始 F-code，不再產生任何滅火介質、PPE、冷卻時間或 do/dont 建議。
#   顏色僅代表「資料狀態」（灰色 = 未經驗證），不代表危險程度，也不得被解讀為安全與否
#   （規格書 3.5：不得用綠色暗示危險品「安全」）。

NOT_VERIFIED_MESSAGE = "目前僅確認 EmS code。詳細處置請查閱船上最新版 EmS Guide 及船舶應急計畫。"

# 系統狀態灰階（規格書 3.5：顏色只能表達系統狀態，不得暗示風險等級或安全與否）
STATUS_COLOR     = "grey"
STATUS_COLOR_HEX = "#6b7280"


def classify_fire_category(fire_ems_code: str) -> dict:
    """
    輸入 EmS Fire Code（如 "F-A"），回傳 fail-closed 的顯示資訊。

    不再輸出滅火介質、do/dont、冷卻時間等未經核准內容——這些欄位在核准資料匯入前
    一律為空字串，僅保留 code 本身與統一的「未經驗證」提示（見 NOT_VERIFIED_MESSAGE）。

    Returns:
        dict with keys: color, color_hex, label, media, do, dont, risk_after, verified
    """
    code = fire_ems_code.strip().upper() if fire_ems_code else ""

    if not code or code == "UNKNOWN":
        return {
            "color":      STATUS_COLOR,
            "color_hex":  STATUS_COLOR_HEX,
            "label":      "查無 EmS Fire Code",
            "media":      "",
            "do":         "",
            "dont":       "",
            "risk_after": NOT_VERIFIED_MESSAGE,
            "verified":   False,
        }

    return {
        "color":      STATUS_COLOR,
        "color_hex":  STATUS_COLOR_HEX,
        "label":      f"EmS {code}",
        "media":      "",
        "do":         "",
        "dont":       "",
        "risk_after": NOT_VERIFIED_MESSAGE,
        "verified":   False,
    }


def get_dominant_color(fire_codes: list[str]) -> dict:
    """
    保留函式介面相容性（供 bay_plan_engine.py 等呼叫）。
    由於顏色不再代表風險等級，多個 EmS Code 共存時不做風險排序，僅回傳第一個
    有效 code 的顯示資訊（皆為統一的「未經驗證」狀態）。
    """
    if not fire_codes:
        return classify_fire_category("")
    for code in fire_codes:
        if code:
            return classify_fire_category(code)
    return classify_fire_category("")


def get_color_legend() -> list[dict]:
    """
    回傳圖例資料。顏色僅代表系統資料狀態，不代表滅火介質或風險等級（規格書 3.5）。
    """
    return [
        {
            "color_hex": STATUS_COLOR_HEX,
            "label":     "⚫ 未經驗證（EmS 詳細指令待核准資料匯入）",
            "media":     NOT_VERIFIED_MESSAGE,
            "example":   "所有 EmS Fire Code（F-A ~ F-J）目前皆為此狀態",
        },
    ]
