# ============================================================
# 🤖 ai_analyzer.py — AI 分析核心模組（強化版）
# ============================================================

from llm_client import get_llm_response
from ems_engine import query_ems, format_ems_report

# ── 系統提示詞（強化版）────────────────────────────────────
SYSTEM_PROMPT = """你是一位資深海運危險品（DG Cargo）應急處置顧問，擁有超過20年的船舶危險品事故處置經驗。
你精通 IMDG Code（最新版）、EMS 應急程序手冊、MFAG 醫療急救指引、SOLAS 公約及 SOPEP 程序。

【核心職責】
1. 根據提供的 IMDG 資料與事故情境，給出精確、可執行的應急處置建議
2. 使用清晰、專業的繁體中文，避免模糊用語
3. 安全優先順序：人員生命安全 > 環境保護 > 財產保護
4. 若資料不足，明確告知並建議聯繫 CHEMTREC (+1-703-527-3887) 或相關機構
5. 格式清晰，分層分點，方便船員在緊急情況下快速閱讀與執行

【回答品質要求】
- 每個建議必須具體可執行，避免空泛描述
- 時間節點明確（前3分鐘、前10分鐘、持續監控等）
- 危險等級評估需依據實際化學特性
- 禁忌事項必須清楚標示 ⛔
- 永遠不要猜測不確定的資料，寧可保守也不冒險
- 結尾必須提醒：此建議僅供參考，實際操作須依官方 IMDG Code 及船長判斷
"""

# ── 火災專用提示詞模板 ──────────────────────────────────────
FIRE_PROMPT_TEMPLATE = """
以下是本次火災事故的危險品資料：

{ems_report}

---
【事故情境】
事故類型：火災事故
{additional_context}

請以資深海運危險品應急顧問身份，提供完整的火災應急分析報告，格式如下：

---
## 🔥 危險品火災應急分析報告

### 📊 危險情勢評估
- 該物質的燃燒特性（閃點、燃點、爆炸極限如有資料）
- 火災蔓延風險評估（高/中/低）及原因
- 燃燒產生的有毒氣體或煙霧種類
- 對船體結構、鄰近貨艙的潛在威脅
- 整體危險等級：🔴 極高 / 🟠 高 / 🟡 中 / 🟢 低

### ⚡ 立即行動（前0～3分鐘）
逐條列出，每條加上執行人員角色（船長/大副/消防隊員等）：
1. ...
2. ...

### 🛡️ 人員防護要求（PPE）
- 最低防護等級（進入現場人員）
- 消防員專用裝備清單
- 急救人員防護要求
- 禁止進入區域半徑建議

### 🚒 詳細滅火作業程序
分階段說明：
**第一階段（偵察與評估，3～10分鐘）**
- ...

**第二階段（滅火作業，10分鐘後）**
- 建議使用的滅火劑種類及原因
- 滅火劑用量估算（如可能）
- 攻火方向與站位建議
- 水霧冷卻鄰近容器的方法

**第三階段（控制後處置）**
- 殘火監控方式
- 復燃預防措施
- 現場保全與通風

### ⛔ 絕對禁忌（Critical DON'Ts）
用醒目格式列出：
⛔ 禁止...（原因）
⛔ 禁止...（原因）

### 💊 人員傷亡急救要點
- 吸入煙霧/有毒氣體處置
- 皮膚/眼睛接觸處置
- MFAG 參考頁碼（如有）

### 📡 外部支援請求時機
明確列出以下情況需立即請求支援：
- 情況一：...
- 情況二：...
聯繫方式：CHEMTREC (+1-703-527-3887)、最近港口當局、船旗國主管機關

### 📋 事故記錄要點
需記錄的關鍵資訊清單（供後續報告使用）

---
⚠️ **免責聲明**：以上建議依據所提供之 IMDG 資料生成，僅供參考。實際應急操作須依船上核准之 SMS 程序、官方 IMDG Code 及船長最終判斷執行。
"""

# ── 洩漏專用提示詞模板 ──────────────────────────────────────
SPILLAGE_PROMPT_TEMPLATE = """
以下是本次洩漏事故的危險品資料：

{ems_report}

---
【事故情境】
事故類型：洩漏事故
{additional_context}

請提供完整的洩漏應急分析報告，格式如下：

---
## 💧 危險品洩漏應急分析報告

### 📊 洩漏危險評估
- 該物質的洩漏特性（揮發性、擴散速度、比重）
- 對人員的主要危害途徑（吸入/皮膚接觸/誤食）
- 環境危害評估（海洋污染等級）
- 整體危險等級：🔴 極高 / 🟠 高 / 🟡 中 / 🟢 低

### ⚡ 立即行動（前0～3分鐘）
1. ...

### 🛡️ 人員防護要求（PPE）
- 進入洩漏區域所需防護等級
- 具體裝備清單
- 安全距離建議

### 🔧 洩漏控制程序
**源頭控制**
- 停止洩漏的方法

**擴散控制**
- 圍堵方式
- 吸附材料選擇

**清理程序**
- 安全清理步驟
- 廢棄物處置方式

### ⛔ 絕對禁忌
⛔ 禁止...（原因）

### 🌊 MARPOL 海洋污染通報要求
- 是否需要通報
- 通報對象與時限

### 📡 外部支援請求時機

---
⚠️ **免責聲明**：以上建議僅供參考，實際操作須依官方 IMDG Code 及船長判斷。
"""

