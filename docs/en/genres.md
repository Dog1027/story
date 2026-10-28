# Writing a genre pack

English | [繁體中文](../zh-TW/genres.md)

Genre packs give different stories different flavors: wuxia has the air of the martial world, Cthulhu an unspeakable dread. If you can write markdown, you can add a genre by adding a folder, with no code changes.

The structure follows [Agent Skills](https://code.claude.com/docs/en/skills) (Claude Code's skills): one folder per genre, each with a `GENRE.md`.

## Where they live

| Location | Use |
|---|---|
| `src/story/games/adventure/genres/<lang>/` | Built-in genres, managed with the project (everyone gets them once committed) |
| `~/.config/story/genres/<lang>/` | Personal genres, only on your own computer |

`<lang>` is `zh-TW` (Traditional Chinese) or `en` (English), chosen with `STORY_LANG` like the prompts, with a full set of genre packs per language. The English packs aren't word-for-word translations: naming material uses names English readers can pronounce, and openings and twists are written as sentences that read naturally in English. The genres don't have to match across languages, and a pack may exist in only one language.

Personal packs win when `name` is the same, so to adjust a built-in genre's style, put a pack with the same `name` in your personal folder (the folder name can differ) instead of editing the built-in one. The web version reads the folders on the computer running the server.

## What's in the folder

```
wuxia/            Folder names are in English (fewer problems across platforms and tools)
├── GENRE.md      Required: settings fields + writing guidance
├── premises.md   Optional: opening ideas (used by random openings, "Another one" and "Suggest one")
├── names.md      Optional: material for names of people, places and groups
└── twists.md     Optional: twist ideas (for more varied act-three twists)
```

### `GENRE.md`

```markdown
---
name: Wuxia
description: Feuds of the martial world, rival sects, chivalry and revenge. For stories of duels, pursuits, hunts for secret manuals, escort missions, and debts of gratitude.
---

## Style
……

## The world and common elements
……

## Clichés to avoid
……
```

- `name`: the genre's name, shown in the menu, e.g. "Wuxia". Defaults to the folder name.
- `description`: a sentence or two on what the genre is and what stories it suits. **This is what the AI goes by when "Auto" is chosen**, so describe the situations it fits. At most 200 words (characters in Chinese; the same below).
- Body: writing guidance for the AI, **sent every turn**, at most 2,000 words. Organize the headings however you like; the built-in genres use "Style, The world and common elements, Common set pieces, Pacing, Clichés to avoid".

### `premises.md`

One opening idea per line, optionally starting with `-`, at most 2,000 words. Used in two places:

- **Random openings**: when starting a new story, the premise used "if left blank" is drawn from here at random (from the chosen genre, or from every pack with "Auto"), and "Another one" redraws. So each one must work as a story premise on its own: second person, a sentence or two, giving who you are and your situation, and leaving a mystery or a danger.
- **"Suggest one"**: when this genre is picked, three of them are given to the AI at random as references (the AI writes a new one rather than copying).

### `names.md`

Material for names, nicknames, places and groups, in any format. Given to the AI when planning the outline and writing the opening. At most 2,000 words.

### `twists.md`

One twist idea per line, optionally starting with `-`, at most 2,000 words.

A story has four acts: setup, development, twist, resolution. When planning the outline, the AI first comes up with a "hidden truth" the players don't know, to be revealed in act three, and plans the clues the first two acts plant. The program draws three ideas from this file at random for the AI to adapt to the story (or to beat with a better one), so the same genre played many times doesn't always have the same twist.

```markdown
- The true culprit behind the massacre of the clan was not the rival family but the master the protagonist always revered; the "enemy" was trying to protect the protagonist.
- The peerless manual everyone is fighting over is a fake; the real art has long been hidden in a chant the protagonist memorized as a child.
```

A good twist **overturns how the players understand their situation** and makes sense in hindsight: write "who someone really is" or "what something was really for", not "a stronger enemy suddenly appears". Put the twist on NPCs, events, places or secrets of the past, **not "the protagonist was dead all along" or "the protagonist has been possessed"**: the program decides whether characters live or die from their wounds, and with several characters, the truth shouldn't rest on one player's character alone. No need for much detail; the AI adjusts people and specifics to the premise. Without this file the AI still designs its own twist, but it falls into clichés more easily.

## When each file is used

Like skills, things are only loaded when needed:

| Content | When the AI gets it |
|---|---|
| Name + description | When players choose "Auto": the AI gets the whole catalog at the start and picks one for the premise (before planning the outline, so the outline can use the genre too) |
| `GENRE.md` body | Once a genre is chosen, near the start of the prompt every turn for the whole game |
| `names.md` | Planning the outline and writing the opening |
| `twists.md` | Planning the outline (three drawn at random) |
| `premises.md` | Random openings and "Another one" (drawn directly, no AI involved); given to the AI as references when "Suggest one" picks this genre |

## Tips for guidance that works

- **Write concrete things, not abstract descriptions**: "write it like a wuxia novel" barely helps; the model already roughly knows what wuxia is. What works is specific vocabulary, character types, things that drive the plot, and common set pieces.
- **Connect to the game's mechanics**: the game has body and mind conditions, a bag, and timed mode. Tell the AI what causes which conditions in this genre, e.g. in Cthulhu "the more truth you see, the worse your mind gets", in wuxia "poison and internal injuries need a famous healer".
- **List the clichés to avoid**: the AI easily falls into the most common tropes, and naming them explicitly helps.
- **Keep it short**: the guidance is sent every turn, and too much of it dilutes the other rules. The built-in genres are about 350 words in English (about 500 characters in Chinese).

## Checking for mistakes

Genre packs with a bad format are skipped and never break the game. Run this in the project folder to see which genres were read, and which were skipped and why:

```bash
uv run python -c "from story.games.adventure.genres import load_genres; g, p = load_genres(); print(list(g)); print(*p, sep='\n')"
```
