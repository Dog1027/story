<!--
Samples for evaluating turtle soup: used by just eval soup (story/evals.py). One per language, with the same sections.
-->

<!-- ---------- Judge calibration: deliberately bad samples (the judge must fail them) and fine ones (it must pass them) ---------- -->

## soup_cases
<!-- Turtle soup evaluation (just eval soup): puzzle title | guess | at least this many key points | at most this many. Taken from real play; an incomplete guess must not get full marks -->
- The Note on the Fridge | His roommate didn't put up a note, which means something happened to him, so Ken called 911 | 1 | 2
- The Note on the Fridge | The roommate died | 0 | 1
- The Note on the Fridge | The roommate has a heart condition, and they agreed he'd put up a note every morning to show he was okay; with no note, Ken feared an attack and called an ambulance | 3 | 3
- The Sunny-Day Umbrella | Because she doesn't like the sun and likes the rain | 0 | 1
- The Sunny-Day Umbrella | Mrs. Wang likes rain and dislikes sunshine | 0 | 1
- The Sunny-Day Umbrella | She is allergic to sunlight and blisters in the sun, so she uses the umbrella for shade on sunny days; on rainy days there's no sun | 2 | 2
- The Dark Lighthouse | The enemy landed in the storm, but the lighthouse was dark and the storm wrecked them | 0 | 1
- The Dark Lighthouse | In the war the enemy was landing by the lighthouse's light, then it suddenly went dark, they lost their way and sank | 3 | 3
