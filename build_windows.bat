@echo off
REM Build the Windows executable (requires Python 3.13 on PATH)
python -m pip install -r requirements.txt pyinstaller
pyinstaller schedule.spec
echo Done - output in dist\schedule\schedule.exe
