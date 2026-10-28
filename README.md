# Story

English | [繁體中文](README.zh-TW.md)

A text game whose story Gemini writes as you play, in the browser on a phone or a computer, alone or with friends. Two games:

- **Adventure**: the AI writes the story, and every choice you make shapes it
- **Turtle soup**: the AI is the judge while everyone guesses the truth behind a strange scenario

The design rule is **the AI tells the story, the program keeps the memory and the rules**: the AI only *proposes* narration and changes, and the program checks them before they enter the game state. So the AI can't kill you in one line or forget what's in your bag, while reckless choices bring real wounds.

## Features

- **A real story structure**: before the opening, a hidden four-act outline and a truth the players don't know are planned; acts one and two plant clues, act three reveals it, and the story ends in about 30 turns with an epilogue
- **Body and mind conditions**: no hit points, just conditions like "torn right arm (severe)" or "fear (moderate)" that heal over in-game time; only accumulated physical wounds can kill
- **Timed mode**: decide before the countdown runs out when things get tense
- **Long-term memory**: every turn is kept word for word; only the oldest parts are summarized once the story gets long
- **Genre packs**: wuxia, Cthulhu, ghost story, creatures, cyberpunk, picked automatically or by you; write your own (see [docs/en/genres.md](docs/en/genres.md))
- **Alone or with friends**: a team of 1 to 4, each with their own conditions, bag, and choices; the turn moves on once everyone has acted. Open rooms in the lobby, with several rooms playing at once
- **Turtle soup**: each round everyone asks a yes/no question or guesses the truth at the same time and sees everyone's results; state every key point to solve it, and those who do in the same round win together. Puzzles come from the bank or are written by the AI

## Playing

You need [uv](https://docs.astral.sh/uv/) (installs Python 3.14 and the packages), a [Gemini API key](https://aistudio.google.com/apikey) (free), and ideally [just](https://github.com/casey/just).

| Command | Without just | What |
|---|---|---|
| `just serve` | `uv run story --host 0.0.0.0` | Start the server, port 8080 by default (`just serve 9000` to change it) |
| `just start` / `just stop` | | Start or stop the server in the background (output in `server.log`) |

The first run asks for a language and an API key, saved to `~/.config/story/config.toml` (editable). Environment variables win: `STORY_LANG` (`zh-TW`, `en`), `GEMINI_API_KEY`.

Open `http://<this computer's IP>:8080` (locally <http://localhost:8080>) on a phone or a computer. The AI uses the host's key; players only enter a name.

- Your name is your character, and the browser remembers it. Open a room with the same group and names to continue your last save
- Open or join a room in the lobby (up to 10 rooms, 4 players each). The host picks adventure or turtle soup
- Anyone can act first; the turn moves on once everyone has. A short notice at the top right shows when others act
- If you disconnect, come back with the same name to return to your room; coming back from the same browser replaces the old connection
- All rooms share one key: the free tier allows 15 AI calls a minute, so busy times queue

> ⚠ There's no HTTPS and names have no passwords (anyone who knows a name can continue that team's save). Use it only on a network you trust.

### Controls

Click a choice (or press its number), or type your own action. Press Enter to speed up text. `/help` lists commands and `/state` shows what the program remembers, or use the ⋯ menu. Every turn saves automatically to `saves/team-<names>.<game>.json`.

## How it's built

```
src/story/
├── core/        Core: the flow every game shares, the reply format, calling the AI, saves
├── games/       Games, side by side, each built on the core
│   ├── adventure/   Adventure: rules, prompts, genre packs
│   └── soup/        Turtle soup: the judge, prompts, puzzles
└── shells/      Shells: client.py is the flow players see, lobby.py and room.py the rooms, web/ the server and page
```

Layers stack from the inside out: the core doesn't know which games exist, games don't depend on each other or know about screens, and shells only handle display and input. Using any game works like calling an LLM: send in a line of text, get a reply back. The architecture is explained in [docs/en/architecture.md](docs/en/architecture.md), and plans are in [docs/en/roadmap.md](docs/en/roadmap.md).

## Customizing

| To change | Look in |
|---|---|
| How the AI writes (rules, length, pacing) | `src/story/games/adventure/prompts/`, starting with its [README](src/story/games/adventure/prompts/README.md) (in Chinese) |
| How strict the turtle soup judge is | `src/story/games/soup/prompts/` |
| Story length, wound rules | `src/story/games/adventure/rules.py` |
| The model | `src/story/core/ai.py` |
| Genre packs | `src/story/games/adventure/genres/` (personal ones in `~/.config/story/genres/`) |
| Turtle soup puzzles | `src/story/games/soup/puzzles/`, one file per puzzle (personal ones in `~/.config/story/puzzles/`) |
| Colors, typing speed | `src/story/shells/web/static/` |

All text is markdown, in each layer's own `prompts/<lang>/` (for the AI) and `ui/<lang>/` (for players). To add a language, copy `en/` in each layer and translate it.

## Tests and evals

| Command | What |
|---|---|
| `just test` | All tests (about 10 seconds); never calls Gemini or touches your saves |
| `just prompts` | Preview the full prompts sent to the AI, without calling it |
| `just eval` | Run fixed scenarios with the real AI and check pacing, the reveal, not deciding for the player, genre tone, and the turtle soup judge (`just eval soup`); results go to `eval_results/` |

Each turn's AI proposals, what the program applied, and how long each call took are logged to `saves/team-<names>.<game>.log.jsonl`. `just clean-logs` deletes only the logs, not saves.
