<!--
Instructions for each turn, placed at the very end of the turn's prompt; also the protagonists listed when planning the outline, and the sentences that stand in for a player's action.
-->

## mode_timed
<!-- The "# Mode" block: timed mode. Variables: {min}, {max} are the range of seconds -->
Timed mode: when things are urgent, use time_limit to give players {min}-{max} seconds to react.

## mode_normal
<!-- The "# Mode" block: normal mode -->
Normal mode: time_limit is always 0.

## timeout_action
<!-- Timed mode ran out and a player did nothing: this sentence stands in for their action in the story log (system.md says how to handle it) -->
(Time ran out: hesitated too long and didn't react in time)

## away_action
<!-- An online player who disconnected: this sentence stands in for their action in the story log -->
(Stepped away for now; no action this turn)

## cast
<!-- The protagonists when planning the outline. Variable: {names} is every character's name -->
# Protagonists (each played by one player)
{names}

## names_sep
<!-- Separator when listing several characters' names -->
, 

## second_person
<!-- When the team has one character, placed after the mode in the story context (the same all game, so caching is unaffected). Variable: {name} -->
# Point of view
The team has one character, "{name}". Always address them in the second person ("you"); never write their name, and don't use "he" or "she" for them.

## focus
<!-- With several characters, one in rotation gets a little more weight each turn, so the AI doesn't keep making the same person the lead. Variable: {name} -->
# Focus
This turn, give "{name}" a little more description and weight in the choices.

## opening
<!-- The opening -->
# Instructions
This is the opening of the story. Introduce the scene and each character's situation, and give each character their own first set of choices.

## action
<!-- A normal turn. Variable: {actions} is each character's action this turn (one per line, see action_entry) -->
# Each character's action this turn
{actions}

# Instructions
Narrate the results of these actions and move the story forward.

## action_entry
<!-- One character's action. Variables: {name}, {action} -->
{name}: {action}

## early_ending_retry
<!-- When the AI declares an ending too early, this is added after the original prompt to ask for a rewrite -->
# Note
Your last reply ended the story too early. The story cannot end yet: rewrite this turn without an ending, set game_over to false, bring in a new development, and give choices.

## death
<!-- The program ruled a character dead of their wounds: ask the AI to write a short scene of them falling. Variables: {narration} is the narration just written, {who} is who fell -->
# What just happened
{narration}

# Instructions
{who}'s wounds are now fatal. Continue from the narration above and write a short scene (under 70 words) of {who} collapsing from their wounds. Output only the narration itself.

## epilogue
<!-- The epilogue after the story ends. Variable: {narration} is the last narration -->
# The last part of the story
{narration}

# Instructions
The story is over. Write an epilogue that closes the journey, and give this ending a title. Look back on the key choices each character made and the price they paid; for characters who died, show the mark they left behind. Do not open any new storyline.
