# ============================================================
# 🚢 app.py — DG Cargo Guardian 主介面
# ============================================================

import streamlit as st
from ems_engine import query_ems, format_ems_report
from ai_analyzer import analyze_incident, ask_dg_question, check_segregation , INCIDENT_SOP_MAP
# ── 積載隔離輔助函數 ─────────────────────────────────────────

def _validate_position(pos: str) -> bool:
    """驗證 BBRRTT 格式：6位純數字"""
    return len(pos) == 6 and pos.isdigit()


def _format_position(pos: str) -> str:
    """將 BBRRTT 轉為可讀格式"""
    if not _validate_position(pos):
        return pos

    bb  = pos[0:2]
    rr  = pos[2:4]
    tt  = pos[4:6]
    rr_int = int(rr)
    tt_int = int(tt)

    # Row 描述：00=中心線，雙數=左舷，單數=右舷
    if rr_int == 0:
        row_desc = "中心線"
    elif rr_int % 2 == 0:
        row_desc = f"左舷第{(rr_int // 2)}列"
    else:
        row_desc = f"右舷第{(rr_int // 2)}列"

    # Tier 描述：02–08=艙內，82起=甲板上第1層
    if tt_int < 80:
        tier_desc = f"艙內第{(tt_int - 2) // 2 + 1}層"
    else:
        tier_desc = f"甲板上第{(tt_int - 82) // 2 + 1}層"

    return f"Bay{bb} Row{rr}({row_desc}) Tier{tt}({tier_desc})"



def _calc_distance(pos_a: str, pos_b: str) -> str:
    """
    計算兩個貨櫃位置的大略距離描述
    Bay 差距 × 6m + Row 差距 × 2.4m
    """
    if not (_validate_position(pos_a) and _validate_position(pos_b)):
        return "未知"

    bay_a, row_a, tier_a = int(pos_a[0:2]), int(pos_a[2:4]), int(pos_a[4:6])
    bay_b, row_b, tier_b = int(pos_b[0:2]), int(pos_b[2:4]), int(pos_b[4:6])

    # Bay 間距約 6m（每個 Bay 含間隔），Row 間距約 2.4m
    bay_dist  = abs(bay_a - bay_b) * 6.0
    row_dist  = abs(row_a - row_b) * 2.4
    tier_dist = abs(tier_a - tier_b) * 2.6

    total = (bay_dist**2 + row_dist**2 + tier_dist**2) ** 0.5

    # 同一位置
    if total == 0:
        return "同一位置"
    elif total < 3:
        return f"約 {total:.1f}m（緊鄰）"
    elif total < 12:
        return f"約 {total:.1f}m（近距）"
    else:
        return f"約 {total:.1f}m"


def _render_position_map(cargos: list):
    """
    用 Streamlit 繪製簡易 Bay/Row 平面示意圖
    """
    import pandas as pd

    # 收集所有 Bay 和 Row
    positions = []
    for c in cargos:
        pos = c["position"]
        if _validate_position(pos):
            positions.append({
                "label":    c["label"],
                "un":       c["un"],
                "bay":      int(pos[0:2]),
                "row":      int(pos[2:4]),
                "tier":     int(pos[4:6]),
                "on_deck":  int(pos[4:6]) >= 80,
                "class":    c["data"]["hazard_class"]
            })

    if not positions:
        return

    # 建立簡易網格顯示
    all_bays = sorted(set(p["bay"] for p in positions))
    all_rows = sorted(set(p["row"] for p in positions))

    # 用 DataFrame 呈現
    grid = {}
    for bay in all_bays:
        col_data = {}
        for row in all_rows:
            items = [p for p in positions if p["bay"] == bay and p["row"] == row]
            if items:
                col_data[f"Row {row:02d}"] = " / ".join(
                    f"{p['label']}(UN{p['un']})" for p in items
                )
            else:
                col_data[f"Row {row:02d}"] = "—"
        grid[f"Bay {bay:02d}"] = col_data

    df = pd.DataFrame(grid).T
    st.dataframe(df, use_container_width=True)

    # 圖例
    cols = st.columns(len(cargos))
    colors = ["🔴", "🔵", "🟢", "🟡", "🟠", "🟣", "⚫", "⚪", "🟤", "🔶"]
    for i, cargo in enumerate(cargos):
        pos = cargo["position"]
        if _validate_position(pos):
            cols[i].caption(
                f"{colors[i % len(colors)]} {cargo['label']} | "
                f"UN{cargo['un']} | "
                f"{_format_position(pos)}"
            )


