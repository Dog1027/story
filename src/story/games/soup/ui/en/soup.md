<!--
Text turtle soup shows players: choosing a puzzle, the scenario, each round's results, the status bar, the ending, puzzle bank problems.
Same format as the prompts: each section starts with "## name"; the name is how the program finds it and must not change. {name} is a variable filled in by the program.
-->

<!-- ---------- Turtle soup ---------- -->

## title
<!-- The game's name: the host's choice in the room (start_game in shells) and room cards in the lobby -->
turtle soup

## busy
<!-- Shown while the judge (the AI) rules on the round -->
The judge is thinking

## description
<!-- A line about the game: under its name when the host picks a game -->
The AI is the judge while everyone asks yes/no questions to uncover the truth behind a strange scenario.

## ask_puzzle
<!-- Asks the host how to get a puzzle (the two choices are soup_from_bank and soup_from_ai) -->
Turtle soup: where should the puzzle come from?

## from_bank
Draw one from the puzzle bank

## from_ai
Have the AI write one

## ai_failed
<!-- The AI failed to write a puzzle; draw from the bank instead. Variable: {error} -->
The AI couldn't write a puzzle ({error}), so here's one from the puzzle bank.

## ai_unsound
The AI's puzzle didn't pass the check, so here's one from the puzzle bank.

## no_puzzles
The puzzle bank is empty and the AI couldn't write one. Try again later, or add puzzles to ~/.config/story/puzzles/.

## stage_make
writing a puzzle

## stage_check
checking the puzzle

## no_ruling
The judge didn't give a complete ruling this round

## surface
<!-- The scenario, shown at the start and when loading. Variables: {title}, {surface}, {points} number of key points -->
"{title}"

{surface}

Each round, choose "Ask" for a yes/no question, or "Guess" to state your theory. State all {points} key points to solve it.

## ask
Ask

## ask_hint
Write a question that can be answered yes or no

## guess
Guess

## guess_hint
Write your guess: what happened, and why

## give_up
Give up

## give_up_confirm
<!-- The confirm box after pressing give up: the question and the two buttons -->
Give up? If everyone gives up in the same round, the truth is revealed.

## give_up_yes
Give up

## give_up_no
Keep guessing

## line_ask
<!-- A question in a round's results. Variables: {name}, {text}, {answer} -->
{name} asked: {text}
→ {answer}

## line_guess
<!-- A guess. Variables: {name}, {text}, {hit} points stated, {total} key points, {hits} (soup_hits, blank when none was hit) -->
{name} guessed: {text}
→ {hit}/{total} key points{hits}

## hits
<!-- Which key points were hit (only those, so players know what's still missing). Variable: {points} the key points, joined with list_sep -->
: {points}

## line_give_up
<!-- Variable: {name} -->
{name} chose to give up

## line_away
<!-- Variable: {name} -->
{name} didn't act this round

## give_up_pending
(The truth is revealed only when everyone gives up in the same round)

## solved
<!-- Variable: {names} -->
{names} stated every key point!

## all_gave_up
Everyone gave up. Here's the truth.

## you
<!-- The name in the results when playing alone -->
You

## won
<!-- The ending title. Variable: {names} -->
{names} solved it

## won_together
<!-- Several people solved it in the same round. Variable: {names} -->
{names} solved it together

## revealed
Nobody solved it: the truth

## reveal
<!-- The ending: before showing the truth, ask for Enter -->
Press Enter for the truth

## record
<!-- The ending record. Variables: {turns}, {questions}, {guesses}, {points} key points (one per line) -->
{turns} rounds, {questions} questions, {guesses} guesses.

Key points:
{points}

## status_questions
<!-- Status bar: questions asked. Variable: {count} -->
{count} asked

## status_best
<!-- Status bar: the most key points stated in a guess. Variables: {hit}, {total} -->
{hit}/{total} found

## memory
<!-- /state: the scenario and earlier rounds. Variables: {title}, {surface}, {rounds} -->
"{title}"
{surface}

{rounds}

## memory_round
<!-- Variables: {turn}, {text} -->
Round {turn}
{text}

## memory_empty
(No questions yet)

## help
Turtle soup: the judge knows the truth; you only know the scenario. Each round everyone acts at once:
- Ask: a yes/no question; the judge answers "Yes", "No", "Irrelevant" or "Yes and no"
- Guess: state your theory; the judge tells everyone how many key points it got
- Give up: when everyone gives up in the same round, the truth is revealed
State every key point to solve it; if several people do it in the same round, they win together.

## puzzle_missing
<!-- A puzzle file is malformed. Variable: {sections} -->
missing sections: {sections}

## puzzle_points
<!-- Variables: {min}, {max} -->
needs {min}-{max} key points
