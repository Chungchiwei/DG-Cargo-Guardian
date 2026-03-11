🚢 船舶危險品管理系統 (DG Cargo Management System) 規格說明書
用途說明: 本規格說明書作為 AI 提示語使用，將此完整內容提交給 AI，AI 將根據規格生成完整的應用程式碼。

📋 系統概述
系統名稱
DG Cargo Guardian — 船舶危險品緊急處置輔助系統

核心功能描述
建立一個基於網頁的船舶危險品（Dangerous Goods）緊急處置輔助工具，能夠：

接受船員輸入危險品 UN Number，即時查詢 IMDG 資料庫中的 EMS（Emergency Schedule）資訊
解析 CASP（Cargo Stowage Plan）貨物積載計畫資料，掌握全船危險品位置
自動比對鄰近艙位的危險品，識別潛在的隔離衝突與複合危險
整合 AI 功能，扮演危險品處置專家角色，依據當前情況給予即時處置建議（水霧 / CO₂ / 撤離等）
提供 IMDG 分類、隔離要求、急救措施、消防方式等完整資訊
技術架構要求
界面框架: Streamlit 框架
資料庫: 內建 IMDG 危險品資料（SQLite 本地資料庫 + JSON 靜態資料）
CASP 解析: 支援 CSV / JSON 格式的積載計畫檔案上傳與解析
AI 模型: OpenAI GPT-4o（或相容 API）
視覺化工具: Plotly（船艙位置示意圖）
資料處理: Pandas, NumPy
HTTP 請求: requests
日期/時間: datetime
部署方式: 可在船上離線環境運行（本地 Python 環境）
🎯 功能需求規格
F-001: 用戶界面設計
基本要求:

頁面標題: "🚢 DG Cargo Guardian — 危險品緊急處置系統"，使用彩虹色分隔線 divider="rainbow"
左側控制區（側邊欄）包含：
系統 Logo 與標題 "⚙️ 系統設定" (divider="rainbow")
OpenAI API Key 輸入欄位 (type="password")
CASP 檔案上傳按鈕（支援 .csv / .json）
船名輸入欄位（選填，用於報告標頭）
航次輸入欄位（選填）
緊急模式切換開關（st.toggle，開啟時介面顯示紅色警示框）
主要操作區：
UN Number 輸入欄位（大字體，醒目設計）
"🔍 查詢 & 分析" 主要執行按鈕
快速查詢歷史記錄（Session State 保存最近 5 筆查詢）
說明:

提供 UN Number 輸入範例（UN1203、UN1965、UN2794）
支援輸入格式容錯（1203 自動補全為 UN1203）
緊急模式下，頁面頂部顯示紅色警示橫幅
F-002: IMDG 資料庫查詢功能
功能目標: 根據輸入的 UN Number，即時查詢 IMDG Code 相關資訊

資料來源與說明:

系統內建 IMDG 危險品靜態資料庫（JSON 格式，隨程式一起部署）
資料結構包含：

{
  "UN1203": {
    "proper_shipping_name": "GASOLINE",
    "class": "3",
    "subsidiary_risk": [],
    "packing_group": "II",
    "ems_fire": "F-E",
    "ems_spillage": "S-E",
    "mfag": "127",
    "stowage_segregation": "Category A",
    "special_provisions": ["144", "367"],
    "description": "汽油，易燃液體",
    "flashpoint": "-40°C",
    "emergency_action": {
      "fire": "使用水霧、泡沫、乾粉或CO₂滅火，切勿使用直射水柱",
      "spillage": "隔離洩漏區域，避免火源，通風處理",
      "first_aid": "移至新鮮空氣處，若皮膚接觸以大量清水沖洗"
    }
  }
}
EMS 查詢輸出:

EMS Fire Schedule（F-A 至 F-J）：對應消防處置方式
EMS Spillage Schedule（S-A 至 S-Z）：對應洩漏處置方式
MFAG（Medical First Aid Guide）編號
隔離等級與積載要求
閃點、沸點等物理特性
處理要求:

