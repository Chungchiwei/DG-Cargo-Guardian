# ============================================================
# 🗺️ bay_plan_engine.py — Bay Plan 座標邏輯引擎
# ============================================================

from collections import defaultdict
from fire_classifier import get_dominant_color

# ── 船舶尺寸常數（可依實際船型調整）────────────────────────
CELL_WIDTH_M  = 6.0   # 每個 Bay 寬度（公尺）
CELL_HEIGHT_M = 2.6   # 每個 Tier 高度（公尺）
CELL_ROW_M    = 2.4   # 每個 Row 寬度（公尺）


def parse_position(pos: str) -> dict | None:
    """
    解析 BBRRTT 位置代碼

    Args:
        pos: 6位數字字串，例如 "010472"

    Returns:
        {"bay": 1, "row": 4, "tier": 72, "on_deck": True}
        或 None（格式錯誤）

    Tier 判斷規則：
        02, 04, 06, 08, 10, 12, 14, 16, 18, 20 = 大艙（Hold）
        70, 72, 74, 76, 78, 80, 82, 84, 86      = 甲板（Deck）
        分界線：tier >= 70 → 甲板
    """
    if not pos or not pos.isdigit() or len(pos) != 6:
        return None
    bay  = int(pos[0:2])
    row  = int(pos[2:4])
    tier = int(pos[4:6])
    return {
        "bay":     bay,
        "row":     row,
        "tier":    tier,
        "on_deck": tier >= 70,   # ← 原本是 >= 80，改為 >= 70
    }



def get_row_label(row: int) -> str:
    """
    Row 號碼轉可讀標籤
    00=中心線，奇數=左舷，偶數=右舷
    """
    if row == 0:
        return "00\n(CL)"
    elif row % 2 == 1:
        return f"{row:02d}\n(P{(row + 1) // 2})"   # Port 左舷
    else:
        return f"{row:02d}\n(S{row // 2})"           # Starboard 右舷


def get_tier_label(tier: int) -> str:
    """
    Tier 號碼轉可讀標籤

    甲板（Deck）：70, 72, 74, 76, 78, 80, 82...
        70 → D1, 72 → D2, 74 → D3 ...
    艙內（Hold）：02, 04, 06, 08, 10, 12...
        02 → H1, 04 → H2, 06 → H3 ...
    """
    if tier >= 70:
        level = (tier - 70) // 2 + 1   # 70→D1, 72→D2, 74→D3
        return f"{tier:02d}\n(D{level})"
    else:
        level = (tier - 2) // 2 + 1    # 02→H1, 04→H2, 06→H3
        return f"{tier:02d}\n(H{level})"



def build_bay_plan(cargo_list: list[dict]) -> dict:
    """
    將貨物清單轉換為 Bay Plan 資料結構

    Args:
        cargo_list: manifest_parser 輸出的標準貨物清單

    Returns:
        {
            3: {                          ← bay number (int)
                "on_deck": {
                    (row, tier): [cargo, ...]   ← 同格子可能多個貨物
                },
                "in_hold": {
                    (row, tier): [cargo, ...]
                }
            },
            ...
        }
    """
    plan = defaultdict(lambda: {"on_deck": defaultdict(list), "in_hold": defaultdict(list)})

    for cargo in cargo_list:
        pos = parse_position(cargo.get("position", ""))
        if pos is None:
            continue

        section = "on_deck" if pos["on_deck"] else "in_hold"
        key     = (pos["row"], pos["tier"])
        plan[pos["bay"]][section][key].append(cargo)

    # 轉為普通 dict（方便序列化）
    return {
        bay: {
            "on_deck": dict(data["on_deck"]),
            "in_hold": dict(data["in_hold"]),
        }
        for bay, data in sorted(plan.items())
    }


def get_cell_display(cargos: list[dict]) -> dict:
    """
    計算單一格子的顯示資訊（可能有多個貨物共用格子）
    """
    if not cargos:
        return None

    _priority = {"red": 0, "yellow": 1, "green": 2, "grey": 3}
    primary   = min(cargos, key=lambda c: _priority.get(c["fire_color"], 3))

    # ── 格子內文字：貨櫃號碼後7碼 + 位置碼 + UN ──────────────
    # 取第一筆（主要貨物）完整顯示，多筆時加 +N more
    pos = primary.get("position", "")

    if len(cargos) == 1:
        label = (
            f"{primary['container_no'][-7:]}\n"   # 貨櫃號後7碼
            f"{pos}\n"                              # 位置碼 BBRRTT
            f"UN{primary['un_number']}"             # UN號
        )
    else:
        label = (
            f"{primary['container_no'][-7:]}\n"
            f"{pos}\n"
            f"UN{primary['un_number']}\n"
            f"+{len(cargos)-1} more"
        )

    # ── Hover Tooltip：完整資訊 ───────────────────────────────
    tooltip_parts = []
    for c in cargos:
        c_pos = c.get("position", "—")
        tooltip_parts.append(
            f"📦 {c['container_no']}<br>"
            f"位置：{c_pos}<br>"
            f"UN{c['un_number']} | Class {c['hazard_class']}<br>"
            f"滅火：{c['fire_label']} ({c['fire_ems']})<br>"
            f"品名：{c['description'][:30] if c['description'] else '—'}"
        )
    tooltip = "<br>─────<br>".join(tooltip_parts)

    return {
        "color_hex": primary["fire_color_hex"],
        "label":     label,
        "tooltip":   tooltip,
        "count":     len(cargos),
        "cargos":    cargos,
    }



def get_bay_dimensions(bay_data: dict) -> dict:
    """
    計算單一 Bay 的格子範圍（用於繪圖座標）

    Returns:
        {
            "rows":  排序後的 row 清單,
            "tiers_deck": 排序後的甲板 tier 清單（由下到上）,
            "tiers_hold": 排序後的艙內 tier 清單（由下到上）,
        }
    """
    all_rows        = set()
    tiers_deck      = set()
    tiers_hold      = set()

    for (row, tier) in bay_data["on_deck"]:
        all_rows.add(row)
        tiers_deck.add(tier)
    for (row, tier) in bay_data["in_hold"]:
        all_rows.add(row)
        tiers_hold.add(tier)

    return {
        "rows":        sorted(all_rows),
        "tiers_deck":  sorted(tiers_deck),        # 甲板由低到高
        "tiers_hold":  sorted(tiers_hold),         # 艙內由低到高
    }


def get_plan_statistics(bay_plan: dict) -> dict:
    """
    統計 Bay Plan 中各顏色分布

    Returns:
        {"green": N, "yellow": N, "red": N, "grey": N, "total_bays": N}
    """
    stats = {"green": 0, "yellow": 0, "red": 0, "grey": 0, "total_bays": len(bay_plan)}

    for bay_data in bay_plan.values():
        for section in ("on_deck", "in_hold"):
            for cargos in bay_data[section].values():
                for cargo in cargos:
                    color = cargo.get("fire_color", "grey")
                    if color in stats:
                        stats[color] += 1

    return stats
