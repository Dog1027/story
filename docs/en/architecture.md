# Architecture

English | [繁體中文](../zh-TW/architecture.md)

For anyone new to the project: read this page and you'll know where things are and where a new feature belongs. What each function does is described at the top of each file and in each function's docstring, so it isn't repeated here.

## In one sentence

**The AI tells the story; the program keeps the memory and the rules.** Each turn the AI only *proposes* narration and changes (wounds, items, how many key points a turtle soup guess hit), and the program checks them before they enter the game state.

Using any game works like calling an LLM: send in a line of text, get a reply back.

```python
core = AdventureCore(api_key, players=["Ming", "Hua"], save_path=…)
reply = core.start()                    # Asks whether to continue if there's a save, otherwise how to start
reply = core.send_as("Ming", "climb up")  # The turn advances only once everyone has acted
reply.narration, reply.choices, reply.characters …
```

## Three layers, stacked from the inside out

```
shells/   Shells: the web page, lobby and rooms, what to show when       Only use names exported by core and games
games/    Games: adventure, soup (turtle soup)                          Side by side; only use core
core/     Core: the flow every game shares, the reply format,          Doesn't know which games exist
          calling the AI, saves
```

| Folder | Main files |
|---|---|
| `core/` | `team.py`: `TeamGame`, the flow every game shares (the team, continuing saves, collecting everyone's actions, restarting, playing again). `reply.py`: `Reply`, the one reply format every game sends to the shells. `ai.py`: calling Gemini. `saves.py`, `prompts.py` (reading text files), `vocab.py` (game vocabulary), `evals.py` (the shared part of evals) |
| `games/adventure/` | `game.py`: `AdventureCore`. `engine.py` ties together `rules.py` (the rules, pure functions), `prompting.py` (building prompts) and the AI calls. `models.py` holds the save format and the AI's response formats. `genres/` holds the genre packs. `evals.py` holds the `just eval` scenarios. `tools/` holds dev tools not used while playing: `samples.py` is a sample story shared by `preview.py` (`just prompts`) and `evals.py` |
| `games/soup/` | `game.py`: `SoupCore`. `judge.py` is the AI judge and puzzle writer, `puzzles/` the puzzle bank, `evals.py` the `just eval soup` scenarios |
| `shells/` | `rooms/` (the server side): `lobby.py` and `room.py`, the lobby and rooms; a room holds one game's core, runs it with `runner.py` (in a background thread, telling everyone how it's going) and times turns with `countdown.py`. They don't know which games exist. `screen/` (one per browser tab): `client.py`, the flow of what to show when; `view.py`, the methods an interface implements (`View`); `premise.py`, the rules of the setup form dialog. It doesn't know about rooms. The two only meet through `connection.py`. `web/`: the web server (`server.py`) and the browser page (`static/`); `web/hosting.py` is the one place that hands the lobby the games in `GAMES`, the API key, the shared call limit and where saves go. `setup.py`: asks for the language and API key on first launch |

Tests enforce these rules (`tests/test_shells.py`): if the core imports a game, games import each other, a shell uses an internal module, or `rooms/` and `screen/` import each other (or `rooms/` imports the games), the tests fail.

## Where a new feature goes

| What changes | Where |
|---|---|
| A flow every game needs | `core/` |
| One game's rules or facts | That game's folder |
| The order and timing people see (choices appear after the narration, the countdown starts once everyone has read) | `shells/screen/client.py` |
| The looks | `shells/web/` |

**Adding a game**: add a folder under `games/`, write a subclass of `TeamGame` (`title` is its name, `description` a line about it), and register it in `GAMES` in `games/__init__.py`. The host's game picker lists it automatically. If it has eval scenarios, register its `evals.py` in `SCENARIOS` in `games/evals.py` (a test checks every game in `GAMES` is registered); the core, the other games and the shells don't change.

## How the shells know what to show

Shells only read the fields of `Reply` and don't know which game is being played:

