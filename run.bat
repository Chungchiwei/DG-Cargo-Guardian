@echo off
chcp 65001 >nul
echo.
echo  ========================================
echo   🚢 DG Cargo Guardian 啟動中...
echo   船舶危險品緊急處置輔助系統
echo  ========================================
echo.

REM 檢查 Python 是否已安裝
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 錯誤：未偵測到 Python，請先安裝 Python 3.9 以上版本
    echo    下載網址：https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 安裝必要套件
echo 📦 正在安裝/更新必要套件...
pip install -r requirements.txt --quiet

REM 檢查 .env 檔案是否存在
if not exist .env (
    echo.
    echo ⚠️  提示：未偵測到 .env 檔案
    echo    請複製 .env.example 為 .env
    echo    並填入 Perplexity API Key
    echo    取得 Key：https://perplexity.ai/account/api
    echo    （不填入 API Key 仍可使用 EMS 查詢，AI 功能將停用）
    echo.
)


REM 啟動 Streamlit 應用程式
echo.
echo 🚀 正在啟動系統，請稍候...
echo    系統啟動後請在瀏覽器開啟：http://localhost:8501
echo.
streamlit run app.py

pause
