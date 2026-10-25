# Story

English | [繁體中文](README.zh-TW.md)

An AI text adventure you can play in the terminal or the browser, alone or online with friends. Gemini writes the story as you go, and every choice you make shapes where it leads.

The design principle is **the AI tells the story, the program keeps the memory and the rules**: each turn the AI only *proposes* what happens and how your condition changes, and the program checks it before anything goes into the game state. So the AI can't kill you off with one sentence or forget what's in your bag. In return, reckless choices bring real wounds, and wounds that pile up to a fatal level will kill you.

## Features

- **A real story structure**: before the opening, the AI plans a hidden four-act outline, along with a truth the player doesn't know. Clues are planted in the first two acts and the truth comes out in the third. The program tracks progress and controls the pacing, so the story reaches its ending in about 30 turns without ending early, followed by an epilogue and a title for your ending
- **Body and mind**: no hit points. Instead you have conditions like "torn right arm (severe)" or "fear (moderate)". Only body wounds that add up to a fatal level kill you; mind conditions affect how you act
- **Hidden in-game time**: wounds heal over time, but severe ones need treatment in the story
- **Timed mode**: when things get tense, you have to decide before the countdown runs out
- **Long-term memory**: the full text of every turn is kept, so the AI sees the whole story; only when it grows past a limit is the oldest part compacted into a summary
- **Genre packs**: Wuxia, Cthulhu, Ghost Story, Monsters & Aliens, and Cyberpunk, each with its own writing guide, opening ideas, and twist ideas. One is picked automatically to fit your premise, or you choose. You can write your own genre pack without touching code; see [docs/genres.md](docs/genres.md) (in Chinese)
- **Random openings**: a new story starts from an opening drawn from the genre packs; press "Another one" to draw again, or "Inspire me" to have the AI invent a new one
- **Play alone or together**: every game is a team of 1 to 4 characters, each played by one person with their own conditions, inventory, and choices. Alone, the story speaks to you as "you"; with friends, the turn advances once everyone has acted. On the web, everyone joins the web page from their own phone or computer, opening rooms or joining friends' rooms in the lobby; several rooms can play at once

## Getting started

You need:

