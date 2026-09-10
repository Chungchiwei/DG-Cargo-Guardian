# ============================================================
# 🧯 segregation_engine.py — Deterministic Segregation Engine
# ============================================================
#
# 規格書 3.3 / docs/INITIAL_SAFETY_AUDIT.md C-1：
#   隔離規則改為版本化、可重現、附帶 rule ID 的 deterministic engine，不使用 LLM
#   進行法規判定。缺少正式隔離表或特殊條款資料時，結果必須是 NOT_VERIFIED，不得由
#   模型補足或猜測。AI 只能將本引擎已完成的結果轉成較容易理解的文字，不能改變、
#   覆寫或重新判斷結果（見 ai_analyzer.py 的對應變更）。
#
# 2026-09 變更（見 docs/KNOWN_LIMITATIONS.md §7.7，回應使用者需求「請幫我搜尋
# 網路上最新的隔離表並把規則加入」，使用者已明確選擇「採用，但清楚標示涵蓋
# 範圍」）：
#   新增「一般類別對類別隔離表」（GENERAL_TABLE_*）。資料來源與涵蓋範圍：
#   - 矩陣結構與數值交叉核對自美國聯邦公開法規 49 CFR §176.83(b)（US DOT
#     Hazardous Materials Regulations，美國政府著作，屬公開領域資料），其
#     class-to-class 隔離矩陣結構與 IMDG Code Chapter 7.2.4 一般隔離表一致
#     （兩者皆源自 UN Model Regulations 的危險品分級隔離架構，美國載運危險品
#     海運規則明文與 IMDG Code 對齊）。
#   - 僅涵蓋「危險品類別對類別」的一般規則（代碼 X / 1 / 2 / 3 / 4，分別對應
#     「無需隔離／away from／separated from／separated by a complete
#     compartment or hold from／separated longitudinally by an intervening
#     complete compartment or hold from」），**不包含**逐物質的 SG／SGG 特殊
#     隔離代碼覆寫規定（IMDG Code 7.2.5，須完整 Dangerous Goods List 第16欄
#     結構化資料，本系統目前沒有），**不包含** Class 1 爆炸品的專屬隔離表
#     （IMDG Code 7.2.7，規則另成一表，本系統以 NOT_VERIFIED 處理）。
#   - 因此 GENERAL_TABLE_OK / GENERAL_TABLE_CAUTION 兩個新狀態，明確與既有
#     COMPLIANT / VIOLATION（保留給「公司核准之完整 Amendment 42-24 逐物質
#     結構化資料」使用，目前尚未取得，故實務上仍不會出現）區隔，避免使用者
#     把「一般規則概略判斷」誤認為「正式合規判定」——is_authoritative() 對
#     GENERAL_TABLE_* 一律回傳 False。
#   - 距離判斷僅依呼叫端提供的概略幾何距離（Bay/Row/Tier 座標推算，見
#     bay_plan_engine.calc_distance_m()），不是真實艙間水密艙壁／艙口蓋等
#     物理邊界驗證，也未區分同艙 vs 不同艙、甲板 vs 艙內的規則差異
#     （代碼 3／4 實際上要求「以完整艙區隔開」而非單純距離），因此僅供
#     「概略提醒」，正式判定仍須依船上核准之 Segregation Table 及大副／
#     船長現場確認。
#
# 2026-09 第三輪回饋（見 docs/KNOWN_LIMITATIONS.md §7.9.1）：使用者上傳公司
# 文件「附表三 危險品隔離表」，要求加入積載隔離檢查頁面供人工同步核對。逐格
# 比對後確認：該文件的 17×17 類別矩陣數值與本模組既有的 GENERAL_TABLE（原
# 交叉核對自 49 CFR §176.83(b)）**完全一致**，等於是同一份「Class 對 Class
# 一般隔離表」的另一來源佐證，並未發現任何差異。因此本次**不需**修改矩陣
# 數值本身，僅新增下方 `GENERAL_TABLE_ROW_LABELS` 等顯示用中文欄位標籤，
# 並在 `app.py` 積載隔離檢查頁新增「📋 附表三 危險品隔離表」原文對照表與
# 逐組結果的代碼對照列——**純顯示既有資料，不改變 evaluate() 判斷邏輯**，
# `GENERAL_TABLE_OK` / `GENERAL_TABLE_CAUTION` 等狀態仍非公司核准之正式
# 判定，`is_authoritative()` 對其仍恆為 False（見下方 §「顯示用中文標籤」）。
#
# 目前狀態：專案內尚未取得合法授權且經公司核准的 Amendment 42-24 Segregation Table
# 與特殊條款結構化資料，因此 COMPLIANT / VIOLATION 兩個狀態實務上不會被觸發。
# TEST_MODE 下才會套用明確標示 TEST_FIXTURE_NOT_FOR_OPERATION 的虛構測試規則，
# 僅供 pytest 驗證 engine 的資料流與 schema，正式操作模式絕不載入。
# 需要哪些正式資料才能完成，見 docs/KNOWN_LIMITATIONS.md。

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

