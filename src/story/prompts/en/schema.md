<!--
Field descriptions for the AI's response format: sent along with the format so the AI knows what goes in each field.
Rules like narration length, number of choices, and condition name length are changed here.
Section names are "Format.field", matching the fields in story/core/models.py, and must not change. Field types and allowed values (e.g. severity can only be light, moderate, severe) are set by the program.
-->

<!-- ---------- ConditionChange: one condition reported by the AI (a wound or an emotion) ---------- -->

## ConditionChange.name
Condition name, 1-4 words, e.g. "broken right leg", "poisoned", "fear"

## ConditionChange.kind
body = wounds, exhaustion, poison, illness; mind = fear, panic, despair, anger

## ConditionChange.severity
light = doesn't hinder action; moderate = clearly hinders action; severe = life-threatening

<!-- ---------- CharacterUpdate: one character's changes this turn ---------- -->

## CharacterUpdate.name
The character's name, exactly as in "Party"

## CharacterUpdate.choices
2-4 action choices for this character, one sentence each; empty if the character is dead

## CharacterUpdate.conditions_changed
This character's new conditions, or existing conditions whose severity changed

## CharacterUpdate.conditions_removed
Names of this character's existing conditions that healed or faded

## CharacterUpdate.items_gained
Names of items this character gained this turn

## CharacterUpdate.items_lost
Names of items this character lost or used up this turn

<!-- ---------- StoryBeat: the response each turn ---------- -->

## StoryBeat.game_over
Decide before writing: does the story reach its natural ending this turn

## StoryBeat.narration
This turn's narration, including the result of every character's action, 100-200 words (up to 260 with several characters); in the second person (\"you\") when there is only one character, by name when there are several

## StoryBeat.character_updates
One entry for each character in the party, in the same order as "Party"

## StoryBeat.time_passed
How much time this turn took: instant = dodging a blow; moment = a conversation, a search; a while = travelling, about an hour; overnight = sleeping

## StoryBeat.start_time_of_day
The current time of day; only used for the opening or when the time is still "unknown"

## StoryBeat.time_limit
In timed mode, the seconds to react when things are urgent; otherwise 0

## StoryBeat.milestone_reached
Whether this turn reached the current act's milestone in "Story progress"

## StoryBeat.flags_set
Newly established long-term facts, e.g. "made an enemy of the gatekeeper"; usually empty

## StoryBeat.key_event
A major event that changes the course of the story, one sentence; an empty string on most turns

<!-- ---------- Act: one act of the outline ---------- -->

## Act.name
The act's title, 2-5 words

## Act.milestone
The key event that must happen before this act ends, one sentence, concrete enough to tell when it has happened

<!-- ---------- StoryArc: the hidden story outline ---------- -->

## StoryArc.goal
The protagonist's core goal or the mystery to solve in this story, one sentence

## StoryArc.twist
The hidden truth: unknown to the player at first, revealed in the third act, and it overturns how the player understands their situation. Surprising but fair; it must not decide whether a player character lives or dies. One sentence

## StoryArc.clues
2-3 clues: details that can surface naturally in acts one and two, in the surroundings, an NPC, an item, or a document. They seem unrelated at the time, but in hindsight all point to the truth. One sentence each

## StoryArc.acts
Exactly four acts: setup (establish the situation), development (go deeper, meet obstacles), turn (reveal the hidden truth; revealing it is the milestone), resolution (climax and ending)

## StoryArc.endings
2-3 possible endings, depending on the player's choices, one sentence each

<!-- ---------- GenrePick: when the genre is "Auto", the genre the AI picks ---------- -->

## GenrePick.genre
Copy the name of the genre in the "Genre catalog" that best fits the premise; leave it empty if none fits

<!-- ---------- Epilogue: the epilogue after the story ends ---------- -->

## Epilogue.title
The ending's title, 2-6 words, like a chapter title in a novel, e.g. "The Lighthouse Keeper", "The Letter Never Sent"

## Epilogue.text
The epilogue, 100-170 words: look back on the key choices of the protagonist's journey, convey the aftertaste of the ending, and you may mention what later became of other characters

<!-- ---------- Turtle soup: Ruling and Judgement are the judge's ruling on this round ---------- -->

## Ruling.move
The number of this round's move (as listed under "This round")

## Ruling.answer
The answer to a question, judged against the truth. If the question has nothing to do with the truth, choose "Irrelevant"; if it's half right, choose "Yes and no"; if it can't be answered yes or no, choose "Not a yes/no question". Guesses must fill this in too: always "Irrelevant"

## Ruling.matched
For a guess, which key points it got right (their numbers). It only counts if the guess states what the key point actually is; brushing against it or a lucky hint doesn't count. Leave empty for questions

## Judgement.rulings
One entry for each move this round, in the order listed under "This round"

<!-- ---------- Turtle soup: a puzzle written by the AI, and the check of it ---------- -->

## PuzzleDraft.title
The puzzle's title, 2-5 words

## PuzzleDraft.surface
The scenario: 40-90 words describing a strange situation that makes people ask "why?". Only what can be seen; don't hint at the reason

## PuzzleDraft.truth
The truth: 80-150 words explaining what really happened, so that every strange detail in the scenario makes sense

## PuzzleDraft.key_points
2-4 key points, one sentence each: the facts a guess must state to solve the puzzle. Together they are the core of the truth; don't list details

## PuzzleCheck.ok
true if the puzzle is sound and fair: the truth explains every strange detail of the scenario, the key points can be reached step by step with yes/no questions, and nothing depends on trivia only the author knows

## PuzzleCheck.problem
If it isn't sound, what's wrong (a sentence or two); empty if it is
