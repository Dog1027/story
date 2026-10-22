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

# 網頁版：每個人各自玩（host 用 0.0.0.0 開放其他電腦連線）
web host="127.0.0.1" port="8080":
    uv run story-web --host {{host}} --port {{port}}

# 線上多人：大家用瀏覽器一起玩同一局（需要伺服器的 GEMINI_API_KEY）
web-party host="127.0.0.1" port="8080":
    uv run story-web --party --host {{host}} --port {{port}}

# 開放區網連線的線上多人
lan port="8080":
    uv run story-web --party --host 0.0.0.0 --port {{port}}

# 全部測試（可以加 pytest 參數，例如 just test -k party）
test *args:
    uv run pytest {{args}}

# 略過會啟動真的伺服器的慢測試
test-fast *args:
    uv run pytest -m "not slow" {{args}}

# 刪除除錯紀錄（*.log.jsonl 等），不會動到存檔
clean-logs:
    rm -fv story_log.jsonl party_log.jsonl saves/*.log.jsonl