ENGINE_VERSION   = "0.2.0-general-table"
REGULATION_BASIS = "IMDG Code 2024 Edition, Amendment 42-24 (effective 2026-01-01)"
GENERAL_TABLE_SOURCE = (
    "一般類別隔離表：結構與數值交叉核對自 49 CFR §176.83(b)（美國聯邦公開法規，"
    "與 IMDG Code 7.2.4 一般隔離表結構一致），並經使用者提供之公司文件「附表三 "
    "危險品隔離表」逐格比對確認數值一致（2026-09）；僅供概略提醒，非公司核准之"
    "正式資料"
)


class SegregationStatus(str, Enum):
    NOT_VERIFIED = "NOT_VERIFIED"  # 缺少正式隔離表資料，無法判斷（預設 fail-closed 狀態）
    COMPLIANT    = "COMPLIANT"     # 依「公司核准之正式隔離表」規則判定為符合（尚無此類資料，目前不會出現）
    VIOLATION    = "VIOLATION"     # 依「公司核准之正式隔離表」規則判定為違規（尚無此類資料，目前不會出現）
    GENERAL_TABLE_OK      = "GENERAL_TABLE_OK"       # 依一般類別隔離表，現有距離/代碼未見明顯問題（非正式判定）
    GENERAL_TABLE_CAUTION = "GENERAL_TABLE_CAUTION"  # 依一般類別隔離表，現有距離可能不足（非正式判定，建議儘速覆核）
    GENERAL_TABLE_INFO    = "GENERAL_TABLE_INFO"     # 僅告知一般類別隔離表要求的隔離代碼，未提供距離無法比對
    TEST_FIXTURE_NOT_FOR_OPERATION = "TEST_FIXTURE_NOT_FOR_OPERATION"  # 僅供測試


@dataclass
class SegregationResult:
    status: SegregationStatus
    un_a: str
    un_b: str
    rule_id: Optional[str] = None
    regulation_basis: str = REGULATION_BASIS
    engine_version: str = ENGINE_VERSION
    reasoning: list = field(default_factory=list)
    message: str = ""
    # 一般類別隔離表附加資訊（GENERAL_TABLE_* 狀態才會填入，其餘為 None）
    general_table_code: Optional[str] = None   # "X" / "1" / "2" / "3" / "4"
    general_table_term: Optional[str] = None   # 代碼對應的中文說明
    required_distance_m: Optional[float] = None

    def is_authoritative(self) -> bool:
        """僅 COMPLIANT / VIOLATION（公司核准之正式隔離表判定）可作為合規依據；
        GENERAL_TABLE_* 屬概略提醒，NOT_VERIFIED／TEST_FIXTURE 皆不得當作結論使用。"""
        return self.status in (SegregationStatus.COMPLIANT, SegregationStatus.VIOLATION)


# ── 測試專用虛構規則（絕不可用於正式操作）───────────────────────────
_TEST_FIXTURE_RULES = {
    ("1", "1"): (
        SegregationStatus.TEST_FIXTURE_NOT_FOR_OPERATION,
        "TEST-0001",
        ["虛構測試規則，僅供單元測試使用，非官方 IMDG 隔離表內容"],
    ),
}


# ══════════════════════════════════════════════════════════════
# 一般類別對類別隔離表（見檔案開頭來源說明）
# ══════════════════════════════════════════════════════════════

