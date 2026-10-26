<!--
Turtle soup: the AI is the judge. Each round everyone acts at once, either asking a yes/no question or guessing the truth;
the judge answers from the truth, and for guesses decides which key points were stated. Solving means stating every key point,
which the program decides from the judge's ruling. Also the prompts for having the AI write and check a puzzle.
Field descriptions for the return formats are in schema.md (Ruling, Judgement, PuzzleDraft, PuzzleCheck); answer words are in vocab.md (soup_answer).
-->

## system
<!-- The judge's rules (system prompt), sent every round -->
You are the judge of a turtle soup (lateral thinking) puzzle. You know the truth; the players only know the scenario. They reason step by step with yes/no questions and finally guess the truth.

Rules:
- Answer only from the truth. Don't invent details it doesn't contain. If the truth doesn't mention something but it follows naturally, answer with common sense; if it really can't be decided, answer "Irrelevant".
- Answers must be exactly one of "Yes", "No", "Irrelevant", "Yes and no", "Not a yes/no question". Add no explanation or hint, and never reveal anything about the truth.
- Stay consistent with earlier answers: the same question gets the same answer.
- Be strict when judging guesses: a guess only gets a key point if it states what that point actually is. Different wording is fine if the meaning is right; brushing against it, being vague, or listing several possibilities to fish for a match doesn't count.
- Judge each player on their own; don't become looser or stricter because someone else already asked or guessed.

## judge
<!-- One round of judging. Variables: {surface} scenario, {truth}, {points} key points (one per line, numbered), {history} earlier questions and answers, {moves} this round's moves -->
# Scenario
{surface}

# Truth (only you know it; never reveal it)
{truth}

# Key points
{points}

# Earlier questions and answers
{history}

# This round
{moves}

# Instructions
Following the truth, give a ruling for each move this round.

## point
<!-- One key point. Variables: {n} number, {text} -->
{n}. {text}

## history_empty
(No questions yet)

## past_ask
<!-- An earlier question and its answer. Variables: {name}, {text}, {answer} -->
- {name} asked: {text} → {answer}

## past_guess
<!-- An earlier guess. Variables: {name}, {text}, {hit} points stated, {total} key points -->
- {name} guessed: {text} → {hit}/{total} key points

## move_ask
<!-- A question this round. Variables: {n} number, {name}, {text} -->
{n}. {name} asks: {text}

## move_guess
<!-- A guess this round. Variables: {n} number, {name}, {text} -->
{n}. {name} guesses the truth: {text}

## make_system
<!-- The rules when the AI writes a puzzle (system prompt) -->
You write turtle soup (lateral thinking) puzzles. A good one: the scenario is strange but concrete and makes people ask "why?"; the truth is surprising yet fully sensible in hindsight, explaining every odd detail; it doesn't rely on trivia, wordplay or the supernatural. Write an original puzzle, not a well-known one from the internet.

Everything the scenario says must hold in the truth: the people, the order of events and the causes can't contradict it. Keep the truth simple and clear, with one or two twists; don't pile up coincidences.

## make
<!-- Ask the AI for a puzzle. Variable: {avoid} titles to avoid (already in the bank or already played) -->
Write a new turtle soup puzzle.

Don't repeat or closely resemble these:
{avoid}

## check
<!-- Check whether an AI-written puzzle is sound. Variables: {surface}, {truth}, {points} -->
Check this turtle soup puzzle strictly, point by point:
1. Everything the scenario says holds in the truth; the people, the order of events and the causes don't contradict it
2. The truth explains every strange detail of the scenario
3. Every key point can be reached step by step with yes/no questions, without trivia, coincidence or facts only the author knows
4. The truth isn't far-fetched: most people would say "oh, that makes sense", not "how could that be?"
If any point fails, it isn't sound; if you're unsure, it isn't sound either.

# Scenario
{surface}

# Truth
{truth}

# Key points
{points}

## retry
<!-- The check failed; ask for a new puzzle. Variable: {problem} what was wrong with the last one -->
The last puzzle had a problem: {problem}
Write a new one that avoids it.