def _generate_report(cargos: list, results: list, violation_count: int) -> str:
    """產生純文字隔離檢查報告"""
    from datetime import datetime

    lines = [
        "=" * 60,
        "  DG CARGO GUARDIAN — 積載隔離檢查報告",
        f"  產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
        "【貨物清單】",
    ]

    for c in cargos:
        lines.append(
            f"  {c['label']:6s} | UN{c['un']:4s} | "
            f"{c['data']['proper_shipping_name'][:35]:35s} | "
            f"Class {c['data']['hazard_class']:4s} | "
            f"位置：{_format_position(c['position'])}"
        )

    lines += [
        "",
        f"【檢查結果摘要】共 {len(results)} 組配對，{violation_count} 項違規",
        "",
    ]

    for res in results:
        is_v = any(
            kw in res["result"]
            for kw in ["違規", "違反", "不得", "禁止", "VIOLATION", "❌"]
        )
        lines += [
            "-" * 60,
            f"{'🚨 [違規]' if is_v else '✅ [合規]'}  "
            f"{res['label_a']}(UN{res['un_a']} @ {res['pos_a']})  ×  "
            f"{res['label_b']}(UN{res['un_b']} @ {res['pos_b']})",
            f"距離：{_calc_distance(res['pos_a'], res['pos_b'])}",
            "",
            res["result"],
            "",
        ]

    lines += [
        "=" * 60,
        "⚠️  本報告僅供參考，實際操作請依 IMDG Code 官方規定",
        "=" * 60,
    ]

    return "\n".join(lines)

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
        options=[
            "deck_container_fire",
            "hold_container_fire",
            "engine_room_fire",
            "cargo_leakage",
            "container_overboard",
            "fire",
            "spillage",
            "first_aid",
            "general",
        ],
        format_func=lambda x: {
            "deck_container_fire": "🔥 甲板貨櫃失火（WHL 3-3）",
            "hold_container_fire": "🔥 貨艙貨櫃失火（WHL 3-4）",
            "engine_room_fire":    "🔥 機艙失火（WHL 1-5）",
            "cargo_leakage":       "💧 貨櫃洩漏 氣體/液體（WHL 3-5）",
            "container_overboard": "📦 貨櫃落海/傾倒/位移（WHL 3-2）",
            "fire":                "🔥 火災事故（一般）",
            "spillage":            "💧 洩漏事故（一般）",
            "first_aid":           "🏥 人員傷亡急救（MFAG）",
            "general":             "📋 一般查詢",
        }[x],
        label_visibility="collapsed"
    )

    # ── SOP 參考標籤（顯示在 selectbox 下方）──
    sop_badges = {
        "deck_container_fire": ("3-3", "#dc2626"),
        "hold_container_fire": ("3-4", "#b45309"),
        "engine_room_fire":    ("1-5", "#7c3aed"),
        "cargo_leakage":       ("3-5", "#0369a1"),
        "container_overboard": ("3-2", "#047857"),
        "fire":                ("IMDG", "#dc2626"),
        "spillage":            ("IMDG", "#0369a1"),
        "first_aid":           ("MFAG", "#047857"),
        "general":             ("IMDG", "#475569"),
    }
    badge_code, badge_color = sop_badges.get(incident_type, ("IMDG", "#475569"))
    st.markdown(
        f'<div style="margin-top:-8px; margin-bottom:8px;">'
        f'<span style="background:{badge_color}; color:#fff; font-size:0.72rem;'
        f'font-weight:700; padding:3px 10px; border-radius:4px;'
        f'letter-spacing:1px;">WHL SOP {badge_code}</span>'
        f'&nbsp;<span style="font-size:0.78rem; color:#64748b;">'
        f'參考：{INCIDENT_SOP_MAP.get(incident_type, "IMDG Code")}</span>'
        f'</div>',
        unsafe_allow_html=True
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
    st.markdown('<div class="sub-title">輸入 UN 號碼與貨櫃位置，檢查是否違反 IMDG 隔離規定</div>', unsafe_allow_html=True)

    # ── BBRRTT 格式說明 ──────────────────────────────────────
    with st.expander("📖 貨櫃位置格式說明 (BBRRTT)"):
        st.markdown("""
        | 欄位 | 說明 | 範例 |
        |------|------|------|
        | **BB** | Bay（貝位，船身前後位置） | 02, 06, 10… |
        | **RR** | Row（列位，左右位置） | 00=中心線, 02=左舷第1列, 01=右舷第1列 |
        | **TT** | Tier（層位，上下位置） | 02=艙內最底層, 82=甲板上第1層 |

        **完整範例：** `030282` = Bay 03, Row 02（左舷第1列）, Tier 82（甲板上第1層）

        > Tier 02–08 為艙內，82 以上為甲板上（每層遞增 2）
        """)

    st.markdown("---")

    # ── 輸入區：支援多筆貨物 ────────────────────────────────
    st.markdown("#### 📦 貨物清單")
    st.caption("最多可新增 10 筆貨物，系統將逐一比對所有組合")

    # Session State 管理貨物清單
    if "cargo_list" not in st.session_state:
        st.session_state.cargo_list = [
            {"un": "", "position": "", "label": "貨物 1"},
            {"un": "", "position": "", "label": "貨物 2"},
        ]

    # 新增 / 移除貨物按鈕
    col_add, col_remove, col_clear = st.columns([1, 1, 2])
    with col_add:
        if st.button("➕ 新增貨物", use_container_width=True):
            if len(st.session_state.cargo_list) < 10:
                n = len(st.session_state.cargo_list) + 1
                st.session_state.cargo_list.append(
                    {"un": "", "position": "", "label": f"貨物 {n}"}
                )
            else:
                st.warning("最多 10 筆貨物")
    with col_remove:
        if st.button("➖ 移除最後一筆", use_container_width=True):
            if len(st.session_state.cargo_list) > 2:
                st.session_state.cargo_list.pop()

    st.markdown("")

    # 貨物輸入表格
    validated_cargos = []  # 通過驗證的貨物清單

    for i, cargo in enumerate(st.session_state.cargo_list):
        col_label, col_un, col_pos, col_status = st.columns([1, 2, 2, 3])

        with col_label:
            st.markdown(f"<br><b>{cargo['label']}</b>", unsafe_allow_html=True)

        with col_un:
            un_val = st.text_input(
                f"UN 號碼",
                value=cargo["un"],
                placeholder="例：1203",
                key=f"seg_un_{i}",
                label_visibility="collapsed" if i > 0 else "visible"
            )
            st.session_state.cargo_list[i]["un"] = un_val

        with col_pos:
            pos_val = st.text_input(
                f"位置 (BBRRTT)",
                value=cargo["position"],
                placeholder="例：030282",
                key=f"seg_pos_{i}",
                label_visibility="collapsed" if i > 0 else "visible",
                max_chars=6
            )
            st.session_state.cargo_list[i]["position"] = pos_val

        with col_status:
            # 即時驗證輸入
            if un_val and pos_val:
                dg_data = query_ems(un_val.strip())
                pos_valid = _validate_position(pos_val.strip())

                if dg_data["found"] and pos_valid:
                    st.success(
                        f"✅ {dg_data['proper_shipping_name'][:25]}… "
                        f"| Class {dg_data['hazard_class']} "
                        f"| {_format_position(pos_val.strip())}",
                        icon=None
                    )
                    validated_cargos.append({
                        "label":    cargo["label"],
                        "un":       un_val.strip(),
                        "position": pos_val.strip(),
                        "data":     dg_data
                    })
                elif not dg_data["found"]:
                    st.error(f"❌ UN{un_val} 查無資料")
                elif not pos_valid:
                    st.warning("⚠️ 位置格式錯誤，請輸入6位數字")
            elif un_val or pos_val:
                st.caption("請同時填入 UN 號碼與位置")

    st.markdown("---")

    # ── 視覺化艙面示意圖 ────────────────────────────────────
    if len(validated_cargos) >= 2:
        st.markdown("#### 🗺️ 貨物位置示意")
        _render_position_map(validated_cargos)

    # ── 檢查按鈕 ─────────────────────────────────────────────
    check_btn = st.button(
        "🔄 執行隔離檢查",
        type="primary",
        use_container_width=True,
        disabled=len(validated_cargos) < 2
    )

    if len(validated_cargos) < 2:
        st.caption("⚠️ 請至少填入 2 筆有效貨物資料才能執行檢查")

    if check_btn and len(validated_cargos) >= 2:
        st.markdown("---")
        st.markdown("#### 📊 隔離檢查結果")

        # 逐一比對所有貨物組合
        from itertools import combinations
        pairs = list(combinations(validated_cargos, 2))

        all_results   = []
        violation_count = 0

        for cargo_a, cargo_b in pairs:
            with st.spinner(f"檢查 {cargo_a['label']} × {cargo_b['label']}..."):
                result = check_segregation(
                    un_a=cargo_a["un"],
                    un_b=cargo_b["un"],
                    pos_a=cargo_a["position"],
                    pos_b=cargo_b["position"]
                )
                all_results.append({
                    "label_a": cargo_a["label"],
                    "label_b": cargo_b["label"],
                    "un_a":    cargo_a["un"],
                    "un_b":    cargo_b["un"],
                    "pos_a":   cargo_a["position"],
                    "pos_b":   cargo_b["position"],
                    "result":  result
                })

                # 簡易判斷是否違規（根據 AI 回傳內容關鍵字）
                if any(kw in result for kw in ["違規", "違反", "不得", "禁止", "VIOLATION", "❌"]):
                    violation_count += 1

        # 總結橫幅
        if violation_count == 0:
            st.success(f"✅ 共檢查 {len(pairs)} 組配對，**未發現隔離違規**")
        else:
            st.error(f"🚨 共檢查 {len(pairs)} 組配對，發現 **{violation_count} 項隔離違規**，請立即處理！")

        # 逐組顯示結果
        for res in all_results:
            dist = _calc_distance(res["pos_a"], res["pos_b"])
            is_violation = any(
                kw in res["result"]
                for kw in ["違規", "違反", "不得", "禁止", "VIOLATION", "❌"]
            )

            with st.expander(
                f"{'🚨' if is_violation else '✅'} "
                f"{res['label_a']} (UN{res['un_a']} @ {res['pos_a']})  ×  "
                f"{res['label_b']} (UN{res['un_b']} @ {res['pos_b']})  "
                f"｜距離約 {dist}",
                expanded=is_violation
            ):
                st.markdown('<div class="ai-response-wrapper">', unsafe_allow_html=True)
                st.markdown(res["result"])
                st.markdown('</div>', unsafe_allow_html=True)

        # 匯出報告按鈕
        st.markdown("---")
        report_text = _generate_report(validated_cargos, all_results, violation_count)
        st.download_button(
            label="📥 下載完整隔離檢查報告",
            data=report_text,
            file_name="segregation_report.txt",
            mime="text/plain",
            use_container_width=True
        )



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
    st.markdown(
        '<div style="font-size:0.72rem; color:#475569; text-transform:uppercase;'
        'letter-spacing:1.5px; margin:10px 0 6px 0;">📖 WHL SOP 快捷問題</div>',
        unsafe_allow_html=True
    )

    quick_questions = {
        "🔥 甲板貨櫃失火，CO2 釋放前需確認哪些事項？":
            "依 WHL 3-3，甲板貨櫃失火時，CO2 釋放前需確認哪些事項？請逐條列出。",
        "💧 貨艙失火，何時應放棄探火直接釋放 CO2？":
            "依 WHL 3-4，貨艙貨櫃失火時，何種情況下應放棄探火，直接釋放 CO2？",
        "🔧 機艙失火，CO2 釋放後需密封多久？":
            "依 WHL 1-5，機艙失火釋放 CO2 後，機艙需保持密封多少小時？原因為何？",
        "📦 貨櫃落海，惡劣天候甲板作業需符合哪些條件？":
            "依 WHL 3-2，貨櫃落海後派員至甲板作業，需符合哪些安全條件？",
        "☎️ 緊急事故發生後，何時需通知海技部？":
            "WHL 各類緊急事故（失火/洩漏/落海），通知海技部（Maritech Division）的時機與內容要點為何？",
    }

    cols = st.columns(2)
    for i, (btn_label, question_text) in enumerate(quick_questions.items()):
        with cols[i % 2]:
            if st.button(btn_label, use_container_width=True, key=f"quick_q_{i}"):
                # 直接觸發問答
                st.session_state.chat_history.append({
                    "role": "user", "content": question_text
                })
                st.rerun()


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
