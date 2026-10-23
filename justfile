# 常用指令。執行 `just` 會列出全部。

# 列出所有指令
default:
    @just --list --unsorted

# 終端機版
play:
    uv run story

# 純文字版
plain:
    uv run story --plain

# 多人模式（大家輪流在同一台電腦上輸入）
party:
    uv run story --party

# 網頁伺服器：線上多人，大家用瀏覽器一起玩同一局（開放區網連線，需要伺服器的 GEMINI_API_KEY）
serve port="8080":
    uv run story-web --party --host 0.0.0.0 --port {{port}}

# 網頁伺服器：每個人各自玩，輸入自己的 API key（開放區網連線）
serve-solo port="8080":
    uv run story-web --host 0.0.0.0 --port {{port}}

# 在背景啟動線上多人的網頁伺服器（已經在執行就重啟）；畫面輸出寫在 server.log
start port="8080":
    #!/usr/bin/env bash
    set -euo pipefail
    just stop
    # setsid：伺服器自成一個程序群組，just stop 才能把 uv 和底下的 Python 一起關掉
    setsid nohup uv run story-web --party --host 0.0.0.0 --port {{port}} > server.log 2>&1 < /dev/null &
    echo $! > .server.pid
    sleep 2
    if kill -0 "$(cat .server.pid)" 2>/dev/null; then
        echo "伺服器已在背景啟動：http://localhost:{{port}}（輸出：server.log，關閉：just stop）"
    else
        echo "伺服器沒有啟動成功："
        cat server.log
        rm -f .server.pid
        exit 1
    fi

# 關閉背景的網頁伺服器
stop:
    #!/usr/bin/env bash
    if [ -f .server.pid ] && pid=$(cat .server.pid) && kill -0 "$pid" 2>/dev/null; then
        kill -TERM -- "-$pid"
        for _ in $(seq 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
        echo "伺服器已關閉"
    fi
    rm -f .server.pid

# 全部測試（可以加 pytest 參數，例如 just test -k party）
test *args:
    uv run pytest {{args}}

# 刪除除錯紀錄（*.log.jsonl 等），不會動到存檔
clean-logs:
    rm -fv story_log.jsonl party_log.jsonl saves/*.log.jsonl
