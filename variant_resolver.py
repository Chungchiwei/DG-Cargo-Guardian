# ============================================================
# 🧭 variant_resolver.py — 正式品名（Variant）選列引擎
# ============================================================
#
# 規格書 3.2 / docs/INITIAL_SAFETY_AUDIT.md C-4：
#   imdg_database.json 中 requires_variant_selection=true 的項目（本資料庫 198 筆中
#   共 47 筆）代表同一 UN Number 依實際 Proper Shipping Name、濃度／組成、Class、
#   副危險、Packing Group、Marine Pollutant、閃點、special provision、包裝型式等
#   欄位可能對應多筆不同的官方分類（official_variants），不得自動選第一筆或任何
#   「代表值」。本模組為 deterministic：不呼叫任何 LLM，不做任何猜測，相同輸入永遠
#   得到相同輸出，所有分支皆 fail closed。

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from database import get_by_un_number


class VariantStatus(str, Enum):
    UNKNOWN_UN        = "UNKNOWN_UN"         # 資料庫查無此 UN Number
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # 缺少必要欄位，無法判斷
    AMBIGUOUS         = "AMBIGUOUS"          # requires_variant_selection=true 且尚未選列
    RESOLVED          = "RESOLVED"           # 已唯一確定正式品名（免選列，或已完成選列）


@dataclass
class VariantResolution:
    status: VariantStatus
    un_number: str
    entry: Optional[dict] = None                     # 原始資料庫 entry（含 official_variants）
    candidates: list = field(default_factory=list)    # AMBIGUOUS 時的候選 official_variants
    selected_variant: Optional[dict] = None           # RESOLVED 後的正式 variant（如僅一筆）
    message: str = ""

    def is_fail_closed(self) -> bool:
        """除 RESOLVED 外，其餘狀態皆代表尚不能顯示確定的 EmS／stowage／segregation 內容。"""
        return self.status != VariantStatus.RESOLVED


@dataclass
class VariantSelectionRecord:
    """人工選列（或 override）的稽核紀錄，供上層寫入稽核系統（規格書 3.2.8/3.2.9、4.4）。"""
    un_number: str
    selected_index: int
    selected_variant: dict
    reason: str
    selected_by: str
    selected_at: str
    manifest_row_ref: Optional[dict] = None
    is_override: bool = False


REQUIRED_FIELDS_FOR_RESOLUTION = ("proper_shipping_name", "class")


def resolve_variant(un_number: str) -> VariantResolution:
    """
    依 UN Number 解析正式品名狀態。永遠 fail closed：
      - 查無資料               → UNKNOWN_UN
      - 缺少必要欄位           → INSUFFICIENT_DATA
      - requires_variant_selection=true → AMBIGUOUS（附上全部候選 official_variants）
      - 其餘（唯一或不需選列） → RESOLVED
    """
    entry = get_by_un_number(un_number)
    if not entry:
        return VariantResolution(
            status=VariantStatus.UNKNOWN_UN,
            un_number=un_number,
            message=f"資料庫查無 {un_number}，請確認 UN Number 是否正確，或查閱船上最新版 IMDG Code。",
        )

    missing = [
        f for f in REQUIRED_FIELDS_FOR_RESOLUTION
        if not entry.get(f) or entry.get(f) == "Unknown"
    ]
    if missing:
        return VariantResolution(
            status=VariantStatus.INSUFFICIENT_DATA,
            un_number=un_number,
            entry=entry,
            message=(
                f"{un_number} 資料缺少必要欄位（{', '.join(missing)}），"
                "無法確認正式品名，請查閱船上最新版 IMDG Code。"
            ),
        )

    requires_selection = bool(entry.get("requires_variant_selection"))
    variants = entry.get("official_variants") or []

    if requires_selection:
        if not variants:
            return VariantResolution(
                status=VariantStatus.INSUFFICIENT_DATA,
                un_number=un_number,
                entry=entry,
                message=(
                    f"{un_number} 標記為需要選列（requires_variant_selection），"
                    "但資料庫未提供 official_variants，無法選列。"
                ),
            )
        return VariantResolution(
            status=VariantStatus.AMBIGUOUS,
            un_number=un_number,
            entry=entry,
            candidates=variants,
            message=(
                entry.get("variant_selection_hint")
                or "此 UN Number 有多筆正式品名，請依 Proper Shipping Name、濃度／組成、"
                   "Packing Group、副危險性及貨物文件（SDS／Dangerous Goods Declaration）"
                   "選擇正確項目。"
            ),
        )

    # 不需要選列：僅有一筆 variant 時視為 RESOLVED 並帶出該筆；無 variant 陣列亦視為
    # RESOLVED（使用頂層代表資料，該資料本身已由資料治理流程驗證為單一分類）。
    selected = variants[0] if len(variants) == 1 else None
    return VariantResolution(
        status=VariantStatus.RESOLVED,
        un_number=un_number,
        entry=entry,
        selected_variant=selected,
        message="",
    )


def record_selection(
    un_number: str,
    selected_index: int,
    candidates: list,
    reason: str,
    selected_by: str,
    manifest_row_ref: Optional[dict] = None,
    is_override: bool = False,
) -> VariantSelectionRecord:
    """
    建立一筆人工選列／override 的稽核紀錄。本函式本身不寫檔，只負責建立結構化紀錄；
    呼叫端須將回傳值寫入稽核系統（Phase 2 audit log）。理由留空或索引超出範圍時
    直接拋出例外（fail closed），不得靜默略過（規格書 3.2.9）。
    """
    if not reason or not reason.strip():
        raise ValueError("人工選列／override 必須輸入理由，不得留空（規格書 3.2.9）。")
    if not (0 <= selected_index < len(candidates)):
        raise ValueError(f"選列索引超出範圍：{selected_index}（候選數：{len(candidates)}）。")

    return VariantSelectionRecord(
        un_number=un_number,
        selected_index=selected_index,
        selected_variant=candidates[selected_index],
        reason=reason.strip(),
        selected_by=selected_by,
        selected_at=datetime.now(timezone.utc).isoformat(),
        manifest_row_ref=manifest_row_ref,
        is_override=is_override,
    )