- [uv](https://docs.astral.sh/uv/): installs Python 3.14 and the dependencies for you
- A Gemini API key: get one free at [Google AI Studio](https://aistudio.google.com/apikey)
- [just](https://github.com/casey/just) (recommended): shortcuts for common commands. Without it, use the `uv run …` commands in the table below

```bash
just play
```

The first time it runs, it asks you four things: the language, your Gemini API key, and, for the terminal version, a color theme and your character's name. The answers are saved in `~/.config/story/config.toml`, so you won't be asked again. You can edit that file directly:

```toml
language = "en"         # or "zh-TW"
api_key = "your key"
theme = "tokyo-night"
name = "Alex"            # your character in the terminal version
```

Environment variables take precedence over the file: `STORY_LANG`, `GEMINI_API_KEY`.

**Language**: the language you choose the first time sticks. To switch temporarily, put `STORY_LANG=zh-TW` (or `en`) in front of a command, e.g. `STORY_LANG=zh-TW just serve`. The story, the interface, and the genre packs all switch; everyone on the same server uses the same language.

## Ways to play

| Command | Without just | What it is |
|---|---|---|
| `just play` | `uv run story` | Terminal version |
| `just plain` | `uv run story --plain` | Plain-text version (just input/print) |
| `just serve` | `uv run story-web --host 0.0.0.0` | Web version: everyone enters a lobby and opens rooms, to play alone or as a team |
| `just start` / `just stop` | | Start / stop the web server in the background (restarts it if already running; output goes to `server.log`) |

The web server uses port 8080 by default (`just serve 9000` to change it). Open `http://this-computer's-IP:8080` in a browser; on the same computer that's <http://localhost:8080>. Phones and computers use the same page, which follows the system's light or dark mode.

### Web: the lobby and rooms

The web version calls the AI with the host's API key (entered the first time you start the server); players only enter a name.

- Enter a name when you join (unique on the whole server); your name is your character in the story
- You start in the lobby: open a new room, or join a room that's still waiting for players. Playing alone is just a room of your own. Several rooms can play at once, so different groups can team up separately (at most 10 rooms, 4 players per room)
- Whoever opens the room is the host, who chooses "Start game", the premise, whether to continue a save, and whether to start over. Once the host sends the premise, everyone sees it, and you all enter the story together when the AI finishes the opening
- In the game everyone sees their own choices and can act in any order; others are notified when someone acts, and the turn advances once everyone has acted. In timed mode the room runs a single countdown, which starts only after everyone has finished reading
- If you disconnect, come back with the same name and you go straight back to your room. If everyone else has acted and you're still away, your character "steps away" for that turn
- If the host leaves, the next person in the room becomes host
- When the story ends you return to the room's waiting screen and can play again, or choose "Leave room" to go back to the lobby (you can also type `/leave` during a game). A room closes when nobody is left in it
- All rooms share one API key: the free tier allows 15 AI calls per minute, so with many rooms calls queue up, and the screen shows "queued"

> ⚠ The web server accepts connections from other computers on the same network. There's no HTTPS yet, so traffic is sent in plain text, and names have no password: anyone who knows the names can continue that team's save. Only use it on a network you trust.

## Controls

**Terminal**

| Key | Action |
|---|---|
| ↑↓, numbers, mouse | Pick a choice |
| Just type | Do your own thing instead of a listed choice |
| Enter (while text appears) | Speed up; press again to show it all |
| Mouse wheel | Scroll the story. You can scroll back while text is still appearing; scroll to the bottom to follow new text again |
| F2 | Choose a color theme (moving up and down previews it; remembered) |
| `/` or Ctrl+P | Open the command menu |
| Ctrl+T | See what the program remembers |
| Ctrl+R | Start over |
| F1 | Help |
| Ctrl+Q | Save and quit |

**Web**: tap a choice, or write an action in the input box at the bottom (on a computer you can also choose with ↑↓ in the input box and press Enter). While text appears, tap the story or press Enter to speed up, and again to show it all. The ⋯ menu at the top right has "What the program remembers", "Start over", help, and appearance (light/dark).

**Saves**: the game saves after every turn, so you can pick up where you left off.

| How you play | Save |
|---|---|
| Terminal | `save.json` in the current folder |
| Web | `saves/team-name.json`, or `saves/team-Alex+Sam.json` for a group (the same group can continue when they open a room again) |

## How it's built

```
src/story/
├── core/       Core: game rules, calling the AI, saves
├── prompts/    What the AI is told (markdown), one folder per language; edit without touching code
├── ui/         What players see (markdown), one folder per language
├── genres/     Genre packs, one folder per language
└── shells/     Shells
    ├── client.py   The flow shared by interfaces for human players; LocalClient plays on this computer
    ├── room_client.py  The same flow for the web: RoomClient joins the lobby and rooms
    ├── textual/    The terminal interface
    ├── web/        The web server and page
    ├── lobby.py    The web lobby: names and the room list
    ├── room.py     A web room: one game per room
    ├── connection.py  In-memory connections between the lobby, rooms, and browser tabs
    └── plain.py    The plain-text version
```

Three layers, each with one job:

- **Core** (`core/`): works like calling an LLM. Send in a line of text, get a reply back (narration, choices, conditions…). It knows nothing about screens, so a new shell such as a Discord bot only has to handle display and input. The plain-text version is the simplest example
- **Shared layer** (`shells/client.py`, `shells/room_client.py`): when to show what. What to ask when starting, choices appearing only after the text finishes typing, the ending arriving in steps, how the web version connects to the lobby and rooms. Both the terminal and web versions use it
- **Interfaces** (`textual/`, `web/`): only decide how things look

Where a new feature goes: changes the game's outcome or facts → core; changes the order, timing, or flow of what a person sees → shared layer; changes the look → interface.

Every file is described in [docs/files.md](docs/files.md), and plans are in [docs/roadmap.md](docs/roadmap.md) (both in Chinese).

## Customizing

Common settings are constants at the top of each file, or separate text files:

- **Story length, wound and healing rules**: `src/story/core/rules.py`; **the model**: `src/story/core/ai.py`
- **How the AI writes** (writing rules, narration length, pacing reminders, the epilogue…): the markdown files in `src/story/prompts/en/`. Start with [src/story/prompts/README.md](src/story/prompts/README.md) (in Chinese), which maps "what you want to change → where"
- **Interface text**: the markdown files in `src/story/ui/en/`
- **Genre packs**: `src/story/genres/en/`; see [docs/genres.md](docs/genres.md) for how to write one
- **Terminal color theme and typing speed**: `src/story/shells/textual/style.py`. Condition colors are derived from the theme's success, warning, and error colors
- **Web colors, fonts, and typing speed**: the color settings at the top of `src/story/shells/web/static/style.css`, and the constants at the top of `app.js`

**Adding a language**: add a folder under `src/story/prompts/` and `src/story/ui/` with the full set of files (copy `en/` and translate), plus genre packs under `src/story/genres/`, then select it with `STORY_LANG`. The tests check that every language has the same files, sections, and variables.

## Tests and evals

| Command | What it does |
|---|---|
| `just test` | All tests (about 30 seconds). They never contact Gemini and never touch your saves or API key. Run them after a change to make sure nothing broke |
| `just prompts` | Preview the full prompts sent to the AI, without calling it. E.g. `just prompts turn`, `just prompts --players 2` |
| `just eval` | Have the AI actually write turns from fixed scenarios, then check them with code and an AI judge: does it end too early, does the third act reveal the truth, does it make decisions for the player, do reckless choices cost something, does the style fit the genre. Calls the real AI; a full run takes six or seven minutes on the free tier. Results are saved in `eval_results/` so you can compare before and after a prompt change |

What each test file checks is in [docs/files.md](docs/files.md#測試-tests).

## Debugging

What the AI proposed each turn and what the program actually applied are logged (one line per turn), so you can trace why a condition changed oddly:

| How you play | Log |
|---|---|
| Terminal | `story_log.jsonl` |
| Web | `saves/team-name.log.jsonl` (one per team, as above) |

Each line's `calls` lists every AI call in that period: the kind (`kind`: `genre` picking a genre, `arc` planning the outline, `turn` a story turn, `rewrite` rewriting an ending that came too early, `death` falling to wounds, `epilogue`, `suggest` inspire me, `compaction` memory compaction), how long it took (`seconds`), and the token counts Gemini reports: sent (`prompt`), of which cached (`cached`), output (`output`), and thinking (`thinking`). If you're waiting a long time, this shows where the time goes.

Logs only grow; a 30-turn story is about 50 KB. Run `just clean-logs` to delete them; it never touches saves.
