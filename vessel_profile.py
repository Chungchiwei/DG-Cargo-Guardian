# ============================================================
# 🚢 vessel_profile.py — VesselProfile（甲板／艙內判定）
# ============================================================
#
# 規格書 3.4 / docs/INITIAL_SAFETY_AUDIT.md C-5：
#   甲板／艙內（on-deck / under-deck）判定必須依「特定船舶」的 VesselProfile
#   （bay/row/tier 合法範圍、deck/hold boundary、hatch/hold mapping 等），不得用
#   全船通用的寫死門檻猜測，也不得宣稱「所有危險品均積載於甲板」——先前
#   bay_plan_engine.py 用 tier>=70、app.py 用 tier>=80，兩者互相矛盾，已在此統一。
#
# 目前狀態：專案尚未取得任何船舶的正式 VesselProfile（General Arrangement /
# Capacity Plan 等公司或船舶提供資料）。本模組提供：
#   1. register_profile() / get_profile()：供未來匯入公司核准的 VesselProfile。
#   2. classify_tier()：統一、單一來源的甲板／艙內判定。找不到指定船舶的正式
#      VesselProfile 時，使用一個「通用推測」門檻並明確標記 verified=False，
#      呼叫端必須將此狀態顯示給使用者（「未經驗證，僅供參考」），不得當作
#      合規依據，也不得宣稱涵蓋「所有」危險品。
#
# 需要哪些資料才能完成本模組的正式版本，見 docs/CONTROLLED_SOURCES.md。

from dataclasses import dataclass
from typing import Optional

NOT_VERIFIED_DECK_MESSAGE = (
    "⚠️ 尚未載入本船 VesselProfile，甲板／艙內判定為通用推測結果，未經驗證，"
    "僅供參考，不得作為積載或應變決策依據，請以船舶實際配載圖（General Arrangement /"
    " Capacity Plan）為準。"
)


@dataclass
class VesselProfile:
    vessel_id: str
    vessel_name: str
    version: str
    approved_by: str
    effective_date: str
    deck_tier_threshold: int          # tier >= 此值視為甲板（該船專屬門檻）
    bay_range: tuple = (0, 99)
    row_range: tuple = (0, 99)
    tier_range: tuple = (0, 99)


@dataclass
class DeckClassification:
    on_deck: Optional[bool]
    verified: bool
    message: str


# 通用推測門檻：非任何特定船舶的正式資料，僅作為找不到 VesselProfile 時的
# fail-closed 佔位邏輯，統一先前 70（bay_plan_engine.py）與 80（app.py /
# ai_analyzer.py）兩種互相矛盾的寫死門檻。
_GENERIC_FALLBACK_DECK_TIER_THRESHOLD = 70

_PROFILES: dict = {}  # 由公司核准後於此登錄（vessel_id -> VesselProfile）


def register_profile(profile: VesselProfile) -> None:
    """登錄一份公司核准的 VesselProfile。目前專案尚無任何正式資料可登錄。"""
    _PROFILES[profile.vessel_id] = profile


def get_profile(vessel_id: Optional[str]) -> Optional[VesselProfile]:
    if not vessel_id:
        return None
    return _PROFILES.get(vessel_id)


def classify_tier(tier: int, vessel_id: Optional[str] = None) -> DeckClassification:
    """
    判定給定 tier 是否為甲板（on-deck）。

    若指定船舶已有正式 VesselProfile，使用該船專屬門檻並標記 verified=True；
    否則使用統一的通用推測門檻，並明確標記 verified=False。
    """
    profile = get_profile(vessel_id)
    if profile is not None:
        return DeckClassification(
            on_deck=tier >= profile.deck_tier_threshold,
            verified=True,
            message=(
                f"依船舶 {profile.vessel_name}（{profile.vessel_id}）"
                f"VesselProfile v{profile.version} 判定"
            ),
        )

    return DeckClassification(
        on_deck=tier >= _GENERIC_FALLBACK_DECK_TIER_THRESHOLD,
        verified=False,
        message=NOT_VERIFIED_DECK_MESSAGE,
    )
