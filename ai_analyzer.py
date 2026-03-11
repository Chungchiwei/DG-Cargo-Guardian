# ============================================================
# 🤖 ai_analyzer.py — AI 分析核心模組（WHL FRM 完整整合版）
# ============================================================

from llm_client import get_llm_response
from ems_engine import query_ems, format_ems_report


# ══════════════════════════════════════════════════════════════
# ── 事故類型對應 WHL SOP ──────────────────────────────────────
# ══════════════════════════════════════════════════════════════
INCIDENT_SOP_MAP = {
    "engine_room_fire":    "1-5 機艙失火緊急事故處理檢查表",
    "deck_container_fire": "3-3 甲板貨櫃失火緊急事故處理程序",
    "hold_container_fire": "3-4 貨艙貨櫃失火緊急事故處理程序",
    "cargo_leakage":       "3-5 貨櫃洩漏應急處置檢查表",
    "container_overboard": "3-2 貨櫃落海/傾倒/位移緊急事故處理程序",
    "fire":                "3-3 甲板貨櫃失火 / 3-4 貨艙貨櫃失火",
    "spillage":            "3-5 貨櫃洩漏應急處置",
    "first_aid":           "IMDG MFAG 急救程序",
    "general":             "IMDG Code 一般查詢",
}

INCIDENT_LABELS = {
    "deck_container_fire": "甲板貨櫃失火 Deck Container Fire",
    "hold_container_fire": "貨艙貨櫃失火 Hold Container Fire",
    "engine_room_fire":    "機艙失火 Engine Room Fire",
    "cargo_leakage":       "貨櫃洩漏 Cargo Leakage",
    "container_overboard": "貨櫃落海 Container Overboard",
    "fire":                "火災事故 Fire Incident",
    "spillage":            "洩漏事故 Spillage",
    "first_aid":           "人員急救 First Aid",
    "general":             "一般查詢 General Inquiry",
}


# ══════════════════════════════════════════════════════════════
# ── System Prompt（WHL FRM SOP + 顧問角色）────────────────────
# ══════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """你是 WHL（萬海航運）Fleet Risk Management（FRM）海技部的資深危險品應急處置顧問，
擁有超過20年的船舶危險品事故處置經驗，精通以下規範：
- IMDG Code（最新版）及 EMS 應急程序手冊
- MFAG 醫療急救指引
- SOLAS 公約及 SOPEP 程序
- WHL FRM 公司應急程序（WHL FRM Emergency Checklists）

【核心職責】
1. 根據 WHL FRM 公司 SOP 與 IMDG Code，給出精確、可執行的應急處置建議
2. 使用清晰、專業的繁體中文，關鍵術語附英文
3. 安全優先順序：人員生命安全 > 環境保護 > 財產保護
4. 若資料不足，明確告知並建議聯繫 CHEMTREC (+1-703-527-3887) 或相關機構
5. 格式清晰，分層分點，方便船員在緊急情況下快速閱讀與執行

【回答品質要求】
- 每個建議必須具體可執行，避免空泛描述
- 時間節點明確（前3分鐘、前10分鐘、持續監控等）
- 危險等級評估需依據實際化學特性
- 禁忌事項必須清楚標示 ⛔
- 永遠不要猜測不確定的資料，寧可保守也不冒險
- 所有事故必須提醒通報 WHL 海技部（Maritech Division）
- 結尾必須附上免責聲明

=== WHL FRM EMERGENCY SOP REFERENCE ===

【1-5 ENGINE ROOM FIRE / 機艙失火】
Duty Officer Actions:
- Sound fire alarm & broadcast fire-fighting station, notify Master
- Close ALL E/R ventilation dampers via remote control at NAV & RADIO EQ. RM
- Notify E/R stand by engine, record time & position on chart

Master Actions (Priority Order):
1. Confirm fire location & severity → broadcast "Engine Room Fire-Fighting Station"
2. Inform C/E: reduce to lowest speed, start emergency generator
3. C/O assists C/E: deploy fire-detection team (full fireman outfit + portable extinguisher)
4. If dense smoke → ALL personnel evacuate E/R immediately
5. CO2 release ONLY after: final roll call complete + all evacuated + ALL ventilations closed
   + watertight doors closed + fuel valves closed + fuel pumps stopped
