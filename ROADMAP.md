# Roadmap

Directions for improvement gathered from comparing the project with today's mainstream harnesses (Claude Code, the Agent SDK and so on), plus other open items. Finished items are deleted; see the git history for what's been done.

## Directions

### 1. Multiple languages

Every layer's prompts and interface text (`prompts/<lang>/`, `ui/<lang>/`) exist in Traditional Chinese and English, as do the genre packs and the turtle soup puzzle bank, chosen with `STORY_LANG`. Still to do for English:

- **Actually play a game in English** and see whether the writing rules, pacing and length limits suit English.

### 2. More turtle soup

The web version has turtle soup (`games/soup/`). What could come next:

- **Evals**: `just eval soup` already checks how guesses are judged (with guesses from real games). Could add: whether asking the same question several times gets consistent answers, and whether answers leak the truth
- **Quality of AI puzzles**: puzzles are written with `gemini-3.5-flash`, and about half pass the strict check; failures fall back to the puzzle bank. The puzzle-writing prompt could be tuned, or given a few good puzzles as examples
- **More puzzles**: the bank has 8 per language
- **Hints**: when the group is stuck for too long, let them ask for a hint (e.g. the direction of one key point)

### 3. A new game: detective

Rooms could also offer "Detective". Before the opening the AI writes a case; players freely write what to investigate ("check the fingerprints on the knife handle", "ask the butler where he was at ten last night"), reason from the clues they find, and finally name the culprit and explain the motive and method. Several people solving a case together is just how rooms already work.

**It's a lot like the adventure, and most of it carries over as is**: narration, free actions, turns, facts and key events, in-game time, memory compaction, saves, and the room's "advance once everyone has acted" pacing need no changes. The hidden truth (`twist`) and clues (`clues`) in today's outline are the seed of a case file; the difference is that the truth is never revealed on its own, and players have to dig it out. The flow both games share is already in `core/team.py` (`TeamGame`), and the detective would be another subclass of it.

**To write from scratch**:

- **The case file** (replaces the outline; kept by the program and hidden from players): the culprit, motive, method, and the true timeline; each suspect's story, alibi, and what they hide or lie about; where each key clue is and how it's found; a few red herrings
- **Two sources of cases, both needed**:
  - Written by the AI on the spot: after writing, another AI call checks fairness (can every conclusion be reached from the clues, could the culprit actually have done it), rewriting if not
  - Curated cases: one folder per case like genre packs, for steady quality
- **Each turn**: the AI writes the investigation results from the case file and reports which clues were uncovered this turn (by number, so it can't invent new key clues), which the program records in a detective's notebook. Important testimony from suspects is recorded as facts, so it stays consistent
- **Hints when stuck**: when too many turns pass without a new clue, remind the AI to make some clue easier to notice (like today's "this act is dragging" pacing reminder)
- **The accusation**: the culprit is picked from the list of suspects and checked directly by the program; motive and method are written freely and judged by another AI call against the case file's points. The ending depends on how much was right: case fully solved, right person for the wrong reasons, or an innocent accused
- **The screen**: the detective's notebook (clues found, suspects, places visited), in `/state` or a side panel
- **Evals** (`just eval`): the opening doesn't leak the culprit, suspects' stories stay consistent, the case is fair (the clues are enough to reach the answer), and judging the accusation is neither too lenient nor too strict

The hardest part is getting the AI to write a sound, fair case. The lesson from turtle soup puzzles: flash-lite's often contradict themselves, so they need a stronger model to write them and a strict check afterwards.

### 4. The reply format: fields only one game uses

The shells only read `Reply`'s fields, so whenever a game needs the shells to show something new, `Reply` gets a field. Some already belong to only one game:

- The adventure: `premise_default`, `suggestion`, `genre`, `genres` (the new story dialog); the shells also have `PremiseForm` and the web's premise dialog just for it
- Turtle soup: `inputs` (ask, guess, give up)

With two games this is simplest; with more, `Reply` turns into a pile of fields each used by one game. If the detective game also needs its own setup form or input modes, turn them into a generic description then: for example, describe a setup form as "fields, buttons, menus" that the game fills in, have the shells draw one generic form, and move the adventure's premise dialog onto it too. Not now, so the abstraction isn't shaped by a single example.

## Other open items

- [ ] **Narration too short**: `schema.md` asks for 150-300 characters a turn, but `just eval` mostly gets 116-145. Could change the wording in `schema.md` or `system.md` (e.g. state "at least 150 characters"), then compare before and after with `just eval`.
- [ ] **Evals with several characters**: one of them falls, not deciding for other players, whether the focus lands on the chosen person. `just eval` only has single-character scenarios for now.
- [ ] **Evaluate a whole game's pacing**: today's `just eval` scenarios each write one turn. Let the AI pick choices and play a whole game, then check how many turns each act took, which turn the truth came out, which turn it ended, and whether anyone died early. A game is about 30-40 calls, about 3 minutes on the free tier; run it now and then, not as part of the usual `just eval`.
- [ ] **Try the web version on a real phone**: Chinese input method candidate selection, touch scrolling, the keyboard not popping up after picking a choice, dialogs with a text box (name, story premise) staying above the keyboard when they come up from the bottom, the choice area not jumping in height, no stale cached files after an update. Headless Chrome only simulated phone sizes.
- [ ] **Play a web game with the real AI**: progress text while generating, long passages of narration, the timed countdown, the ending revealed in parts.

## Not planned

- **Subagents, multiple agents**: each turn writes one passage; splitting it across agents would only be slower and more expensive.
- **Letting the AI change state directly with tools** (checking the bag itself, deciding wounds itself): having the program guard life and death, wounds and the bag is this project's core design, and handing that to the AI would remove the guardrails.
