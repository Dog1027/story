<!--
Single-player instructions for each turn, placed at the very end of the turn's prompt.
The parts that differ in multiplayer are in party_turn.md.
-->

## mode_timed
<!-- The "# Mode" block: timed mode. Variables: {min}, {max} are the range of seconds -->
Timed mode: when things are urgent, use time_limit to give the player {min}-{max} seconds to react.

## mode_normal
<!-- The "# Mode" block: normal mode -->
Normal mode: time_limit is always 0.

## timeout_action
<!-- Timed mode ran out and the player did nothing: this sentence stands in for the player's action in the story log (system.md says how to handle it) -->
(Time ran out: you hesitated too long and didn't react in time)

## opening
<!-- The opening -->
# Instructions
This is the opening of the story. Introduce the scene and the protagonist's situation, and give the first set of choices.

## action
<!-- A normal turn. Variable: {action} is the player's action this turn -->
# The player's action this turn
{action}

# Instructions
Narrate the result of this action and move the story forward.

## early_ending_retry
<!-- When the AI declares an ending too early, this is added after the original prompt to ask for a rewrite -->
# Note
Your last reply ended the story too early. The story cannot end yet: rewrite this turn without an ending, set game_over to false, bring in a new development, and give choices.

## death
<!-- The program ruled the protagonist dead of their wounds, but the AI's narration still has them alive: ask the AI to write the death. Variable: {narration} is the narration just written -->
# What just happened
{narration}

# Instructions
The protagonist's wounds are now fatal. Continue from the narration above and write the ending in which the protagonist dies of their wounds. Leave choices empty and set game_over to true.

## epilogue
<!-- The epilogue after the story ends. Variables: {narration} is the last narration, {look_back} is epilogue_look_back below (multiplayer uses the one in party_turn.md) -->
# The last part of the story
{narration}

# Instructions
The story is over. Write an epilogue that closes the journey, and give this ending a title. {look_back}Do not open any new storyline.

## epilogue_look_back
Look back on the key choices the protagonist made and the price they paid; if the protagonist died, show the mark they left behind. 
