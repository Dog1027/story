<!--
Multiplayer instructions for each turn (the parts that differ from single-player turn.md).
-->

## cast
<!-- The protagonists when planning the outline. Variable: {names} is every character's name -->
# Protagonists (multiplayer, each played by one player)
{names}

## names_sep
<!-- Separator when listing several characters' names -->
, 

## away_action
<!-- An online player who disconnected: this sentence stands in for their action in the story log -->
(Stepped away for now; no action this turn)

## focus
<!-- Each turn one character, in rotation, gets a little more weight, so the AI doesn't keep making the same person the lead. Variable: {name} -->
# Focus
This turn, give "{name}" a little more description and weight in the choices.

## opening
# Instructions
This is the opening of the story. Introduce the scene and each character's situation, and give each character their own first set of choices.

## action
<!-- Variable: {actions} is each character's action this turn (one per line, see action_entry) -->
# Each character's action this turn
{actions}

# Instructions
Narrate the results of these actions and move the story forward.

## action_entry
<!-- One character's action. Variables: {name}, {action} -->
{name}: {action}

## death
<!-- The program ruled a character dead of their wounds: ask the AI to write a short scene of them falling. Variables: {narration} is the narration just written, {who} is who fell -->
# What just happened
{narration}

# Instructions
{who}'s wounds are now fatal. Continue from the narration above and write a short scene (under 70 words) of {who} collapsing from their wounds. Output only the narration itself.

## epilogue_look_back
Look back on the key choices each character made and the price they paid; for characters who died, show the mark they left behind. 

## turn_label
<!-- The label of the action line in the story log (single-player uses turn_label in context.md) -->
Actions

## status
<!-- The multiplayer game state: every character's state, as JSON. Variable: {json} -->
# Party
{json}
