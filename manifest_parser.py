# ============================================================
# 📋 manifest_parser.py — DG 艙單解析器（含 ASC 格式支援）
# ============================================================

import re
import io
import pandas as pd
from fire_classifier import classify_fire_category
from ems_engine import query_ems


# ══════════════════════════════════════════════════════════════
# ── 欄位別名對照表（Excel / CSV 用）
# ══════════════════════════════════════════════════════════════
COLUMN_ALIASES = {
    "container_no": [
        "Container No", "Container No.", "CNTR NO", "CTR NO",
        "Container Number", "貨櫃號碼", "櫃號"
    ],
    "un_number": [
        "UN No", "UN No.", "UN Number", "UN", "UN#",
        "UN號碼", "UN號", "危險品編號"
    ],
    "class": [
        "Class", "Hazard Class", "DG Class", "IMO Class",
        "危險品類別", "類別"
    ],
    "packing_group": [
        "PG", "Packing Group", "Pack Group",
        "包裝等級", "PG等級"
    ],
    "position": [
        "Position", "Stowage", "Bay/Row/Tier", "BBRRTT",
        "Location", "位置", "艙位", "貨位"
    ],
    "description": [
        "Description", "Proper Shipping Name", "PSN",
        "Cargo Description", "貨物名稱", "品名"
    ],
}


# ══════════════════════════════════════════════════════════════
# ── ASC 檔案解析（核心新功能）
# ══════════════════════════════════════════════════════════════

def _parse_hazard_class(raw_class: str) -> str:
    """
    將 ASC 格式的 Class 代碼轉為標準格式
    例如：
        "003"  → "3"
        "0021" → "2.1"
        "0022" → "2.2"
        "0023" → "2.3"
        "008"  → "8"
        "009"  → "9"
        "0061" → "6.1"
        "0062" → "6.2"
        "0041" → "4.1"
        "0042" → "4.2"
        "0043" → "4.3"
        "0051" → "5.1"
        "0052" → "5.2"
        "0071" → "7"
        "0011" → "1.1" (爆炸物)
    """
    s = raw_class.strip().lstrip("0")   # 去除前導零

    if not s:
        return "未知"

    # 長度 1：直接是 Class（如 "3", "8", "9"）
    if len(s) == 1:
        return s

    # 長度 2：Class + 子類（如 "21" → "2.1"）
    if len(s) == 2:
        return f"{s[0]}.{s[1]}"

    # 其他情況直接回傳
    return s


def _parse_un_number(raw_un: str) -> str:
    """
    從 DG 資料行的 UN 欄位提取 UN 號碼
    格式：前4碼是 UN NO，後面是其他資料
    例如：'199300000' → '1993'
          '126600000' → '1266'
          '1132500000' → '1132' (Class 4.1 等較長格式)
    """
    s = raw_un.strip()
    if len(s) >= 4:
        candidate = s[:4]
        if candidate.isdigit():
            return candidate
    return ""


