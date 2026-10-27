<!--
Game vocabulary: the program and save files use language-neutral codes (before the colon); what the AI sees, what it returns, and what players see are the words here (after the colon).
The options in the AI's response format (e.g. severity can only be light, moderate, severe) are these words, so schema.md and system.md must use the same words when they mention them.
The codes are used by the program and must not change or be removed; only change the part after the colon. Words within one section must not repeat.
-->

## severity
<!-- How bad a condition is, from mild to worst -->
light: light
moderate: moderate
severe: severe

## kind
<!-- What kind of condition -->
body: body
mind: mind

## time_span
<!-- How long a turn took (StoryBeat.time_passed in schema.md says what each word means) -->
instant: instant
moment: moment
while: a while
hours: hours
night: overnight
days: days

## time_of_day
<!-- Time of day: picked by the AI for the opening, then worked out by the program from the clock -->
dawn: dawn
morning: morning
noon: noon
afternoon: afternoon
dusk: dusk
evening: evening
late_night: late night

## level
<!-- The body's overall state (decided by the program from the wound score), from best to worst -->
healthy: unhurt
minor: lightly hurt
injured: injured
serious: badly hurt
dying: dying
dead: dead
