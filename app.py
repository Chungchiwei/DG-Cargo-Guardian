# ============================================================
# 🚢 app.py — DG Cargo Guardian 主介面
# ============================================================

import streamlit as st
from ems_engine import query_ems, format_ems_report
from ai_analyzer import analyze_incident, ask_dg_question, check_segregation

# ── 頁面設定 ────────────────────────────────────────────────
st.set_page_config(
    page_title="DG Cargo Guardian",
    page_icon="⚠️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── 自訂 CSS ─────────────────────────────────────────────────
st.markdown("""
<style>
    /* ── 主標題 ── */
    .main-title {
        font-size: 2rem;
        font-weight: 700;
        color: #FF4B4B;
        text-align: center;
        padding: 1rem 0 0.2rem 0;
    }
    .sub-title {
        font-size: 1rem;
        color: #888;
        text-align: center;
        margin-bottom: 2rem;
    }

    /* ── 資料卡片 ── */
    .info-card {
        background: #2A1F2E;
        border-left: 4px solid #FF4B4B;
        border-radius: 8px;
        padding: 1rem 1.2rem;
        margin: 0.5rem 0;
        color: #F0F0F0;
    }
    .info-card-blue {
        background: #1A2535;
        border-left: 4px solid #4B9EFF;
        border-radius: 8px;
        padding: 1rem 1.2rem;
        margin: 0.5rem 0;
        color: #F0F0F0;
    }
    .info-card-green {
        background: #1A2B25;
        border-left: 4px solid #4BFF9E;
        border-radius: 8px;
        padding: 1rem 1.2rem;
        margin: 0.5rem 0;
        color: #F0F0F0;
    }

    /* ── EMS Badge ── */
    .ems-badge {
        display: inline-block;
        background: #FF4B4B;
        color: white;
        font-size: 1.1rem;
        font-weight: 700;
        padding: 0.3rem 0.8rem;
        border-radius: 6px;
        margin-right: 0.5rem;
        letter-spacing: 1px;
    }
    .ems-badge-blue {
        display: inline-block;
        background: #4B9EFF;
        color: white;
        font-size: 1.1rem;
        font-weight: 700;
        padding: 0.3rem 0.8rem;
        border-radius: 6px;
        margin-right: 0.5rem;
        letter-spacing: 1px;
    }

    /* ── AI 回應區塊 ── */
    .ai-response-wrapper {
        background: #F8F9FA;
        border: 1px solid #DEE2E6;
        border-radius: 10px;
        padding: 1.5rem 1.8rem;
        margin-top: 0.5rem;
    }

    /* ── 警告橫幅 ── */
    .warning-banner {
        background: #3D1F00;
        border: 1px solid #FF8C00;
        border-radius: 8px;
        padding: 0.7rem 1rem;
        color: #FFB347;
        font-size: 0.85rem;
        text-align: center;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)


# ── Session State 初始化 ─────────────────────────────────────
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "last_un" not in st.session_state:
    st.session_state.last_un = ""


# ── 側邊欄 ───────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/color/96/hazmat.png", width=80)
    st.markdown("## ⚠️ DG Cargo Guardian")
    st.markdown("*海運危險品應急處置系統*")
    st.divider()

    # 功能選單
    page = st.radio(
        "📋 功能選單",
        options=[
            "🔍 EMS 快速查詢",
            "🤖 AI 事故分析",
            "🔄 積載隔離檢查",
            "💬 自由問答"
        ],
        label_visibility="collapsed"
    )

    st.divider()

    # 常用 UN 號碼快捷
    st.markdown("#### 🔖 常用 UN 號碼")
    quick_uns = {
        "UN1203 — 汽油": "1203",
        "UN1017 — 氯氣": "1017",
        "UN1789 — 鹽酸": "1789",
        "UN3480 — 鋰電池": "3480",
        "UN1072 — 氧氣": "1072",
    }
    for label, un in quick_uns.items():
        if st.button(label, use_container_width=True):
            st.session_state.last_un = un

    st.divider()
    st.markdown(
        "<div style='font-size:0.75rem; color:#666; text-align:center;'>"
        "⚠️ 本系統僅供參考<br>實際操作請依官方 IMDG Code"
        "</div>",
        unsafe_allow_html=True
    )


# ══════════════════════════════════════════════════════════════
# 頁面 1：EMS 快速查詢
# ══════════════════════════════════════════════════════════════
if page == "🔍 EMS 快速查詢":

    st.markdown('<div class="main-title">🔍 EMS 快速查詢</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">輸入 UN 號碼，即時取得 IMDG 應急程序資料</div>', unsafe_allow_html=True)

    # 輸入區
    col1, col2 = st.columns([3, 1])
    with col1:
        un_input = st.text_input(
            "UN 號碼",
            value=st.session_state.last_un,
            placeholder="例如：1203",
            label_visibility="collapsed"
        )
    with col2:
        search_btn = st.button("🔍 查詢", use_container_width=True, type="primary")

    if search_btn and un_input:
        st.session_state.last_un = un_input.strip()
        data = query_ems(un_input.strip())

        if not data["found"]:
            st.error(f"❌ {data['message']}")
        else:
            # ── 基本資料 ──
            st.markdown("---")
            col_a, col_b, col_c, col_d = st.columns(4)
            col_a.metric("UN 號碼", data["un_number"])
            col_b.metric("危險品類別", f"Class {data['hazard_class']}")
            col_c.metric("包裝等級", data["packing_group"] or "N/A")
            col_d.metric("MFAG", data["mfag"] or "N/A")

            st.markdown(f"### 📦 {data['proper_shipping_name']}")
            st.caption(data["description"])

            # ── EMS 代碼 ──
            st.markdown("#### 🚨 EMS 應急程序代碼")
            ems = data["ems"]

            col_e, col_f = st.columns(2)
            with col_e:
                st.markdown(
                    f'<div class="info-card">'
                    f'<span class="ems-badge">🔥 {ems["fire_code"]}</span>'
                    f'<br><br><b>{ems["fire_description"]}</b>'
                    f'</div>',
                    unsafe_allow_html=True
                )
            with col_f:
                st.markdown(
                    f'<div class="info-card-blue">'
                    f'<span class="ems-badge-blue">💧 {ems["spillage_code"]}</span>'
                    f'<br><br><b>{ems["spillage_description"]}</b>'
                    f'</div>',
                    unsafe_allow_html=True
                )

            # ── 應急處置 ──
            st.markdown("#### 🛡️ 應急處置指引")
            ea = data.get("emergency_action", {})

            tab1, tab2, tab3 = st.tabs(["🔥 火災處置", "💧 洩漏處置", "🏥 急救處置"])
            with tab1:
                st.info(ea.get("fire", "無資料"))
            with tab2:
                st.info(ea.get("spillage", "無資料"))
            with tab3:
                st.info(ea.get("first_aid", "無資料"))

            # ── 積載資訊 ──
            st.markdown("#### 📍 積載與隔離")
            col_g, col_h = st.columns(2)
            with col_g:
                st.markdown(
                    f'<div class="info-card-green">'
                    f'<b>積載類別</b><br>{data["stowage"] or "N/A"}'
                    f'</div>',
                    unsafe_allow_html=True
                )
            with col_h:
                sp = "、".join(data["special_provisions"]) if data["special_provisions"] else "無"
                st.markdown(
                    f'<div class="info-card-green">'
                    f'<b>特殊規定</b><br>{sp}'
                    f'</div>',
                    unsafe_allow_html=True
                )

            # ── 原始報告 ──
            with st.expander("📄 查看完整原始報告"):
                st.code(format_ems_report(data), language="text")


# ══════════════════════════════════════════════════════════════
# 頁面 2：AI 事故分析
# ══════════════════════════════════════════════════════════════
elif page == "🤖 AI 事故分析":

    st.markdown('<div class="main-title">🤖 AI 事故分析</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">描述事故情境，AI 根據 IMDG 資料給出應急建議</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="warning-banner">'
        '⚠️ AI 建議僅供參考，緊急情況請立即聯繫 CHEMTREC (+1-703-527-3887) 或當地應急機構'
        '</div>',
        unsafe_allow_html=True
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        un_input = st.text_input(
            "UN 號碼",
            value=st.session_state.last_un,
            placeholder="例如：1203"
        )
    with col2:
        incident_type = st.selectbox(
            "事故類型",
            options=["fire", "spillage", "first_aid", "general"],
            format_func=lambda x: {
                "fire":      "🔥 火災事故",
                "spillage":  "💧 洩漏事故",
                "first_aid": "🏥 人員傷亡急救",
                "general":   "📋 一般查詢"
            }[x]
        )

    additional = st.text_area(
        "額外情境說明（選填）",
        placeholder="例如：船艙內發現濃煙，疑似貨物起火，風速 15 節，船員 3 人在附近...",
        height=100
    )

    analyze_btn = st.button("🤖 開始 AI 分析", type="primary", use_container_width=True)

    if analyze_btn and un_input:
        st.session_state.last_un = un_input.strip()

        # 先顯示 EMS 資料摘要
        data = query_ems(un_input.strip())
        if data["found"]:
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("UN 號碼", data["un_number"])
            col_b.metric("物質名稱", data["proper_shipping_name"])
            col_c.metric("危險品類別", f"Class {data['hazard_class']}")

        st.markdown("---")
        st.markdown("#### 🤖 AI 應急建議")

        with st.spinner("AI 正在分析事故情境..."):
            result = analyze_incident(
                un_number=un_input.strip(),
                incident_type=incident_type,
                additional_info=additional
            )

        # ✅ 淺色背景容器 + st.markdown 渲染 Markdown 格式
        st.markdown('<div class="ai-response-wrapper">', unsafe_allow_html=True)
        st.markdown(result)
        st.markdown('</div>', unsafe_allow_html=True)

    elif analyze_btn and not un_input:
        st.warning("⚠️ 請輸入 UN 號碼")


# ══════════════════════════════════════════════════════════════
# 頁面 3：積載隔離檢查
# ══════════════════════════════════════════════════════════════
elif page == "🔄 積載隔離檢查":

    st.markdown('<div class="main-title">🔄 積載隔離檢查</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">檢查兩種危險品是否需要隔離</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 危險品 A")
        un_a = st.text_input("UN 號碼 A", placeholder="例如：1203", key="un_a")
        if un_a:
            data_a = query_ems(un_a.strip())
            if data_a["found"]:
                st.success(f"✅ {data_a['proper_shipping_name']} | Class {data_a['hazard_class']}")
            else:
                st.error("❌ 查無此 UN 號碼")

    with col2:
        st.markdown("#### 危險品 B")
        un_b = st.text_input("UN 號碼 B", placeholder="例如：1017", key="un_b")
        if un_b:
            data_b = query_ems(un_b.strip())
            if data_b["found"]:
                st.success(f"✅ {data_b['proper_shipping_name']} | Class {data_b['hazard_class']}")
            else:
                st.error("❌ 查無此 UN 號碼")

    check_btn = st.button("🔄 檢查相容性", type="primary", use_container_width=True)

    if check_btn:
        if not un_a or not un_b:
            st.warning("⚠️ 請輸入兩個 UN 號碼")
        else:
            st.markdown("---")
            st.markdown("#### 🤖 AI 相容性分析")

            with st.spinner("AI 正在分析積載相容性..."):
                result = check_segregation(un_a.strip(), un_b.strip())

            # ✅ 淺色背景容器 + st.markdown 渲染 Markdown 格式
            st.markdown('<div class="ai-response-wrapper">', unsafe_allow_html=True)
            st.markdown(result)
            st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# 頁面 4：自由問答
# ══════════════════════════════════════════════════════════════
elif page == "💬 自由問答":

    st.markdown('<div class="main-title">💬 自由問答</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">詢問任何 IMDG / 危險品相關問題</div>', unsafe_allow_html=True)

    # 聊天記錄顯示
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 選填 UN 號碼
    with st.expander("🔖 附加 UN 號碼資料（選填）"):
        ref_un = st.text_input(
            "UN 號碼",
            placeholder="填入後 AI 會參考該危險品資料回答",
            key="chat_un"
        )

    # 輸入框
    user_input = st.chat_input("輸入你的問題，例如：Class 3 危險品的主要火災風險是什麼？")

    if user_input:
        # 顯示使用者訊息
        st.session_state.chat_history.append({
            "role": "user",
            "content": user_input
        })
        with st.chat_message("user"):
            st.markdown(user_input)

        # AI 回應
        with st.chat_message("assistant"):
            with st.spinner("思考中..."):
                response = ask_dg_question(
                    question=user_input,
                    un_number=ref_un.strip() if ref_un else None
                )
            st.markdown(response)

        st.session_state.chat_history.append({
            "role": "assistant",
            "content": response
        })

    # 清除對話
    if st.session_state.chat_history:
        if st.button("🗑️ 清除對話記錄"):
            st.session_state.chat_history = []
            st.rerun()