# ── 急救專用提示詞模板 ──────────────────────────────────────
FIRST_AID_PROMPT_TEMPLATE = """
以下是本次人員傷亡事故的危險品資料：

{ems_report}

---
【事故情境】
事故類型：人員傷亡急救
{additional_context}

請提供完整的急救應急分析報告，格式如下：

---
## 🏥 危險品人員傷亡急救報告

### ⚡ 立即急救行動（前0～3分鐘）
優先處置步驟：
1. ...

### 🩺 依暴露途徑分類處置

**吸入（Inhalation）**
- 症狀識別
- 處置步驟

**皮膚接觸（Skin Contact）**
- 症狀識別
- 處置步驟

**眼睛接觸（Eye Contact）**
- 症狀識別
- 處置步驟

**誤食（Ingestion）**
- 症狀識別
- 處置步驟

### 🏥 MFAG 醫療指引
- 參考頁碼
- 關鍵醫療注意事項
- 需要醫療撤離的判斷標準

### 📡 醫療諮詢聯繫
- CHEMTREC 醫療熱線
- 船旗國醫療顧問聯繫方式

### ⛔ 急救禁忌
⛔ 禁止...（原因）

---
⚠️ **免責聲明**：以上建議僅供參考，實際操作須依官方 MFAG 及船醫/醫療顧問指示。
"""

# ── 一般查詢提示詞模板 ──────────────────────────────────────
GENERAL_PROMPT_TEMPLATE = """
以下是相關危險品資料：

{ems_report}

---
【查詢情境】
{additional_context}

請提供完整的危險品資訊分析，格式如下：

---
## 📋 危險品資訊分析報告

### 🧪 物質特性摘要
- 主要化學/物理特性
- 主要危害類型
- 運輸注意事項

### 🚢 海運規範重點
- IMDG 積載要求
- 隔離要求
- 特殊規定

### 🛡️ 一般安全注意事項
- 日常處置要點
- 緊急聯繫資訊

---
⚠️ **免責聲明**：以上資訊僅供參考，實際操作須依官方 IMDG Code。
"""


# ══════════════════════════════════════════════════════════════
# ── 情境分析模式（主函數）────────────────────────────────────
# ══════════════════════════════════════════════════════════════
def analyze_incident(
    un_number: str,
    incident_type: str,
    additional_info: str = ""
) -> str:
    """
    分析特定事故情境並給出 AI 建議（強化版）

    Args:
        un_number      : UN 號碼，例如 "1203"
        incident_type  : 事故類型 "fire" / "spillage" / "first_aid" / "general"
        additional_info: 額外情境描述（選填）

    Returns:
        AI 分析建議文字
    """
    # 取得 EMS 資料
    ems_data = query_ems(un_number)
    ems_report = format_ems_report(ems_data)

    # 額外情境格式化
    additional_context = f"額外情境說明：{additional_info}" if additional_info else "（無額外情境說明）"

    # 依事故類型選擇對應模板
    template_map = {
        "fire":      FIRE_PROMPT_TEMPLATE,
        "spillage":  SPILLAGE_PROMPT_TEMPLATE,
        "first_aid": FIRST_AID_PROMPT_TEMPLATE,
        "general":   GENERAL_PROMPT_TEMPLATE,
    }

    template = template_map.get(incident_type, GENERAL_PROMPT_TEMPLATE)

    user_prompt = template.format(
        ems_report=ems_report,
        additional_context=additional_context
    )

    return get_llm_response(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_prompt
    )


# ══════════════════════════════════════════════════════════════
# ── 自由問答模式 ─────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════
def ask_dg_question(
    question: str,
    un_number: str = None
) -> str:
    """
    自由問答模式，可選擇性附加 UN 號碼資料

    Args:
        question  : 使用者問題
        un_number : 選填，若提供則自動附加該 UN 的 IMDG 資料

    Returns:
        AI 回答文字
    """
    context = ""
    if un_number:
        ems_data = query_ems(un_number)
        ems_report = format_ems_report(ems_data)
        context = f"""
【參考危險品資料】
{ems_report}

---
"""

    user_prompt = f"""{context}
【問題】
{question}

請以專業海運危險品顧問身份回答，要求：
- 回答具體且可執行
- 引用相關 IMDG 規範（如適用）
- 若涉及安全操作，明確標示注意事項
- 使用繁體中文，格式清晰易讀
"""

    return get_llm_response(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_prompt
    )


