@echo off
chcp 65001 >nul
echo.
echo  ========================================
echo   DG Cargo Guardian 啟動中...
echo   船舶危險品緊急處置輔助系統
echo  ========================================
echo.

REM 檢查 Python 是否已安裝
python --version >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 未偵測到 Python，請先安裝 Python 3.10 以上版本
    echo    下載網址：https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ────────────────────────────────────────────────────────────
REM 規格書第五節 / docs/INITIAL_SAFETY_AUDIT.md C-6：
REM 先前每次啟動都會強制執行 pip install，代表船上無網路時連「啟動」都會卡住，
REM 違反「所有核心功能在完全沒有網路時仍可使用」的最高原則。
REM 改為：只在偵測到必要套件缺少時才嘗試安裝（並提示需要網路），
REM 已安裝過的情況下離線也能直接啟動。完整的離線安裝包／lockfile／portable
REM package 屬於 Phase 3 工作範圍，尚未完成（見 docs/CONTROLLED_SOURCES.md）。
REM ────────────────────────────────────────────────────────────
python -c "import streamlit, openai, pandas, plotly, openpyxl, dotenv" >nul 2>&1
if errorlevel 1 (
    echo [提示] 偵測到必要套件尚未安裝，將嘗試安裝（需要網路連線，僅需執行一次）...
    pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo [錯誤] 套件安裝失敗（可能無網路連線）。
        echo    離線環境請預先在有網路的電腦上安裝好套件，或聯繫公司 IT 取得離線安裝包。
        pause
        exit /b 1
    )
) else (
    echo [OK] 必要套件已安裝，離線啟動中...
)

REM 檢查 .env 檔案是否存在
if not exist .env (
    echo.
    echo [提示] 未偵測到 .env 檔案（AI 功能為選用，非核心功能）
    echo    如需啟用 AI 輔助說明功能，請複製 .env.example 為 .env 並填入 API Key
    echo    （不填入 API Key／不建立 .env，核心查詢、隔離檢查、Bay Plan 等離線功能仍可正常使用）
    echo.
)

REM 啟動 Streamlit 應用程式（規格書第五節 M-5：預設僅綁定 localhost，避免船上區網
REM 其他裝置意外連線；如需開放區網存取，請由管理者另行設定）
echo.
echo 正在啟動系統，請稍候...
echo    系統啟動後請在瀏覽器開啟：http://localhost:8501
echo.
streamlit run app.py --server.address 127.0.0.1

pause
