@echo off
rem Deterministic pytest runner for the reference implementation evals.
rem Usage: run_tests.bat [pytest args...]
cd /d "%~dp0.."
"C:\Users\lnxzf\Desktop\projects\ufo\ufo\.venv\Scripts\python.exe" -m pytest %*
exit /b %ERRORLEVEL%