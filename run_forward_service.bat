@echo off
cd /d D:\FOREX
echo Checking existing ZF scanner service...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | Where-Object { $_.CommandLine -like '*zf_core_scanner_v20.py*' } | ForEach-Object { Write-Host ('Stopping existing scanner PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }"
echo.
echo Starting ZF Core Scanner V20 forward service...
echo.
python zf_core_scanner_v20.py --service
echo.
echo Service stopped or failed. Press any key to close this window.
pause >nul
