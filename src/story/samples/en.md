<!--
The sample story: the lighthouse story used by just prompts (story/preview.py) and just eval (story/evals.py). Not a prompt; it just makes previews and evals look like a real game.
One file per language, with the same section names. Sections with one item per line may start each line with -; "A | B" separates the fields of one item.
-->

<!-- ---------- The story ---------- -->

## premise
You are a traveller with no memory who wakes on a stormy night at the bottom of an abandoned lighthouse.

## goal
Find out why the lighthouse keeper disappeared

## twist
The keeper never disappeared; he has been hiding in a secret chamber beneath the lighthouse all along, guarding a secret no one must ever learn

## clues
- Someone refills the lighthouse lamp every night
- There are fresh muddy footprints on the floor by the chamber's entrance

## acts
<!-- Four acts: name | milestone -->
- The Night of the Storm | Find the journal the keeper left in the lighthouse
- Signals at Sea | Decode the light signals in the journal
- The Chamber Below | Open the secret chamber and reveal the keeper's secret
- Before Dawn | Decide whether to bring the secret into the light

## endings
- Keep the secret and leave the island alone
- Hand the truth over to the people of the town

## history
<!-- The story log: narration | the player's action after reading it -->
- On a stormy night you wake at the bottom of the lighthouse, a rusty key clutched in your hand. | Climb up and see if anyone is in the lamp room
- The lamp room is empty, yet the lamp is still burning, and a rain-soaked journal lies open on the desk. | Open the journal

## key_events
- Found the keeper's journal

## flags
- The lighthouse door was locked from the outside

## narration
The journal's last page reads: "Three long flashes and one short means they've come." Outside the window, a light flares on the sea.

## summary
<!-- For previewing memory compaction: the earlier summary -->
The earlier summary

## event
<!-- For previewing memory compaction: the name of each of many key events (followed by a number) -->
Event

## wounds
<!-- The first character's conditions: name | kind | severity (codes from vocab.md) -->
- torn right arm | body | moderate
- fear | mind | light

## inventory
- key
- oil lamp

## players
<!-- The team: name | inventory (playing alone uses the first character, with the inventory above) -->
- Alex | oil lamp
- Sam | key


## actions
<!-- Each character's action this turn: name | action (playing alone uses the first line) -->
- Alex | Answer with the light signal from the journal
- Sam | Hide by the stairs and watch

## fall
<!-- Previewing a fall when playing alone: the narration just written -->
You tumble down the stairs and slam hard into the stone wall.

## fall_named
<!-- Previewing a fall with several characters: the first character falls -->
Alex tumbles down the stairs and slams hard into the stone wall.

<!-- ---------- Eval (just eval) scenarios ---------- -->

## armed
<!-- The reckless and dying scenarios: the narration just written -->
The door downstairs bursts open, and a man in black with a knife charges up the stairs, blocking the only way out.

## reckless_action
Ignore the wound in my arm and lunge bare-handed at the man with the knife

## dying_wounds
<!-- The dying scenario: name | kind | severity -->
- torn right arm | body | severe
- blood loss | body | moderate

## dying_action
Ignore my wounds and lunge bare-handed at the man with the knife

## early_narration
The journal's last page reads: "Stop looking." The storm has passed, and a small boat is tied up at the shore.

## early_action
Throw the journal into the sea, take the boat from the shore, leave this island, and never come back

## reveal_narration
You pry up the floor at the bottom of the lighthouse: beneath it, stone steps lead down to a secret chamber, faint light glows in the depths, and someone is coughing.

## reveal_action
Go down the steps into the chamber

<!-- ---------- Judge calibration: deliberately bad samples (the judge must fail them) and fine ones (it must pass them) ---------- -->

## agency_bad
You raise the oil lamp and flash three long and one short, just as the journal says. You think to yourself that someone will finally come to save you, and a wave of relief washes over you. You decide to head down to the dock to wait for them, tuck the journal into your coat, and say to the empty lamp room, "I'll be back, I promise."

## agency_good
You raise the oil lamp and flash three long and one short, just as the journal says. The light on the sea goes dark for a moment, then answers two short and one long, as if confirming something. Downstairs, a bolt slides back, and someone in soaking boots starts climbing the stairs, step by step.

## early_bad
You hurl the journal into the churning waves and row away from the island. The lighthouse beam grows smaller behind you until it vanishes over the horizon. Years later you settle in a distant port and never think of that night again. And so your story comes to an end.

## early_good
You hurl the journal into the waves, cast off, and leap into the boat. You've rowed barely a hundred feet when wood splinters beneath you and seawater gushes through the crack. Looking back, you see a figure at the lamp-room window, raising a light and flashing three long and one short at you.

## early_good_choices
- Swim back to shore
- Grab a drifting plank

## opening_bad
The storm batters the lighthouse as you wake at the bottom, a rusty key in your hand. Coughing drifts up from beneath the floor. You will soon discover that the keeper the town believes vanished never disappeared at all; he has been hiding in a secret chamber beneath the lighthouse, guarding a secret no one must ever learn.

## reveal_bad
You go down the steps. The chamber is empty except for a still-warm oil lamp and an overturned chair. The walls are carved all over with marks of three long and one short. The coughing has stopped at some point; you feel one step away from the truth, yet you can't work out what any of it means.

## tone_bad
<!-- Style that doesn't fit the genre: shown to the judge for the Wuxia genre pack (folder wuxia) -->
You pull out your phone and check the map: the Yuelai Inn is still three kilometers away. "OK, let's grab some food first," you say, giving your senior brother a thumbs-up. A row of share bikes is parked outside the inn, and the waiter is ordering on a tablet.