- `phase` drives the flow: `ask_continue` (found a save) → `setup` (starting: a free-text setup form when the game sends `form` (`SetupForm`: default text, genre menu, suggestion; the adventure's story premise), otherwise a choice dialog over `choices`) → `playing` → `ending` → `ended`. `confirm_restart` confirms starting over. `ask_continue`, `setup` and `confirm_restart` are `HOST_PHASES`: only the host answers them
- `narration`, `choices`: the story and the choices; with `inputs` (turtle soup's ask and guess), choices switch the input mode
- `characters`: the status bar; the game supplies the words to show and the warnings
- `ending`: the ending, the epilogue (the truth in turtle soup), the journey record

Each field is described in `core/reply.py`. The message formats between the lobby, rooms and browser are described at the top of `shells/rooms/lobby.py`, `shells/rooms/room.py` and `shells/web/view.py`.

## Text

All text is markdown, kept with the layer that uses it, one folder per language (`zh-TW/`, `en/`) with the same sections:

- For the AI: `prompts/<lang>/`. How to change the adventure's prompts: `games/adventure/prompts/README.md`
- For players: `ui/<lang>/`

To add a language, copy `en/` in each layer and translate it.

Each section starts with `## name`, `{name}` is a variable the program fills in, and `<!-- -->` comments are notes for whoever writes the text and are never sent to the AI. Tests check that every language has the same sections and variables and that every text the code uses exists.

## Customizing

Paths are under `src/story/`.

| To change | Where |
|---|---|
| How the AI writes (rules, length, pacing) | `games/adventure/prompts/`, starting with its [README](../../src/story/games/adventure/prompts/README.md) |
| How strict the turtle soup judge is | `games/soup/prompts/` |
| Genre packs | `games/adventure/genres/` (personal ones in `~/.config/story/genres/`); see [Writing a genre pack](genres.md) |
| Turtle soup puzzles | `games/soup/puzzles/`, one file per puzzle (personal ones in `~/.config/story/puzzles/`) |
| The model, the timeout | `MODEL`, `REQUEST_TIMEOUT` in `core/ai.py` |
| Story length, the earliest turn it can end, the minimum turns per act | `TARGET_TURNS`, `MIN_ENDING_TURN`, `MIN_ACT_TURNS` in `games/adventure/rules.py` |
| Wound scores, the death threshold, healing times | `games/adventure/rules.py` |
| Most players on a team | `MAX_PLAYERS` in `core/reply.py` |
| Number of rooms, most AI calls per minute | `MAX_ROOMS` in `shells/rooms/lobby.py`, `AI_PER_MINUTE` in `shells/web/hosting.py` |
| Colors, typing speed | `shells/web/static/`: `style.css`, and `CHAR_DELAY` in `app.js` |

## Files created while running

They always go in the project folder (`settings.DATA_DIR`), whatever folder the program is started from.

| File | Contents |
|---|---|
| `saves/team-<names>.<game>.json` | Each team's save for each game (several names are joined with `+`) |
| `saves/team-<names>.<game>.log.jsonl` | One line per turn: players' actions, the changes the AI proposed and the program applied, and each AI call's kind (`kind`), seconds and token usage. Look here when things feel slow or results look odd |
| `server.log` | Output of the server started by `just start` |
| `~/.config/story/config.toml` | The language and API key |

## Tests and other commands

| Command | What |
|---|---|
| `just test` | All tests (about 10 seconds) |
| `just lint` | Check the code with ruff (likely bugs, import order); `just lint --fix` fixes what it can |
| `just prompts` | Preview the full prompts sent to the AI, without calling it |
| `just eval` | Run fixed scenarios with the real AI and check pacing, the reveal, not deciding for the player, genre tone, and the turtle soup judge (`just eval soup`); results go to `eval_results/` |
| `just clean-logs` | Delete the logs (`saves/*.log.jsonl`), never the saves |

Tests never connect to Gemini or touch your saves: fakes stand in for the AI (`tests/conftest.py`), and each test runs in a temp folder. Whether the real AI writes well is checked with `just eval`: scenarios live in each game's own `evals.py`, and `games/evals.py` gathers them through `SCENARIOS` and runs them.

On every push to GitHub, GitHub Actions runs `just lint` and `just test` automatically (`.github/workflows/test.yml`).

When the program hits an unexpected error (not a failed AI call), the core restores the turn from the save and lets players try again; the room has a last line of defence too, keeping the room and connections. The full error goes to the server's output (`server.log` under `just start`).
