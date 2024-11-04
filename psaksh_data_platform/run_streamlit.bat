@echo off
REM PSAKSH Streamlit Dashboard Launcher
REM =====================================================
REM HOW TO USE:
REM   1. Open Command Prompt or PowerShell
REM   2. Navigate to: C:\wamp64\www\dataeng\rads_data_platform
REM   3. Run: run_streamlit.bat
REM   OR double-click this file from Windows Explorer
REM      while in the rads_data_platform folder
REM =====================================================

title PSAKSH Streamlit Dashboard

REM Set working directory to THIS file location
cd /d "%~dp0"

echo ============================================================
echo   PSAKSH Streamlit Dashboard
echo   Working dir: %CD%
echo ============================================================
echo.

REM Verify correct directory
if not exist "dashboards\app.py" (
    echo ERROR: dashboards\app.py not found in %CD%
    echo.
    echo Please run from: C:\wamp64\www\dataeng\rads_data_platform\
    echo.
    pause
    exit /b 1
)

REM Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install from https://python.org
    pause
    exit /b 1
)
echo Python: & python --version

REM Install streamlit if missing
python -c "import streamlit" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo Installing Streamlit (first time only)...
    pip install streamlit plotly pandas numpy pyarrow --quiet
)

REM Verify python -m streamlit works (CLI may not be on PATH)
python -m streamlit --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: streamlit module not working. Try: pip install --upgrade streamlit
    pause
    exit /b 1
)

REM Check for data
if not exist "data\gold\fct_child_nutrition.parquet" (
    echo.
    echo WARNING: No Gold data found. Charts will be empty.
    echo Run first:
    echo   python -m data_generator.run --households 500 --output-dir data\raw
    echo   [then click Run ETL in the Flask dashboard]
    echo.
)

echo.
echo ============================================================
echo   Starting Streamlit...
echo   URL: http://localhost:8501
echo   Press Ctrl+C to stop
echo ============================================================
echo.

REM Kill any existing streamlit on port 8501
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8501" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM Start streamlit and open browser
start "" "http://localhost:8501"
python -m streamlit run dashboards\app.py --server.port 8501 --server.headless false --browser.gatherUsageStats false --theme.primaryColor "#1a365d" --theme.backgroundColor "#f0f4f8" --theme.secondaryBackgroundColor "#ffffff" --theme.textColor "#2d3748"

pause
