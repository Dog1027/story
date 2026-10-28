<!--
Text the core shows players that every game uses: choices, notices, errors. Each game's own text is in story/games/<game>/ui/.
Same format as the prompts: each section starts with "## name"; the name is how the program finds it and must not change. {name} is a variable filled in by the program.
-->

<!-- ---------- Lists and punctuation ---------- -->

## list_sep
<!-- Separator when joining several items into one line (conditions, items, names) -->
, 

<!-- ---------- Choices (players can also type these words) ---------- -->

## choice_continue
Continue

## choice_new_game
New game

## choice_confirm
Confirm

## choice_cancel
Cancel

## choice_play_again
Play again

<!-- ---------- Notices ---------- -->

## found_save
<!-- Variables: {turn}, {premise} -->
Found a save (turn {turn}): {premise}

Continue?

## resumed
<!-- Variable: {premise} -->
Loaded save: {premise}

## answer_continue
Enter 1 (continue) or 2 (new game).

## answer_confirm
Enter 1 (confirm) or 2 (cancel).

## answer_play_again
Enter 1 to play again.

## confirm_restart
Give up your progress and start over?

## unknown_command
<!-- Variable: {command} -->
There's no {command} command. Type /help for help.

## enter_action
Type an action, or a number to pick a choice.

## no_story_yet
No story has started yet.

## character_fallen
Your character has fallen.

## already_acted
You've already acted this turn. Waiting for the others.

## team_size
<!-- Variables: {min}, {max} -->
A team needs {min} to {max} players with different names.

<!-- ---------- Errors ---------- -->

## key_invalid
The server's Gemini API key is invalid or lacks permission. Please tell whoever runs the server.

## failed
<!-- An AI call failed. Variables: {hint} (failed_turn, failed_ending, or blank), {error} -->
{hint}Something went wrong: {error}

## failed_turn
This turn didn't go through; please choose your action again. 

## failed_ending
<!-- Wrapping up the ending after the story ended failed: it isn't retried automatically (the same error would just repeat); players decide when to try again -->
The ending isn't ready yet; send anything to try again. 

## timeout
Gemini took too long to respond, couldn't be reached, or the connection broke off. Please try again later.

## unexpected
<!-- The program itself failed (not an AI call): the turn has been restored and can be tried again -->
a problem in the program itself (details are in the server's server.log)

## unparsable
<!-- The AI's response was malformed. Variable: {reason} -->
Couldn't read the model's output ({reason}). Try a different action.

## no_content
no content

<!-- ---------- /help and /state ---------- -->

## help_title
Help

## memory_title
What the program remembers
