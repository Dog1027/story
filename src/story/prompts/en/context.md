<!--
The story content sent to the AI with every turn (everything except the instructions), in this order:
premise, mode, genre guide, summary (rarely change) → story log (only grows at the end) → key events, story progress, game state (change with the story).
What rarely changes goes first, so Gemini's automatic cache (which only matches an identical beginning) hits as much as possible. The instructions from turn.md come after this.
-->

## premise
<!-- Variable: {premise} -->
# Premise
{premise}

## mode
<!-- Variable: {mode} is mode_timed or mode_normal from turn.md -->
# Mode
{mode}

## genre_guide
<!-- The chosen genre pack, fixed for the whole story. Variables: {name}, {guide} -->
# Genre: {name} (writing guide)
{guide}

## summary
<!-- The long-term summary (when the story log gets too long, the oldest part is compacted into it). Variable: {summary} -->
# Summary of the story so far
{summary}

## history
<!-- The story text. Variable: {entries} is each turn's history_entry, separated by a blank line -->
# Story log (oldest first)
{entries}

## history_entry
<!-- One turn: the narration at that time and what the player did after reading it. Variables: {narration}, {label} (turn_label), {action} -->
[Narration] {narration}
[{label}] {action}

## history_last
<!-- The last turn's action is this turn's action, listed separately in the instructions, so only the narration goes here. Variable: {narration} -->
[Narration] {narration}

## turn_label
Player

## key_events
<!-- Variable: {events} (one event per line) -->
# Key events
{events}

## status
<!-- The game state: facts the program keeps, as JSON. Variable: {json} -->
# Game state
{json}

## overall
<!-- "Overall" in the game state: lets the AI know how far the protagonist is from death. Variables: {level}, {score}, {death} -->
{level} (body wounds {score}/{death}, death at {death}; light=1 moderate=2 severe=4)

## status_keys
<!-- Field names in the game state JSON, one "code: name shown to the AI" per line. The codes are used by the program and must not change; only change the part after the colon -->
turn: Turn
time: Time
body: Body
mind: Mind
overall: Overall
inventory: Inventory
flags: Established facts
characters: Characters
name: Name
state: State

## status_empty
<!-- What the game state shows when something is empty, same format as above -->
time_unknown: unknown
body: unhurt
mind: steady
inventory: (empty)
flags: (none)
dead: dead

## condition
<!-- One condition in the game state. Variables: {name}, {severity} (light, moderate, severe) -->
{name} ({severity})

## clock
<!-- The in-game time, shown only to the AI. Variables: {day}, {period} (dawn, dusk…), {hour}, {minute} (numbers; :02d pads to two digits) -->
Day {day}, {period} ({hour:02d}:{minute:02d})