def parse_asc_file(file_bytes: bytes) -> tuple[list[dict], list[str]]:
    """
    解析 ASC 格式的船舶積載計畫檔案，提取所有 DG 危險品貨物

    IMDG 段落實際格式（經實測確認，三種變體）：
        格式A："0001003 186600000  N"  → 序號(4) + Class(3碼) + 空格 + UN(4) + 5碼
        格式B："0002008 273500000  N"  → 同上
        格式C："00030022316300000  N"  → 序號(4) + Class(4碼) + UN(4) + 5碼（無空格）

    Class 欄位規律：
        3碼 Class → 後面有空格（如 003、008）
        4碼 Class → 後面無空格，直接接 UN（如 0022 = Class 2.2）
    """
    warnings   = []
    cargo_list = []

    # ── 步驟 0：解碼 ─────────────────────────────────────────
    content = None
    for encoding in ["utf-8", "utf-8-sig", "big5", "latin-1"]:
        try:
            content = file_bytes.decode(encoding, errors="ignore")
            break
        except Exception:
            continue

    if content is None:
        return [], ["❌ 無法解析 ASC 檔案編碼"]

    content = content.replace("\x00", "").replace("`", "")
    lines   = content.splitlines()

    if not lines:
        return [], ["❌ 檔案內容為空"]

    # ── 步驟 1：解析標頭 ─────────────────────────────────────
    ship_name = "Unknown"
    voyage    = "Unknown"
    for line in lines[:5]:
        m = re.search(r'\$604\w*/([^/]+)/([^/]+)/', line)
        if m:
            ship_name = m.group(1).strip()
            voyage    = m.group(2).strip()
            break

    # ── 步驟 2：定位 IMDG 區段起始行 ────────────────────────
    imdg_section_start = None
    for i, line in enumerate(lines):
        if "Refer to the following IMDG" in line:
            imdg_section_start = i + 1
            break

    if imdg_section_start is None:
        warnings.append("⚠️ 未找到 IMDG 資料區段（***Refer to the following IMDG.）")
        return [], warnings

    # ── 步驟 3：掃描貨物行，找出 DG 貨物 ────────────────────
    CARGO_CODE_RE = re.compile(
        r'(?:2200|2230|2250|2270|2500|4300|4350|4500|4530|4550|9500)\d{3}[FE]'
    )

    dg_position_map = {}

    for line in lines[:imdg_section_start]:
        if not re.match(r'^\d{6}\s', line):
            continue

        parts = line.split()
        if len(parts) < 5:
            continue

        position     = parts[0]
        container_no = parts[1]

        if not re.match(r'^[A-Z]{4}\d{7}$', container_no):
            continue

        cargo_match = CARGO_CODE_RE.search(line)
        if not cargo_match:
            continue

        after_cargo = line[cargo_match.end():]
        candidates  = re.findall(r'(?<!\d)(\d{4})(?!\d)', after_cargo)

        dg_seq = None
        for cand in candidates:
            if 1 <= int(cand) <= 9999:
                dg_seq = cand.zfill(4)
                break

        if dg_seq is None:
            continue

        if dg_seq not in dg_position_map:
            dg_position_map[dg_seq] = {
                "position":     position,
                "container_no": container_no,
            }

    if not dg_position_map:
        warnings.append("⚠️ 未找到任何 DG 標記（貨物行中無 4 碼 DG 序號）")
        return [], warnings

    # ── 步驟 4：解析 IMDG 資料區段 ──────────────────────────
    #
    # 三種實際格式：
    #   "0001003 186600000  N" → Class=003(3碼)+空格, UN=1866
    #   "0002008 273500000  N" → Class=008(3碼)+空格, UN=2735
    #   "00030022316300000  N" → Class=0022(4碼)+無空格, UN=3163
    #
    # 統一正則：
    #   (\d{4}|\d{3})\s?  →  4碼Class（後無空格）或 3碼Class（後有空格）
    #   兩者都用 \s? 收尾，4碼時 \s? 匹配0個空格，3碼時匹配1個空格
    # ─────────────────────────────────────────────────────────

    IMDG_RE = re.compile(
        r'^(\d{4})'           # 序號（4碼）
        r'(\d{4}|\d{3})\s?'   # Class：4碼（無空格）或 3碼（後接可選空格）
        r'(\d{4})'            # UN 號碼（4碼）
        r'\d{5}'              # 其他數字（5碼）
    )

    dg_detail_map = {}

    for line in lines[imdg_section_start:]:
        line_clean = line.strip()

        if not line_clean:
            continue
        if line_clean.startswith("$") or line_clean.startswith("*"):
            continue
        if not re.match(r'^\d{4}', line_clean):
            continue

        m = IMDG_RE.match(line_clean)
        if not m:
            continue

        dg_seq    = m.group(1).zfill(4)
        class_raw = m.group(2)
        un_number = m.group(3)

        if not un_number.isdigit() or un_number == "0000":
            continue

        hazard_class = _parse_hazard_class(class_raw)

        if dg_seq not in dg_detail_map:
            dg_detail_map[dg_seq] = {
                "un":    un_number,
                "class": hazard_class,
            }

    # ── 步驟 5：交叉比對，建立最終貨物清單 ──────────────────
    matched_count  = 0
    unmatched_seqs = []

    for dg_seq, pos_info in sorted(dg_position_map.items()):
        detail = dg_detail_map.get(dg_seq)

        if not detail:
            unmatched_seqs.append(dg_seq)
            warnings.append(
                f"⚠️ DG序號 {dg_seq}"
                f"（{pos_info['container_no']} @ {pos_info['position']}）"
                f"：IMDG 區段無對應資料"
            )
            continue

        un_number = detail["un"]
        position  = pos_info["position"]

        ems_data      = query_ems(un_number)
        fire_code     = ""
        spill_code    = ""
        description   = ""
        packing_group = ""

        if ems_data.get("found"):
            fire_code     = ems_data["ems"].get("fire_code",     "")
            spill_code    = ems_data["ems"].get("spillage_code", "")
            description   = ems_data.get("proper_shipping_name", "")
            packing_group = ems_data.get("packing_group",        "")
        else:
            warnings.append(
                f"⚠️ DG序號 {dg_seq}（UN{un_number}）：查無 EMS 資料"
            )

        fire_cat = classify_fire_category(fire_code)

        cargo_list.append({
            "container_no":   pos_info["container_no"],
            "dg_seq":         dg_seq,
            "un_number":      un_number,
            "position":       position,
            "description":    description,
            "hazard_class":   detail["class"],
            "packing_group":  packing_group,
            "fire_ems":       fire_code,
            "spill_ems":      spill_code,
            "fire_color":     fire_cat.get("color",      "grey"),
            "fire_color_hex": fire_cat.get("color_hex",  "#6b7280"),
            "fire_label":     fire_cat.get("label",      "未知"),
            "fire_media":     fire_cat.get("media",      ""),
            "fire_do":        fire_cat.get("do",         ""),
            "fire_dont":      fire_cat.get("dont",       ""),
            "fire_risk":      fire_cat.get("risk_after", ""),
            "ems_found":      ems_data.get("found", False),
            "requires_variant_selection": ems_data.get("requires_variant_selection", False),
            "variant_status": ems_data.get("variant_status", ""),
            "source":         "ASC",
            "ship_name":      ship_name,
            "voyage":         voyage,
        })
        matched_count += 1

    # ── 步驟 6：組裝摘要訊息 ─────────────────────────────────
    warnings.insert(0,
        f"✅ ASC 解析完成 | 船名：{ship_name} 航次：{voyage} | "
        f"DG 標記：{len(dg_position_map)} 個 | "
        f"成功比對：{matched_count} 筆 | "
        f"未比對：{len(unmatched_seqs)} 筆"
    )

    if not cargo_list:
        warnings.append("⚠️ 最終未產生任何有效 DG 貨物記錄")

    return cargo_list, warnings