查詢結果在 1 秒內返回（本地資料庫）
UN Number 不存在時，顯示友善提示並建議查閱紙本 IMDG Code
支援模糊搜尋（輸入貨物名稱關鍵字也能找到對應 UN Number）
F-003: CASP 解析功能
功能目標: 解析上傳的積載計畫檔案，建立全船危險品位置地圖

支援格式:

CSV 格式（標準欄位：container_id, bay, row, tier, un_number, class, weight_kg, location_type）
JSON 格式（巢狀結構，包含 vessel 資訊與 container list）
CASP CSV 欄位說明:

欄位名稱	說明	範例
container_id	貨櫃號碼	MSCU1234567
bay	Bay 號（前後位置）	02, 04, 06
row	Row 號（左右位置）	01, 02, 03
tier	Tier 號（上下層）	82, 84, 86
un_number	UN 編號	UN1203
class	IMDG 分類	3
weight_kg	重量（公斤）	18000
location_type	位置類型	DECK / HOLD
解析輸出:

全船危險品清單（DataFrame 格式）
按 Bay/Row/Tier 建立三維位置索引
統計各 IMDG Class 的數量與重量
顯示解析成功/失敗的貨櫃數量
F-004: 鄰近危險品比對功能
功能目標: 當查詢特定 UN Number 時，自動找出 CASP 中所有相同或鄰近位置的危險品，評估複合風險

比對邏輯:


鄰近定義：
- 同 Bay，Row 差距 ≤ 2，Tier 差距 ≤ 2 → 視為「直接鄰近」
- 相鄰 Bay（差距 2），同 Row 範圍 → 視為「次鄰近」
- 同 Hold 或同甲板區段 → 視為「同區域」
隔離衝突檢查:

依據 IMDG Segregation Table 檢查兩種危險品是否可以共同積載
隔離等級：
Away from：需保持一定距離
Separated from：需在不同艙間
Separated by a complete compartment or hold from：需完全隔離
Separated longitudinally by an intervening complete compartment or hold from：縱向完全隔離
輸出格式:

列表顯示所有鄰近危險品（貨櫃號、位置、UN Number、Class）
以顏色標示風險等級：
🟢 綠色：無衝突
🟡 黃色：需注意（Away from）
🔴 紅色：嚴重衝突（Separated from 以上）
提供 Plotly 互動式船艙示意圖，標示目標貨櫃與鄰近危險品位置
F-005: 船艙位置視覺化
展示方式: 使用 Plotly 繪製簡化的船艙俯視圖與側視圖

展示內容:

俯視圖（Bay-Row 平面）：顯示甲板面危險品分布
側視圖（Bay-Tier 截面）：顯示垂直方向的積載關係
目標貨櫃以紅色閃爍標示
鄰近危險品以黃色/橙色標示
一般貨物以灰色顯示
互動功能:

懸停顯示貨櫃詳細資訊（貨櫃號、UN Number、Class、重量）
支援縮放與平移
可切換顯示層（甲板 / 艙內）
F-006: AI 危險品處置專家功能
分析目標: 整合當前 UN Number 資訊、EMS 資料、鄰近危險品情況，由 AI 給予即時處置建議

AI 角色設定: 資深船舶危險品處置專家，熟悉 IMDG Code、SOLAS 公約、船舶消防規程，能根據現場情況給予具體可操作的處置指令

完整 AI 提示語結構:


## 系統角色 (System Message)
你是一位資深的船舶危險品處置專家（DG Cargo Emergency Response Expert），擁有超過20年的海上危險品事故處置經驗，精通：

1. IMDG Code（國際海運危險品規則）全部分類與處置程序
2. SOLAS 公約消防與緊急應變規定
3. 船舶固定式 CO₂ 滅火系統操作規程
4. 水霧（Water Mist）與泡沫滅火系統應用
5. 危險品洩漏、火災、爆炸的複合事故處置
6. 船員緊急撤離與人員安全保護

你的職責：
- 根據提供的 UN Number、EMS 資訊、鄰近危險品情況，給予**具體、可立即執行**的處置建議
- 明確指出應使用何種滅火媒介（水霧 / CO₂ / 泡沫 / 乾粉），並說明原因
- 指出哪些危險品**絕對不可使用直射水柱**
- 評估是否需要啟動 CO₂ 全區釋放（Total Flooding），並說明觸發條件
- 提醒船員個人防護裝備（PPE）要求
- 評估是否需要緊急呼叫 MAYDAY 或聯繫最近港口

