<!--
The judge for evals (just eval): after the game's AI writes a turn, another AI call uses the criteria here to decide whether it got it right.
Never used in the game itself, only in evals. Change this to make the judge stricter or more lenient; the scenarios themselves (states, player actions) are in games/adventure/evals.py.
The judge returns a reason and whether it passed (Verdict.reason and Verdict.passed describe those two fields).
-->

## system
You are a quality judge for a text adventure game. An AI acts as the narrator; using the given criterion, decide whether its turn is acceptable.
Judge only the one thing the criterion asks about; don't mark it down for prose quality or other problems. When the criterion is unclear, side with the player's experience.

## Verdict.reason
First give the reason for your judgment in one or two sentences, quoting the key lines from the narration

## Verdict.passed
Whether it meets the criterion

## no_ending
<!-- The story is only halfway through, and the player did something that sounds like ending it. Variables: {action}, {narration}, {choices} -->
Criterion: the story is in its middle and must not end this turn. The player's action can have consequences, but the narration must leave suspense or a new development so the story continues; it must not read as an ending (e.g. "from then on", "years later", summing up the whole journey, the protagonist's story coming to a close).

The player's action: {action}

Narration:
{narration}

Choices given to the player:
{choices}

## agency
<!-- Does the narration make decisions for the player. Variables: {action}, {narration} -->
Criterion: the narration may only describe the action the player said they take, and how the world and other characters respond. It must not make decisions beyond that action for the player, put words in the player's mouth, or declare the player's inner feelings and thoughts (e.g. "you decide…", "you think to yourself…", "a wave of relief washes over you").
Physical reactions caused by conditions like wounds or fear (shaking hands, a racing heart) are fine, and so is naturally completing the described action (walking over, reaching out).

The player's action: {action}

Narration:
{narration}

## twist_hidden
<!-- The opening: the hidden truth must not be given away. Variables: {twist}, {narration} -->
Criterion: this is the opening of the story, and the hidden truth below is only revealed in the third act. The opening must not give it away or hint so heavily that the player could guess it at once. Planting an inconspicuous clue is fine.

Hidden truth: {twist}

Opening narration:
{narration}

## reveal
<!-- Act three: the truth must be revealed. Variables: {twist}, {clues}, {narration} -->
Criterion: the story is in its third act, this act has dragged on, and the player has reached the key place this turn. This turn's narration must reveal the hidden truth below (its core is enough, not word for word), ideally echoing the clues planted earlier. Merely getting closer or still hinting does not pass.

Hidden truth: {twist}

Clues planted earlier:
{clues}

Narration:
{narration}

## tone
<!-- The genre's style. Variables: {genre}, {guide}, {narration} -->
Criterion: the story's genre is "{genre}". The narration's wording, mood, and elements must fit the genre guide below, especially "Style" and "Clichés to avoid". It doesn't need to use everything in the guide, but must not clearly violate it (e.g. modern slang in wuxia, a ghost story played for laughs).

Genre guide:
{guide}

Opening narration:
{narration}
