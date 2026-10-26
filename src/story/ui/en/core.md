<!--
Text the core shows players: notices, errors, /help, /state, the journey record, labels for turn changes, and the whole plain-text output.
Same format as story/prompts/: each section starts with "## name"; the name is how the program finds it and must not change. {name} is a variable filled in by the program.
-->

<!-- ---------- Lists and punctuation ---------- -->

## list_sep
<!-- Separator when joining several items into one line (conditions, items, names) -->
, 

## condition
<!-- A condition with its severity. Variables: {name}, {severity} -->
{name} ({severity})

## condition_change
<!-- A condition whose severity changed. Variables: {name}, {old}, {new} -->
{name} ({old}→{new})

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

## genre_auto
<!-- Special genre choice: the AI picks a genre pack from the premise. Also accepted after /genre -->
Auto

## genre_none
<!-- Special genre choice: no genre pack -->
None

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

## rerolled
Drew a different opening.

## mode_switched_timed
Switched to timed mode.

## mode_switched_normal
Switched to normal mode.

## genre_unknown
<!-- Variables: {choice}, {options} -->
There's no genre called "{choice}". Choose from: {options}

## genre_chosen
<!-- Variable: {choice} -->
Genre: {choice}

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

## epilogue_failed
<!-- Variable: {error} -->
Couldn't write the epilogue: {error}

## timeout
Gemini took too long to respond or couldn't be reached. Please try again later.

## no_suggestion
The AI didn't come up with an opening. Please try again.

## no_epilogue
Couldn't write the epilogue.

## unparsable
<!-- The AI's response was malformed. Variable: {reason} -->
Couldn't read the model's output ({reason}). Try a different action.

## no_content
no content

<!-- ---------- Progress while starting a new story (shown after "Writing the story") ---------- -->

## stage_genre
choosing a genre

## stage_arc
planning the outline

## stage_opening
writing the opening

<!-- ---------- Changes between turns ---------- -->

## change_new
New

## change_worse
Worse

## change_better
Better

## change_healed
Healed

## change_gained
Gained

## change_lost
Lost

<!-- ---------- /help and /state ---------- -->

## help_title
Help

## help
During the game: type a number to pick a choice, or write your own action.

/state      See what the program remembers
/restart    Start over
/help       Show this help

When starting a new story:
Send an empty line   Use the default premise
/suggest             Have the AI come up with an opening
/random              Draw a different opening from the genre packs (no waiting for the AI)
/timed on|off        Turn timed mode on or off (decide within a time limit when things get tense)
/genre name          Choose a genre (genre pack), or /genre Auto, /genre None

In timed mode the countdown is up to the shell, which sends /timeout when time runs out.

## memory_title
What the program remembers

## memory
<!-- Variables: {bags} (one line per person, see memory_bag, memory_named_bag), {flags}, {events} (one line per event, see memory_event), {summary}, {turns} -->
[Inventory]
{bags}

[Established facts]
  {flags}

[Key events]
{events}

[Long-term summary]
  {summary}

[Story log] {turns} turns of full text

## memory_bag
<!-- The inventory when there is one character. Variable: {items} -->
  {items}

## memory_named_bag
<!-- One person's inventory when there are several characters. Variables: {name}, {items} -->
  {name}: {items}

## memory_event
<!-- Variable: {event} -->
  - {event}

## memory_empty_bag
empty

## memory_no_flags
none

## memory_no_events
  (none)

## memory_no_summary
(none yet)

<!-- ---------- The journey record ---------- -->

## record
<!-- Variables: {turns}, {days} -->
{turns} turns over {days} days.

## record_alive
You reached the end of the story.

## record_dead
You fell on this journey.

## record_all_alive
Everyone reached the end of the story together.

## record_some_fallen
<!-- Variable: {names} -->
{names} fell on this journey; the others reached the end of the story.

## record_all_fallen
The whole team fell on this journey.

## record_events
<!-- Variable: {events} (one line per event, see record_event) -->
Along the way:
{events}

## record_event
<!-- Variable: {event} -->
• {event}

<!-- ---------- Plain-text output ---------- -->

## text_notice
<!-- Variable: {notice} -->
({notice})

## text_info
<!-- Variables: {title}, {body} -->
[{title}]
{body}

## text_suggested
Here's an opening. Send an empty line to start with it, or edit it and send.

## text_new_story
<!-- Variables: {mode} (text_mode_timed or text_mode_normal), {genre}, {premise} -->
A new story ({mode}, genre: {genre}). Type a premise, or send an empty line to use:
{premise}
(/random for another, /suggest to let the AI think of one, /timed to toggle timed mode, /genre to choose a genre)

## text_mode_timed
timed mode

## text_mode_normal
normal mode

## text_genres
<!-- Variable: {genres} -->
Genres: {genres}

## text_ending_title
<!-- Variable: {title} -->
─── {title} ───

## text_story_over
The End

## text_status
<!-- Variables: {turn}, {timed} (text_status_timed or blank), {conditions} -->
Turn {turn}{timed} | Condition: {conditions}

## text_status_timed
 (timed mode)

## text_warning
<!-- The warning when in danger. Variables: {level}, {conditions} -->
⚠ {level}  {conditions}

## text_character_line
<!-- One character, when there are several. Variables: {name}, {conditions} -->
{name} | {conditions}

## text_history_trimmed
(Earlier parts of the story were condensed into a summary; see /state)

## text_action
<!-- In the plain-text version when loading a save: one action in the earlier story. Variable: {action} -->
› {action}

## text_fallen
fallen

## text_changes
<!-- One group of changes. Variables: {label}, {items} -->
{label}: {items}

## text_changes_sep
<!-- Separator between groups of changes -->
   

## text_named_changes
<!-- One character's changes, when there are several. Variables: {name}, {changes} -->
{name}  {changes}

## text_send_for_epilogue
(The story is over. Send anything to see the epilogue.)

## text_actor
<!-- Variable: {name} -->
{name}'s turn:

## text_time_limit
<!-- Variable: {seconds} -->
({seconds} seconds)

<!-- ---------- Genre pack format problems (for people writing genre packs) ---------- -->

## genre_no_file
GENRE.md not found

## genre_no_header
GENRE.md must start with settings wrapped in ---

## genre_no_description
Missing description (the AI uses it to decide whether a story fits this genre)

## genre_long_description
<!-- Variable: {max} -->
The description is over {max} words

## genre_no_guide
GENRE.md has no writing guide

## genre_long_guide
<!-- Variables: {max}, {length} -->
The writing guide is over {max} words (currently {length})

## genre_long_extra
<!-- Variables: {file}, {max} -->
{file} is over {max} words
