# ============================================================
# 🚢 app.py — DG Cargo Guardian 主介面（完整版）
# ============================================================

import io
import contextlib
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from itertools import combinations

import streamlit as st
from ems_engine       import query_ems, format_ems_report
from ai_analyzer      import (
    analyze_incident, ask_dg_question, INCIDENT_SOP_MAP,
    check_segregation_deterministic, explain_segregation_result,
    judge_segregation_with_ai,
)
from llm_client        import AI_ENABLED
from manifest_parser  import (
    parse_manifest_excel, parse_manifest_csv,
    parse_asc_file,
    get_manifest_summary, generate_sample_template,
)
from bay_plan_engine  import (
    build_bay_plan, get_bay_dimensions, parse_position,
    get_cell_display, get_row_label, get_tier_label,
    get_plan_statistics, get_class_color, get_class_color_legend,
    get_ems_fire_color, get_ems_fire_color_legend,
    get_ems_extinguish_guidance, get_ems_extinguish_legend, EMS_EXTINGUISH_SOURCE,
    get_action_card_guidance,
    find_nearby_dg, get_nearby_segregation_summary,
    calc_distance_m, describe_distance,
)
from fire_classifier  import get_color_legend
from segregation_engine import (
    get_general_table_display_rows, GENERAL_TABLE_COL_LABELS,
    GENERAL_TABLE_TERMS, GENERAL_TABLE_SOURCE,
)
from vessel_profile    import classify_tier
from variant_resolver  import record_selection
from audit_log         import append_event
from llm_client       import get_llm_response
from ai_analyzer      import SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════════
# ── 積載隔離輔助函數
# ══════════════════════════════════════════════════════════════

def _validate_position(pos: str) -> bool:
    """驗證 BBRRTT 格式：6位純數字"""
    return len(pos) == 6 and pos.isdigit()


def _format_position(pos: str) -> str:
    """將 BBRRTT 轉為可讀格式"""
    if not _validate_position(pos):
        return pos

    bb     = pos[0:2]
    rr     = pos[2:4]
    tt     = pos[4:6]
    rr_int = int(rr)
    tt_int = int(tt)

    # Row 描述：00=中心線，奇數=左舷，偶數=右舷
    if rr_int == 0:
        row_desc = "中心線"
    elif rr_int % 2 == 1:
        row_desc = f"左舷第{(rr_int + 1) // 2}列"
    else:
        row_desc = f"右舷第{rr_int // 2}列"

    # Tier 描述（甲板／艙內判定：見 vessel_profile.classify_tier()）。
    # 2026-09 第四輪回饋（見 docs/KNOWN_LIMITATIONS.md §7.10.2）：使用者
    # 要求移除畫面上的「未經驗證」字樣以符合展示用途，經 AskUserQuestion
    # 明確選擇「整個系統移除」——本行僅移除顯示文字，classify_tier() 判定
    # 邏輯本身未變更，甲板／艙內仍是通用推測，實務仍須以船舶實際配載圖為準
    # （見 vessel_profile.py 檔案開頭說明）。
    deck = classify_tier(tt_int)
    tier_desc = "甲板上" if deck.on_deck else "艙內"

    return f"Bay{bb} Row{rr}({row_desc}) Tier{tt}({tier_desc})"


def _calc_distance(pos_a: str, pos_b: str) -> str:
    """
    計算兩個貨櫃位置的大略距離描述。

    改為呼叫 bay_plan_engine.calc_distance_m() / describe_distance()（與
    Bay Plan「鄰近 DG 貨物」功能共用同一套幾何近似公式與常數），避免同一套
    距離邏輯在 app.py 與 bay_plan_engine.py 各維護一份、日後容易產生落差。
    """
    return describe_distance(calc_distance_m(pos_a, pos_b))


_SEG_STATUS_ICON = {
    "NOT_VERIFIED":                     "⚫",
    "COMPLIANT":                        "🟢",
    "VIOLATION":                        "🔴",
    "GENERAL_TABLE_OK":                 "🟢",
    "GENERAL_TABLE_CAUTION":            "🟡",
    "GENERAL_TABLE_INFO":               "ℹ️",
    "TEST_FIXTURE_NOT_FOR_OPERATION":   "🧪",
}


def _render_nearby_dg_panel(cargo: dict, cargo_list: list, radius_m: float = 15.0, key_prefix: str = "") -> dict | None:
    """
    Deterministic（非 AI）：顯示目標貨物半徑內的其他 DG 貨物，及其
    SegregationEngine（deterministic）判定狀態。規格書 F-004「鄰近危險品」
    功能，供 DG Bay Plan 頁面的「三秒判斷卡」與 AI 事故分析頁面的「情境快照」
    共用，避免同一段邏輯重複維護。

    回傳 nearby_summary（get_nearby_segregation_summary() 的結果），供上層
    （例如 AI 事故分析頁面）進一步組成 vessel_context 傳給 analyze_incident()；
    若目標貨物缺少有效位置則回傳 None。
    """
    position = cargo.get("position", "")
    if not _validate_position(position):
        st.caption("⚫ 此貨物缺少有效位置資料，無法計算鄰近 DG 貨物")
        return None

    radius_m = st.slider(
        "搜尋半徑（公尺，依 Bay/Row/Tier 幾何近似，非官方配載圖精確距離）",
        min_value=3.0, max_value=60.0, value=float(radius_m), step=1.0,
        key=f"{key_prefix}_nearby_radius",
    )

    nearby = find_nearby_dg(
        cargo_list, position, radius_m=radius_m,
        exclude_container=cargo.get("container_no"),
    )
    if not nearby:
        st.caption(f"半徑 {radius_m:.0f}m 內未偵測到其他 DG 貨物（依目前已上傳艙單資料）")
        return {"checked": [], "not_verified": 0, "compliant": 0, "violation": 0,
                "general_ok": 0, "general_caution": 0}

    nearby_summary = get_nearby_segregation_summary(cargo, nearby)
    st.caption(
        f"半徑 {radius_m:.0f}m 內共 {len(nearby_summary['checked'])} 筆鄰近 DG 貨物 — "
        f"🟡 一般表可能不足 {nearby_summary['general_caution']}　"
        f"🟢 一般表未見不足 {nearby_summary['general_ok']}　"
        f"⚫ NOT_VERIFIED {nearby_summary['not_verified']}　"
        f"🔴 VIOLATION {nearby_summary['violation']}"
    )
    seg_df = pd.DataFrame([{
        "狀態":     f"{_SEG_STATUS_ICON.get(item['status'], '⚫')} {item['status']}",
        "貨櫃號碼": item["container_no"],
        "UN No":    f"UN{item['un_number']}",
        "Class":    item["hazard_class"],
        "距離":     item["distance_label"],
    } for item in nearby_summary["checked"]])
    st.dataframe(
        seg_df, use_container_width=True,
        height=min(300, 45 + len(seg_df) * 36),
    )
    st.caption(
        "⚠️ 隔離狀態由 SegregationEngine（deterministic）判定，非 AI 產生。"
        "🟡／🟢 依「一般類別對類別隔離表」（非公司核准之正式資料，不含逐物質 "
        "SG/SGG 特殊規定，距離為概略幾何估算）概略提醒；NOT_VERIFIED 代表連一般表"
        "也無法辨識類別。仍須依船上最新版 IMDG Code Segregation Table 及大副／"
        "船長判斷執行，不得僅依本清單做積載決策。"
    )
    return nearby_summary


def _build_bay_grid_figure(rows: list, tiers: list, cargo_by_pos: dict, title: str, plot_bg: str = "#0f172a", color_mode: str = "ems"):
    """
    共用的 Bay Plan 格狀圖繪製邏輯，甲板（Deck）與艙內（In-Hold）共用同一套
    繪圖邏輯（先前艙內完全沒有格狀圖，只有一份扁平清單，不利於快速掌握
    空間關係，見 docs/INITIAL_SAFETY_AUDIT.md C-5）。

    color_mode 直接透傳給 get_cell_display()：
        "extinguish" （2026-09 新增，預設）依滅火介質通則上色——回應使用者
                需求「應該要區分像是可用水 / CO2滅火，甚至高危險的類別要
                特別標示」；高風險 EmS 通則分組以紅色粗邊框特別標示。
        "ems"   依 EmS Fire Code（F-A ~ F-J）上色——回應使用者需求
                「根據 EMS 處理方式進行顏色的區隔」。
        "class" 依危險品 Class 上色。
    以上皆僅供視覺辨識，非風險等級（除紅色邊框代表高風險 EmS 通則分組，見
    get_ems_extinguish_guidance() 模組註解）。待確認品名格子在非高風險時以
    較粗的橘色邊框標示，方便與一般格子區分。

    2026-09 第五輪回饋：使用者提供 Bay Plan 視覺化參考圖（乾淨的格狀風險圖，
    格內僅顯示大字 UN 號碼），據此重新設計格內文字與排列邏輯（見
    docs/KNOWN_LIMITATIONS.md §7.11）：
      1. 格內文字改用 cell["primary"]（bay_plan_engine.get_cell_display()
         2026-09 新增欄位）僅顯示「UN{號碼}」大字，多貨物共用格時加註
         「+N」；完整貨櫃號碼／位置／Fire-Spill EMS／品名等細節仍完整保留在
         hover tooltip（cell["tooltip"]，滑鼠移到格子上即可查看），不因此
         遺漏任何資訊。
      2. 修正原本 Tier（垂直）排列反向的問題：原本用 reversed(tiers) 造成
         數字較大的 Tier 被畫在圖表下方，但實際船舶 Tier 編號越大代表位置
         越高（甲板上、艙內皆同），此處改直接依 tiers（已由
         get_bay_dimensions() 由小到大排序）由下到上繪製，數字大的 Tier
         自然出現在圖表上方，符合實際船舶結構與參考圖的視覺直覺。
      3. 以 scaleanchor 強制 x/y 軸等比例，格子固定為正方形，避免先前
         Row/Tier 數量不對稱時格子被拉伸成長條。
    """
    fig = go.Figure()

    # 2026-09 第八輪回饋（見 docs/KNOWN_LIMITATIONS.md §7.14.1）：
    # get_bay_dimensions() 現在會補齊 Row／Tier 之間所有物理存在、但危險品
    # 艙單中查無資料的座標（見 bay_plan_engine._fill_row_range()／
    # _fill_tier_range()），格子數量因此變多。這些補齊出來的格子維持中性
    # 灰階、不上色（只有實際登記為危險品的格子才依 EmS／Class 上色，呼應
    # 使用者需求「危險櫃變色就好」），並明確以「一般貨／空位」文字標示，
    # 誠實反映本系統僅追蹤危險品艙單、無法分辨該位置究竟是一般貨櫃還是
    # 真正空位。
    _GENERAL_CELL_BG     = "#1e293b"
    _GENERAL_CELL_BORDER = "#334155"
    _GENERAL_CELL_TEXT   = "#64748b"

    for ti, tier in enumerate(tiers):
        for ri, row in enumerate(rows):
            cargos     = cargo_by_pos.get((row, tier), [])
            cell       = get_cell_display(cargos, color_mode=color_mode)
            bg_color   = cell["color_hex"]    if cell else _GENERAL_CELL_BG
            txt_color  = cell["text_color"]   if cell else _GENERAL_CELL_TEXT
            border_hex = cell["border_hex"]   if cell else _GENERAL_CELL_BORDER
            border_w   = cell["border_width"] if cell else 1
            hover_txt  = (
                cell["tooltip"] if cell
                else f"Row {row:02d} / Tier {tier:02d} — 非本系統危險品艙單登記範圍"
                     f"（可能為一般貨櫃或空位，本系統僅追蹤危險品艙單，無法分辨）"
            )

            if cell:
                primary  = cell["primary"]
                text_lbl = f"UN{primary['un_number']}"
                if cell["count"] > 1:
                    text_lbl += f"<br><span style='font-size:0.6em;'>+{cell['count']-1}</span>"
            else:
                text_lbl = "<span style='font-size:0.55em;'>一般貨</span>"

            fig.add_shape(
                type="rect",
                x0=ri,       y0=ti,
                x1=ri + 1.0, y1=ti + 1.0,
                fillcolor=bg_color,
                line=dict(color=border_hex, width=border_w),
            )
            if text_lbl:
                fig.add_annotation(
                    x=ri + 0.5, y=ti + 0.5,
                    text=text_lbl,
                    showarrow=False,
                    font=dict(size=15, color=txt_color, family="Arial Black, Arial, sans-serif"),
                    align="center",
                )

            fig.add_trace(go.Scatter(
                x=[ri + 0.5], y=[ti + 0.5],
                mode="markers",
                marker=dict(size=30, opacity=0),
                hovertext=hover_txt,
                hoverinfo="text",
                showlegend=False,
            ))

    fig.update_xaxes(
        tickvals=[i + 0.5 for i in range(len(rows))],
        ticktext=[get_row_label(r) for r in rows],
        showgrid=False, zeroline=False,
        tickfont=dict(size=12, color="white"),
        range=[0, len(rows)],
        constrain="domain",
    )
    fig.update_yaxes(
        tickvals=[i + 0.5 for i in range(len(tiers))],
        ticktext=[get_tier_label(t) for t in tiers],
        showgrid=False, zeroline=False,
        tickfont=dict(size=12, color="white"),
        range=[0, len(tiers)],
        scaleanchor="x",
        scaleratio=1,
    )
    fig.update_layout(
        title=dict(text=title, font=dict(color="white", size=13)),
        height=max(160, len(tiers) * 90 + 80),
        margin=dict(l=60, r=20, t=40, b=40),
        paper_bgcolor=plot_bg,
        plot_bgcolor=plot_bg,
        font=dict(color="white"),
    )
    return fig