重要原則：
- 建議必須**具體可操作**，使用指令式語句（「立即...」、「確認...後再...」）
- 優先考慮**人員安全**，其次才是貨物保護
- 明確區分「可以做」與「絕對不可以做」的行動
- 考慮複合危險情境（多種危險品同時受影響）
- 使用**繁體中文**，術語清晰，避免歧義
- 在建議末尾加上「⚠️ 本建議基於提供資訊，現場情況以船長最終判斷為準」

## 用戶提示語 (User Prompt)
請根據以下船上危險品緊急情況，提供即時處置建議：

### 📍 事故基本資訊
- 船名：{vessel_name}
- 航次：{voyage}
- 事故時間：{incident_time}
- 問題貨櫃 UN Number：{un_number}
- 貨物名稱：{proper_shipping_name}
- IMDG 分類：Class {class}，包裝組別 {packing_group}
- 貨櫃位置：Bay {bay} / Row {row} / Tier {tier}（{location_type}）

### 🔥 EMS 資訊
- EMS Fire Schedule：{ems_fire}
- EMS Spillage Schedule：{ems_spillage}
- MFAG 編號：{mfag}
- 閃點：{flashpoint}
- 積載隔離要求：{stowage_segregation}

### ⚠️ 鄰近危險品清單
以下是與事故貨櫃距離 ≤ 2 個位置的其他危險品：
{nearby_dg_list}

### 🏗️ 隔離衝突分析
{segregation_conflicts}

### 📋 處置建議架構

請依照以下架構提供建議：

#### 1. 🚨 立即行動（0-5 分鐘）
- 人員安全與撤離範圍
- 個人防護裝備要求
- 隔離區域設定

#### 2. 🔥 消防處置方式
- 明確說明：使用水霧 OR CO₂ OR 泡沫 OR 乾粉，並說明原因
- 是否啟動固定式 CO₂ 系統（Total Flooding）的判斷標準
- 絕對禁止的滅火方式

#### 3. ☣️ 洩漏處置（如適用）
- 洩漏控制方法
- 防止污染擴散措施
- 廢棄物處理

#### 4. 🏥 急救措施
- 皮膚/眼睛接觸處置
- 吸入處置
- 送醫建議

#### 5. 🔗 複合危險評估
- 鄰近危險品的額外風險
- 是否有爆炸/毒氣擴散風險
- 建議優先處置順序

#### 6. 📡 通報建議
- 是否需要發出 MAYDAY
- 建議聯繫的岸上支援（CHEMTREC、船公司 DPA 等）
- 航行建議（是否需要就近靠港）
AI 提示語模板設計原則:

系統角色要強調可操作性，避免模糊建議
明確要求 AI 在水霧 vs CO₂ 的選擇上給出具體理由
複合危險情境要納入鄰近危險品的交互影響
輸出結構化格式，船員可快速掃讀執行
F-007: 查詢結果展示
展示方式: 使用分頁標籤（st.tabs）組織不同類型資訊

Tab 1 — 🔥 EMS 緊急處置:

以大字體、醒目顏色顯示 EMS Fire / Spillage Schedule
消防方式、洩漏處置、急救措施分欄顯示
使用 st.metric() 顯示關鍵數值（閃點、MFAG 編號）
Tab 2 — 📍 CASP 位置分析:

顯示該 UN Number 在 CASP 中的所有貨櫃
鄰近危險品列表（含風險等級顏色標示）
隔離衝突警告
Tab 3 — 🗺️ 船艙示意圖:

Plotly 互動式船艙位置圖
目標貨櫃與鄰近危險品標示
Tab 4 — 🤖 AI 處置建議:

AI 生成的完整處置建議報告
顯示生成時間戳記
提供「列印 / 匯出 PDF」按鈕（使用 st.download_button 匯出 Markdown 文字）
Tab 5 — 📊 全船 DG 總覽:

