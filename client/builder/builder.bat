@echo off
setlocal

cd ..
call venv\Scripts\activate.bat

flet pack main.py ^
    --add-binary tunnel_protocol.py;. ^
    --icon builder/icon.ico ^
    --product-name "nigarok" ^
    --file-description "Nigarok client" ^
    --product-version 1.2 ^
    --company-name "Nigarok"

deactivate

cd builder

endlocal