# 代碼意義（IMDG Code 7.2.4 / 49 CFR 176.83(b) 共通定義；中文簡稱對齊使用者
# 提供之公司文件「附表三 危險品隔離表」備註原文寫法，方便直接對照紙本）
GENERAL_TABLE_TERMS = {
    "X": "依 IMDG 第 3.2 章危險品表隔離規定（無一般規則層級之強制隔離要求；仍可能有逐物質 SG/SGG 特殊規定）",
    "1": "遠離（Away from）：至少橫向相隔約 3 公尺，不得同一貨物運輸單元",
    "2": "隔開（Separated from）：至少橫向相隔約 6 公尺，或位於不同艙區",
    "3": "全艙隔開（Separated by a complete compartment or hold from）：須以完整艙區（貨艙／貨櫃艙）隔開",
    "4": "縱向全艙隔開（Separated longitudinally by an intervening complete compartment or hold from）：須以完整艙區縱向隔開",
    "*": "依 IMDG Code 7.2.7 爆炸品隔離規定（Class 1 爆炸品另有專屬隔離表，本系統未涵蓋）",
}

# 代碼 → 概略最小距離（公尺）。3／4 的真正規定是「以完整艙區隔開」而非單純距離，
# 這裡用一般文獻常見的概略對照值（12／24 公尺）僅供距離「明顯不足」時的粗略示警，
# 不代表滿足此距離就等同「以完整艙區隔開」——這點在 message 中會明確註明。
_GENERAL_TABLE_MIN_METERS = {"X": 0.0, "1": 3.0, "2": 6.0, "3": 12.0, "4": 24.0}

# 17 個一般隔離表分類（1.1/1.2/1.5 與 1.4/1.6 分別合併為一類，其餘為單一 Class）
_CATS = ["1.1", "1.3", "1.4", "2.1", "2.2", "2.3", "3", "4.1", "4.2", "4.3",
         "5.1", "5.2", "6.1", "6.2", "7", "8", "9"]

# 每一列的值，欄位順序與 _CATS 相同（來源見檔案開頭；已核對矩陣對稱性）
_MATRIX_ROWS = {
    "1.1": ["*", "*", "*", "4", "2", "2", "4", "4", "4", "4", "4", "4", "2", "4", "2", "4", "X"],
    "1.3": ["*", "*", "*", "4", "2", "2", "4", "3", "3", "4", "4", "4", "2", "4", "2", "2", "X"],
    "1.4": ["*", "*", "*", "2", "1", "1", "2", "2", "2", "2", "2", "2", "X", "4", "2", "2", "X"],
    "2.1": ["4", "4", "2", "X", "X", "X", "2", "1", "2", "2", "2", "2", "X", "4", "2", "1", "X"],
    "2.2": ["2", "2", "1", "X", "X", "X", "1", "X", "1", "X", "X", "1", "X", "2", "1", "X", "X"],
    "2.3": ["2", "2", "1", "X", "X", "X", "2", "X", "2", "X", "X", "2", "X", "2", "1", "X", "X"],
    "3":   ["4", "4", "2", "2", "1", "2", "X", "X", "2", "2", "2", "2", "X", "3", "2", "X", "X"],
    "4.1": ["4", "3", "2", "1", "X", "X", "X", "X", "1", "X", "1", "2", "X", "3", "2", "1", "X"],
    "4.2": ["4", "3", "2", "2", "1", "2", "2", "1", "X", "1", "2", "2", "1", "3", "2", "1", "X"],
    "4.3": ["4", "4", "2", "2", "X", "X", "2", "X", "1", "X", "2", "2", "X", "2", "2", "1", "X"],
    "5.1": ["4", "4", "2", "2", "X", "X", "2", "1", "2", "2", "X", "2", "1", "3", "1", "2", "X"],
    "5.2": ["4", "4", "2", "2", "1", "2", "2", "2", "2", "2", "2", "X", "1", "3", "2", "2", "X"],
    "6.1": ["2", "2", "X", "X", "X", "X", "X", "X", "1", "X", "1", "1", "X", "1", "X", "X", "X"],
    "6.2": ["4", "4", "4", "4", "2", "2", "3", "3", "3", "2", "3", "3", "1", "X", "3", "3", "X"],
    "7":   ["2", "2", "2", "2", "1", "1", "2", "2", "2", "2", "1", "2", "X", "3", "X", "2", "X"],
    "8":   ["4", "2", "2", "1", "X", "X", "X", "1", "1", "1", "2", "2", "X", "3", "2", "X", "X"],
    "9":   ["X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X", "X"],
}
GENERAL_TABLE = {row: dict(zip(_CATS, vals)) for row, vals in _MATRIX_ROWS.items()}

