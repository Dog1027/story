# 常用指令。執行 `just` 會列出全部。

# 列出所有指令
default:
    @just --list --unsorted

# 網頁伺服器：大家進大廳開房間，一個人玩或和朋友組隊都可以（開放區網連線）
serve port="8080":
    uv run story-web --host 0.0.0.0 --port {{port}}

# 在背景啟動網頁伺服器（已經在執行就重啟）；畫面輸出寫在 server.log
start port="8080":
    #!/usr/bin/env bash
    set -euo pipefail
    uv run story-web --setup-only  # 第一次啟動：先問語言與 API key（背景裡沒辦法問）
    just stop
    # setsid：伺服器自成一個程序群組，just stop 才能把 uv 和底下的 Python 一起關掉
    setsid nohup uv run story-web --host 0.0.0.0 --port {{port}} > server.log 2>&1 < /dev/null &
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

# 預覽送給 AI 的完整提示詞（不會呼叫 AI）：just prompts、just prompts turn、just prompts --players 2、just prompts --genre 克蘇魯 opening
prompts *args:
    @uv run python -m story.preview {{args}}

# 評估 AI 寫得好不好（會呼叫真的 API，改了提示詞之後手動跑）：just eval、just eval reveal agency、just eval --runs 5
eval *args:
    @uv run python -m story.evals {{args}}

# 全部測試（可以加 pytest 參數，例如 just test -k room）
test *args:
    uv run pytest {{args}}

# 刪除除錯紀錄（*.log.jsonl 等），不會動到存檔
clean-logs:
    rm -fv story_log.jsonl saves/*.log.jsonl
