@echo off
cd /d "%~dp0"
title Nemesis Missions Bot

echo ==========================================
echo  Nemesis Missions Bot
echo ==========================================
echo.
echo Bot is starting...
echo Keep this window open while the bot works.
echo To stop the bot, press Ctrl+C.
echo.

python bot.py

echo.
echo Bot stopped or failed to start.
echo If there is an error above, send me its text.
pause
