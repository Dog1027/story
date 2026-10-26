<!--
Text shared by the shells: the shared layer (story/shells/client.py), the web lobby and rooms (lobby.py, room.py), name checks (players.py),
the web server (web/__init__.py), and the plain-text shell (plain.py). Same format as core.md.
-->

<!-- ---------- First-launch setup (story/setup.py) ---------- -->

## language_name
<!-- This language's name, shown when choosing a language -->
English

## setup_key
A Gemini API key is needed; get one free at https://aistudio.google.com/apikey. It's saved in ~/.config/story/config.toml.

## setup_key_prompt
Gemini API key (hidden while typing; press Enter to skip for now): 

## setup_name
What's your character's name? (You can change it later in ~/.config/story/config.toml)

## setup_name_prompt
<!-- Press Enter to use default_name -->
Name (press Enter for "Hero"): 

## default_name
<!-- The character's name in the terminal version when no name is set -->
Hero

## setup_theme
Choose a color theme for the terminal version (you can change it in the game with F2):

## setup_theme_prompt
<!-- Variable: {default} is the theme used if you just press Enter -->
Enter a number (or press Enter for {default}): 

<!-- ---------- Shared layer ---------- -->

## mode_timed
<!-- The mode shown on the same line as the turn in the status bar -->
Timed mode

## mode_normal
Normal mode


## ask_missing_key
No Gemini API key found.

## ask_new_key
The API key is invalid or lacks permission. Please enter it again.


## busy
<!-- Shown while waiting for the AI. Variable: {progress} (busy_progress, or blank) -->
Writing the story{progress}…

## busy_progress
<!-- Variable: {progress}, e.g. "planning the outline" -->
: {progress}

## ask_continue
<!-- The confirm box when a save is found. Variable: {notice} (found_save in core.md) -->
{notice}

Continue?

## wait_epilogue
Press Enter for the epilogue

## wait_ending
Press Enter to see the ending

## story_over
The End

## hint_input
<!-- The input box hint -->
↑↓ to choose, or write your action

## hint_others_acted
<!-- Web: you haven't acted yet, but others have. Variable: {names} -->
{names} acted. ↑↓ to choose, or write your action

## hint_waiting
<!-- Web: you've already acted. Variable: {names} -->
Waiting for {names}…

## list_sep
, 

<!-- ---------- Lobby and rooms (lobby.py, room.py) ---------- -->

## lobby_title
<!-- The lobby's title (in the status bar, followed by the people in the lobby) -->
Lobby

## room_create
Open a new room

## room_entry
<!-- A room waiting for players. Variables: {host}, {count}, {max} -->
Join {host}'s room ({count}/{max})

## rooms_hint
<!-- The lobby's input hint -->
Join a room, or open one (even to play alone)

## rooms_full
<!-- Variable: {max} -->
All rooms are taken (at most {max}). Please wait for a game to finish.

## room_gone
That room has closed.

## room_title
<!-- The title of a room's waiting screen. Variable: {host} -->
{host}'s room

## room_hint_host
Wait for friends, or start the game

## leave_room
<!-- A choice on the waiting screen; during a game you can also type /leave -->
Leave room

## queued
<!-- While waiting for the AI: the shared call limit is used up, so the call is queued -->
queued (everyone shares one API key)

<!-- ---------- Notices in a room ---------- -->


## room_lost
Lost the connection to the game room.

## session_replaced
<!-- The same browser came back from another tab or reconnected: the old tab shows this -->
You entered the game from another tab or device, so this one has left.

## room_disconnected
Lost the connection to the game room. Please reload the page.

## lobby_waiting_host
<!-- Variable: {host} -->
Waiting for {host} (the host) to start…

## start_game
<!-- The host's choice in the lobby -->
Start game

## room_name_taken
That name is already taken. Please choose another.

## room_members_only
<!-- Variable: {players} -->
A game is in progress; only team members ({players}) can rejoin.

## room_full
<!-- Variable: {max} -->
The room is full (at most {max} players).

## room_back
<!-- Variable: {name} -->
{name} is back.

## room_left
<!-- Variable: {name} -->
{name} went offline.

## host_setting_up
The host is setting up the story. Please wait.

## wait_host_story
<!-- Variable: {host} -->
Waiting for {host} (the host) to set up the story.

## wait_host_start
<!-- Variable: {host} -->
Waiting for {host} (the host) to start the game.


## host_only_restart
Only the host can start over.

## server_key_invalid
The server's Gemini API key is invalid or lacks permission. Please tell whoever runs the server.

<!-- ---------- Names ---------- -->

## name_empty
Please enter a name.

## name_too_long
<!-- Variable: {max} -->
Names can be at most {max} characters.

## name_bad_chars
Names may only contain letters, numbers, underscores, and hyphens.

<!-- ---------- Web server (what the person running it sees in the terminal) ---------- -->

## server_full
<!-- Variable: {max} -->
The server is full ({max} people online). Please try again later.

## server_description
Play Story in the browser

## server_host_help
Address to listen on; 0.0.0.0 lets other computers connect (default: this computer only)


## server_no_key
The web server calls the AI with the host's API key: run uv run story-web once in a terminal to enter it, or set the GEMINI_API_KEY environment variable.

## server_open_warning
⚠ Other computers can connect. There's no HTTPS yet, so traffic (names, the story) is sent in plain text and names have no password; only use this on a network you trust.



## server_started
<!-- Variables: {host}, {port} -->
Server running at http://{host}:{port}  Press Ctrl+C to stop.

<!-- ---------- Plain-text shell ---------- -->

## plain_ask_key
Gemini API key (hidden while typing): 

## plain_bye
Saved. See you next time.
