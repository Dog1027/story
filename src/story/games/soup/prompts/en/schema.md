<!--
Field descriptions for turtle soup's AI return formats, sent with the format to tell the AI what to put in each field.
Section names are "Format.field", matching the fields in story/games/soup/models.py; don't rename them.
-->

<!-- ---------- Turtle soup: Ruling and Judgement are the judge's ruling on this round ---------- -->

## Ruling.move
The number of this round's move (as listed under "This round")

## Ruling.answer
The answer to a question, judged against the truth. If the question has nothing to do with the truth, choose "Irrelevant"; if it's half right, choose "Yes and no"; if it can't be answered yes or no, choose "Not a yes/no question". Guesses must fill this in too: always "Irrelevant"

## Ruling.points
For a guess, one entry for every key point, in order, none missing; leave empty for questions

## PointCheck.point
The key point's number

## PointCheck.quote
Copy the sentence of the guess that speaks to this key point; leave empty if the guess doesn't mention it at all

## PointCheck.stated
Whether the quoted sentence states the core of this key point. The core meaning counts even if details and wording differ (key point "he is left-handed", guess "he writes with his left hand": true); missing the core fact doesn't (key point "she is allergic to pollen", guess "she felt unwell": false). Brushing against it, or having no matching sentence, is false

## Judgement.rulings
One entry for each move this round, in the order listed under "This round"

<!-- ---------- Turtle soup: a puzzle written by the AI, and the check of it ---------- -->

## PuzzleDraft.title
The puzzle's title, 2-5 words

## PuzzleDraft.surface
The scenario: 40-90 words describing a strange situation that makes people ask "why?". Only what can be seen; don't hint at the reason

## PuzzleDraft.truth
The truth: 80-150 words explaining what really happened, so that every strange detail in the scenario makes sense

## PuzzleDraft.key_points
2-4 key points, one sentence each: the facts a guess must state to solve the puzzle. Together they are the core of the truth; don't list details

## PuzzleCheck.ok
true if the puzzle is sound and fair: the truth explains every strange detail of the scenario, the key points can be reached step by step with yes/no questions, and nothing depends on trivia only the author knows

## PuzzleCheck.problem
If it isn't sound, what's wrong (a sentence or two); empty if it is