# ══════════════════════════════════════════════════════════════
# ── Excel / CSV 解析（原有功能，保持不變）
# ══════════════════════════════════════════════════════════════

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map    = {}
    df_cols_lower = {col.strip().lower(): col for col in df.columns}
    for standard_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.strip().lower() in df_cols_lower:
                rename_map[df_cols_lower[alias.strip().lower()]] = standard_name
                break
    return df.rename(columns=rename_map)


def _clean_un_number(raw) -> str:
    if pd.isna(raw):
        return ""
    s = str(raw).strip().upper()
    s = s.replace("UN", "").replace(" ", "").replace("-", "")
    return s.zfill(4) if s.isdigit() else s


def _clean_position(raw) -> str:
    if pd.isna(raw):
        return ""
    s = str(raw).strip().replace(" ", "").replace("-", "")
    return s.zfill(6) if s.isdigit() else s


def parse_manifest_excel(file_bytes: bytes, sheet_name=0) -> tuple[list[dict], list[str]]:
    """解析 Excel 格式的 DG 艙單"""
    if not file_bytes:
        return [], ["❌ 檔案內容為空，請確認上傳的是正確的 Excel 檔案"]
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, dtype=str)
    except Exception as e:
        # 修正：先前這裡沒有 try/except，pandas/openpyxl 的例外（例如空檔案、
        # 檔案損毀、副檔名為 .xlsx 但內容不是合法 Excel）會直接以完整 Python
        # Traceback 顯示在畫面上，嚇壞使用者也沒有任何行動建議。
        # 統一改為與其他解析函式一致的 (list, warnings) 回傳格式，並提示可能原因。
        return [], [
            f"❌ 無法解析 Excel 檔案（{type(e).__name__}）：檔案可能已損毀、"
            "為空白檔案，或副檔名與實際格式不符。請改用「下載範例模板」提供的格式重新製作。"
        ]
    return _process_dataframe(df)


def parse_manifest_csv(file_bytes: bytes) -> tuple[list[dict], list[str]]:
    """解析 CSV 格式的 DG 艙單"""
    if not file_bytes:
        return [], ["❌ 檔案內容為空，請確認上傳的是正確的 CSV 檔案"]

    last_error = None
    for encoding in ["utf-8", "utf-8-sig", "big5", "gbk"]:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, encoding=encoding)
            return _process_dataframe(df)
        except UnicodeDecodeError:
            continue
        except Exception as e:
            # 修正：EmptyDataError（空白檔案）、ParserError（格式錯亂的 CSV）等例外
            # 先前未被捕捉，會以完整 Python Traceback 直接顯示在畫面上。
            last_error = e
            break

    if last_error is not None:
        return [], [
            f"❌ 無法解析 CSV 檔案（{type(last_error).__name__}）：檔案可能為空白、"
            "格式錯亂，或欄位分隔符號不是逗號。請改用「下載範例模板」提供的格式重新製作。"
        ]
    return [], ["❌ 無法解析 CSV 編碼，請另存為 UTF-8 格式後重試"]


