<!--
Planning a new story: picking a genre and planning the hidden outline.
-->

## pick_genre
<!-- When the genre is "Auto", ask the AI to pick one from the premise. Variables: {premise}, {catalog} (one genre per line, see catalog_entry) -->
Pick a genre for this interactive text adventure.
# Premise
{premise}

# Genre catalog
{catalog}

## catalog_entry
<!-- One genre in the catalog. Variables: {name}, {description} -->
- {name}: {description}

## arc
<!-- Plan the outline. Variables: {target_turns}, {premise}, {cast} (the protagonists in multiplayer, empty in single-player), {situation} (arc_new or arc_resume below) -->
Plan the outline for this interactive text adventure, about {target_turns} turns long.
# Premise
{premise}
{cast}{situation}
Milestones must be concrete, so it is clear whether they have happened. The endings must depend on the player's choices; don't make them all "escape successfully".
First decide the hidden truth (twist); the third act's milestone is revealing it. Then design clues that can surface naturally in the first two acts, so that when the truth comes out the player thinks back and goes "of course", instead of it coming out of nowhere. Avoid the tired "a companion betrays you" or "someone else was behind it all" unless you bring something new.
The truth must not decide whether a player character lives or dies, and must not reveal that a player character isn't really human (e.g. dead all along, a ghost, possessed): characters' life, death, and conditions are decided by the program. The truth must concern every protagonist, not just one; it can be about NPCs, events, places, items, or the protagonists' past. Put clues in the surroundings, NPCs, items, or documents, never in the player characters' own feelings or actions; those are for the players to decide.

## arc_new
The story hasn't started yet.

## arc_resume
<!-- An old save without an outline: write one that fits the story so far. Variables: {turn}, {summary} (summary_none when there is none), {events} (one key event per line) -->
The story is already {turn} turns in. The outline must continue from the story so far; put what has already happened in the earlier acts.
# Summary of the story so far
{summary}
# Key events
{events}

## genre
<!-- The chosen genre pack, added when planning the outline. Variables: {name}, {guide} -->
# Genre: {name}
{guide}

## names
<!-- The genre pack's naming material, added when planning the outline and writing the opening. Variable: {names} -->
# Naming material (for reference; no need to use it all)
{names}

## twist_ideas
<!-- The genre pack's twist ideas; a few are drawn at random when planning the outline. Variable: {ideas} (one per line) -->
# Twist ideas (pick one and rework it to fit this story, or come up with something better; don't copy it as is)
{ideas}

## summary_none
(none)