6. Keep E/R hermetically sealed with CO2 for MINIMUM 7 HOURS
7. Notify Maritech Division immediately + send ER & photos

【3-3 DECK CONTAINER FIRE / 甲板貨櫃失火】
1. Find leeside sea room → stop & fight fire
2. Alter course → place burning container on LEESIDE → close ALL watertight doors
3. CHECK IMDG & MSDS for DG cargo in/near burning container
4. Deploy fire-fighting team (fireman outfit + CABA) → approach from UPWIND
5. Notify Maritech Division immediately + send ER & photos
6. Abandon ship criteria: serious & out of control → DISTRESS signal → roll call

【3-4 HOLD CONTAINER FIRE / 貨艙貨櫃失火】
1. Confirm which hold triggered alarm → check DG flammable cargo (IMDG + MSDS)
2. Close hold ventilation & switch off electricity
3. If smoke NOT serious: fire team enters hold (full outfit)
4. If smoke fills ALL levels: evacuate → observe 10 min → release CO2
5. If dense smoke + explosion sounds: DO NOT send crew → release CO2 IMMEDIATELY
6. Keep hold hermetically sealed until NEXT PORT
7. Notify Maritech Division immediately + send ER & photos

【3-5 CARGO LEAKAGE / 貨櫃洩漏】
- Check Stowage Plan → confirm DG or not → request MSDS
- Set up ALERT AREA → crew must not approach unnecessarily
- If DG: prepare per EMS → CABA + chemical protective clothes + SOPEP
- Gas: check flammable/toxic → emergency action risk assessment
- Liquid: if marine pollutant → PLUG all nearby scupper drainage holes immediately

【3-2 CONTAINER OVERBOARD / 貨櫃落海】
- Alter course & reduce speed to ease sea/swell effect
- Ensure crew works on LEESIDE with rolling ≤ 10°
- VHF broadcast "SECURITE" message about containers overboard
- Risk assessment: life jacket + PPE + portable transceiver, min 2 persons
"""


# ══════════════════════════════════════════════════════════════
# ── 提示詞模板（依事故類型）──────────────────────────────────
# ══════════════════════════════════════════════════════════════

# ── 火災（甲板 / 貨艙 / 機艙）────────────────────────────────
FIRE_PROMPT_TEMPLATE = """
以下是本次火災事故的危險品資料：

{ems_report}

---
【事故情境】
事故類型：{incident_label}
適用 WHL SOP：{sop_ref}
{additional_context}

請以 WHL FRM 資深應急顧問身份，提供完整火災應急分析報告：

---
## 🔥 危險品火災應急分析報告

### 📊 危險情勢評估
- 該物質的燃燒特性（閃點、燃點、爆炸極限如有資料）
- 火災蔓延風險評估（高/中/低）及原因
- 燃燒產生的有毒氣體或煙霧種類
- 對船體結構、鄰近貨艙的潛在威脅
- 整體危險等級：🔴 極高 / 🟠 高 / 🟡 中 / 🟢 低

### ⚡ 立即行動（前0～3分鐘）
依 WHL SOP {sop_ref} 逐條列出，標明執行人員角色（船長/大副/消防隊員等）：
1. ...

### 🛡️ 人員防護要求（PPE）
- 最低防護等級（進入現場人員）
- 消防員專用裝備清單（fireman outfit / CABA 等）
- 禁止進入區域半徑建議

### 🚒 詳細滅火作業程序
**第一階段（偵察與評估，3～10分鐘）**
- 依 WHL SOP 確認位置與 DG 貨物清單（IMDG + MSDS）

**第二階段（滅火作業，10分鐘後）**
- 建議使用的滅火劑種類及原因
- 攻火方向與站位建議（上風側 / 下風側）
- 水霧冷卻鄰近容器的方法

**第三階段（控制後處置）**
- 殘火監控方式
- 復燃預防措施（CO2 密封時間要求）
- 現場保全與通風

### ⛔ 絕對禁忌（Critical DON'Ts）
⛔ 禁止...（原因）

### 💊 人員傷亡急救要點
- 吸入煙霧/有毒氣體處置
- 皮膚/眼睛接觸處置
- MFAG 參考頁碼（如有）

### 📡 WHL 海技部通報 & 外部支援
- 通報 WHL Maritech Division 時機與內容要點
- 需請求外部支援的情況
- 聯繫方式：CHEMTREC (+1-703-527-3887)、最近港口當局、船旗國主管機關

