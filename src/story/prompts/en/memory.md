<!--
Memory compaction: when the story log gets too long, the oldest part is folded into the long-term summary.
-->

## system
<!-- The rules for the AI when compacting memory (the system prompt) -->
You compact the story log of a text adventure game. Write plain English text (no Markdown or LaTeX). Keep the characters, places, promises, grudges, clues, and anything else that may matter later; drop the flourishes.

## summary
<!-- Variable: {summary} is the current summary (summary_none when there isn't one yet) -->
# Current summary
{summary}

## turns
<!-- The story text to fold in. Variable: {entries} (each turn is history_entry from context.md) -->
# New story log
{entries}

## old_facts
<!-- Old events and facts to fold in when there are too many. Variable: {items} (one per line) -->
# Old events and facts to fold in
{items}

## compact
Fold everything above into the summary and output the complete updated summary (under 350 words). Output only the summary itself.

## summary_none
(none yet)
