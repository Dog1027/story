<!--
The "Story progress" block: the hidden outline and reminders, shown only to the AI. The program decides from the outline and turn count which lines to add each turn.
-->

## header
<!-- Variable: {lines} is the items below, one per line -->
# Story progress (hidden from the player)
{lines}

## goal
<!-- Variable: {goal} -->
Goal: {goal}

## act
<!-- One act of the outline. Variables: {number}, {name}, {milestone}, {mark} (act_current, act_done, or blank) -->
Act {number} "{name}": {milestone} {mark}

## act_current
← current

## act_done
✓ done

## endings
<!-- Variable: {endings} (separated by endings_sep) -->
Possible endings: {endings}

## endings_sep
<!-- Separator between the possible endings -->
; 

## act_just_started
<!-- This act hasn't run its minimum number of turns. Variable: {left} is how many more turns to build it up -->
Pacing: this act has just begun; build it up for at least {left} more turn(s). Don't reach the milestone this turn; set milestone_reached to false.

## ending_locked
<!-- The story can't end yet. Variable: {min_ending_turn} -->
Ending rule: the story can end no earlier than turn {min_ending_turn}, and only after entering the final act. Until then always set game_over to false and don't write an ending.

## overdue
<!-- Past the planned length. Variable: {target_turns} -->
Wrap-up: the story has run past the planned {target_turns} turns. Write the climax and ending within the next turn or two, and set game_over to true when it's reached. Don't open new subplots or crises.

## final_act
Wrap-up: this is the final act. Drive toward the climax and ending, and don't open new subplots; when the last milestone is reached, write the ending and set game_over to true.

## act_too_long
Pacing: this act has dragged on too long. This turn must bring a turn of events that clearly moves toward the current milestone.

## twist_hidden
<!-- Acts one and two: the hidden truth. Variable: {twist} -->
Hidden truth (revealed only in act three; until then don't give it away or hint at it too obviously): {twist}

## twist_clues
<!-- Acts one and two: the clues to plant. Variable: {clues} (one clue per line) -->
Clues (work them in naturally at good moments during the first two acts, one at a time, without explaining what they mean):
{clues}

## twist_reveal
<!-- Act three: reveal the truth. Variable: {twist} -->
This act must reveal the hidden truth: {twist}

## twist_reveal_clues
<!-- Act three: on the line after twist_reveal. Variable: {clues} -->
When revealing it, echo the clues planted earlier:
{clues}

## twist_known
<!-- Act four: the truth is out. Variable: {twist} -->
The revealed truth: {twist}