# ── 顯示用中文標籤（僅供 app.py 畫面呈現「附表三」原文對照表使用，不影響
#    上方 evaluate() 的判斷邏輯與 _CATS 內部鍵值）──────────────────────
# 欄位表頭（短版，對齊使用者提供之附表三欄位寫法）
GENERAL_TABLE_COL_LABELS = {
    "1.1": "1.1 1.2 1.5", "1.3": "1.3 1.6", "1.4": "1.4",
    "2.1": "2.1", "2.2": "2.2", "2.3": "2.3", "3": "3",
    "4.1": "4.1", "4.2": "4.2", "4.3": "4.3",
    "5.1": "5.1", "5.2": "5.2", "6.1": "6.1", "6.2": "6.2",
    "7": "7", "8": "8", "9": "9",
}
# 列表頭（含中文品名，對齊使用者提供之附表三列寫法）
GENERAL_TABLE_ROW_LABELS = {
    "1.1": "爆炸品 1.1 1.2 1.5", "1.3": "爆炸品 1.3 1.6", "1.4": "爆炸品 1.4",
    "2.1": "易燃氣體 2.1", "2.2": "非易燃無毒氣體 2.2", "2.3": "毒性氣體 2.3",
    "3":   "易燃液體 3",
    "4.1": "易燃固體 4.1", "4.2": "自燃物品 4.2", "4.3": "遇水產出易燃氣體 4.3",
    "5.1": "氧化劑 5.1", "5.2": "有機過氧化物 5.2",
    "6.1": "毒性物質 6.1", "6.2": "傳染性物質 6.2",
    "7":   "放射性物質 7", "8": "腐蝕性物質 8", "9": "其他危險品 9",
}


def get_general_table_display_rows() -> list[dict]:
    """回傳供 UI 呈現「附表三 危險品隔離表」原文對照表用的資料結構：
    [{"row_key": "1.1", "row_label": "爆炸品 1.1 1.2 1.5", "values": ["*","*",...]}, ...]
    欄位順序固定為 _CATS。純資料轉換，不做任何判斷。"""
    return [
        {
            "row_key":   row_key,
            "row_label": GENERAL_TABLE_ROW_LABELS[row_key],
            "values":    [GENERAL_TABLE[row_key][col_key] for col_key in _CATS],
        }
        for row_key in _CATS
    ]


def _class_to_category(hazard_class: str) -> Optional[str]:
    """把 hazard_class（例如 "1.2"／"2.3"／"3"）對應到一般隔離表的 17 個分類之一。
    無法辨識（含 Class 1 爆炸品——1.1/1.2/1.5 → "1.1"，1.4/1.6 → "1.4"，1.3 → "1.3"）
    時回傳 None。"""
    if not hazard_class:
        return None
    c = hazard_class.strip()
    if c in ("1.1", "1.2", "1.5"):
        return "1.1"
    if c in ("1.4", "1.6"):
        return "1.4"
    if c in _CATS:
        return c
    # 容錯：只給主類別數字（例如 "4"）時，無法唯一對應 4.1/4.2/4.3，視為無法辨識
    return None


def _lookup_general_table(class_a: str, class_b: str):
    """回傳 (code, term) 或 (None, None)（任一 class 無法辨識，或屬 Class1 專屬表 "*"）。"""
    cat_a = _class_to_category(class_a)
    cat_b = _class_to_category(class_b)
    if not cat_a or not cat_b:
        return None, None
    code = GENERAL_TABLE.get(cat_a, {}).get(cat_b)
    if code is None or code == "*":
        return None, None
    return code, GENERAL_TABLE_TERMS.get(code, "")


