# Common commands. Run `just` to list them all.

# List every command
default:
    @just --list --unsorted

# The web server: everyone opens rooms in the lobby, alone or with friends (open to the local network)
serve port="8080":
    uv run story --host 0.0.0.0 --port {{port}}

# Start the web server in the background (restarts it if already running); output goes to server.log
start port="8080":
    #!/usr/bin/env bash
    set -euo pipefail
    uv run story --setup-only  # First launch: ask for the language and API key first (can't ask in the background)
    just stop
    # setsid: the server gets its own process group, so just stop can stop uv and the Python under it together
    setsid nohup uv run story --host 0.0.0.0 --port {{port}} > server.log 2>&1 < /dev/null &
    echo $! > .server.pid
    sleep 2
    if kill -0 "$(cat .server.pid)" 2>/dev/null; then
        echo "Server started in the background: http://localhost:{{port}} (output: server.log, stop: just stop)"
    else
        echo "The server failed to start:"
        cat server.log
        rm -f .server.pid
        exit 1
    fi

# Stop the background web server
stop:
    #!/usr/bin/env bash
    if [ -f .server.pid ] && pid=$(cat .server.pid) && kill -0 "$pid" 2>/dev/null; then
        kill -TERM -- "-$pid"
        for _ in $(seq 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
        echo "Server stopped"
    fi
    rm -f .server.pid

# Preview the full prompts sent to the AI (doesn't call the AI): just prompts, just prompts turn, just prompts --players 2, just prompts --genre <genre name> opening
prompts *args:
    @uv run python -m story.games.adventure.preview {{args}}

# Evaluate how well the AI writes (calls the real API; run by hand after changing prompts): just eval, just eval reveal agency, just eval --runs 5
eval *args:
    @uv run python -m story.evals {{args}}

# Every test (pytest arguments work too, e.g. just test -k room)
test *args:
    uv run pytest {{args}}

# Check the code for likely bugs and import order (ruff); just lint --fix fixes what it can
lint *args:
    uv run ruff check src tests {{args}}

# Delete debug logs (*.log.jsonl), never saves
clean-logs:
    rm -fv saves/*.log.jsonl