全船危險品統計表（按 Class 分類）
各 Class 數量與重量圓餅圖
F-008: 輔助功能
進度顯示:

使用 st.spinner("🔍 查詢 IMDG 資料庫中...") 顯示查詢進度
使用 st.spinner("🤖 AI 專家分析中，請稍候...") 顯示 AI 分析進度
使用 st.progress() 顯示 CASP 解析進度
查詢歷史記錄:

使用 st.session_state 保存最近 5 筆查詢記錄
側邊欄顯示歷史查詢列表，可點擊快速重查
顯示查詢時間、UN Number、貨物名稱
報告匯出:

使用 st.download_button 匯出完整處置報告（Markdown / TXT 格式）
報告包含：查詢時間、船名、航次、UN Number、EMS 資訊、AI 建議
狀態管理:

st.success() — 查詢成功、CASP 解析完成
st.error() — UN Number 不存在、API 錯誤、CASP 格式錯誤
st.warning() — 發現隔離衝突、鄰近高風險危險品
st.info() — 查詢進度、資料處理狀態
F-009: 錯誤處理與用戶體驗
輸入驗證:

檢查 UN Number 格式（4位數字，自動補全 UN 前綴）
驗證 CASP 檔案格式與必要欄位完整性
檢查 OpenAI API Key 是否已輸入（AI 功能啟用時）
提供 UN Number 輸入範例（UN1203 汽油、UN1965 烴類混合氣、UN2794 蓄電池）
錯誤處理:

所有 API 調用都要有 try-except 錯誤處理
CASP 解析失敗時，顯示具體錯誤行號與欄位名稱
UN Number 不存在時，建議查閱紙本 IMDG Code 或聯繫 DPA
OpenAI API 失敗時，仍顯示 EMS 靜態資料，AI 建議部分顯示錯誤提示
用戶指導:

提供 CASP CSV 範本下載（st.download_button）
在側邊欄提供 IMDG Class 快速參考表
提供 EMS Schedule 說明連結
F-010: 免責聲明與安全
免責聲明位置: 側邊欄底部 (st.sidebar.markdown)


### ⚠️ 重要聲明
本系統提供之 AI 建議**僅供參考輔助**，不取代船長、大副及受訓消防人員的專業判斷。
緊急情況下，**船長擁有最終決策權**。
所有處置行動須依據船上實際情況、SOLAS 規定及公司 SMS 程序執行。
系統作者不對任何處置行動的後果負責。
安全要求:

API Key 使用 type="password" 安全輸入
CASP 資料僅在本地處理，不上傳至外部伺服器（除 AI 分析摘要外）
不在程式碼中寫入任何敏感資訊
AI 分析傳送給 OpenAI 的資料僅包含危險品技術資訊，不含船舶識別資訊（除非用戶主動輸入）
🎨 界面設計與體驗標準
整體風格要求
專業感: 深色系主題，符合船橋/貨控室的使用環境（低光源友好）
緊急感: 緊急模式下使用紅色警示色系，視覺衝擊明確
易讀性: 大字體、高對比度，適合在緊急情況下快速閱讀
一致性: 統一使用海事/工業風格圖示與術語
操作流程設計標準
進入系統: 顯示系統標題、船名/航次輸入、CASP 上傳提示
CASP 載入: 上傳積載計畫，系統解析並顯示全船 DG 統計
緊急查詢: 輸入 UN Number，點擊查詢按鈕
結果展示: 分頁顯示 EMS 資訊、位置分析、AI 建議
報告匯出: 一鍵匯出完整處置報告
視覺化標準
圖表工具: Plotly Graph Objects 繪製船艙示意圖
色彩配置: 紅色（高危）、黃色（注意）、綠色（安全）、灰色（一般貨物）
互動功能: 懸停顯示貨櫃詳情
響應式設計: use_container_width=True
📊 品質標準
功能品質標準
IMDG 查詢在 1 秒內返回結果
CASP 解析支援 1000+ 貨櫃的大型積載計畫
鄰近比對演算法準確識別所有相關位置
AI 分析建議具體可操作，明確區分水霧 / CO₂ 使用場景
離線運行標準
IMDG 資料庫為本地 JSON 檔案，無需網路連線即可查詢
CASP 解析完全本地處理
僅 AI 分析功能需要網路連線（OpenAI API）
無網路時，AI 功能顯示提示，其餘功能正常運作
安全品質標準
緊急情況下，系統必須在 3 秒內顯示 EMS 核心資訊
所有錯誤提示友善且提供替代方案
離線模式下仍能提供完整的靜態 EMS 資訊
🤖 AI 實作指令
請根據以上完整規格說明書，生成一個完整可運行的 Streamlit 網頁應用程式。