def _render_compact_color_legend(color_mode: str):
    """
    緊湊型圓點圖例（呼應使用者提供的 Bay Plan 參考圖：格狀風險圖旁附一份
    簡潔的圓點＋文字圖例）。僅為既有 get_*_legend() 資料的另一種精簡排版，
    不新增任何色標或資料；完整版圖例（含來源、範圍限制等免責聲明）仍保留在
    下方「🎨 色標說明」展開區塊，此處僅供快速對照，不取代完整版。
    """
    if color_mode == "extinguish":
        items = [{"hex": i["hex"], "label": i["label"]} for i in get_ems_extinguish_legend()]
    elif color_mode == "class":
        items = [{"hex": i["hex"], "label": f"Class {i['class']}"} for i in get_class_color_legend()]
    else:
        items = [{"hex": i["hex"], "label": i["code"]} for i in get_ems_fire_color_legend()]

    chip_html = "".join(
        f'<span style="display:inline-flex; align-items:center; gap:6px; '
        f'margin:3px 14px 3px 0; font-size:0.82rem;">'
        f'<span style="width:13px; height:13px; border-radius:50%; '
        f'background:{item["hex"]}; display:inline-block; flex-shrink:0;"></span>'
        f'{item["label"]}</span>'
        for item in items
    )
    st.markdown(
        f'<div style="padding:8px 12px; background:rgba(255,255,255,0.04); '
        f'border-radius:8px; margin-bottom:8px;">{chip_html}'
        f'<span style="display:inline-flex; align-items:center; gap:6px; '
        f'margin:3px 14px 3px 0; font-size:0.82rem;">'
        f'<span style="width:13px; height:13px; border-radius:3px; '
        f'border:3px solid #DC2626; display:inline-block; flex-shrink:0;"></span>'
        f'高風險 EmS 通則</span>'
        f'<span style="display:inline-flex; align-items:center; gap:6px; '
        f'margin:3px 0; font-size:0.82rem;">'
        f'<span style="width:13px; height:13px; border-radius:3px; '
        f'border:3px solid #f59e0b; display:inline-block; flex-shrink:0;"></span>'
        f'待確認品名</span>'
        # 2026-09 第八輪回饋（見 §7.14.1）：格狀圖補齊了物理間距後新增大量
        # 中性「一般貨／空位」格子，於圖例中明確標示其意義，避免使用者誤以
        # 為是危險品格子或誤判色標涵蓋範圍。
        f'<span style="display:inline-flex; align-items:center; gap:6px; '
        f'margin:3px 0; font-size:0.82rem;">'
        f'<span style="width:13px; height:13px; border-radius:3px; '
        f'background:#1e293b; border:1px solid #334155; display:inline-block; '
        f'flex-shrink:0;"></span>'
        f'一般貨／空位（非本系統危險品艙單登記範圍）</span></div>',
        unsafe_allow_html=True,
    )


def _render_position_map(cargos: list):
    """用 Streamlit 繪製簡易 Bay/Row 平面示意圖"""
    positions = []
    for c in cargos:
        pos = c["position"]
        if _validate_position(pos):
            positions.append({
                "label":   c["label"],
                "un":      c["un"],
                "bay":     int(pos[0:2]),
                "row":     int(pos[2:4]),
                "tier":    int(pos[4:6]),
                "on_deck": classify_tier(int(pos[4:6])).on_deck,
                "class":   c["data"]["hazard_class"],
            })

    if not positions:
        return

    all_bays = sorted(set(p["bay"] for p in positions))
    all_rows = sorted(set(p["row"] for p in positions))

    grid = {}
    for bay in all_bays:
        col_data = {}
        for row in all_rows:
            items = [p for p in positions if p["bay"] == bay and p["row"] == row]
            col_data[f"Row {row:02d}"] = (
                " / ".join(f"{p['label']}(UN{p['un']})" for p in items)
                if items else "—"
            )
        grid[f"Bay {bay:02d}"] = col_data

    df = pd.DataFrame(grid).T
    st.dataframe(df, use_container_width=True)

    colors = ["🔴", "🔵", "🟢", "🟡", "🟠", "🟣", "⚫", "⚪", "🟤", "🔶"]
    cols   = st.columns(len(cargos))
    for i, cargo in enumerate(cargos):
        if _validate_position(cargo["position"]):
            cols[i].caption(
                f"{colors[i % len(colors)]} {cargo['label']} | "
                f"UN{cargo['un']} | {_format_position(cargo['position'])}"
            )