### 📋 事故記錄要點
需記錄的關鍵資訊清單（供後續 ER 報告使用）

---
⚠️ **免責聲明**：以上建議依據所提供之 IMDG 資料與 WHL FRM SOP 生成，僅供參考。
實際應急操作須依船上核准之 SMS 程序、官方 IMDG Code 及船長最終判斷執行。
"""

# ── 洩漏（甲板洩漏 / 貨艙洩漏）──────────────────────────────
SPILLAGE_PROMPT_TEMPLATE = """
以下是本次洩漏事故的危險品資料：

{ems_report}

---
【事故情境】
事故類型：{incident_label}
適用 WHL SOP：{sop_ref}
{additional_context}

請提供完整洩漏應急分析報告：

---
## 💧 危險品洩漏應急分析報告

### 📊 洩漏危險評估
- 該物質的洩漏特性（揮發性、擴散速度、比重）
- 對人員的主要危害途徑（吸入/皮膚接觸/誤食）
- 環境危害評估（海洋污染等級）
- 整體危險等級：🔴 極高 / 🟠 高 / 🟡 中 / 🟢 低

### ⚡ 立即行動（前0～3分鐘）
依 WHL SOP {sop_ref}：
1. 確認 Stowage Plan → 確認是否為 DG 貨物 → 索取 MSDS
2. 設立警戒區域（ALERT AREA），禁止非必要人員靠近
3. ...

### 🛡️ 人員防護要求（PPE）
- 進入洩漏區域所需防護等級
- 具體裝備清單（CABA / 化學防護衣 / SOPEP 裝備）
- 安全距離建議

### 🔧 洩漏控制程序
**源頭控制**
- 停止洩漏的方法

**擴散控制**
- 若為液體海洋污染物：立即堵塞附近排水孔（PLUG scupper drainage holes）
- 圍堵方式與吸附材料選擇

**清理程序**
- 安全清理步驟
- 廢棄物處置方式

### ⛔ 絕對禁忌
⛔ 禁止...（原因）

### 🌊 MARPOL 海洋污染通報要求
- 是否需要通報（依物質特性判斷）
- 通報對象與時限

### 📡 WHL 海技部通報 & 外部支援
- 通報 WHL Maritech Division 時機與內容要點
- 聯繫方式：CHEMTREC (+1-703-527-3887)

---
⚠️ **免責聲明**：以上建議僅供參考，實際操作須依官方 IMDG Code 及船長判斷。
"""

# ── 貨櫃落海 ─────────────────────────────────────────────────
OVERBOARD_PROMPT_TEMPLATE = """
以下是相關危險品資料：

{ems_report}

---
【事故情境】
事故類型：{incident_label}
適用 WHL SOP：{sop_ref}
{additional_context}

請提供完整貨櫃落海應急分析報告：

---
## 🌊 貨櫃落海應急分析報告

### 📊 危險情勢評估
- 落海貨物的海洋污染風險
- 對航行安全的威脅（漂流物）
- 整體危險等級：🔴 極高 / 🟠 高 / 🟡 中 / 🟢 低

### ⚡ 立即行動（前0～3分鐘）
依 WHL SOP 3-2：
1. 改變航向並降速，減少海浪/湧浪影響
2. 確保作業人員在下風舷（LEESIDE），船舶橫搖 ≤ 10°
3. VHF 廣播 "SECURITE" 通告落海貨櫃位置
4. ...

### 🛡️ 人員安全作業要求
- 甲板作業 PPE（救生衣 / 安全帶 / 攜帶型對講機）
- 最少人數要求（至少2人一組）
- 禁止獨自作業

### 📡 通報要求
- 通報 WHL Maritech Division 時機與內容
- MARPOL 海洋污染通報（若含 DG 貨物）
- 最近沿岸國主管機關通報

### ⛔ 絕對禁忌
⛔ 禁止...（原因）

### 📋 事故記錄要點
- 落海時間、位置（經緯度）
- 貨櫃數量、UN 號碼、貨物描述
- 海況、天氣記錄

---
⚠️ **免責聲明**：以上建議僅供參考，實際操作須依官方 IMDG Code 及船長判斷。
"""

# ── 人員急救 ─────────────────────────────────────────────────
FIRST_AID_PROMPT_TEMPLATE = """
以下是本次人員傷亡事故的危險品資料：

