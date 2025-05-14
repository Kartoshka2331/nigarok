@echo off

cd ..

flet pack main.py ^
    --add-binary tunnel_protocol.py;. ^
    --icon builder/icon.ico ^
    --product-name "nigarok" ^
    --file-description "Nigarok client" ^
    --product-version 1.1 ^
    --company-name "Nigarok"

del main.spec
rmdir build
rename dist build
cd builder