def evaluate(
    un_a: str,
    class_a: str,
    un_b: str,
    class_b: str,
    *,
    distance_m: Optional[float] = None,
    test_mode: bool = False,
) -> SegregationResult:
    """
    評估兩項危險品的隔離狀態。

    正式操作模式（test_mode=False，預設）：
    1. 若任一 hazard_class 無法辨識，或屬 Class 1 爆炸品專屬隔離表範圍，回傳
       NOT_VERIFIED（與先前行為一致）。
    2. 否則依「一般類別對類別隔離表」（見檔案開頭來源說明）查出隔離代碼：
       - 未提供 distance_m：回傳 GENERAL_TABLE_INFO，只告知代碼與定義，不做
         合規／違規式的判斷。
       - 有提供 distance_m：代碼 X 或實際距離達到概略最小值 → GENERAL_TABLE_OK；
         否則 → GENERAL_TABLE_CAUTION（可能不足，建議儘速以船上正式資料覆核）。
       兩者皆非公司核准之正式判定，is_authoritative() 恆為 False。
    COMPLIANT／VIOLATION 保留給日後公司核准之完整 Amendment 42-24 逐物質結構化
    資料使用，目前尚未取得，故不會被觸發。

    test_mode=True 僅供 pytest 使用，套用明確標示 TEST_FIXTURE_NOT_FOR_OPERATION 的
    虛構規則，驗證 engine 的資料流與 schema；其結果不得顯示於正式 UI 或報表。
    """
    if test_mode:
        ca = class_a.split(".")[0] if class_a else ""
        cb = class_b.split(".")[0] if class_b else ""
        rule = _TEST_FIXTURE_RULES.get((ca, cb)) or _TEST_FIXTURE_RULES.get((cb, ca))
        if rule:
            status, rule_id, reasoning = rule
            return SegregationResult(
                status=status,
                un_a=un_a,
                un_b=un_b,
                rule_id=rule_id,
                reasoning=list(reasoning),
                message="⚠️ TEST_FIXTURE_NOT_FOR_OPERATION — 本結果為測試用虛構規則，嚴禁用於實際船上操作。",
            )

    code, term = _lookup_general_table(class_a, class_b)

    if code is None:
        return SegregationResult(
            status=SegregationStatus.NOT_VERIFIED,
            un_a=un_a,
            un_b=un_b,
            rule_id=None,
            reasoning=[
                "無法依一般類別隔離表判斷（危險品類別無法辨識，或屬 Class 1 爆炸品專屬隔離表範圍），"
                "且專案尚未取得公司核准之 Amendment 42-24 Segregation Table 結構化資料"
            ],
            message=(
                f"⚫ NOT_VERIFIED — 本系統目前無法自動判定 UN{un_a} 與 UN{un_b} 的隔離合規性。"
                "請依船上最新版 IMDG Code Segregation Table、公司 SMS 程序及大副／船長判斷執行，"
                "不得僅依本系統結果做出積載決策。"
            ),
        )

    cat_a, cat_b = _class_to_category(class_a), _class_to_category(class_b)
    rule_id = f"GENTAB-{cat_a}x{cat_b}-{code}"
    required_m = _GENERAL_TABLE_MIN_METERS.get(code, 0.0)
    caveat = (
        "本結果僅依「一般類別對類別隔離表」概略判斷（" + GENERAL_TABLE_SOURCE + "），"
        "不含逐物質 SG／SGG 特殊隔離規定，代碼 3／4 實際要求「以完整艙區隔開」而非單純"
        "距離，本系統僅以概略幾何距離提醒，非公司核准之正式判定，仍須依船上最新版 IMDG "
        "Code Segregation Table、公司 SMS 程序及大副／船長判斷執行。"
    )

    if distance_m is None:
        return SegregationResult(
            status=SegregationStatus.GENERAL_TABLE_INFO,
            un_a=un_a, un_b=un_b, rule_id=rule_id,
            reasoning=[f"一般隔離表：Class {class_a} × Class {class_b} → 代碼 {code}（{term}）"],
            message=(
                f"ℹ️ GENERAL_TABLE_INFO — 依一般類別隔離表，UN{un_a}（Class {class_a}）與 "
                f"UN{un_b}（Class {class_b}）的隔離要求為代碼「{code}」：{term}。未提供兩者間"
                f"距離，僅供參考。{caveat}"
            ),
            general_table_code=code, general_table_term=term, required_distance_m=required_m,
        )

    ok = (code == "X") or (distance_m >= required_m)
    status = SegregationStatus.GENERAL_TABLE_OK if ok else SegregationStatus.GENERAL_TABLE_CAUTION
    icon = "🟢" if ok else "🟡"
    verdict = "現有距離未見明顯不足" if ok else "現有距離可能不足，建議儘速覆核"
    return SegregationResult(
        status=status,
        un_a=un_a, un_b=un_b, rule_id=rule_id,
        reasoning=[
            f"一般隔離表：Class {class_a} × Class {class_b} → 代碼 {code}（{term}）",
            f"概略最小距離約 {required_m:.0f} 公尺，實際約 {distance_m:.1f} 公尺",
        ],
        message=(
            f"{icon} {status.value} — 依一般類別隔離表，UN{un_a}（Class {class_a}）與 "
            f"UN{un_b}（Class {class_b}）代碼「{code}」：{term}（概略最小距離約 "
            f"{required_m:.0f} 公尺，實際約 {distance_m:.1f} 公尺）。{verdict}。{caveat}"
        ),
        general_table_code=code, general_table_term=term, required_distance_m=required_m,
    )
