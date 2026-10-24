<!--
Premises: the default opening, and "Inspire me" (asking the AI for a new premise).
The "Inspire me" sections are joined in order with line breaks: intro, (when a genre pack was picked) pack and pack_ideas, rules, (when there is a premise to avoid) avoid.
-->

## intro
<!-- Variables: {genre} is a randomly picked genre, {setting} a randomly picked situation -->
Come up with an original premise for an interactive text adventure. Genre: {genre}; the story begins: {setting}.

## pack
<!-- When a genre pack was picked, its description. Variable: {description} -->
About the genre: {description}

## pack_ideas
<!-- Three opening ideas drawn at random from the genre pack. Variable: {ideas} (one per line) -->
Inspiration (don't copy these; write something new):
{ideas}

## rules
Write in English, in the second person ("you"), one or two sentences, under 50 words. Establish who the protagonist is and their situation, and leave an intriguing mystery or danger. Output only the premise itself, with no title or explanation.

## avoid
<!-- After pressing "Inspire me" several times, avoid the previous one. Variable: {avoid} -->
Don't make it similar to this premise: {avoid}

## default
<!-- The premise used when there is no genre pack to draw from and the player typed nothing -->
You are a traveller with no memory who wakes on a stormy night at the bottom of an abandoned lighthouse, clutching a key that isn't yours.

## genres
<!-- Genres "Inspire me" picks from at random (when one has a genre pack, the pack's description is included), one per line -->
- Epic fantasy
- Cyberpunk
- Cthulhu
- Wuxia
- Post-apocalyptic survival
- Steampunk
- Space exploration
- Detective mystery
- Folk horror
- Pirates on the high seas
- Court intrigue
- Fairy tale gone dark
- School ghost stories
- The Wild West

## settings
<!-- Situations "Inspire me" picks from at random: when the story begins, one per line -->
- late at night
- in the middle of a storm
- at a funeral
- while on the run
- just after waking up
- as a letter arrives
- on a festival day
- when everything seems calm
