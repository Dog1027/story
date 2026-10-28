# Prompts

English | [繁體中文](README.zh-TW.md)

This is all the text the adventure sends to the AI. To change how the AI writes the story, edit the files here; no code changes needed.

```
prompts/
├── en/             English (a full set of files with the same names)
└── zh-TW/          Traditional Chinese
    ├── system.md        Writing and game rules
    ├── schema.md        Field descriptions for the response format (narration length, number of choices…)
    ├── context.md       Each turn's story content: the format of the premise, story log and game state
    ├── turn.md          Each turn's instructions: the opening, a normal turn, the epilogue, death from wounds…
    ├── progress.md      Reminders in the story progress: pacing, when to end, the hidden truth and clues
    ├── plan.md          Starting a new story: picking a genre, planning the outline
    ├── premise.md       The default opening, "Suggest one"
    ├── memory.md        Memory compaction
    ├── vocab.md         Game vocabulary: light/moderate/severe, a moment/overnight…
    └── eval.md          The judge's criteria for evals (just eval); never used in the game
```

Genre packs (each genre's writing guidance, e.g. Wuxia or Cthulhu) aren't here but next door in `genres/<lang>/`; see `docs/en/genres.md` for how to write one. Text for players (notices, help) isn't here either but in `ui/<lang>/` next door (text every game uses is in `story/core/ui/`, the interface's in `story/shells/ui/`). Turtle soup's prompts are in `story/games/soup/prompts/`.

## What one call is made of

When writing a turn, the AI receives three things:

1. **Writing and game rules** (`system.md`): the same for the whole game.
2. **The response format**: which fields to fill and what goes in each (`schema.md`).
3. **This turn's content**, from top to bottom:
   - The story content (`context.md`): story premise → mode → genre guidance → long-term summary → story log → key events → story progress (`progress.md`) → game state
   - This turn's instructions (`turn.md`): the opening, a normal turn, the epilogue, or death from wounds

What rarely changes goes first and what changes goes later, so Gemini's automatic cache hits, which is faster and cheaper. Try not to disturb this order when editing.

**To see how it fits together**: run `just prompts`. It prints the full prompt for every kind of call using sample scenarios, without calling the AI.

```bash
just prompts                      # Every scenario
just prompts turn reveal          # Only "a normal turn" and "act three: revealing the truth"
just prompts --players 2 death    # A team of two characters, "falling from wounds"
just prompts --genre Cthulhu arc  # With a genre pack, the outline planning (genre names are in the current language)
```

## What to change, and where

| To change | File | Section |
|---|---|---|
| Style, narrative person, how different the choices are | `system.md` | The rules |
| How harsh wounds are, how dangerous reckless choices are | `system.md` | The "Choices must carry real costs" rules |
| Narration length, number of choices, length of condition names | `schema.md` | `StoryBeat.narration`, `CharacterUpdate.choices`, `ConditionChange.name` |
| Pacing: an act just started, dragging on, time to wrap up | `progress.md` | `act_just_started`, `act_too_long`, `final_act`, `overdue` |
| How to ask for a rewrite when the ending comes too early | `turn.md` | `early_ending_retry` |
| The hidden truth, how clues are planted, when it's revealed | `progress.md`, `plan.md` | `twist_*`, `arc` |
| How the outline is planned (four acts, possible endings) | `plan.md`, `schema.md` | `arc`, `StoryArc.*` |
| Instructions for the opening and a normal turn | `turn.md` | `opening`, `action` |
| The epilogue | `turn.md`, `schema.md` | `epilogue`, `Epilogue.*` |
| The scene of falling from wounds | `turn.md` | `death` |
| The line that stands in for a player when time runs out or they're away | `turn.md` | `timeout_action`, `away_action` |
| "Suggest one": its genres, settings and rules | `premise.md` | `genres`, `settings`, `rules` |
| The default story opening | `premise.md` | `default` |
| What memory compaction keeps | `memory.md` | `system` |
| Field names in the game state, how time is written | `context.md` | `status_keys`, `status_empty`, `clock` |
| How strict the turtle soup judge is, the standard for puzzles | `soup.md`, `schema.md` in `story/games/soup/prompts/` | `system`, `make_system`, `check`, `Ruling.*`, `PuzzleDraft.*` |
| Which words to use for game vocabulary such as severity and time of day (the AI returns them and players see them) | `vocab.md` | `severity`, `kind`, `time_span`, `time_of_day`, `level` (only change the part after the colon; if you do, also change the words mentioned in `schema.md` and `system.md`) |

## File format

- `<!-- -->` comments at the top and above each section are notes for you (when the section is used, which variables it has) and are **never sent to the AI**.
- In files with several sections, each starts with `## name`. **The name is how the program finds the section and must not change**; change the content below it.
- `{name}` is a variable the program fills in, e.g. `{left}` is how many more turns to build up and `{twist}` is the hidden truth. The variables each section can use are listed in its notes. No other braces may appear in the content.
- In "code: text" tables such as `status_keys`, only change the part after the colon.

## After editing

1. `just prompts` to see how it fits together.
2. `just test` to make sure nothing broke; a misspelled variable or a renamed section, for example, is pointed out by the tests.
3. Prompts are read when the program starts: run `just start` to restart the server.
4. `just eval` has the AI really write a few turns in fixed scenarios and checks whether it ends too early, reveals the truth in act three, decides for the player, makes reckless choices cost something, and fits the genre's style. It calls the real AI and takes about six or seven minutes on the free tier; to run only a few checks, use `just eval reveal agency`. Results are saved in `eval_results/` to compare with before the change.
5. Play a game to see how the AI does.

## Adding a language

Each language has a folder with **a full set of files and sections with the same names**, chosen with an environment variable:

```bash
STORY_LANG=en just start
```

There are `zh-TW` (Traditional Chinese) and `en` (English) so far. A new language needs a full set of text for every layer (the `prompts/<lang>/` and `ui/<lang>/` of the core, each game, and the shells); `just test` checks that every language has the same files, sections and variables as `zh-TW`. When you change one language's rules, the others usually need the same change.
