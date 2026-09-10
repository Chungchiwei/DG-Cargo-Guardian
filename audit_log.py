# ============================================================
# 🧾 audit_log.py — 最小可用稽核紀錄（Phase 1 過渡版）
# ============================================================
#
# 規格書 4.4：完整稽核系統（角色、登入、多種事件類型、岸端匯出）屬於 Phase 2
# 工作範圍，尚未建立。本模組先提供一個最小、可離線運作的 append-only JSONL
# 紀錄器，讓 P0 的 variant selection（規格書 3.2.8/3.2.9）與 segregation
# override 等安全關鍵操作，從現在起就有紀錄可查，而不是完全沒有稽核紀錄。
#
# 限制（將於 Phase 2 補強）：
#   - 沒有角色／帳號系統，selected_by 目前為自由輸入文字，非經驗證的帳號。
#   - 沒有防竄改機制（例如簽章、hash chain）。
#   - 沒有岸端匯出介面，僅為本機 JSONL 檔案。

import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone

AUDIT_LOG_PATH = os.path.join(os.path.dirname(__file__), "audit_log", "events.jsonl")


def _to_dict(obj):
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return obj
    raise TypeError(f"不支援的稽核紀錄型別：{type(obj)}")


def append_event(event_type: str, payload) -> dict:
    """
    附加一筆稽核事件到本機 JSONL 檔案（append-only）。

    Args:
        event_type: 事件類型，例如 "variant_selection"、"segregation_override"
        payload    : dataclass 或 dict，會被序列化為 JSON

    Returns:
        寫入的完整紀錄（含 timestamp/event_type）
    """
    os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)

    record = {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "payload":    _to_dict(payload),
    }

    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    return record