def _generate_segregation_report(cargos: list, results: list, violation_count: int) -> str:
    """產生純文字隔離檢查報告"""
    lines = [
        "=" * 60,
        "  DG CARGO GUARDIAN — 積載隔離檢查報告",
        f"  產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60, "",
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
        seg = res["seg"]
        status_tag = {
            "VIOLATION":              "🚨 [VIOLATION]",
            "COMPLIANT":              "✅ [COMPLIANT]",
            "GENERAL_TABLE_CAUTION":  "🟡 [GENERAL_TABLE_CAUTION]",
            "GENERAL_TABLE_OK":       "🟢 [GENERAL_TABLE_OK]",
            "GENERAL_TABLE_INFO":     "ℹ️ [GENERAL_TABLE_INFO]",
        }.get(seg["status"], f"⚫ [{seg['status']}]")
        lines += [
            "-" * 60,
            f"{status_tag}  "
            f"{res['label_a']}(UN{res['un_a']} @ {res['pos_a']})  ×  "
            f"{res['label_b']}(UN{res['un_b']} @ {res['pos_b']})",
            f"距離：{_calc_distance(res['pos_a'], res['pos_b'])}",
            f"規則來源：{seg['regulation_basis']}（engine v{seg['engine_version']}"
            + (f"，rule {seg['rule_id']}" if seg['rule_id'] else "") + "）",
            "",
            seg["message"],
            "",
        ]
    lines += [
        "=" * 60,
        "⚠️  本報告為系統輔助紀錄，不取代 IMDG Code、公司 SMS 及船長判斷。",
        "    NOT_VERIFIED 項目代表系統尚無法自動判定，須由人工依正式資料確認。",
        "=" * 60,
    ]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# ── 頁面設定
# ══════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="DG Cargo Guardian — WHL",
    page_icon="🚢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ══════════════════════════════════════════════════════════════
# 🎨 企業視覺風格（萬海航運 WHL 色系）
# ══════════════════════════════════════════════════════════════
# 主色為萬海航運品牌識別的紅色系（船體／標誌用色），輔以海事產業慣用的深色底、
# 高對比設計，符合規格書「深色系主題、低光源友好、大字體高對比」的要求。
# 顏色僅作為「品牌識別／版面設計」用途；系統狀態色（灰＝未經驗證、黃＝待處理、
# 紅＝VIOLATION、綠＝COMPLIANT／成功）維持既有語意，不因企業色改變安全判讀邏輯
# （規格書 3.5：顏色不得暗示滅火介質或風險等級）。
st.markdown("""
<style>
    :root {
        --whl-red:        #E4002B;
        --whl-red-dark:   #A5001F;
        --whl-red-tint:   #3A0E15;
        --whl-navy:       #0B1220;
        --whl-navy-panel: #111A2E;
        --whl-navy-card:  #16213A;
        --whl-steel:      #2F6FB0;
        --whl-steel-tint: #10233A;
        --whl-ink:        #E8ECF4;
        --whl-ink-dim:    #94A3B8;
        --whl-border:     #26324A;
    }

    .stApp {
        background: var(--whl-navy);
        color: var(--whl-ink);
    }
    section[data-testid="stSidebar"] {
        background: var(--whl-navy-panel);
        border-right: 1px solid var(--whl-border);
    }
    section[data-testid="stSidebar"] * { color: var(--whl-ink) !important; }

    /* WHL 品牌識別區塊（取代先前依賴外部網路圖示 icons8.com 的 sidebar logo，
       離線環境下也能正常顯示，並改善規格書 C-6 提到的離線可用性問題）*/
    .whl-badge-wrap {
        display: flex; align-items: center; gap: 0.7rem;
        margin-bottom: 0.6rem;
    }
    .whl-badge {
        display: flex; align-items: center; justify-content: center;
        width: 46px; height: 46px; border-radius: 9px;
        background: linear-gradient(160deg, var(--whl-red) 0%, var(--whl-red-dark) 100%);
        color: #fff; font-weight: 800; font-size: 1.05rem; letter-spacing: 0.5px;
        box-shadow: 0 2px 8px rgba(228,0,43,0.35);
        flex-shrink: 0;
    }
    .whl-wordmark { line-height: 1.15; }
    .whl-wordmark .line1 {
        font-size: 0.72rem; font-weight: 700; letter-spacing: 2px;
        color: var(--whl-ink-dim); text-transform: uppercase;
    }
    .whl-wordmark .line2 {
        font-size: 1.05rem; font-weight: 800; color: var(--whl-ink);
    }

    .main-title {
        font-size: 2.1rem;
        font-weight: 800;
        color: var(--whl-ink);
        text-align: center;
        padding: 1rem 0 0.2rem 0;
        letter-spacing: 0.5px;
    }
    .main-title::before {
        content: "";
    }
    .sub-title {
        font-size: 1rem;
        color: var(--whl-ink-dim);
        text-align: center;
        margin-bottom: 1.6rem;
    }
    .whl-eyebrow {
        text-align: center;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 3px;
        text-transform: uppercase;
        color: var(--whl-red);
        margin-bottom: 0.2rem;
    }

    .info-card {
        background: var(--whl-red-tint);
        border-left: 4px solid var(--whl-red);
        border-radius: 8px;
        padding: 1rem 1.2rem;
        margin: 0.5rem 0;
        color: var(--whl-ink);
    }
    .info-card-blue {
        background: var(--whl-steel-tint);
        border-left: 4px solid var(--whl-steel);
        border-radius: 8px;
        padding: 1rem 1.2rem;
        margin: 0.5rem 0;
        color: var(--whl-ink);
    }
    .info-card-green {
        background: #0F2A1E;
        border-left: 4px solid #22C55E;
        border-radius: 8px;
        padding: 1rem 1.2rem;
        margin: 0.5rem 0;
        color: var(--whl-ink);
    }
    .info-card-grey {
        background: #1A2233;
        border-left: 4px solid #64748B;
        border-radius: 8px;
        padding: 1rem 1.2rem;
        margin: 0.5rem 0;
        color: var(--whl-ink);
    }
    .ems-badge {
        display: inline-block;
        background: var(--whl-red);
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
        background: var(--whl-steel);
        color: white;
        font-size: 1.1rem;
        font-weight: 700;
        padding: 0.3rem 0.8rem;
        border-radius: 6px;
        margin-right: 0.5rem;
        letter-spacing: 1px;
    }
    .whl-source-strip {
        display: inline-block;
        background: var(--whl-navy-card);
        border: 1px solid var(--whl-border);
        color: var(--whl-ink-dim);
        font-size: 0.75rem;
        padding: 0.35rem 0.7rem;
        border-radius: 999px;
        margin: 0.2rem 0.3rem 0.2rem 0;
    }
    .ai-response-wrapper {
        background: var(--whl-navy-card);
        border: 1px solid var(--whl-border);
        border-radius: 10px;
        padding: 1.5rem 1.8rem;
        margin-top: 0.5rem;
        color: var(--whl-ink);
    }
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

    /* Streamlit 原生元件配色微調，統一融入 WHL 深色主題 */
    div[data-testid="stMetric"] {
        background: var(--whl-navy-card);
        border: 1px solid var(--whl-border);
        border-radius: 10px;
        padding: 0.8rem 1rem;
    }
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] {
        color: var(--whl-ink-dim) !important;
    }
    /* 2026-09 修正：st.metric 預設值字型（~2.25rem）搭配 white-space:nowrap +
       text-overflow:ellipsis，長文字（例如完整危險品名稱）會被硬生生截斷、
       看不到完整內容。改為較小字級並允許換行，避免內容被裁掉。 */
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: var(--whl-ink) !important;
        font-size: 1.25rem !important;
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: unset !important;
        line-height: 1.35 !important;
        word-break: break-word;
    }
    code {
        background: #0B1220 !important;
        color: #FCA5A5 !important;
        border: 1px solid var(--whl-border);
        padding: 0.1rem 0.4rem;
        border-radius: 4px;
    }
    .stButton>button[kind="primary"] {
        background: var(--whl-red);
        border-color: var(--whl-red);
    }
    .stButton>button[kind="primary"]:hover {
        background: var(--whl-red-dark);
        border-color: var(--whl-red-dark);
    }
    div[data-testid="stExpander"] {
        background: var(--whl-navy-card);
        border: 1px solid var(--whl-border);
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)


# ── Session State 初始化 ─────────────────────────────────────
for key, default in {
    "chat_history":   [],
    "last_un":        "",
    "cargo_list":     [
        {"un": "", "position": "", "label": "貨物 1"},
        {"un": "", "position": "", "label": "貨物 2"},
    ],
    "dg_cargo_list":  [],
    "dg_bay_plan":    {},
    "seg_check_result": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ══════════════════════════════════════════════════════════════
# ── 側邊欄
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    # WHL 品牌識別（純 CSS／文字組成，不依賴外部圖片網址，離線環境下也能正常顯示——
    # 先前使用 https://img.icons8.com/... 的外部圖示，船上無網路時會顯示破圖）
    st.markdown(
        '<div class="whl-badge-wrap">'
        '<div class="whl-badge">WHL</div>'
        '<div class="whl-wordmark">'
        '<div class="line1">Wan Hai Lines</div>'
        '<div class="line2">DG Cargo Guardian</div>'
        '</div></div>',
        unsafe_allow_html=True
    )
    st.markdown(
        "<div style='color:#94A3B8; font-size:0.85rem; margin-top:-0.4rem;'>"
        "海運危險品應急處置輔助系統</div>",
        unsafe_allow_html=True
    )
    st.divider()

    page = st.radio(
        "📋 功能選單",
        options=[
            "🔍 EMS 快速查詢",
            "🤖 AI 事故分析",
            "🔄 積載隔離檢查",
            "🗺️ DG Bay Plan",
            "💬 自由問答",
        ],
        label_visibility="collapsed"
    )

    st.divider()

    st.markdown("#### 🔖 常用 UN 號碼")
    quick_uns = {
        "UN1203 — 汽油":  "1203",
        "UN1017 — 氯氣":  "1017",
        "UN1789 — 鹽酸":  "1789",
        "UN3480 — 鋰電池":"3480",
        "UN1072 — 氧氣":  "1072",
    }
    for label, un in quick_uns.items():
        if st.button(label, use_container_width=True):
            st.session_state.last_un = un

    st.divider()

    # ── AI 功能狀態（規格書強化：先前 DG_AI_ENABLED 只能靠讀原始碼才知道，
    #    使用者設定了 API Key 卻不知道還需要另外開關，容易誤以為「AI 分析故障」。
    #    此處明確顯示目前狀態，狀態本身仍完全依真實環境變數決定，不做任何偽裝。）
    st.markdown("#### 🤖 AI 輔助功能狀態")
    if AI_ENABLED:
        st.success("🟢 已啟用（DG_AI_ENABLED=true）")
    else:
        st.markdown(
            '<div class="info-card-grey" style="font-size:0.8rem; padding:0.7rem 0.9rem;">'
            "🔒 <b>未啟用</b>（系統預設關閉）<br>"
            "如需啟用：於 <code>.env</code> 設定 <code>DG_AI_ENABLED=true</code> 並重新啟動。"
            "核心查詢／隔離檢查／Bay Plan 等離線功能不受影響。"
            "</div>",
            unsafe_allow_html=True
        )

    st.divider()
    st.markdown(
        "<div style='font-size:0.75rem; color:#94A3B8; text-align:center;'>"
        "⚠️ 本系統為決策輔助工具，僅供參考<br>"
        "實際操作請依船上核准之 IMDG Code、EmS Guide、MFAG 及公司 SMS 程序，"
        "最終決定權屬船長<br>"
        "Wan Hai Lines © DG Cargo Guardian"
        "</div>",
        unsafe_allow_html=True
    )


# ══════════════════════════════════════════════════════════════
# 頁面 1：EMS 快速查詢
# ══════════════════════════════════════════════════════════════
if page == "🔍 EMS 快速查詢":

    st.markdown('<div class="main-title">🔍 EMS 快速查詢</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">輸入 UN 號碼，即時取得 IMDG 應急程序資料</div>', unsafe_allow_html=True)

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
            st.markdown("---")
            col_a, col_b, col_c, col_d = st.columns(4)
            col_a.metric("UN 號碼",   data["un_number"])
            col_b.metric("危險品類別", f"Class {data['hazard_class']}")
            col_c.metric("包裝等級",   data["packing_group"] or "N/A")
            col_d.metric("MFAG",       data["mfag"] or "N/A")

            st.markdown(f"### 📦 {data['proper_shipping_name']}")
            st.caption(data["description"])

            # ── 正式品名選列（規格書 3.2 / C-4）────────────────
            if data.get("requires_variant_selection"):
                st.info(f"📝 **待確認品名**：{data.get('variant_message', '')}")
                candidates = data.get("variant_candidates", [])
                option_labels = [
                    f"#{i+1} | PG {v.get('packing_group','N/A')} | "
                    f"Stowage {v.get('stowage_category','N/A')} | "
                    f"限量 {v.get('limited_quantity','N/A')} | "
                    f"來源頁碼 {v.get('source_page','N/A')}"
                    for i, v in enumerate(candidates)
                ]
                chosen_idx = st.radio(
                    "請依貨物文件（SDS／Dangerous Goods Declaration）選擇正確項目：",
                    options=list(range(len(candidates))),
                    format_func=lambda i: option_labels[i],
                    key=f"variant_radio_{data['un_number']}",
                )
                reason = st.text_input(
                    "選列依據（必填，將寫入稽核紀錄）",
                    key=f"variant_reason_{data['un_number']}",
                    placeholder="例如：依 SDS 濃度 45%，對應 PG II",
                )
                selected_by = st.text_input(
                    "選列人員（帳號／姓名，必填）",
                    key=f"variant_by_{data['un_number']}",
                    placeholder="例如：2/O Chen",
                )
                if st.button("✅ 確認選列", key=f"variant_confirm_{data['un_number']}"):
                    if not reason.strip() or not selected_by.strip():
                        st.error("請填寫選列依據與選列人員後再確認（規格書 3.2.9：override／選列必須留下理由與稽核紀錄）。")
                    else:
                        try:
                            record = record_selection(
                                un_number=data["un_number"],
                                selected_index=chosen_idx,
                                candidates=candidates,
                                reason=reason,
                                selected_by=selected_by,
                            )
                            append_event("variant_selection", record)
                            st.success(
                                f"已記錄選列：UN{data['un_number']} → #{chosen_idx+1}"
                                f"（PG {candidates[chosen_idx].get('packing_group','N/A')}）。"
                                "此為本次工作階段的暫時選列（Phase 2 將接入正式稽核與工作階段儲存），"
                                "本頁重新查詢後需重新選列。"
                            )
                        except ValueError as e:
                            st.error(str(e))
                st.info("在完成選列前，下方 Packing Group／積載類別欄位保持空白，不得依此做出積載決策。")

            # 2026-09 變更（見 docs/KNOWN_LIMITATIONS.md §7.8.1）：使用者於上一輪
            # 要求本頁「只留基礎查詢功能」，移除了本區塊；本輪使用者回報「EMS
            # 查詢頁面還是錯誤，要把EMS顯示進去，看他是要怎麼處置」，並在
            # AskUserQuestion 中明確選擇恢復「舊版具體處置文字＋顯眼警示」（與
            # §7.6.1 相同做法）。本區塊固定顯示、不可摺疊，內容為
            # imdg_database.json 既有的 legacy_unverified.emergency_action 欄位
            # （未依 IMDG Code 2024 Supplement 或 SDS 逐一核對來源），僅整理呈現，
            # 不做任何改寫或推測。
            #
            # 2026-09 第六輪回饋（見 §7.12）：使用者要求把下方原本「fail-closed
            # 預設提示」的 emergency_action 欄位換成每筆資料實際可用的內容——
            # 已依 UN 號碼比對美國/加拿大/墨西哥運輸主管機關 ERG2024 官方 Guide
            # Number 譯寫。此區塊因此不再是「預設提示」，改標示實際來源
            # （emergency_action_source），但仍維持原本「舊版資料optional展示、
            # 次要區塊對照」的畫面位階，未變更上一輪已確認的顯示順序。
            legacy_ea = data.get("legacy_emergency_action") or {}
            ea        = data.get("emergency_action") or {}
            ea_src    = data.get("emergency_action_source") or {}

            def _render_ea_source_caption():
                if ea_src.get("reference"):
                    st.caption(
                        f"來源：{ea_src['reference']}，"
                        f"Guide {ea_src.get('guide_number','')}"
                        f"（{ea_src.get('guide_title_en','')}）。{ea_src.get('note_cn','')}"
                    )

            if data.get("legacy_emergency_action_available"):
                st.markdown(
                    '<div class="warning-banner">'
                    '⚠️ 以下為系統舊版資料，尚未依 IMDG Code 2024 Supplement 核對來源，'
                    '不是官方逐字條文，僅供快速參考；正式處置仍須以船上核准之 IMDG Code、'
                    'EmS Guide、MFAG 及公司 SMS 程序，並經船長／大副確認為準'
                    '</div>',
                    unsafe_allow_html=True
                )
                st.markdown("#### 🔥 應急處置指引（舊版參考資料）")
                tab_fire, tab_spill, tab_first_aid = st.tabs(["🔥 滅火 Fire", "💧 洩漏 Spillage", "🏥 急救 First Aid"])
                with tab_fire:
                    st.markdown(legacy_ea.get("fire") or "（無資料）")
                with tab_spill:
                    st.markdown(legacy_ea.get("spillage") or "（無資料）")
                with tab_first_aid:
                    st.markdown(legacy_ea.get("first_aid") or "（無資料）")

                with st.expander("🧯 ERG2024 應急程序對照（美國/加拿大/墨西哥運輸主管機關公開資料）"):
                    st.markdown(f"**滅火 Fire**：{ea.get('fire', '')}")
                    st.markdown(f"**洩漏 Spillage**：{ea.get('spillage', '')}")
                    st.markdown(f"**急救 First Aid**：{ea.get('first_aid', '')}")
                    _render_ea_source_caption()
            else:
                st.info(
                    f"🔥 **滅火**：{ea.get('fire', '')}\n\n"
                    f"💧 **洩漏**：{ea.get('spillage', '')}\n\n"
                    f"🏥 **急救**：{ea.get('first_aid', '')}"
                )
                _render_ea_source_caption()

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

            # ── 隔離代碼（真實資料庫欄位，僅供對照，非合規判定）───────────
            seg_codes = data.get("segregation_codes") or []
            if data.get("requires_variant_selection"):
                st.caption("📝 隔離代碼待確認正式品名後才會顯示")
            elif seg_codes:
                seg_chips = " ".join(
                    '<span class="whl-source-strip">{}</span>'.format(c) for c in seg_codes
                )
                st.markdown(
                    f'<div class="info-card-grey">'
                    f'<b>隔離代碼（Segregation Codes）</b><br>'
                    f'{seg_chips}'
                    f'<div style="font-size:0.72rem; color:#94A3B8; margin-top:0.4rem;">'
                    f'僅供對照船上最新版 IMDG Code Segregation Table 使用，'
                    f'不構成合規／違規判定（判定請見「積載隔離檢查」頁面）。</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
            else:
                st.caption("⚫ 本筆資料尚無登記的隔離代碼")

            # ── 資料來源與版本（規格書強化：讓每筆查詢結果可稽核出處）──────
            if data.get("source_edition"):
                pages = data.get("source_pdf_pages") or []
                pages_str = "、".join(str(p) for p in pages) if pages else "N/A"
                with st.expander("📚 資料來源與版本"):
                    st.markdown(
                        f"**IMDG Code {data['source_edition']} Edition**"
                        + (f"，Amendment {data['source_amendment']}" if data.get("source_amendment") else "")
                        + (f"（{data['source_resolution']}）" if data.get("source_resolution") else "")
                    )
                    if data.get("source_effective_from"):
                        st.caption(f"生效日：{data['source_effective_from']}")
                    st.caption(f"Dangerous Goods List 頁碼：{pages_str}")
                    if data.get("source_verified_scope"):
                        st.markdown(f"✅ **已核對欄位**：{', '.join(data['source_verified_scope'])}")
                    if data.get("source_not_verified_scope"):
                        st.markdown(f"⚫ **待 2024 Supplement／SDS 核對欄位**：{', '.join(data['source_not_verified_scope'])}")

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
        '⚠️ AI 建議可能有錯誤，緊急情況請依船上應急聯絡清單聯繫項專業單位尋求協助'
        '</div>',
        unsafe_allow_html=True
    )

    # ── 從已上傳 Bay Plan 艙單選擇貨櫃（選填，可複選）──────────────
    # 真實事故通常發生在「某艘船某個航次某個貨櫃」，而非孤立的 UN 號碼；
    # 若使用者已在「DG Bay Plan」頁面上傳過艙單，這裡可直接選擇實際貨櫃，
    # 自動帶入位置、甲板／艙內判定與鄰近 DG 貨物的 deterministic 隔離狀態，
    # 讓 AI 的說明對應到目前真正裝載的情況（而不只是自由輸入的 UN 號碼）。
    #
    # 2026-09 第七輪回饋（見 docs/KNOWN_LIMITATIONS.md §7.13.2）：使用者反映
    # 「危險櫃可能同時裝有不同種的危險櫃，所以要能輸入多個不同的UN 號碼」——
    # 選單改為 st.multiselect 可複選多個實際貨櫃；每個選取的貨櫃分別顯示
    # 自己的情境快照與鄰近 DG 貨物面板，不互相覆蓋。
    loaded_cargo_list = st.session_state.get("dg_cargo_list", [])
    selected_cargos    = []   # 使用者複選的貨櫃（來自艙單），list[dict]
    cargo_un_numbers   = []   # 上列貨櫃對應的 UN 號碼（去重、保留順序）
    # 各貨櫃的鄰近 DG 摘要另存於獨立 dict（依貨櫃號碼），不寫回
    # st.session_state.dg_cargo_list 內的原始貨物字典，避免污染其他頁面
    # （例如 Bay Plan 頁）共用的同一份資料結構。
    nearby_summary_by_container = {}

    if loaded_cargo_list:
        cargo_labels = {
            f"{c['container_no']} ｜ UN{c['un_number']} ｜ "
            f"{c['position'] or '無位置'} ｜ {(c['description'] or '')[:20]}": c
            for c in loaded_cargo_list
        }
        picks = st.multiselect(
            "🔗 從已上傳 Bay Plan 艙單選擇貨櫃（可複選，自動帶入位置與鄰近 DG 貨物資訊）",
            options=list(cargo_labels.keys()),
            key="ai_cargo_picker",
        )
        for pick in picks:
            cargo = cargo_labels[pick]
            selected_cargos.append(cargo)
            if cargo["un_number"] not in cargo_un_numbers:
                cargo_un_numbers.append(cargo["un_number"])

        if selected_cargos:
            if len(selected_cargos) == 1:
                st.session_state.last_un = selected_cargos[0]["un_number"]
            st.markdown("##### 🧭 情境快照（Deterministic，非 AI；將一併提供給 AI 作為背景資料）")
            for idx, cargo in enumerate(selected_cargos, 1):
                # 2026-09 第四輪回饋（見 docs/KNOWN_LIMITATIONS.md §7.10.2）：
                # 使用者要求移除「未經驗證」字樣，經 AskUserQuestion 明確選擇
                # 「整個系統移除」——本區塊僅移除顯示文字，parse_position()
                # 判定邏輯本身未變更。
                pos_info  = parse_position(cargo.get("position", "")) if cargo.get("position") else None
                deck_desc = "未知（缺少有效位置）"
                if pos_info:
                    deck_desc = "🚢 甲板上 On-Deck" if pos_info["on_deck"] else "🕳️ 艙內 In-Hold"

                st.markdown(
                    f"**貨櫃 {idx}／{len(selected_cargos)}：{cargo['container_no']} "
                    f"（UN{cargo['un_number']}）**"
                )
                snap_c1, snap_c2, snap_c3 = st.columns(3)
                snap_c1.metric("貨櫃位置", cargo.get("position") or "—")
                snap_c2.metric("甲板／艙內", deck_desc)
                snap_c3.metric(
                    "正式品名選列",
                    "📝 待確認品名" if cargo.get("requires_variant_selection") else "✅ 已確定"
                )
                with st.expander(f"📍 {cargo['container_no']} 鄰近 DG 貨物與隔離狀態", expanded=(len(selected_cargos) == 1)):
                    nearby_summary_by_container[cargo["container_no"]] = _render_nearby_dg_panel(
                        cargo, loaded_cargo_list, radius_m=15.0, key_prefix=f"ai_page_{idx}"
                    )
            st.markdown("---")

    # 2026-09 修正：col1（UN 號碼）先前顯示標籤文字，col2（事故類型）label 卻
    # 被 label_visibility="collapsed" 隱藏，兩欄輸入框因此高度不同、視覺上沒
    # 對齊。改為兩欄都顯示標籤，並整段包在有邊框的卡片容器內，避免頁面看起來
    # 空空的（st.container(border=True) 需 Streamlit ≥ 1.29，本專案已符合）。
    with st.container(border=True):
        st.markdown("##### 📝 事故基本資訊")
        col1, col2 = st.columns([1, 1])
        with col1:
            # 2026-09 第七輪回饋（見 docs/KNOWN_LIMITATIONS.md §7.13.2）：
            # 使用者反映「危險櫃可能同時裝有不同種的危險櫃，所以要能輸入多個
            # 不同的UN 號碼」——輸入框改為可接受多個 UN 號碼（以逗號／頓號／
            # 分號／空白／換行分隔皆可），上方複選的貨櫃 UN 號碼會自動一併
            # 納入分析，兩者取聯集、不重複。
            un_input = st.text_input(
                "UN 號碼（可輸入多個，以逗號或空白分隔）",
                value=st.session_state.last_un,
                placeholder="例如：1203, 3077, 1830"
            )
        with col2:
            incident_type = st.selectbox(
                "事故類型",
                options=[
                    "deck_container_fire",
                    "hold_container_fire",
                    "engine_room_fire",
                    "cargo_leakage",
                    "dg_fire_leakage",
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
                    "dg_fire_leakage":     "☣️ 危險貨櫃事故 失火／洩漏（WHL 3-5-1）",
                    "container_overboard": "📦 貨櫃落海/傾倒/位移（WHL 3-2）",
                    "fire":                "🔥 火災事故（一般）",
                    "spillage":            "💧 洩漏事故（一般）",
                    "first_aid":           "🏥 人員傷亡急救（MFAG）",
                    "general":             "📋 一般查詢",
                }[x],
            )

        # SOP 參考標籤
        sop_badges = {
            "deck_container_fire": ("3-3", "#dc2626"),
            "hold_container_fire": ("3-4", "#b45309"),
            "engine_room_fire":    ("1-5", "#7c3aed"),
            "cargo_leakage":       ("3-5", "#0369a1"),
            "dg_fire_leakage":     ("3-5-1", "#991b1b"),
            "container_overboard": ("3-2", "#047857"),
            "fire":                ("IMDG", "#dc2626"),
            "spillage":            ("IMDG", "#0369a1"),
            "first_aid":           ("MFAG", "#047857"),
            "general":             ("IMDG", "#475569"),
        }
        badge_code, badge_color = sop_badges.get(incident_type, ("IMDG", "#475569"))
        st.markdown(
            f'<div style="margin-top:2px; margin-bottom:8px;">'
            f'<span style="background:{badge_color}; color:#fff; font-size:0.72rem;'
            f'font-weight:700; padding:3px 10px; border-radius:4px;'
            f'letter-spacing:1px;">WHL SOP {badge_code}</span>'
            f'&nbsp;<span style="font-size:0.78rem; color:#94A3B8;">'
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

    # 2026-09 第七輪回饋：解析多個 UN 號碼（手動輸入 ∪ 上方複選貨櫃），
    # 純字串處理，不涉及任何判斷邏輯。支援逗號、頓號、分號（全形／半形）、
    # 空白、換行等常見分隔方式。
    _raw_manual = (un_input or "").strip()
    for _sep in ("，", "、", ";", "；", "\n", "\t"):
        _raw_manual = _raw_manual.replace(_sep, ",")
    manual_un_numbers = []
    for _piece in _raw_manual.split(","):
        manual_un_numbers.extend(_piece.split())

    all_un_numbers = []
    for u in cargo_un_numbers + manual_un_numbers:
        u = u.strip()
        if u and u not in all_un_numbers:
            all_un_numbers.append(u)

    if analyze_btn and all_un_numbers:
        st.session_state.last_un = un_input.strip()

        ems_lookup = {u: query_ems(u) for u in all_un_numbers}
        for u in all_un_numbers:
            data = ems_lookup[u]
            if data["found"]:
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("UN 號碼",  data["un_number"])
                col_b.metric("物質名稱", data["proper_shipping_name"])
                col_c.metric("危險品類別", f"Class {data['hazard_class']}")
            else:
                st.warning(f"⚠️ UN{u}：資料庫查無此 UN 號碼")

        st.markdown("---")
        st.markdown("#### 🤖 AI 應急建議")

        # 若使用者從上方複選了實際已載入的貨櫃，組裝 deterministic 情境快照
        # （每個選取的貨櫃各自一份）一併提供給 AI（見
        # ai_analyzer._build_situation_context）；完全未選擇貨櫃、僅手動輸入
        # UN 號碼時 vessel_context 維持 None，行為與先前相同。
        vessel_context = None
        if selected_cargos:
            containers = []
            for cargo in selected_cargos:
                pos_info = (
                    parse_position(cargo.get("position", ""))
                    if cargo.get("position") else None
                )
                containers.append({
                    "vessel_name":      cargo.get("ship_name") or "",
                    "voyage":           cargo.get("voyage") or "",
                    "container_no":     cargo.get("container_no", ""),
                    "position":         cargo.get("position", ""),
                    "on_deck":          pos_info["on_deck"] if pos_info else None,
                    "on_deck_verified": pos_info["on_deck_verified"] if pos_info else False,
                    "ambiguous":        bool(cargo.get("requires_variant_selection")),
                    "nearby_summary":   nearby_summary_by_container.get(cargo.get("container_no")),
                })
            vessel_context = {"containers": containers}

        with st.spinner("AI 正在分析事故情境..."):
            result = analyze_incident(
                un_numbers      = all_un_numbers,
                incident_type   = incident_type,
                additional_info = additional,
                vessel_context  = vessel_context,
            )

        st.markdown('<div class="ai-response-wrapper">', unsafe_allow_html=True)
        st.markdown(result)
        st.markdown('</div>', unsafe_allow_html=True)

    elif analyze_btn and not all_un_numbers:
        st.warning("⚠️ 請輸入至少一個 UN 號碼，或從上方艙單選擇至少一個貨櫃")


# ══════════════════════════════════════════════════════════════
# 頁面 3：積載隔離檢查
# ══════════════════════════════════════════════════════════════
elif page == "🔄 積載隔離檢查":

    st.markdown('<div class="main-title">🔄 積載隔離檢查</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">輸入 UN 號碼與貨櫃位置，檢查是否違反 IMDG 隔離規定</div>', unsafe_allow_html=True)

    with st.expander("📖 貨櫃位置說明"):
        st.markdown("""
        | 欄位 | 說明 | 範例 |
        |------|------|------|
        | **BB** | Bay（貝位，船身前後位置） | 01, 03, 05… |
        | **RR** | Row（列位，左右位置） | 00=中心線, 01=左舷第1列, 02=右舷第1列 |
        | **TT** | Tier（層位，上下位置） | 數值越大通常代表越高層 |

        **完整範例：** `030282` = Bay 03, Row 02（右舷第1列）, Tier 82
        """)

    # 2026-09 第三輪回饋（見 docs/KNOWN_LIMITATIONS.md §7.9.1）：使用者上傳
    # 公司文件「附表三 危險品隔離表」，要求加入本頁供人工同步核對。此區塊
    # 純粹原樣呈現該文件的類別對類別矩陣（與既有 GENERAL_TABLE 逐格比對後
    # 確認數值一致，見 segregation_engine.py 檔案開頭說明），僅供人工目視
    # 對照，不是新的判斷邏輯——下方「隔離檢查結果」仍完全依既有 deterministic
    # engine／AI 判斷顯示，此表不參與任何計算。
    with st.expander("📋 附表三　危險品隔離表", expanded=False):
        st.caption(
            "公司文件「附表三 危險品隔離表」原文重現，"
            "數值已與系統一般類別隔離表逐格核對一致。"
            f"（{GENERAL_TABLE_SOURCE}）"
        )
        # 2026-09 第四輪回饋：原始版本邊框顏色（#555）與對齊方式在深色主題下
        # 顯得雜亂，改用與整體品牌 CSS 變數（--whl-*）一致的配色、統一置中
        # 對齊、加上表頭 sticky／整表圓角卡片樣式，並以淡色分組凸顯「同一
        # 類別對自身」（對角線）儲存格，提升可讀性與專業度。純視覺調整，
        # 表格數值與資料來源皆未變更。
        display_rows = get_general_table_display_rows()
        col_keys = list(GENERAL_TABLE_COL_LABELS.keys())

        table_html = (
            '<div style="overflow-x:auto; border-radius:10px; border:1px solid var(--whl-border); '
            'box-shadow:0 2px 10px rgba(0,0,0,0.25);">'
            '<table style="border-collapse:collapse; font-size:0.8rem; width:100%; min-width:900px;">'
        )
        table_html += (
            '<thead><tr>'
            '<th style="position:sticky; left:0; z-index:2; background:var(--whl-red); color:#fff; '
            'padding:8px 10px; text-align:left; white-space:nowrap; font-weight:700; '
            'border-bottom:2px solid var(--whl-red-dark); border-right:1px solid var(--whl-red-dark);">類　別</th>'
        )
        for ck in col_keys:
            table_html += (
                '<th style="background:var(--whl-red); color:#fff; padding:8px 6px; text-align:center; '
                'white-space:nowrap; font-weight:700; border-bottom:2px solid var(--whl-red-dark); '
                f'border-left:1px solid var(--whl-red-dark);">{GENERAL_TABLE_COL_LABELS[ck]}</th>'
            )
        table_html += "</tr></thead><tbody>"

        for i, row in enumerate(display_rows):
            row_bg = "var(--whl-navy-card)" if i % 2 == 0 else "var(--whl-navy-panel)"
            table_html += (
                f'<tr style="background:{row_bg};">'
                f'<td style="position:sticky; left:0; z-index:1; background:{row_bg}; color:var(--whl-ink); '
                f'padding:6px 10px; text-align:left; white-space:nowrap; font-weight:600; '
                f'border-right:1px solid var(--whl-border); border-bottom:1px solid var(--whl-border);">'
                f'{row["row_label"]}</td>'
            )
            for ck, v in zip(col_keys, row["values"]):
                is_self = (ck == row["row_key"])
                cell_style = (
                    "padding:6px 4px; text-align:center; color:var(--whl-ink); "
                    "border-bottom:1px solid var(--whl-border); border-left:1px solid var(--whl-border);"
                )
                if is_self:
                    cell_style += " background:rgba(148,163,184,0.12); color:var(--whl-ink-dim);"
                elif v == "X":
                    cell_style += " color:var(--whl-ink-dim);"
                else:
                    cell_style += " font-weight:700;"
                table_html += f'<td style="{cell_style}">{v}</td>'
            table_html += "</tr>"
        table_html += "</tbody></table></div>"
        st.markdown(table_html, unsafe_allow_html=True)

        st.markdown("###### 備註：表列數字及符號說明")
        legend_cols = st.columns(3)
        for i, code in enumerate(["1", "2", "3", "4", "X", "*"]):
            legend_cols[i % 3].caption(f"**{code}**：{GENERAL_TABLE_TERMS[code]}")

    st.markdown("---")
    st.markdown("#### 📦 貨物清單")
    st.caption("最多可新增 10 筆貨物，系統將逐一比對所有組合")

    col_add, col_remove, _ = st.columns([1, 1, 2])
    with col_add:
        if st.button("➕ 新增貨物", use_container_width=True):
            if len(st.session_state.cargo_list) < 10:
                n = len(st.session_state.cargo_list) + 1
                st.session_state.cargo_list.append(
                    {"un": "", "position": "", "label": f"貨物 {n}"}
                )
                st.session_state.seg_check_result = None  # 貨物清單已變動，舊結果失效
            else:
                st.warning("最多 10 筆貨物")
    with col_remove:
        if st.button("➖ 移除最後一筆", use_container_width=True):
            if len(st.session_state.cargo_list) > 2:
                st.session_state.cargo_list.pop()
                st.session_state.seg_check_result = None  # 貨物清單已變動，舊結果失效

    st.markdown("")

    validated_cargos = []

    for i, cargo in enumerate(st.session_state.cargo_list):
        col_label, col_un, col_pos, col_status = st.columns([1, 2, 2, 3])

        with col_label:
            st.markdown(f"<br><b>{cargo['label']}</b>", unsafe_allow_html=True)

        with col_un:
            un_val = st.text_input(
                "UN 號碼",
                value=cargo["un"],
                placeholder="例：1203",
                key=f"seg_un_{i}",
                label_visibility="collapsed" if i > 0 else "visible"
            )
            st.session_state.cargo_list[i]["un"] = un_val

        with col_pos:
            pos_val = st.text_input(
                "位置 (BBRRTT)",
                value=cargo["position"],
                placeholder="例：030282",
                key=f"seg_pos_{i}",
                label_visibility="collapsed" if i > 0 else "visible",
                max_chars=6
            )
            st.session_state.cargo_list[i]["position"] = pos_val

        with col_status:
            # 2026-09 第三輪回饋（見 docs/KNOWN_LIMITATIONS.md §7.9.2）：使用者
            # 要求「輸入 UN Number 時同步顯示 Class，方便判讀」——原本只有
            # UN 號碼與位置都填完才會查詢並顯示 Class，改為只要 UN 號碼一
            # 填入就立即查詢並顯示（不需等位置欄位），位置欄位可稍後再填。
            dg_data = query_ems(un_val.strip()) if un_val else None

            if un_val and pos_val:
                pos_valid = _validate_position(pos_val.strip())

                if dg_data["found"] and pos_valid:
                    st.success(
                        f"✅ {dg_data['proper_shipping_name'][:25]}… "
                        f"| Class {dg_data['hazard_class']} "
                        f"| {_format_position(pos_val.strip())}"
                    )
                    validated_cargos.append({
                        "label":    cargo["label"],
                        "un":       un_val.strip(),
                        "position": pos_val.strip(),
                        "data":     dg_data,
                    })
                elif not dg_data["found"]:
                    st.error(f"❌ UN{un_val} 查無資料")
                elif not pos_valid:
                    st.warning("⚠️ 位置格式錯誤，請輸入6位數字")
            elif un_val:
                # 僅輸入 UN 號碼、尚未輸入位置：先行顯示 Class 供判讀，
                # 尚不加入 validated_cargos（仍須位置才能執行隔離檢查）。
                if dg_data["found"]:
                    st.info(
                        f"📦 Class {dg_data['hazard_class']}　"
                        f"{dg_data['proper_shipping_name'][:25]}…　"
                        f"（請繼續輸入位置以完成驗證）"
                    )
                else:
                    st.error(f"❌ UN{un_val} 查無資料")
            elif pos_val:
                st.caption("請同時填入 UN 號碼與位置")

    st.markdown("---")

    if len(validated_cargos) >= 2:
        st.markdown("#### 🗺️ 貨物位置示意")
        _render_position_map(validated_cargos)

    check_btn = st.button(
        "🔄 執行隔離檢查",
        type="primary",
        use_container_width=True,
        disabled=len(validated_cargos) < 2
    )

    if len(validated_cargos) < 2:
        st.caption("⚠️ 請至少填入 2 筆有效貨物資料才能執行檢查")

    # 修正（隔離結果查詢會出現錯誤）：原本整個結果區塊只在
    # 「if check_btn and ...」內渲染，check_btn 是 st.button 的一次性
    # 回傳值，只有點擊當下那一輪 rerun 為 True。使用者點擊按鈕看到結果
    # 後，只要再與結果區塊內的任何元件互動（展開某組配對），就會觸發新的
    # rerun，此時 check_btn 已變回 False，導致整個結果區塊（含剛剛互動的
    # 元件）瞬間消失，使用者體驗上等同「查詢出現錯誤」。改為將計算結果存入
    # st.session_state，僅在按下按鈕時重新計算，其餘互動皆從 session_state
    # 讀取既有結果並持續顯示。
    #
    # 2026-09 第二輪回饋（見 docs/KNOWN_LIMITATIONS.md §7.8.3）：使用者要求
    # 「積載隔離應該要讓 AI 判斷是否有隔離問題」，並在 AskUserQuestion 中明確
    # 選擇「改由 AI 直接判定合規／違規，作為主要結果」——這是對 C-1 的明確、
    # 經記錄例外。deterministic SegregationEngine（check_segregation_
    # deterministic()）仍照常計算、結果仍完整保留並顯示，只是不再是畫面上
    # 最主要呈現的結論；AI_ENABLED 時另呼叫 judge_segregation_with_ai()
    # 逐組取得 AI 直接判斷，作為主要顯示結果。AI 未啟用時，頁面自動退回原本
    # 純 deterministic 顯示，不影響離線可用性。
    if check_btn and len(validated_cargos) >= 2:
        pairs           = list(combinations(validated_cargos, 2))
        all_results     = []
        not_verified_count = 0
        violation_count     = 0
        general_caution_count = 0
        ai_violation_count  = 0
        ai_uncertain_count  = 0
        ai_ok_count         = 0

        spinner_ctx = st.spinner("🤖 AI 正在逐組判斷隔離狀況…") if AI_ENABLED else contextlib.nullcontext()
        with spinner_ctx:
            for cargo_a, cargo_b in pairs:
                dist_m = calc_distance_m(cargo_a["position"], cargo_b["position"])
                seg = check_segregation_deterministic(
                    un_a=cargo_a["un"], un_b=cargo_b["un"], distance_m=dist_m,
                )
                if seg["status"] == "VIOLATION":
                    violation_count += 1
                elif seg["status"] == "GENERAL_TABLE_CAUTION":
                    general_caution_count += 1
                elif seg["status"] in ("NOT_VERIFIED", "TEST_FIXTURE_NOT_FOR_OPERATION"):
                    not_verified_count += 1

                ai_judge = None
                if AI_ENABLED:
                    ai_judge = judge_segregation_with_ai(cargo_a, cargo_b, seg)
                    if ai_judge["verdict"] == "VIOLATION":
                        ai_violation_count += 1
                    elif ai_judge["verdict"] == "UNCERTAIN":
                        ai_uncertain_count += 1
                    else:
                        ai_ok_count += 1

                all_results.append({
                    "label_a":  cargo_a["label"],
                    "label_b":  cargo_b["label"],
                    "un_a":     cargo_a["un"],
                    "un_b":     cargo_b["un"],
                    "pos_a":    cargo_a["position"],
                    "pos_b":    cargo_b["position"],
                    "class_a":  cargo_a["data"].get("hazard_class", ""),
                    "class_b":  cargo_b["data"].get("hazard_class", ""),
                    "seg":      seg,
                    "ai_judge": ai_judge,
                })

        st.session_state.seg_check_result = {
            "validated_cargos":      validated_cargos,
            "all_results":           all_results,
            "pairs_count":           len(pairs),
            "violation_count":       violation_count,
            "not_verified_count":    not_verified_count,
            "general_caution_count": general_caution_count,
            "ai_violation_count":    ai_violation_count,
            "ai_uncertain_count":    ai_uncertain_count,
            "ai_ok_count":           ai_ok_count,
        }

    seg_result = st.session_state.get("seg_check_result")
    if seg_result:
        st.markdown("---")
        st.markdown("#### 📊 隔離檢查結果")

        all_results            = seg_result["all_results"]
        violation_count        = seg_result["violation_count"]
        not_verified_count     = seg_result["not_verified_count"]
        general_caution_count  = seg_result.get("general_caution_count", 0)
        pairs_count            = seg_result["pairs_count"]
        ai_violation_count     = seg_result.get("ai_violation_count", 0)
        ai_uncertain_count     = seg_result.get("ai_uncertain_count", 0)

        if AI_ENABLED:
            # 2026-09 使用者明確要求「AI 直接判定合規／違規，作為主要結果」
            # （見上方區塊註解、docs/KNOWN_LIMITATIONS.md §7.8.3）。此處摘要
            # 改以 AI 判斷計數為主要訊息，deterministic 摘要以次要區塊呈現。
            if ai_violation_count > 0:
                st.error(f"🚨 共檢查 {pairs_count} 組配對，AI 判定 **{ai_violation_count} 組可能違反隔離規定**，請立即人工覆核！")
            if ai_uncertain_count > 0:
                st.warning(f"❓ 共 {ai_uncertain_count} / {pairs_count} 組配對 AI 判定為「無法確定」，請人工查閱下方系統資料並依船上核准文件確認。")
            if ai_violation_count == 0 and ai_uncertain_count == 0:
                st.success(f"✅ 共檢查 {pairs_count} 組配對，AI 判定均未發現隔離問題。")
            st.caption(
                "⚠️ 以上為 AI 直接產生的判斷，可能有誤，"
                "最終決定權屬大副／船長覆核。"
            )
            with st.expander("⚫ deterministic 系統資料摘要（次要參考，非畫面主要結論）"):
                if violation_count > 0:
                    st.markdown(f"🚨 deterministic engine 判定 **{violation_count} 項違規**")
                if general_caution_count > 0:
                    st.markdown(f"🟡 依一般類別隔離表，{general_caution_count} 組現有距離可能不足")
                if not_verified_count > 0:
                    st.markdown(f"⚫ {not_verified_count} 組狀態為 NOT_VERIFIED（連一般表也無法辨識）")
                if violation_count == 0 and general_caution_count == 0 and not_verified_count == 0:
                    st.markdown("✅ deterministic 系統資料依一般類別隔離表現有距離未見明顯不足")
        else:
            # AI 未啟用：退回純 deterministic 顯示（與 AI 導入前行為一致，離線可用）。
            if violation_count > 0:
                st.error(f"🚨 共檢查 {pairs_count} 組配對，deterministic engine 判定 **{violation_count} 項違規**，請立即處理！")
            if general_caution_count > 0:
                st.warning(
                    f"🟡 共 {general_caution_count} / {pairs_count} 組配對依「一般類別隔離表」"
                    "（非公司核准正式資料，見下方各配對詳情）現有距離可能不足，建議儘速覆核。"
                )
            if not_verified_count > 0:
                st.warning(
                    f"⚫ 共 {not_verified_count} / {pairs_count} 組配對狀態為 **NOT_VERIFIED**"
                    "（連一般類別隔離表也無法辨識、或屬 Class 1 專屬隔離表範圍）。"
                    "請依船上最新版 IMDG Code Segregation Table 及大副／船長判斷。"
                )
            if violation_count == 0 and general_caution_count == 0 and not_verified_count == 0:
                st.success(f"✅ 共檢查 {pairs_count} 組配對，依一般類別隔離表現有距離**未見明顯不足**")
            st.caption("🔒 AI 功能未啟用，僅顯示 deterministic 系統資料；啟用 AI 後可取得 AI 直接判斷。")

        for res_i, res in enumerate(all_results):
            dist = _calc_distance(res["pos_a"], res["pos_b"])
            seg  = res["seg"]
            ai_judge = res.get("ai_judge")

            if ai_judge:
                title_icon = {"VIOLATION": "🚨", "OK": "✅", "UNCERTAIN": "❓"}.get(ai_judge["verdict"], "❓")
                title = (
                    f"{title_icon} {ai_judge['verdict_label']}　"
                    f"{res['label_a']} (UN{res['un_a']} @ {res['pos_a']})  ×  "
                    f"{res['label_b']} (UN{res['un_b']} @ {res['pos_b']})  "
                    f"｜距離約 {dist}"
                )
                expanded = ai_judge["verdict"] in ("VIOLATION", "UNCERTAIN")
            else:
                status_icon = _SEG_STATUS_ICON.get(seg["status"], "⚫")
                title = (
                    f"{status_icon} [{seg['status']}] "
                    f"{res['label_a']} (UN{res['un_a']} @ {res['pos_a']})  ×  "
                    f"{res['label_b']} (UN{res['un_b']} @ {res['pos_b']})  "
                    f"｜距離約 {dist}"
                )
                expanded = seg["status"] in ("VIOLATION", "GENERAL_TABLE_CAUTION")

            with st.expander(title, expanded=expanded):
                if ai_judge:
                    st.markdown(f"##### {ai_judge['verdict_label']}")
                    st.markdown(ai_judge["explanation"])
                    st.markdown("---")
                    st.markdown("**⚫ deterministic 系統資料（次要參考）**")
                st.markdown(f"**規則來源**：{seg['regulation_basis']}　|　**Engine 版本**：{seg['engine_version']}"
                            + (f"　|　**Rule ID**：{seg['rule_id']}" if seg['rule_id'] else ""))
                st.info(seg["message"])
                # 2026-09 第三輪回饋：使用者上傳「附表三 危險品隔離表」，要求
                # 能同步檢查確認——此處直接標示這一組配對在附表三（與既有
                # GENERAL_TABLE 數值一致）中對應的代碼，方便船員對照原文
                # 紙本／頁面上方「📋 附表三」展開表快速核對，純顯示 engine
                # 已計算好的既有欄位（general_table_code/term），不是新判斷。
                if seg.get("general_table_code"):
                    st.caption(
                        f"📋 附表三對照：Class {res.get('class_a', '')} × "
                        f"Class {res.get('class_b', '')} → "
                        f"代碼「{seg['general_table_code']}」（{seg['general_table_term']}）"
                    )
                if not ai_judge and AI_ENABLED:
                    # 理論上不會發生（AI_ENABLED 時一定會計算 ai_judge），保留作為
                    # fail-safe：若真的發生，仍提供舊版「AI 轉譯」功能不中斷使用。
                    if st.toggle("🤖 AI說明", key=f"seg_ai_toggle_{res_i}"):
                        st.markdown(explain_segregation_result(seg))

        st.markdown("---")
        st.download_button(
            label="📥 下載完整隔離檢查報告",
            data=_generate_segregation_report(seg_result["validated_cargos"], all_results, violation_count),
            file_name=f"segregation_report_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            mime="text/plain",
            use_container_width=True,
            key="seg_download_report",
        )


# ══════════════════════════════════════════════════════════════
# 頁面 4：DG Bay Plan
# ══════════════════════════════════════════════════════════════
elif page == "🗺️ DG Bay Plan":

    st.markdown('<div class="main-title">🗺️ DG Bay Plan</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-title">上傳 DG 艙單，自動產生滅火介質視覺化積載圖</div>',
        unsafe_allow_html=True
    )
    st.markdown(
        '<div class="warning-banner">'
        '⚠️ 本功能僅供船端緊急參考，實際操作請依官方 IMDG Code 及船長判斷'
        '</div>',
        unsafe_allow_html=True
    )

    # ── 色標說明 ────────────────────────────────────────────
    # Bay Plan 格子提供兩種上色依據可切換（下方「🗺️ Bay Plan 危險櫃裝載視覺化」
    # 區塊有切換選項）：依 EmS Fire Code（預設，回應使用者需求「根據 EMS
    # 處理方式進行顏色的區隔」）或依危險品 Class（來源：IMDG Code Chapter 5.3
    # 官方危險標誌底色）。先前依 fire_color 紅/黃/綠上色的邏輯已因
    # fire_classifier fail-closed 而失去意義，已全面改為上述兩種並在此明確
    # 標示「僅供辨識，非風險等級」（規格書 3.5）；下方另保留系統資料狀態圖例。
    with st.expander("🎨 色標說明", expanded=False):
        st.markdown("###### 🔥 依 EmS Fire Code 上色（預設；僅供視覺辨識，非滅火介質或風險等級）")
        st.caption(
            "依貨物的 EmS Fire Code（F-A ~ F-J，資料庫已核對來源的代碼本身）分組上色，"
            "方便一眼看出「哪些貨櫃屬於同一個 EmS 分組」，對照船上 EmS Guide 查閱對應章節；"
            "顏色本身不透露、也不代表任何具體滅火介質或危險程度。"
        )
        ems_legend  = get_ems_fire_color_legend()
        ems_cols    = st.columns(5)
        for i, item in enumerate(ems_legend):
            ems_cols[i % 5].markdown(
                f'<div style="background:{item["hex"]}; color:{item["text"]}; '
                f'padding:8px; border-radius:6px; text-align:center; '
                f'font-weight:700; margin-bottom:6px; font-size:0.85rem;">'
                f'{item["code"]}</div>',
                unsafe_allow_html=True
            )

        st.markdown("###### 🧯 依滅火介質通則上色（可用水 / CO2等特殊介質 / 高風險特別標示）")
        st.caption(
            f"來源：{EMS_EXTINGUISH_SOURCE}。僅反映 F-A~F-J 代碼本身的官方通則分組（可用水／"
            "需監控降溫／禁水須用乾粉等特殊介質／勿逕自撲滅氣體火焰），不含逐物質冷卻時間、"
            "PPE、確切用量等戰術細節，**不是本船／本公司核准之逐物質應變 SOP**；"
            "實際處置仍須查閱船上最新版 EmS Guide 該貨物對應章節，並依船長／大副現場判斷。"
        )
        ext_legend = get_ems_extinguish_legend()
        ext_cols   = st.columns(len(ext_legend))
        for i, item in enumerate(ext_legend):
            ext_cols[i].markdown(
                f'<div style="background:{item["hex"]}; color:{item["text"]}; '
                f'padding:8px; border-radius:6px; text-align:center; '
                f'font-weight:700; margin-bottom:6px; font-size:0.75rem;">'
                f'{item["label"]}</div>',
                unsafe_allow_html=True
            )
        st.caption(
            "⚠️ 紅色粗邊框＝該格主要貨物之 EmS 通則屬「高風險」分組（容易誤判滅火方式，"
            "例如誤用水、誤撲滅氣體火焰），僅代表通則本身的滅火陷阱，不代表該貨物整體"
            "危險程度高於其他類別，也不是 IMDG Code 官方風險分級。"
        )

        st.markdown("###### 📦 依危險品類別（Class）上色（僅供視覺辨識，非風險等級）")
        st.caption(
            "來源：IMDG Code Chapter 5.3 / UN Model Regulations §5.2.2.2 官方危險標誌底色。"
            "部分類別官方標誌實際為雙色或條紋圖案，此處簡化為單一辨識色；"
            "顏色僅幫助快速分辨「這是哪一類危險品」，與滅火介質、風險程度或是否安全無關。"
        )
        class_legend = get_class_color_legend()
        legend_cols  = st.columns(5)
        for i, item in enumerate(class_legend):
            legend_cols[i % 5].markdown(
                f'<div style="background:{item["hex"]}; color:{item["text"]}; '
                f'padding:8px; border-radius:6px; text-align:center; '
                f'font-weight:700; margin-bottom:6px; font-size:0.8rem;">'
                f'Class {item["class"]}'
                f'<br><span style="font-size:0.68rem; font-weight:400;">{item["note"]}</span>'
                f'</div>',
                unsafe_allow_html=True
            )
        st.caption("📝 待確認品名貨物另以橘色邊框標示，與上述任一色標無關。")

        st.markdown("###### ⚫ 系統資料狀態圖例（EmS 詳細指令）")
        legend = get_color_legend()
        cols   = st.columns(len(legend))
        for i, item in enumerate(legend):
            cols[i].markdown(
                f'<div style="background:{item["color_hex"]}; '
                f'color:white; padding:12px; border-radius:8px; '
                f'text-align:center; font-weight:700; min-height:100px;">'
                f'{item["label"]}<br>'
                f'<span style="font-size:0.75rem; font-weight:400;">'
                f'{item["media"]}</span><br>'
                f'<span style="font-size:0.7rem; opacity:0.85;">'
                f'EMS: {item["example"]}</span>'
                f'</div>',
                unsafe_allow_html=True
            )

    st.markdown("---")

    # ── 範本下載 + 檔案上傳 ─────────────────────────────────
    col_dl, col_up = st.columns([1, 2])

    with col_dl:
        st.markdown("#### 📥 下載範例模板")
        st.caption("不確定格式？先下載範例 Excel 填寫後上傳")
        st.download_button(
            label="⬇️ 下載 DG Manifest 範例",
            data=generate_sample_template(),
            file_name="dg_manifest_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="dl_sample_template"
        )

    with col_up:
        st.markdown("#### 📤 上傳 DG 艙單")
        st.caption("支援 Excel (.xlsx)、CSV (.csv) 或船舶積載計畫 (.ASC)")
        uploaded_file = st.file_uploader(
            "支援 Excel (.xlsx)、CSV (.csv) 或 ASC 積載計畫",
            type=["xlsx", "xls", "csv", "asc"],
            label_visibility="collapsed",
            key="dg_bay_plan_uploader"
        )

    # ── 解析艙單（有上傳才執行）────────────────────────────
    if uploaded_file:
        file_bytes = uploaded_file.read()
        file_ext   = uploaded_file.name.split(".")[-1].lower()

        # 修正：先前解析函式若丟出未預期例外（例如檔案為空、格式損毀），會直接
        # 顯示完整 Python Traceback 給使用者（已於 manifest_parser.py 修正主要
        # 成因）；此處加一層防護，任何解析器仍可能遺漏的例外都改以友善訊息呈現，
        # 不中斷整個頁面。
        try:
            with st.spinner("解析艙單中..."):
                if file_ext in ("xlsx", "xls"):
                    parsed_list, parse_warnings = parse_manifest_excel(file_bytes)
                elif file_ext == "csv":
                    parsed_list, parse_warnings = parse_manifest_csv(file_bytes)
                elif file_ext == "asc":
                    parsed_list, parse_warnings = parse_asc_file(file_bytes)
                else:
                    parsed_list, parse_warnings = [], [f"❌ 不支援的檔案格式：.{file_ext}"]
        except Exception as e:
            st.error(
                f"❌ 解析艙單時發生未預期錯誤（{type(e).__name__}）。"
                "請確認檔案未損毀，或改用「下載範例模板」的格式重新製作後再試一次。"
            )
            st.stop()

        success_msgs = [w for w in parse_warnings if w.startswith("✅")]
        error_msgs   = [w for w in parse_warnings if w.startswith("❌")]
        warn_msgs    = [w for w in parse_warnings if w.startswith("⚠️")]

        for w in success_msgs:
            st.success(w)
        for w in error_msgs:
            st.error(w)

        if warn_msgs:
            if len(warn_msgs) <= 5:
                for w in warn_msgs:
                    st.warning(w)
            else:
                st.warning(f"⚠️ 共有 {len(warn_msgs)} 條警告訊息")
                with st.expander(f"展開查看所有警告（{len(warn_msgs)} 條）"):
                    for w in warn_msgs:
                        st.warning(w)

        if not parsed_list:
            st.error("❌ 未能解析任何有效貨物資料，請確認檔案格式")
            st.stop()

        if parsed_list[0].get("source") == "ASC":
            ship = parsed_list[0].get("ship_name", "")
            voy  = parsed_list[0].get("voyage",    "")
            if ship or voy:
                st.info(f"🚢 **{ship}** | 航次：{voy}")

        st.session_state["dg_cargo_list"] = parsed_list
        st.session_state["dg_bay_plan"]   = build_bay_plan(parsed_list)

    # ── 從 Session State 取值 ────────────────────────────────
    cargo_list = st.session_state.get("dg_cargo_list", [])
    bay_plan   = st.session_state.get("dg_bay_plan",   {})

    if not cargo_list:
        st.info("📤 請上傳 DG 艙單以開始分析")
        st.stop()

    # ════════════════════════════════════════════════════════
    # 區塊 A：統計摘要
    # ════════════════════════════════════════════════════════
    summary = get_manifest_summary(cargo_list)

    st.markdown("---")
    st.markdown("#### 📊 艙單摘要")

    if cargo_list[0].get("source") == "ASC":
        ship = cargo_list[0].get("ship_name", "")
        voy  = cargo_list[0].get("voyage",    "")
        if ship or voy:
            st.caption(f"🚢 {ship}　|　航次：{voy}")

    m1, m2, m3 = st.columns(3)
    m1.metric("🚢 全船裝載 DG 總數",       summary["total"])
    m2.metric("🔥 已取得 EmS Fire Code",   summary["ems_known"])
    m3.metric("📝 待確認品名", summary["ambiguous"])
    if summary["ambiguous"] > 0:
        st.caption(
            f"📝 {summary['ambiguous']} 筆貨物因 UN 號碼對應多種正式品名，"
            "請依貨物文件於「EMS 快速查詢」頁面確認後選列。"
        )

    if summary["no_position"] > 0:
        st.warning(
            f"⚠️ 有 {summary['no_position']} 筆貨物缺少位置資料，"
            f"將不會顯示在 Bay Plan 圖上"
        )

    # ── 類別分布（取代先前無意義的 fire_color 紅/黃/綠統計）─────
    # 大副／船副實際想快速掌握的是「這艘船裝了哪些 Class、各幾櫃、
    # 甲板／艙內各幾櫃」，而非早已 fail-closed 停用的滅火色碼分布
    # （見 bay_plan_engine.get_plan_statistics 註解）。
    plan_stats = get_plan_statistics(bay_plan)
    if plan_stats["by_class"]:
        st.caption(
            f"📦 甲板 On-Deck {plan_stats['on_deck']} 櫃　|　"
            f"🕳️ 艙內 In-Hold {plan_stats['in_hold']} 櫃　|　"
            f"🧯 高風險滅火通則分組 {plan_stats.get('high_risk_extinguish', 0)} 櫃"
            "（見「🧯 滅火介質通則」色標說明）　|　"
            "類別分布（依數量排序）："
        )
        chip_html = "".join(
            f'<span style="display:inline-block; background:{get_class_color(cls)["hex"]}; '
            f'color:{get_class_color(cls)["text"]}; padding:3px 10px; border-radius:12px; '
            f'font-size:0.78rem; font-weight:700; margin:2px 4px 2px 0;">'
            f'Class {cls} × {count}</span>'
            for cls, count in plan_stats["by_class"].items()
        )
        st.markdown(chip_html, unsafe_allow_html=True)

    if plan_stats.get("by_fire_code"):
        st.caption("🔥 EmS Fire Code 分布（依數量排序，僅代碼分組視覺辨識，不代表滅火介質或風險等級）：")
        fire_chip_html = "".join(
            f'<span style="display:inline-block; background:{get_ems_fire_color(code)["hex"]}; '
            f'color:{get_ems_fire_color(code)["text"]}; padding:3px 10px; border-radius:12px; '
            f'font-size:0.78rem; font-weight:700; margin:2px 4px 2px 0;">'
            f'{code} × {count}</span>'
            for code, count in plan_stats["by_fire_code"].items()
        )
        st.markdown(fire_chip_html, unsafe_allow_html=True)

        # 2026-09 第四輪回饋：使用者要求「補上 F-A F-E F-D 這些的意思，幫助
        # 在看船上危險櫃時能夠直覺的知道重要資訊」——在代碼分布下方直接列出
        # 本航次實際出現的每個代碼對應的 IMO EmS Guide 通則意義（引用既有
        # bay_plan_engine.get_ems_extinguish_guidance() 的 note_cn，來源見
        # EMS_EXTINGUISH_SOURCE，純顯示既有資料，非新增判斷）。
        _MEDIUM_ICON = {
            "water": "🌊", "water_caution": "🌊⚠️",
            "no_water": "🚫💧", "flame_caution": "🔥⚠️", "unknown": "⚫",
        }
        meaning_html = "".join(
            f'<div style="padding:4px 0; font-size:0.82rem; color:var(--whl-ink);">'
            f'<span style="display:inline-block; background:{get_ems_fire_color(code)["hex"]}; '
            f'color:{get_ems_fire_color(code)["text"]}; padding:1px 8px; border-radius:8px; '
            f'font-weight:700; margin-right:6px;">{code}</span>'
            f'{_MEDIUM_ICON.get(get_ems_extinguish_guidance(code)["medium_hint"], "⚫")}　'
            f'{get_ems_extinguish_guidance(code)["note_cn"]}</div>'
            for code in plan_stats["by_fire_code"].keys()
        )
        st.markdown(meaning_html, unsafe_allow_html=True)
        st.caption(f"來源：{EMS_EXTINGUISH_SOURCE}")

    # ════════════════════════════════════════════════════════
    # 區塊 A2：危險櫃清單（新增）
    # ════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("#### 📋 本航次危險品貨櫃清單")
    st.caption("依位置排序")

    # 規格書 3.5：顏色不得暗示滅火介質或風險等級，僅標示資料狀態。
    # 依「是否待選列正式品名」排序（待選列優先顯示，須優先處理），同狀態再依位置排序。
    sorted_cargo = sorted(
        cargo_list,
        key=lambda c: (0 if c.get("requires_variant_selection") else 1, c["position"])
    )

    dg_table_df = pd.DataFrame([{
        "狀態":      "📝 待確認品名" if c.get("requires_variant_selection") else "✅ 品名已確定",
        "貨櫃號碼":  c["container_no"],
        "位置":      c["position"],
        "UN No":     f"UN{c['un_number']}",
        "Class":     c["hazard_class"],
        "PG":        c["packing_group"] or ("待確認" if c.get("requires_variant_selection") else ""),
        "品名":      c["description"][:35] if c["description"] else "—",
        "Fire EMS":  c["fire_ems"]  if c["fire_ems"]  else "—",
        "Spill EMS": c["spill_ems"] if c["spill_ems"] else "—",
    } for c in sorted_cargo])

    def _highlight_dg_table(row):
        if "待確認品名" in row["狀態"]:
            return ["background-color:#fef3c7; color:#92400e"] * len(row)
        return ["background-color:#f3f4f6; color:#374151"] * len(row)

    if not dg_table_df.empty:
        st.dataframe(
            dg_table_df.style.apply(_highlight_dg_table, axis=1),
            use_container_width=True,
            height=min(400, 45 + len(dg_table_df) * 38),  # 動態高度，最高 400px
        )
    else:
        st.info("無貨物資料")

    # ════════════════════════════════════════════════════════
    # 區塊 B：Bay Plan 視覺化（甲板圖 + 艙內清單）
    # ════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("#### 🗺️ Bay Plan 危險櫃裝載視覺化")
    st.caption(
        "甲板（Deck）與艙內（In-Hold）皆以格狀圖呈現，並排顯示以貼近實際盤點時"
        "「先看甲板、再查艙內」的使用習慣；橘色粗邊框代表該格含待確認品名貨物，"
        "紅色粗邊框代表該格主要貨物屬「高風險」EmS 滅火通則分組（見下方色標說明）。"
    )
    # 2026-09 第二輪回饋：使用者要求 Bay Plan 頁面「先不要考量
    # VesselProfile，只要根據 EMS 資料顯示」，並在 AskUserQuestion 中選擇
    # 「只移除 VesselProfile 相關文字，滅火介質分類維持現狀」——故本頁不再
    # 顯示 NOT_VERIFIED_DECK_MESSAGE 警示框；甲板／艙內分類邏輯本身
    # （vessel_profile.classify_tier()）未變更，僅移除畫面上的說明文字，
    # 降低頁面複雜度（見 docs/KNOWN_LIMITATIONS.md §7.8.4）。

    if not bay_plan:
        st.info("所有貨物均缺少位置資料，無法繪製 Bay Plan")
    else:
        sel_col1, sel_col2 = st.columns([1, 1])
        with sel_col1:
            bay_options = sorted(bay_plan.keys())
            chosen_bay = st.selectbox(
                "選擇 Bay",
                options=["全部"] + [f"Bay {b:02d}" for b in bay_options],
                key="bayplan_selector"
            )
        with sel_col2:
            # 2026-09 新增：格子上色依據可切換，預設「EMS 處理方式」（回應
            # 使用者需求：「Bay plan 請幫我根據 EMS 處理方式進行顏色的區隔」）。
            color_mode_label = st.selectbox(
                "貨櫃格顏色依據",
                options=[
                    "🧯 滅火介質通則（可用水／高風險標示）",
                    "🔥 EMS 處理方式（Fire Code）",
                    "📦 危險品類別（Class）",
                ],
                key="bayplan_color_mode",
            )
            if color_mode_label.startswith("🧯"):
                bay_color_mode = "extinguish"
            elif color_mode_label.startswith("🔥"):
                bay_color_mode = "ems"
            else:
                bay_color_mode = "class"
        if bay_color_mode == "extinguish":
            st.caption(
                f"目前顏色依滅火介質通則分組（來源：{EMS_EXTINGUISH_SOURCE}）；"
                "紅色粗邊框＝高風險 EmS 通則分組。僅供快速辨識，非逐物質 SOP，"
                "實際處置仍須查閱船上最新版 EmS Guide 及船長判斷。"
            )
        elif bay_color_mode == "ems":
            st.caption(
                "目前顏色依 EmS Fire Code 分組（僅供視覺辨識、對照 EmS Guide 分組使用，"
                "非滅火介質或風險等級）"
            )
        else:
            st.caption(
                "目前顏色依危險品 Class 分組（來源：IMDG Code Chapter 5.3 官方標誌底色，"
                "僅供視覺辨識，非風險等級）"
            )

        _render_compact_color_legend(bay_color_mode)

        bays_to_show = (
            {int(chosen_bay.replace("Bay ", "")): bay_plan[int(chosen_bay.replace("Bay ", ""))]}
            if chosen_bay != "全部"
            else bay_plan
        )

        rendered_deck = False
        rendered_hold = False

        for bay_num, bay_data in sorted(bays_to_show.items()):
            dims = get_bay_dimensions(bay_data)

            rows       = dims.get("rows", [])
            tiers_deck = dims.get("tiers_deck", [])
            tiers_hold = dims.get("tiers_hold", [])

            if not rows:
                continue   # 此 Bay 甲板／艙內皆無 DG，跳過

            if tiers_deck:
                rendered_deck = True
                st.markdown(f"##### 🚢 Bay {bay_num:02d} — 甲板 Deck")
                fig_deck = _build_bay_grid_figure(
                    rows, tiers_deck, bay_data["on_deck"],
                    f"Bay {bay_num:02d} — Deck", plot_bg="#0f172a",
                    color_mode=bay_color_mode,
                )
                st.plotly_chart(fig_deck, use_container_width=True)

            if tiers_hold:
                rendered_hold = True
                st.markdown(f"##### 🕳️ Bay {bay_num:02d} — 艙內 In-Hold")
                fig_hold = _build_bay_grid_figure(
                    rows, tiers_hold, bay_data["in_hold"],
                    f"Bay {bay_num:02d} — Hold", plot_bg="#111827",
                    color_mode=bay_color_mode,
                )
                st.plotly_chart(fig_hold, use_container_width=True)

        if not rendered_deck and not rendered_hold:
            st.info("選擇的 Bay 範圍內無 DG 貨物")
        else:
            if not rendered_deck:
                st.caption("選擇的 Bay 範圍內無甲板 DG 貨物")
            if not rendered_hold:
                st.caption("選擇的 Bay 範圍內無艙內 DG 貨物")

        # ── 艙內（In-Hold）明細清單：格狀圖之外另保留完整清單，確保不因格狀圖
        #    的顯示上限（例如多貨物共用同一格僅顯示 +N more）而遺漏任何一筆
        #    （見 docs/INITIAL_SAFETY_AUDIT.md C-5：先前版本艙內貨物完全不顯示）。
        with st.expander("📋 艙內（In-Hold）DG 貨物明細清單", expanded=False):
            in_hold_rows = []
            for bay_num, bay_data in sorted(bays_to_show.items()):
                for (row, tier), cargos in bay_data.get("in_hold", {}).items():
                    for c in cargos:
                        in_hold_rows.append({
                            "Bay":       f"{bay_num:02d}",
                            "Row":       f"{row:02d}",
                            "Tier":      f"{tier:02d}",
                            "狀態":      "📝 待確認品名" if c.get("requires_variant_selection") else "✅ 品名已確定",
                            "貨櫃號碼":  c.get("container_no", ""),
                            "UN No":     f"UN{c.get('un_number','')}",
                            "Class":     c.get("hazard_class", ""),
                            "品名":      (c.get("description") or "")[:35],
                        })

            if in_hold_rows:
                st.dataframe(pd.DataFrame(in_hold_rows), use_container_width=True)
            else:
                st.caption("選擇的 Bay 範圍內無艙內 DG 貨物（或所有貨物皆缺少可辨識的艙內位置）")

    # ════════════════════════════════════════════════════════
    # 區塊 C：三秒判斷卡（Action Card）
    # ════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("#### ⚡ 三秒判斷卡")
    st.caption("選擇貨物，即時查看緊急處置摘要")

    cargo_options = {
        f"{c['container_no']} | UN{c['un_number']} | {c['description'][:25]}": c
        for c in cargo_list
    }
    selected_label = st.selectbox(
        "選擇貨物",
        options=list(cargo_options.keys()),
        label_visibility="collapsed",
        key="action_card_select"
    )

    if selected_label:
        cargo = cargo_options[selected_label]

        # 2026-09 第五輪回饋：使用者提供的 Bay Plan 參考圖附一張深色「三秒
        # 判斷卡：應做／禁止／後續風險」摘要卡片，據此重新設計本區塊（見
        # docs/KNOWN_LIMITATIONS.md §7.11.3）。內容完全來自既有已核對來源的
        # bay_plan_engine.get_action_card_guidance()（EMS_EXTINGUISH_SOURCE：
        # IMO EmS Guide 總則 F-A~F-J 官方通則），僅依 medium_hint（5 種分組）
        # 拆成三行顯示，不新增任何逐物質戰術判斷，避免重蹈 fire_classifier.py
        # 被 fail-closed 停用的錯誤（docs/INITIAL_SAFETY_AUDIT.md C-3）。
        action = get_action_card_guidance(cargo.get("fire_ems", ""))
        risk_badge = (
            '<span style="background:#DC2626; color:#fff; padding:2px 10px; '
            'border-radius:10px; font-size:0.72rem; font-weight:700; margin-left:8px;">'
            '⚠️ 高風險 EmS 通則</span>'
        ) if action["high_risk"] else ""

        # 注意：st.markdown 對多行、帶縮排的 HTML 字串可能被 CommonMark 誤判為
        # 程式碼區塊（4 個空白起始視為 code block）而不會實際渲染，因此此處改用
        # 單行字串（無跨行縮排）組合 HTML，與檔案內其餘 HTML 區塊（如
        # meaning_html／chip_html）的既有寫法一致。
        action_card_html = (
            '<div style="background:#0f172a; border-radius:12px; padding:18px 20px; '
            'border:1px solid #1e293b; margin-bottom:10px;">'
            '<div style="color:#f1f5f9; font-weight:700; font-size:1.02rem; margin-bottom:10px;">'
            f"UN{cargo['un_number']} ｜ Class {cargo['hazard_class']} ｜ "
            f"Fire EMS {cargo['fire_ems'] or '—'} / Spill EMS {cargo['spill_ems'] or '—'}"
            f"{risk_badge}</div>"
            '<div style="display:grid; grid-template-columns:1fr; gap:8px;">'
            '<div style="background:#14532d; border-radius:8px; padding:10px 14px;">'
            '<span style="color:#86efac; font-weight:700; font-size:0.85rem;">✅ 應做</span>'
            f'<div style="color:#f0fdf4; font-size:0.9rem; margin-top:2px;">{action["do"]}</div></div>'
            '<div style="background:#450a0a; border-radius:8px; padding:10px 14px;">'
            '<span style="color:#fca5a5; font-weight:700; font-size:0.85rem;">🚫 禁止</span>'
            f'<div style="color:#fef2f2; font-size:0.9rem; margin-top:2px;">{action["avoid"]}</div></div>'
            '<div style="background:#451a03; border-radius:8px; padding:10px 14px;">'
            '<span style="color:#fdba74; font-weight:700; font-size:0.85rem;">⚠️ 後續風險</span>'
            f'<div style="color:#fff7ed; font-size:0.9rem; margin-top:2px;">{action["risk"]}</div></div>'
            '</div></div>'
        )
        st.markdown(action_card_html, unsafe_allow_html=True)
        st.caption(
            f"來源：{EMS_EXTINGUISH_SOURCE}。僅為 F-A~F-J 代碼通則分組，"
            "非本船／本公司核准之逐物質應變 SOP，實際處置仍須查閱船上最新版 "
            "EmS Guide 該貨物對應章節，並依船長／大副現場判斷。"
        )
        st.info(cargo['fire_risk'])
        if cargo.get("requires_variant_selection"):
            st.info("📝 此貨物正式品名待確認，請於「EMS 快速查詢」頁面完成選列以取得 Packing Group／積載類別。")

        with st.expander("📄 查看完整 IMDG 應急程序"):
            ems_data = query_ems(cargo["un_number"])
            if ems_data["found"]:
                tab_f, tab_s, tab_fa = st.tabs(["🔥 火災", "💧 洩漏", "🏥 急救"])
                with tab_f:
                    st.info(ems_data["emergency_action"].get("fire",      "無資料"))
                with tab_s:
                    st.info(ems_data["emergency_action"].get("spillage",  "無資料"))
                with tab_fa:
                    st.info(ems_data["emergency_action"].get("first_aid", "無資料"))
                # 2026-09 第六輪（見 §7.12）：emergency_action 內容來源標示。
                ea_src = ems_data.get("emergency_action_source") or {}
                if ea_src.get("reference"):
                    st.caption(
                        f"來源：{ea_src['reference']}，Guide {ea_src.get('guide_number','')}"
                        f"（{ea_src.get('guide_title_en','')}）。{ea_src.get('note_cn','')}"
                    )
            else:
                st.warning(f"UN{cargo['un_number']} 查無 IMDG 資料")

        # 規格書 F-004「鄰近危險品」：先前系統內完全沒有此功能。真實應變時，
        # 除了這一櫃本身的資料外，指揮官同樣關心「附近還有哪些 DG、彼此隔離
        # 狀態如何」，此處以 deterministic（非 AI）方式呈現，供快速掌握現場。
        with st.expander("📍 鄰近 DG 貨物與隔離狀態（Deterministic，非 AI）", expanded=False):
            _render_nearby_dg_panel(cargo, cargo_list, radius_m=15.0, key_prefix="actioncard")

    # ════════════════════════════════════════════════════════
    # 區塊 D：篩選器 + 貨物清單
    # ════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("#### 🔍 篩選貨物清單")

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        all_bays_str = sorted(set(
            c["position"][0:2]
            for c in cargo_list if len(c["position"]) == 6
        ))
        filter_bay = st.multiselect(
            "依 Bay 篩選",
            options=[f"Bay {b}" for b in all_bays_str],
            default=[],
            key="filter_bay"
        )
    with col_f2:
        filter_class = st.multiselect(
            "依危險品類別篩選",
            options=sorted(set(
                c["hazard_class"] for c in cargo_list if c["hazard_class"]
            )),
            default=[],
            key="filter_class"
        )
    filter_ambiguous_only = st.checkbox("僅顯示待確認品名貨物", key="filter_ambiguous_only")

    filtered = cargo_list
    if filter_bay:
        allowed_bays = {b.replace("Bay ", "") for b in filter_bay}
        filtered = [c for c in filtered if c["position"][0:2] in allowed_bays]
    if filter_class:
        filtered = [c for c in filtered if c["hazard_class"] in filter_class]
    if filter_ambiguous_only:
        filtered = [c for c in filtered if c.get("requires_variant_selection")]

    st.caption(f"顯示 {len(filtered)} / {len(cargo_list)} 筆貨物")

    preview_df = pd.DataFrame([{
        "貨櫃號碼":  c["container_no"],
        "UN":        c["un_number"],
        "品名":      c["description"][:30],
        "Class":     c["hazard_class"],
        "PG":        c["packing_group"] or ("待確認" if c.get("requires_variant_selection") else ""),
        "位置":      c["position"],
        "Fire EMS":  c["fire_ems"],
        "Spill EMS": c["spill_ems"],
        "狀態":      "📝 待確認品名" if c.get("requires_variant_selection") else "✅ 品名已確定",
    } for c in filtered])

    def _highlight_row(row):
        if "待確認品名" in row["狀態"]:
            return ["background-color: #fef3c7; color: #92400e"] * len(row)
        return ["background-color: #f3f4f6; color: #374151"] * len(row)

    if not preview_df.empty:
        st.dataframe(
            preview_df.style.apply(_highlight_row, axis=1),
            use_container_width=True,
            height=400
        )
    else:
        st.info("目前篩選條件下無貨物資料")

    # ════════════════════════════════════════════════════════
    # 區塊 E：艙單風險提示（非 AI，deterministic）＋ 選用 AI 文字說明
    # ════════════════════════════════════════════════════════
    #
    # 規格書 3.5 / docs/INITIAL_SAFETY_AUDIT.md C-3：先前這裡會依 fire_color
    # （紅/黃/綠）把貨物分組，再要求 AI「產生船長級別的應急風險摘要」，其中包含
    # 大量未經核准的具體內容（例如：「EMS F-A → 水霧為主」「啟用 Bay XX 附近左舷
    # 消防水帶站，部署 1 線水帶」「巡檢頻率：高危每 4 小時」等）。這些內容並非
    # 官方 EmS Guide / SMS 條文，已全面移除。
    #
    # 本區塊現在只做兩件事：
    #   1. 以 deterministic 方式（純 Python，非 AI）列出「待選列」與「Bay 內含
    #      多種危險品類別」等中性事實，不做風險分級、不建議滅火介質或戰術。
    #   2. 若公司已啟用 AI（DG_AI_ENABLED），可選擇性請 AI 把上述事實轉譯為更
    #      易讀的文字，但 system prompt 已明確禁止 AI 產生風險等級、滅火介質、
    #      PPE、隔離／撤離距離等具體建議（見 ai_analyzer.SYSTEM_PROMPT）。
    st.markdown("---")
    st.markdown("#### 📋 艙單風險提示（Deterministic）")

    ambiguous_cargos = [c for c in cargo_list if c.get("requires_variant_selection")]

    bay_class_groups: dict[str, set] = {}
    for c in cargo_list:
        pos = c.get("position", "")
        if len(pos) == 6 and pos.isdigit():
            bay_key = f"Bay {pos[0:2]}"
            bay_class_groups.setdefault(bay_key, set()).add(c.get("hazard_class", ""))
    multi_class_bays = {b: classes for b, classes in bay_class_groups.items() if len(classes) > 1}

    if ambiguous_cargos:
        st.info(
            f"📝 {len(ambiguous_cargos)} 筆貨物正式品名待確認，"
            "請於「EMS 快速查詢」頁面完成選列以取得 Packing Group／Stowage："
            + "、".join(f"UN{c['un_number']}({c['container_no']})" for c in ambiguous_cargos[:10])
            + ("…" if len(ambiguous_cargos) > 10 else "")
        )
    else:
        st.success("✅ 本航次貨物皆不需要（或已完成）正式品名選列")

    if multi_class_bays:
        st.info(
            "以下 Bay 內含多種危險品類別，隔離相容性請依船上最新版 IMDG Code "
            "Segregation Table 或本系統「積載隔離檢查」頁面（deterministic）確認：\n"
            + "\n".join(f"  • {b}：Class {', '.join(sorted(c for c in classes if c))}"
                          for b, classes in sorted(multi_class_bays.items()))
        )

    st.caption(
        "⚫ 本頁不提供滅火介質、PPE、隔離／撤離距離等具體建議——這些內容待公司核准的 "
        "2024 EmS Supplement 與 Amendment 42-24 Segregation Table 匯入後才會顯示，"
        "且一律附文件來源與版本。"
    )

    if AI_ENABLED:
        if st.button("🤖 AI說明", use_container_width=True, key="ai_risk_summary"):
            summary_lines = [
                f"貨物總數：{len(cargo_list)}",
                f"待確認品名：{len(ambiguous_cargos)} 筆",
                f"含多種危險品類別的 Bay：{len(multi_class_bays)} 個",
            ]
            prompt = (
                "以下是本航次艙單的中性事實（非風險分級、非滅火建議），"
                "請用清晰的繁體中文條列整理成船副易讀的摘要，"
                "不得新增任何滅火介質、PPE、隔離距離或風險等級判斷：\n\n"
                + "\n".join(summary_lines)
            )
            with st.spinner("AI 正在整理摘要..."):
                result = get_llm_response(
                    system_prompt = SYSTEM_PROMPT,
                    user_message  = prompt,
                    max_tokens    = 600,
                    temperature   = 0.0,
                )
            st.markdown('<div class="ai-response-wrapper">', unsafe_allow_html=True)
            st.markdown(result)
            st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.caption("🔒 AI 功能目前未啟用（系統預設關閉），以上事實提示已足夠用於初步檢視。")


    # ════════════════════════════════════════════════════════
    # ════════════════════════════════════════════════════════
    # 區塊 F：匯出報告
    # ════════════════════════════════════════════════════════
    #
    # 規格書 3.5：匯出內容不再依 fire_color（紅/黃/綠）分組或上色——該分類先前
    # 暗示「滅火介質/風險等級」，現已 fail-closed 移除；改以「是否待選列
    # （AMBIGUOUS）」分組，並在報告中明確加註本系統的限制與資料版本。
    st.markdown("---")
    st.markdown("#### 📥 匯出報告")

    col_exp1, col_exp2 = st.columns(2)

    with col_exp1:
        if st.button("📊 產生 Excel 報告", use_container_width=True, key="gen_excel"):
            try:
                from openpyxl import Workbook
                from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

                wb = Workbook()
                ws = wb.active
                ws.title = "DG Bay Plan Report"

                headers = [
                    "貨櫃號碼", "UN", "品名", "Class", "PG",
                    "位置", "Fire EMS", "Spill EMS", "狀態"
                ]
                header_fill = PatternFill("solid", fgColor="1e293b")
                thin_border = Border(
                    left=Side(style="thin"),  right=Side(style="thin"),
                    top=Side(style="thin"),   bottom=Side(style="thin"),
                )

                for col_idx, header in enumerate(headers, 1):
                    cell           = ws.cell(row=1, column=col_idx, value=header)
                    cell.font      = Font(bold=True, color="FFFFFF")
                    cell.fill      = header_fill
                    cell.alignment = Alignment(horizontal="center")
                    cell.border    = thin_border

                ambiguous_fill = PatternFill("solid", fgColor="fef3c7")
                default_fill   = PatternFill("solid", fgColor="f3f4f6")

                sorted_cargos = sorted(
                    cargo_list,
                    key=lambda x: (0 if x.get("requires_variant_selection") else 1, x["position"])
                )

                for row_idx, c in enumerate(sorted_cargos, 2):
                    is_ambiguous = bool(c.get("requires_variant_selection"))
                    values = [
                        c["container_no"], c["un_number"], c["description"],
                        c["hazard_class"],
                        c["packing_group"] or ("待確認" if is_ambiguous else ""),
                        c["position"], c["fire_ems"], c["spill_ems"],
                        "待確認品名" if is_ambiguous else "品名已確定",
                    ]
                    fill = ambiguous_fill if is_ambiguous else default_fill
                    for col_idx, val in enumerate(values, 1):
                        cell           = ws.cell(row=row_idx, column=col_idx, value=val)
                        cell.fill      = fill
                        cell.border    = thin_border
                        cell.alignment = Alignment(horizontal="left")

                for col in ws.columns:
                    max_len = max(len(str(cell.value or "")) for cell in col)
                    ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 45)

                ws.freeze_panes = "A2"

                buf = io.BytesIO()
                wb.save(buf)

                st.download_button(
                    label="⬇️ 下載 Excel 報告",
                    data=buf.getvalue(),
                    file_name=f"dg_bayplan_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="dl_excel_report"
                )
            except ImportError:
                st.error("請安裝 openpyxl：pip install openpyxl")

    with col_exp2:
        # 船名航次資訊（用於報告標頭）
        _ship = cargo_list[0].get("ship_name", "") if cargo_list else ""
        _voy  = cargo_list[0].get("voyage",    "") if cargo_list else ""
        _ship_line = f"  船名：{_ship}　航次：{_voy}" if _ship or _voy else ""

        lines = [
            "=" * 65,
            "  DG CARGO GUARDIAN — Bay Plan 報告",
            f"  產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        if _ship_line:
            lines.append(_ship_line)
        lines += [
            "=" * 65, "",
            f"  總貨物數                  ：{summary['total']}",
            f"  已取得 EmS Fire Code       ：{summary['ems_known']}",
            f"  待確認品名        ：{summary['ambiguous']}",
            "", "-" * 65,
            "  【依「是否待確認品名」+ 位置排序】",
            "-" * 65,
        ]
        for is_ambiguous, group_label in [(True, "📝 待確認品名"), (False, "✅ 品名已確定")]:
            group = sorted(
                [c for c in cargo_list if bool(c.get("requires_variant_selection")) == is_ambiguous],
                key=lambda c: c["position"]
            )
            if not group:
                continue
            lines.append(f"\n  {group_label}（{len(group)} 個）")
            lines.append("  " + "-" * 60)
            for c in group:
                lines.append(
                    f"  {c['container_no']} | UN{c['un_number']:4s} | "
                    f"{c['description'][:28]:28s} | "
                    f"EMS {c['fire_ems']:4s} | 位置 {c['position']}"
                )
        lines += [
            "", "=" * 65,
            "  ⚠️  本報告為系統輔助紀錄，不取代 IMDG Code、EmS Guide、公司 SMS 及船長判斷。",
            "      滅火介質／PPE／隔離等詳細指令待公司核准資料匯入後才會顯示。",
            "=" * 65,
        ]

        st.download_button(
            label="📄 下載文字報告",
            data="\n".join(lines),
            file_name=f"dg_bayplan_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            mime="text/plain",
            use_container_width=True,
            key="dl_text_report"
        )


# ══════════════════════════════════════════════════════════════
# 頁面 5：自由問答
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

    # 清除旗標需在 text_area 實例化「之前」處理，避免
    # StreamlitAPIException：元件建立後不可再修改其綁定的 session_state。
    if st.session_state.get("_clear_free_qa_draft"):
        st.session_state.free_qa_draft = ""
        st.session_state._clear_free_qa_draft = False

    cols = st.columns(2)
    for i, (btn_label, question_text) in enumerate(quick_questions.items()):
        with cols[i % 2]:
            if st.button(btn_label, use_container_width=True, key=f"quick_q_{i}"):
                # 直接帶入下方問題欄位（st.chat_input 不支援程式化預填，
                # 故改用可綁定 session_state 的 st.text_area + 送出按鈕）。
                st.session_state.free_qa_draft = question_text

    # 輸入框（改用 text_area + 送出按鈕，讓快捷問題可直接帶入欄位）
    input_col, send_col = st.columns([5, 1])
    with input_col:
        draft = st.text_area(
            "輸入你的問題",
            placeholder="輸入你的問題，例如：Class 3 危險品的主要火災風險是什麼？",
            key="free_qa_draft",
            height=80,
            label_visibility="collapsed",
        )
    with send_col:
        send_clicked = st.button("📤 送出", use_container_width=True, key="free_qa_send")

    if send_clicked and draft and draft.strip():
        user_input = draft.strip()
        st.session_state.chat_history.append({
            "role": "user",
            "content": user_input
        })

        with st.spinner("思考中..."):
            response = ask_dg_question(
                question  = user_input,
                un_number = ref_un.strip() if ref_un else None
            )

        st.session_state.chat_history.append({
            "role":    "assistant",
            "content": response
        })

        # 送出後清空輸入框：延遲至下次腳本執行開頭才清除（見上方旗標處理），
        # 避免在本次 text_area 已實例化後直接修改其 session_state 而觸發例外。
        st.session_state._clear_free_qa_draft = True
        st.rerun()

    # 清除對話
    if st.session_state.chat_history:
        if st.button("🗑️ 清除對話記錄"):
            st.session_state.chat_history = []
            st.rerun()

