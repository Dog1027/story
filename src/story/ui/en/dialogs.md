<!--
Dialog text, shared by the terminal version (story/shells/textual/dialogs.py) and the web version (story/shells/web/static/app.js).
Same format as core.md. For the web, the server sends this file together with web.md to the browser.
-->

<!-- ---------- Buttons ---------- -->

## leave
Leave

## ok
OK

## cancel
Cancel

## close
Close

## enter
Enter

## start
Start

## reroll
Another one

## suggest
Inspire me

## thinking
<!-- The "Inspire me" button while waiting for the AI -->
Thinking…

## play_again
Play again

## send
Send

<!-- ---------- API key ---------- -->

## key_placeholder
Paste your API key

## key_where
<!-- Where to get an API key. Variable: {link} (the address; a link on the web) -->
You can get one free at {link}. 

## key_link_text
<!-- The link text on the web -->
Google AI Studio

## key_not_stored
<!-- Web: the key isn't stored on the server -->
The key is only used for this session and never stored on the server; you'll enter it again next time.

## key_save
<!-- Terminal: whether to save it. Variable: {path} -->
Save to {path} and use it automatically next time

<!-- ---------- Name (web) ---------- -->

## name_title
Your name

## name_hint
Each name has its own save; come back with the same name to pick up where you left off.

## name_placeholder
e.g. Alex

<!-- ---------- New story ---------- -->

## premise_title
A new story

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

## premise_hint
Premise: edit it directly, or press "Another one" or "Inspire me"

## premise_placeholder
e.g. You are a courier delivering letters in a city at the end of the world…

## timed_option
Timed mode: when things get tense, decide within a time limit

## suggest_failed
The AI didn't come up with an opening

<!-- ---------- Ending ---------- -->

## ending_title
<!-- Variable: {title} -->
Ending: {title}

## story_over
The End

<!-- ---------- Notifications ---------- -->

## error_title
Something went wrong
