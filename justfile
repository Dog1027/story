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

# 全部測試（可以加 pytest 參數，例如 just test -k party）
test *args:
    uv run pytest {{args}}

# 刪除除錯紀錄（*.log.jsonl 等），不會動到存檔
clean-logs:
    rm -fv story_log.jsonl party_log.jsonl saves/*.log.jsonl
