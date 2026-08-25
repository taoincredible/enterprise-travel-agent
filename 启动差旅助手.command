#!/bin/bash

PROJECT_DIR="/Users/zhoutao/Desktop/实习/差旅助手-Web"

osascript <<'APPLESCRIPT'
tell application "Terminal"
    activate
    do script "cd \"/Users/zhoutao/Desktop/实习/差旅助手-Web\" && source .venv312/bin/activate && uvicorn server.main:app --reload --port 8000"
    delay 2
    do script "cd \"/Users/zhoutao/Desktop/实习/差旅助手-Web\" && if [ ! -d node_modules ]; then npm install; fi && npm run dev"
end tell
APPLESCRIPT