# ══════════════════════════════════════════════════════════════
# ── 相容性檢查模式 ───────────────────────────────────────────
# ══════════════════════════════════════════════════════════════
def check_segregation(
    un_a: str,
    un_b: str,
    pos_a: str = None,
    pos_b: str = None
) -> str:
    """
    檢查兩種危險品的積載相容性。
    若提供 pos_a / pos_b（BBRRTT格式），額外分析實際距離是否符合隔離要求。
    """
    from ems_engine import query_ems

    data_a = query_ems(un_a)
    data_b = query_ems(un_b)

    # 組合貨物資訊
    def _cargo_summary(un, data):
        if not data["found"]:
            return f"UN{un}（查無資料）"
        return (
            f"UN{un} {data['proper_shipping_name']} | "
            f"Class {data['hazard_class']} | "
            f"Subsidiary Risk: {data.get('subsidiary_risk', [])} | "
            f"Stowage: {data.get('stowage', 'N/A')}"
        )

    summary_a = _cargo_summary(un_a, data_a)
    summary_b = _cargo_summary(un_b, data_b)

    # 位置資訊
    position_context = ""
    if pos_a and pos_b:
        def _parse_pos(pos):
            return {
                "bay":     int(pos[0:2]),
                "row":     int(pos[2:4]),
                "tier":    int(pos[4:6]),
                "on_deck": int(pos[4:6]) >= 80
            }

        pa = _parse_pos(pos_a)
        pb = _parse_pos(pos_b)

        bay_diff  = abs(pa["bay"]  - pb["bay"])
        row_diff  = abs(pa["row"]  - pb["row"])
        tier_diff = abs(pa["tier"] - pb["tier"])

        same_bay    = bay_diff == 0
        same_row    = row_diff == 0
        adjacent    = bay_diff <= 1 and row_diff <= 1
        a_on_deck   = pa["on_deck"]
        b_on_deck   = pb["on_deck"]
        both_deck   = a_on_deck and b_on_deck
        cross_deck  = a_on_deck != b_on_deck  # 一個艙內一個甲板上

        position_context = f"""
## 📍 實際位置資訊

| 項目 | 貨物 A | 貨物 B |
|------|--------|--------|
| 位置代碼 | {pos_a} | {pos_b} |
| Bay | {pa['bay']:02d} | {pb['bay']:02d} |
| Row | {pa['row']:02d} | {pb['row']:02d} |
| Tier | {pa['tier']:02d} | {pb['tier']:02d} |
| 位置 | {'甲板上' if a_on_deck else '艙內'} | {'甲板上' if b_on_deck else '艙內'} |

**位置關係：**
- Bay 差距：{bay_diff} 個 Bay（約 {bay_diff * 6}m）
- Row 差距：{row_diff} 個 Row（約 {row_diff * 2.4}m）
- 是否同一 Bay：{'是' if same_bay else '否'}
- 是否緊鄰：{'是（高風險）' if adjacent else '否'}
- 艙內/甲板：{'兩者均在甲板上' if both_deck else ('一艙內一甲板' if cross_deck else '兩者均在艙內')}

請根據以上位置關係，結合 IMDG Code 隔離要求，判斷：
1. 此距離是否滿足所需隔離等級（Away from / Separated from / Separated by a complete compartment / Separated longitudinally）
2. 艙內/甲板的配置是否符合規定
3. 是否存在違規，並明確標示 ❌ 違規 或 ✅ 合規
"""

    prompt = f"""
你是 IMDG Code 積載隔離專家。請根據以下資訊，詳細分析兩種危險品的積載相容性。

## 貨物資訊
- **貨物 A**：{summary_a}
- **貨物 B**：{summary_b}

{position_context}

## 請依序分析以下項目：

### 1. 隔離要求判定
根據 IMDG Code Segregation Table，這兩種危險品的隔離要求是什麼？
（Away from / Separated from / Separated by a complete compartment or hold / Separated longitudinally）

### 2. 位置合規性評估
{'根據上方提供的實際位置，評估目前配置是否符合隔離要求。' if pos_a and pos_b else '（未提供位置資訊，僅分析理論隔離要求）'}

### 3. 違規判定
明確標示：
- ✅ **合規** — 符合 IMDG 隔離要求
- ❌ **違規** — 違反 IMDG 隔離要求（說明違反哪條規定）

### 4. 風險說明
說明若兩者未正確隔離，可能發生的危險情境。

### 5. 建議措施
若違規，建議如何調整貨物位置以符合規定。

請以繁體中文回答，格式清晰，重點加粗。
"""

    # ✅ 修正：改用專案統一的 get_llm_response()
    return get_llm_response(
        system_prompt=SYSTEM_PROMPT,
        user_message=prompt
    )

