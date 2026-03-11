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
    
    ASC 位置碼格式：BBRRTT
        BB = Bay（01~99）
        RR = Row（01~99）
        TT = Tier
            02~18（偶數）= 大艙 Hold
            70, 72, 74, 76, 78, 80, 82... = 甲板 Deck
    """
    warnings   = []
    cargo_list = []

    # ── 讀取並清理內容 ───────────────────────────────────────
    for encoding in ["utf-8", "utf-8-sig", "big5", "latin-1"]:
        try:
            content = file_bytes.decode(encoding, errors="ignore")
            break
        except Exception:
            continue
    else:
        return [], ["❌ 無法解析 ASC 檔案編碼"]

    content = content.replace("\x00", "").replace("`", "")
    lines   = content.splitlines()

    # ── 第一步：解析標頭資訊 ─────────────────────────────────
    ship_name = "Unknown"
    voyage    = "Unknown"
    for line in lines[:5]:
        m = re.search(r'\$604\w*/([^/]+)/([^/]+)/', line)
        if m:
            ship_name = m.group(1).strip()
            voyage    = m.group(2).strip()
            break

    # ── 第二步：找到 IMDG 區段分隔線 ────────────────────────
    imdg_section_start = None
    for i, line in enumerate(lines):
        if "Refer to the following IMDG" in line:
            imdg_section_start = i + 1
            break

    if imdg_section_start is None:
        warnings.append("⚠️ 未找到 IMDG 資料區段（Refer to the following IMDG）")
        return [], warnings

    # ── 第三步：解析貨物區段，找出 DG 貨物位置與櫃號 ────────
    #
    # ASC 貨物行完整格式（固定欄位，空格分隔）：
    #
    #   欄1  : 位置碼    6碼數字  BBRRTT
    #   欄2  : 貨櫃號碼  11碼英數  [A-Z]{4}\d{7}
    #   欄3  : 業者代碼
    #   欄4  : 目的港
    #   欄5  : 貨物代碼  如 2270238F / 4500216F
    #   欄6  : DG序號（可選，4碼數字 0001~9999）← 只有 DG 貨物才有
    #   ...  : 其他欄位（重量、行序號等）
    #
    # DG 序號識別規則：
    #   - 出現在貨物代碼（欄5）之後
    #   - 是獨立的 4碼數字，範圍 0001~9999
    #   - 行序號（末尾 5碼如 00007）不會被誤抓，因為是 5碼
    #   - 重量碼（如 23800）是 5碼，也不會被誤抓
    #
    # ⚠️ 關鍵：DG 序號是嚴格的 4碼（不多不少）
    # ─────────────────────────────────────────────────────────

    CARGO_CODE_RE = re.compile(
        r'\b(?:2200|2230|2250|2270|2500|4300|4350|4500|4530|4550|9500)\d{3}[FE]\b'
    )

    # DG 序號：嚴格 4碼數字，0001~9999
    # 使用 (?<!\d) 和 (?!\d) 確保前後不是數字（精確匹配4碼）
    DG_SEQ_RE = re.compile(r'(?<!\d)(0[0-9]{3})(?!\d)')

    dg_position_map = {}

    for line in lines[:imdg_section_start]:
        # ── 行首必須是 6 碼數字（位置碼）+ 空白 ──────────────
        if not re.match(r'^\d{6}\s', line):
            continue

        parts = line.split()
        if len(parts) < 5:
            continue

        position     = parts[0]   # 行首 6 碼 = 位置碼
        container_no = parts[1]   # 第二欄 = 貨櫃號碼
        

        # ── 驗證貨櫃號碼格式 ──────────────────────────────────
        if not re.match(r'^[A-Z]{4}\d{7}$', container_no):
            continue

        # ── Tier 判斷：只處理甲板貨物（Tier >= 70）────────────
        try:
            tier = int(position[4:6])
        except ValueError:
            continue

        if tier < 70:
            continue   # 大艙貨物，跳過

        # ── 找貨物代碼（確認這是有效的貨物行）───────────────
        cargo_match = CARGO_CODE_RE.search(line)
        if not cargo_match:
            continue

        # ── 在貨物代碼之後，尋找嚴格 4碼 DG 序號 ────────────
        # 取貨物代碼結束位置之後的文字
        after_cargo = line[cargo_match.end():]

        # 找所有 4碼數字候選
        candidates = re.findall(r'(?<!\d)(\d{4})(?!\d)', after_cargo)

        dg_seq = None
        for cand in candidates:
            val = int(cand)
            if 1 <= val <= 9999:
                # 排除明顯是重量或其他用途的值
                # DG 序號通常是 0001~0999 範圍（本航次最多幾百個 DG）
                # 但保守起見只排除 0000
                if cand != "0000":
                    dg_seq = cand.zfill(4)
                    break

        if dg_seq is None:
            continue   # 無 DG 序號，普通甲板貨物

        if dg_seq not in dg_position_map:
            dg_position_map[dg_seq] = {
                "position":     position,
                "container_no": container_no,
            }

    if not dg_position_map:
        warnings.append("⚠️ 在甲板貨物區段未找到任何 DG 標記（Tier >= 70）")
        return [], warnings

 # ── 第四步：解析 IMDG 資料區段 ──────────────────────────
    #
    # 實際觀察到的行格式變體：
    #   "00010041271700000               N"
    #   "0002009 308200000               N      N  0"
    #   "00140022285700000               N"
    #
    # 規則：
    #   前段（DG序號 + Class + UN資料）一定是數字（含空白）
    #   後段是任意旗標（N/Y/0 等），可以有多個，不影響前段解析
    #
    # 解法：只取行的「前段純數字部分」來解析，忽略後段旗標
    # ─────────────────────────────────────────────────────────

    # 只匹配行首的數字資料部分，後面接空白+任意字元都允許
    IMDG_LINE_RE = re.compile(
        r'^(\d{4})'           # DG 序號（4碼）
        r'\s*(\d{3,4})\s*'    # Class 代碼（3或4碼，允許空白分隔）
        r'(\d{9})'            # UN(4碼) + 其他(5碼) = 9碼
        r'[\s\S]*$'           # 後面接任何內容（N/Y/0 旗標等）都允許
    )

    dg_detail_map = {}

    for line in lines[imdg_section_start:]:
        line_clean = line.strip()

        if not line_clean:
            continue
        if line_clean.startswith("$") or line_clean.startswith("*"):
            continue

        # ── 關鍵修正：只驗證「行首數字段」是純數字 ──────────
        # 取第一個空白區塊之前的所有 token 組合，
        # 只要行首是 4碼數字開頭就嘗試解析，不再要求整行是純數字
        #
        # 原本的過濾邏輯（去掉末尾 N/Y 後剩餘必須是純數字）
        # 會被 "N  0" 這種多旗標格式誤殺，改為：
        # 只要行首符合 \d{4} 就嘗試正規表示式匹配
        if not re.match(r'^\d{4}', line_clean):
            continue   # 行首不是4碼數字，直接跳過（排除聯絡人行等）

        m = IMDG_LINE_RE.match(line_clean)
        if not m:
            continue

        dg_seq    = m.group(1).zfill(4)
        class_raw = m.group(2)
        un_block  = m.group(3)

        un_number = un_block[:4]
        if not un_number.isdigit() or un_number == "0000":
            continue

        hazard_class = _parse_hazard_class(class_raw)

        if dg_seq not in dg_detail_map:
            dg_detail_map[dg_seq] = {
                "un":    un_number,
                "class": hazard_class,
            }


    # ── 第五步：交叉比對，建立最終貨物清單 ──────────────────
    matched_count  = 0
    unmatched_seqs = []

    for dg_seq, pos_info in sorted(dg_position_map.items()):
        detail = dg_detail_map.get(dg_seq)

        if not detail:
            unmatched_seqs.append(dg_seq)
            warnings.append(
                f"⚠️ DG編號 {dg_seq}"
                f"（{pos_info['container_no']} @ {pos_info['position']}）"
                f"：在 IMDG 區段找不到對應詳細資料"
            )
            continue

        un_number = detail["un"]
        position  = pos_info["position"]

        ems_data      = query_ems(un_number)
        fire_code     = ""
        spill_code    = ""
        description   = ""
        packing_group = ""

        if ems_data["found"]:
            fire_code     = ems_data["ems"].get("fire_code",     "")
            spill_code    = ems_data["ems"].get("spillage_code", "")
            description   = ems_data.get("proper_shipping_name", "")
            packing_group = ems_data.get("packing_group",        "")
        else:
            warnings.append(
                f"⚠️ DG編號 {dg_seq}（UN{un_number}）"
                f"：查無 IMDG EMS 資料，滅火分類標記為未知"
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
            "ems_found":      ems_data["found"],
            "source":         "ASC",
            "ship_name":      ship_name,
            "voyage":         voyage,
        })
        matched_count += 1

    warnings.insert(0,
        f"✅ ASC 解析完成：找到 {len(dg_position_map)} 個 DG 標記（甲板），"
        f"成功比對 {matched_count} 筆，"
        f"未比對 {len(unmatched_seqs)} 筆"
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
    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, dtype=str)
    return _process_dataframe(df)


def parse_manifest_csv(file_bytes: bytes) -> tuple[list[dict], list[str]]:
    """解析 CSV 格式的 DG 艙單"""
    for encoding in ["utf-8", "utf-8-sig", "big5", "gbk"]:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, encoding=encoding)
            return _process_dataframe(df)
        except UnicodeDecodeError:
            continue
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

    return {
        "total":    len(cargo_list),
        "by_color": {
            "green":  color_count.get("green",  0),
            "yellow": color_count.get("yellow", 0),
            "red":    color_count.get("red",    0),
            "grey":   color_count.get("grey",   0),
        },
        "by_class":    dict(class_count.most_common()),
        "no_position": no_pos,
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
