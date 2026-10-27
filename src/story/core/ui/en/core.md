<!--
Text the core shows players that every game uses: choices, notices, errors, shared plain-text formats. Each game's own text is in story/games/<game>/ui/.
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
The API key is invalid or lacks permission.

## failed
<!-- An AI call failed. Variables: {hint} (failed_turn, or blank), {error} -->
{hint}Something went wrong: {error}

## failed_turn
This turn didn't go through; please choose your action again. 

## timeout
Gemini took too long to respond or couldn't be reached. Please try again later.

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

<!-- ---------- Plain-text output ---------- -->

## text_notice
<!-- Variable: {notice} -->
({notice})

## text_info
<!-- Variables: {title}, {body} -->
[{title}]
{body}

## text_ending_title
<!-- Variable: {title} -->
─── {title} ───