必要實現要求
完全實現所有功能需求 (F-001 到 F-010)
內建 IMDG 資料庫 — 至少包含 50 筆常見危險品資料（涵蓋 Class 1–9）
CASP 解析引擎 — 支援 CSV/JSON 格式，含格式驗證
鄰近比對演算法 — 基於 Bay/Row/Tier 三維座標計算距離
AI 整合 — 使用 OpenAI GPT-4o，按照提示語模板生成處置建議
啟動方式 — 雙擊 run.bat 或執行 streamlit run app.py
技術實現要求
框架: Streamlit
AI 整合: OpenAI Python SDK (openai 套件)
資料庫: 內建 JSON 靜態資料（imdg_database.json）
視覺化: Plotly Graph Objects
程式品質: 清晰的中文註釋，模組化設計
程式結構要求
主要函數需求:

load_imdg_database() — 載入本地 IMDG JSON 資料庫
query_un_number(un_number) — 查詢指定 UN Number 的完整資訊
parse_casp_file(uploaded_file) — 解析上傳的 CASP 檔案
find_nearby_dg(casp_df, target_bay, target_row, target_tier, threshold=2) — 找出鄰近危險品
check_segregation_conflicts(dg_list) — 檢查隔離衝突
generate_ai_advice(un_info, nearby_dg, conflicts, vessel_info) — 呼叫 OpenAI 生成處置建議
plot_cargo_map(casp_df, highlight_containers) — 繪製 Plotly 船艙示意圖
export_report(un_info, ai_advice, vessel_info) — 生成可下載的處置報告
主程式邏輯:

設置頁面標題、側邊欄（API Key、CASP 上傳、船名/航次）
載入 IMDG 資料庫
解析 CASP 檔案（若已上傳）
接受 UN Number 輸入，執行查詢
顯示 EMS 資訊（Tab 1）
執行鄰近比對與隔離衝突檢查（Tab 2）
繪製船艙示意圖（Tab 3）
呼叫 AI 生成處置建議（Tab 4）
顯示全船 DG 統計（Tab 5）
提供報告匯出功能
交付物要求
最終交付物: 完整 Python 程式，包含：

app.py — 主程式（所有 import、函數、主程式邏輯、中文註釋）
imdg_database.json — 內建 IMDG 資料庫（至少 50 筆，涵蓋 Class 1–9）
segregation_table.json — IMDG 隔離表資料
sample_casp.csv — CASP 範本檔案（含 10 筆範例資料）
requirements.txt — 套件清單（含 python-dotenv）
.env.example — 環境變數範本
run.bat — Windows 啟動腳本
requirements.txt 內容:


streamlit>=1.28.0
openai>=1.0.0
pandas>=2.0.0
numpy>=1.24.0
plotly>=5.15.0
requests>=2.31.0
python-dotenv>=1.0.0
run.bat 內容:


@echo off
echo 🚢 啟動 DG Cargo Guardian 系統...
pip install -r requirements.txt
streamlit run app.py
pause
.env.example 內容:


OPENAI_API_KEY=your_openai_api_key_here
📌 給 AI 的最終提醒: 本系統將在真實船舶緊急情況下使用，AI 生成的處置建議必須準確、具體、可操作。IMDG 資料庫的內容必須符合 IMDG Code 第 41 版標準。水霧 vs CO₂ 的選擇邏輯必須正確反映 EMS Schedule 的規定（例如：Class 3 易燃液體火災通常使用泡沫/CO₂，Class 5.1 氧化劑火災禁用 CO₂）。