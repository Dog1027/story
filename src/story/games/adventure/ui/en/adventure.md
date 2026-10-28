<!--
Text the adventure shows players: notices, /help, /state, the ending record, labels for changes between turns, and genre pack problems.
Same format as the prompts: each section starts with "## name"; the name is how the program finds it and must not change. {name} is a variable filled in by the program.
-->

## title
<!-- The game's name: the host's choice in the room (start_game in shells) and room cards in the lobby -->
adventure

## busy_label
<!-- Shown while the AI writes (progress may follow, e.g. ": planning the story outline") -->
Writing the story

## description
<!-- A line about the game: under its name when the host picks a game -->
The AI writes the story as you play, and every choice shapes it. Pick a genre, or play against the clock.

<!-- ---------- Lists and punctuation ---------- -->

## condition
<!-- A condition with its severity. Variables: {name}, {severity} -->
{name} ({severity})

## condition_change
<!-- A condition whose severity changed. Variables: {name}, {old}, {new} -->
{name} ({old}→{new})

<!-- ---------- Choices (players can also type these words) ---------- -->

## genre_auto
<!-- Special genre choice: the AI picks a genre pack from the premise. Also accepted after /genre -->
Auto

## genre_none
<!-- Special genre choice: no genre pack -->
None

<!-- ---------- The genre menu in the new story dialog ---------- -->

## genre_option
<!-- One item in the genre menu. Variable: {name} -->
Genre: {name}

## genre_auto_option
Genre: Auto (picked from the premise)

## genre_none_option
Genre: None

## genre_auto_hint
Automatically picks a genre pack that fits the premise, or none if nothing fits.

## genre_none_hint
No genre pack; written the ordinary way.

<!-- ---------- Notices ---------- -->

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

<!-- ---------- Errors ---------- -->

## epilogue_failed
<!-- Variable: {error} -->
Couldn't write the epilogue: {error}

## no_suggestion
The AI didn't come up with an opening. Please try again.

## no_epilogue
Couldn't write the epilogue.

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