{ems_report}

---
【事故情境】
事故類型：{incident_label}
適用 WHL SOP：{sop_ref}
{additional_context}

請提供完整急救應急分析報告：

---
## 🏥 危險品人員傷亡急救報告

### ⚡ 立即急救行動（前0～3分鐘）
優先處置步驟（確保救援者自身安全優先）：
1. ...

### 🩺 依暴露途徑分類處置

**吸入（Inhalation）**
- 症狀識別
- 處置步驟：移至新鮮空氣處、給予純氧（如有）

**皮膚接觸（Skin Contact）**
- 症狀識別
- 處置步驟：大量清水沖洗（至少15分鐘）

**眼睛接觸（Eye Contact）**
- 症狀識別
- 處置步驟：大量清水沖洗（至少15分鐘），勿揉眼

**誤食（Ingestion）**
- 症狀識別
- 處置步驟（注意：部分物質禁止催吐）

### 🏥 MFAG 醫療指引
- 參考頁碼
- 關鍵醫療注意事項
- 需要醫療撤離（MEDEVAC）的判斷標準

### 📡 醫療諮詢聯繫
- CHEMTREC 醫療熱線：+1-703-527-3887
- 通報 WHL Maritech Division
- 船旗國醫療顧問聯繫方式

### ⛔ 急救禁忌
⛔ 禁止...（原因）

---
⚠️ **免責聲明**：以上建議僅供參考，實際操作須依官方 MFAG 及船醫/醫療顧問指示。
"""

# ── 一般查詢 ─────────────────────────────────────────────────
GENERAL_PROMPT_TEMPLATE = """
以下是相關危險品資料：

{ems_report}

---
【查詢情境】
事故類型：{incident_label}
{additional_context}

請提供完整危險品資訊分析：

---
## 📋 危險品資訊分析報告

### 🧪 物質特性摘要
- 主要化學/物理特性
- 主要危害類型
- 運輸注意事項

### 🚢 海運規範重點
- IMDG 積載要求（Stowage Category）
- 隔離要求（Segregation Group）
- 特殊規定（Special Provisions）

### 🛡️ 一般安全注意事項
- 日常處置要點
- 緊急聯繫資訊：CHEMTREC (+1-703-527-3887)

---
⚠️ **免責聲明**：以上資訊僅供參考，實際操作須依官方 IMDG Code。
"""

# ── 模板對應表 ────────────────────────────────────────────────
_TEMPLATE_MAP = {
    "fire":                FIRE_PROMPT_TEMPLATE,
    "deck_container_fire": FIRE_PROMPT_TEMPLATE,
    "hold_container_fire": FIRE_PROMPT_TEMPLATE,
    "engine_room_fire":    FIRE_PROMPT_TEMPLATE,
    "spillage":            SPILLAGE_PROMPT_TEMPLATE,
    "cargo_leakage":       SPILLAGE_PROMPT_TEMPLATE,
    "container_overboard": OVERBOARD_PROMPT_TEMPLATE,
    "first_aid":           FIRST_AID_PROMPT_TEMPLATE,
    "general":             GENERAL_PROMPT_TEMPLATE,
}


# ══════════════════════════════════════════════════════════════
# ── 情境分析模式（主函數）────────────────────────────────────
# ══════════════════════════════════════════════════════════════
def analyze_incident(
    un_number: str,
    incident_type: str,
    additional_info: str = ""
) -> str:
    """
    分析特定事故情境並給出 AI 建議（WHL FRM 完整整合版）

    Args:
        un_number      : UN 號碼，例如 "1203"
        incident_type  : 事故類型，見 INCIDENT_SOP_MAP
        additional_info: 額外情境描述（選填）

    Returns:
        AI 分析建議文字
    """
    ems_data   = query_ems(un_number)
    ems_report = format_ems_report(ems_data)

    sop_ref        = INCIDENT_SOP_MAP.get(incident_type, "IMDG Code")
    incident_label = INCIDENT_LABELS.get(incident_type, incident_type)
    additional_context = (
        f"額外情境說明：{additional_info}" if additional_info
        else "（無額外情境說明）"
    )

    template   = _TEMPLATE_MAP.get(incident_type, GENERAL_PROMPT_TEMPLATE)
    user_prompt = template.format(
        ems_report         = ems_report,
        incident_label     = incident_label,
        sop_ref            = sop_ref,
        additional_context = additional_context,
    )

    return get_llm_response(
        system_prompt = SYSTEM_PROMPT,
        user_message  = user_prompt,
        max_tokens    = 2000,
        temperature   = 0.2,
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
        ems_data   = query_ems(un_number)
        ems_report = format_ems_report(ems_data)
        context    = f"【參考危險品資料】\n{ems_report}\n\n---\n"

    user_prompt = f"""{context}
