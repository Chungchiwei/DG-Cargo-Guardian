# ============================================================
# 🤖 llm_client.py — LLM 統一呼叫介面
# ============================================================

import os
from openai import OpenAI
from dotenv import load_dotenv

# 強制重新載入 .env（避免快取舊值）
load_dotenv(override=True)

# ── 讀取設定 ─────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "perplexity")
LLM_API_KEY  = os.getenv("LLM_API_KEY", "")
LLM_MODEL    = os.getenv("LLM_MODEL", "sonar-pro")

# ── 除錯：啟動時印出 Key 前綴確認有讀到 ─────────────────────
print(f"[llm_client] Provider : {LLM_PROVIDER}")
print(f"[llm_client] Model    : {LLM_MODEL}")
print(f"[llm_client] API Key  : {LLM_API_KEY[:12]}..." if LLM_API_KEY else "[llm_client] ❌ API Key 為空！")

# ── 建立 Client ──────────────────────────────────────────────
def _get_client() -> OpenAI:
    if LLM_PROVIDER == "perplexity":
        return OpenAI(
            api_key=LLM_API_KEY,
            base_url="https://api.perplexity.ai"
        )
    elif LLM_PROVIDER == "openai":
        return OpenAI(api_key=LLM_API_KEY)
    else:
        raise ValueError(f"不支援的 LLM_PROVIDER：{LLM_PROVIDER}")


# ── 統一呼叫介面 ─────────────────────────────────────────────
def get_llm_response(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.2,
    max_tokens: int = 2048
) -> str:
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message}
            ],
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content

    except Exception as e:
        return f"❌ LLM 呼叫失敗：{e}"