def _process_dataframe(df: pd.DataFrame) -> tuple[list[dict], list[str]]:
    """將 DataFrame 轉換為標準貨物清單"""
    warnings   = []
    cargo_list = []

    df = _normalize_columns(df)
    df = df.dropna(how="all")

    required = ["container_no", "un_number", "position"]
    missing  = [col for col in required if col not in df.columns]
    if missing:
        warnings.append(
            f"⚠️ 缺少必要欄位：{', '.join(missing)}。請確認欄位名稱。"
        )
        return [], warnings

    for idx, row in df.iterrows():
        row_num      = idx + 2
        container_no = str(row.get("container_no", "")).strip()
        un_number    = _clean_un_number(row.get("un_number", ""))
        position     = _clean_position(row.get("position",  ""))

        if not container_no or not un_number:
            continue

        if not un_number.isdigit() or len(un_number) != 4:
            warnings.append(f"第 {row_num} 行：UN 號碼格式異常（{row.get('un_number','')}），已跳過")
            continue

        if position and (not position.isdigit() or len(position) != 6):
            warnings.append(f"第 {row_num} 行：位置格式異常（{row.get('position','')}），已設為空白")
            position = ""

        ems_data   = query_ems(un_number)
        fire_code  = ""
        spill_code = ""

        if ems_data["found"]:
            fire_code  = ems_data["ems"].get("fire_code",     "")
            spill_code = ems_data["ems"].get("spillage_code", "")
            fire_cat   = classify_fire_category(fire_code)
        else:
            warnings.append(f"第 {row_num} 行：UN{un_number} 查無 IMDG 資料")
            fire_cat = classify_fire_category("UNKNOWN")

        cargo_list.append({
            "container_no":   container_no,
            "dg_seq":         "",
            "un_number":      un_number,
            "position":       position,
            "description":    str(row.get("description", ems_data.get("proper_shipping_name", ""))).strip(),
            "hazard_class":   str(row.get("class",        ems_data.get("hazard_class",        ""))).strip(),
            "packing_group":  str(row.get("packing_group",ems_data.get("packing_group",       ""))).strip(),
            "fire_ems":       fire_code,
            "spill_ems":      spill_code,
            "fire_color":     fire_cat.get("color",     "grey"),
            "fire_color_hex": fire_cat.get("color_hex", "#6b7280"),
            "fire_label":     fire_cat.get("label",     "未知"),
            "fire_media":     fire_cat.get("media",     ""),
            "fire_do":        fire_cat.get("do",        ""),
            "fire_dont":      fire_cat.get("dont",      ""),
            "fire_risk":      fire_cat.get("risk_after",""),
            "ems_found":      ems_data["found"],
            "requires_variant_selection": ems_data.get("requires_variant_selection", False),
            "variant_status": ems_data.get("variant_status", ""),
            "source":         "Excel/CSV",
            "ship_name":      "",
            "voyage":         "",
        })

    if not cargo_list:
        warnings.append("⚠️ 未解析到任何有效貨物資料，請確認檔案格式")

    return cargo_list, warnings


# ══════════════════════════════════════════════════════════════
# ── 共用工具函數
# ══════════════════════════════════════════════════════════════

def get_manifest_summary(cargo_list: list[dict]) -> dict:
    """產生艙單統計摘要"""
    from collections import Counter

    color_count = Counter(c["fire_color"]   for c in cargo_list)
    class_count = Counter(c["hazard_class"] for c in cargo_list if c["hazard_class"])
    no_pos      = sum(1 for c in cargo_list if not c["position"])
    ambiguous   = sum(1 for c in cargo_list if c.get("requires_variant_selection"))
    ems_known   = sum(1 for c in cargo_list if c.get("fire_ems"))

    return {
        "total":      len(cargo_list),
        # 顏色不再代表滅火介質或風險等級（規格書 3.5），僅供內部統計沿用既有 key。
        "by_color": {
            "green":  color_count.get("green",  0),
            "yellow": color_count.get("yellow", 0),
            "red":    color_count.get("red",    0),
            "grey":   color_count.get("grey",   0),
        },
        "by_class":       dict(class_count.most_common()),
        "no_position":    no_pos,
        "ambiguous":      ambiguous,   # requires_variant_selection=true 且尚未選列
        "ems_known":      ems_known,   # 已取得 EmS Fire Code（僅代表有 code，非詳細指令）
    }


def generate_sample_template() -> bytes:
    """產生範例 Excel 模板供使用者下載"""
    sample_data = {
        "Container No": ["WHLU1234567", "WHLU7654321", "WHLU1111111"],
        "UN No":        ["1203",        "1017",        "3480"       ],
        "Class":        ["3",           "2.3",         "9"          ],
        "PG":           ["II",          "N/A",         "II"         ],
        "Position":     ["030282",      "050184",      "070086"     ],
        "Description":  ["GASOLINE",   "CHLORINE",    "LITHIUM BATTERIES"],
    }
    df  = pd.DataFrame(sample_data)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()