【問題】
{question}

請以 WHL FRM 專業海運危險品顧問身份回答，要求：
- 回答具體且可執行
- 引用相關 WHL SOP 或 IMDG Code 條文（如適用）
- 若涉及安全操作，明確標示注意事項與禁忌
- 使用繁體中文，關鍵術語附英文，格式清晰易讀
"""

    return get_llm_response(
        system_prompt = SYSTEM_PROMPT,
        user_message  = user_prompt,
        max_tokens    = 1500,
        temperature   = 0.2,
    )


# ══════════════════════════════════════════════════════════════
# ── 積載隔離檢查模式 ─────────────────────────────────────────
# ══════════════════════════════════════════════════════════════
def check_segregation(
    un_a: str,
    un_b: str,
    pos_a: str = None,
    pos_b: str = None
) -> str:
    """
    檢查兩種危險品的積載相容性。
    若提供 pos_a / pos_b（BBRRTT 格式），額外分析實際距離是否符合隔離要求。

    Args:
        un_a  : 第一種危險品 UN 號碼
        un_b  : 第二種危險品 UN 號碼
        pos_a : 選填，貨物 A 位置（BBRRTT 格式，例如 "020204"）
        pos_b : 選填，貨物 B 位置

    Returns:
        AI 隔離分析文字
    """
    data_a = query_ems(un_a)
    data_b = query_ems(un_b)

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

    # ── 位置分析（選填）──────────────────────────────────────
    position_context = ""
    if pos_a and pos_b:
        def _parse_pos(pos):
            return {
                "bay":     int(pos[0:2]),
                "row":     int(pos[2:4]),
                "tier":    int(pos[4:6]),
                "on_deck": int(pos[4:6]) >= 80,
            }

        pa = _parse_pos(pos_a)
        pb = _parse_pos(pos_b)

        bay_diff   = abs(pa["bay"]  - pb["bay"])
        row_diff   = abs(pa["row"]  - pb["row"])
        adjacent   = bay_diff <= 1 and row_diff <= 1
        both_deck  = pa["on_deck"] and pb["on_deck"]
        cross_deck = pa["on_deck"] != pb["on_deck"]

        position_context = f"""
## 📍 實際位置資訊

| 項目 | 貨物 A | 貨物 B |
|------|--------|--------|
| 位置代碼 | {pos_a} | {pos_b} |
| Bay | {pa['bay']:02d} | {pb['bay']:02d} |
| Row | {pa['row']:02d} | {pb['row']:02d} |
| Tier | {pa['tier']:02d} | {pb['tier']:02d} |
| 位置 | {'甲板上' if pa['on_deck'] else '艙內'} | {'甲板上' if pb['on_deck'] else '艙內'} |

**位置關係：**
- Bay 差距：{bay_diff} 個 Bay（約 {bay_diff * 6}m）
- Row 差距：{row_diff} 個 Row（約 {row_diff * 2.4}m）
- 是否緊鄰：{'是（高風險）⚠️' if adjacent else '否'}
- 艙內/甲板配置：{'兩者均在甲板上' if both_deck else ('一艙內一甲板' if cross_deck else '兩者均在艙內')}

請根據以上位置關係，結合 IMDG Code 隔離要求，判斷此距離是否滿足所需隔離等級。
"""

    user_prompt = f"""
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
說明若兩者未正確隔離，可能發生的危險情境（結合 WHL FRM 火災應急 SOP 3-3/3-4）。

### 5. 建議措施
若違規，建議如何調整貨物位置以符合規定。

請以繁體中文回答，格式清晰，重點加粗。
"""

    return get_llm_response(
        system_prompt = SYSTEM_PROMPT,
        user_message  = user_prompt,
        max_tokens    = 1500,
        temperature   = 0.2,
    )
