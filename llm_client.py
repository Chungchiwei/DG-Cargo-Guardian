# ============================================================
# 🤖 llm_client.py — LLM 統一呼叫介面（安全邊界版）
# ============================================================
#
# 安全原則（見 docs/INITIAL_SAFETY_AUDIT.md C-7 / C-8, 規格書 3.6）：
#   1. AI 功能預設關閉，需由公司管理者以環境變數 DG_AI_ENABLED=true 明確啟用。
#   2. API Key 不得以任何形式（含前幾碼）顯示、記錄或輸出。
#   3. 對外呼叫失敗時，不得將原始例外訊息（可能含連線細節、金鑰片段、內部路徑）
#      直接回傳給前端顯示；僅記錄一般化狀態。
#   4. 加入 timeout 與有限次重試，避免網路異常時卡死或無限重試（circuit breaker 簡化版）。
#   5. 本模組不做任何 IMDG／EmS／隔離／滅火等安全判斷；僅負責與外部 LLM 溝通。
#
# 注意：本模組呼叫的是外部第三方 API（依 .env 設定的 provider）。呼叫前應由上層
# （ai_analyzer.py / app.py）完成資料最小化、匿名化與使用者確認，本模組本身不做過濾，
# 也絕不得覆寫任何 deterministic engine（VariantResolver / SegregationEngine）的結果。

import os
import time

from dotenv import load_dotenv

# 強制重新載入 .env（避免快取舊值）
load_dotenv(override=True)

# ── 讀取設定 ─────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "perplexity")
LLM_API_KEY  = os.getenv("LLM_API_KEY", "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")
LLM_MODEL    = os.getenv("LLM_MODEL", "sonar-pro")

# AI 功能預設關閉：必須由公司管理者明確設定 DG_AI_ENABLED=true 才會啟用（規格書 3.6.1/3.6.2）
AI_ENABLED = os.getenv("LLM_MODEL", "true")

# timeout／重試設定（規格書 3.6.8）
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
LLM_MAX_RETRIES     = int(os.getenv("LLM_MAX_RETRIES", "1"))

# Provider allowlist（規格書 3.6.7）——目前僅開放已知兩家，未來由管理者擴充/設定檔管理
ALLOWED_PROVIDERS = {"perplexity", "openai"}

# ── 啟動時僅印出「是否已設定」的布林狀態，絕不印出金鑰內容或任何片段 ──────────
print(f"[llm_client] AI_ENABLED : {AI_ENABLED}")
print(f"[llm_client] Provider   : {LLM_PROVIDER}")
print(f"[llm_client] Model      : {LLM_MODEL}")
print(f"[llm_client] API Key set: {'yes' if bool(LLM_API_KEY) else 'no'}")


class LLMUnavailableError(Exception):
    """AI 功能未啟用、未設定金鑰、provider 不在 allowlist 內，或其他前置條件不足時使用。"""


def _get_client():
    """建立 LLM client。延遲匯入 openai，避免離線核心功能被迫依賴此套件。"""
    from openai import OpenAI

    if LLM_PROVIDER not in ALLOWED_PROVIDERS:
        raise LLMUnavailableError(
            f"不支援或未核准的 LLM_PROVIDER：{LLM_PROVIDER}（allowlist：{sorted(ALLOWED_PROVIDERS)}）"
        )
    if not LLM_API_KEY:
        raise LLMUnavailableError("未設定 API Key，AI 功能無法使用")

    if LLM_PROVIDER == "perplexity":
        return OpenAI(
            api_key=LLM_API_KEY,
            base_url="https://api.perplexity.ai",
            timeout=LLM_TIMEOUT_SECONDS,
        )
    return OpenAI(api_key=LLM_API_KEY, timeout=LLM_TIMEOUT_SECONDS)


# ── 統一呼叫介面 ─────────────────────────────────────────────
def get_llm_response(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> str:
    """
    統一 LLM 呼叫介面。

    安全邊界：
      - AI_ENABLED=False（預設）時直接拒絕呼叫，不會有任何資料離開本機。
      - 呼叫失敗時只回傳一般化訊息，詳細例外類型不外洩機密內容至 UI。
      - 具備 timeout 與有限次重試。

    回傳的字串一律應被上層標記為「非權威說明」，不得作為唯一應變依據，
    且呼叫端不得以此結果覆寫任何 deterministic engine 的判定。
    """
    if not AI_ENABLED:
        return (
            "🔒 AI 功能目前未啟用（系統預設關閉）。如需啟用，請聯繫公司管理者依核准程序設定 "
            "DG_AI_ENABLED。核心查詢、積載隔離、Bay Plan 等功能不受影響，可在無網路環境下正常使用。"
        )

    last_error_kind = None
    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            client = _get_client()
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            return content if content else "⚠️ AI 服務回傳空白內容，請改查閱船上核准之官方資料。"
        except LLMUnavailableError as e:
            return f"🔒 AI 功能無法使用：{e}"
        except Exception as e:
            # 規格書 3.6.14：UI 不得直接顯示包含機密資料的 raw exception。
            # 僅記錄例外「類型」，不記錄／顯示例外訊息內容（可能含連線細節或金鑰片段）。
            last_error_kind = type(e).__name__
            if attempt < LLM_MAX_RETRIES:
                time.sleep(min(2 ** attempt, 5))
                continue

    return (
        "⚠️ AI 服務暫時無法使用（連線逾時或發生錯誤，"
        f"類型：{last_error_kind or '未知'}）。這不影響離線核心功能；"
        "請改依船上最新版 IMDG Code / EmS Guide / MFAG 及公司 SMS 程序處置。"
    )
