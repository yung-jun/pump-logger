@echo off
REM 水處理廠泵浦監控 DAQ pipeline 啟動腳本
REM 可雙擊直接手動啟動，或由 Task Scheduler 呼叫

cd /d C:\Users\USER\Desktop\ncku-daq
venv\Scripts\python.exe -m pump_monitor.main
