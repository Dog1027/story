"""The adventure's record helpers: changes between turns, the ending record, the memory text. Data only, no looks. Saving and loading are in story/core/saves.py."""

from collections import Counter

from story.core.reply import ChangeGroups
from story.games.adventure.models import AdventureState, Character, word
from story.games.adventure.prompting import PREMISE
from story.games.adventure.rules import DAY, SEVERITY_ORDER
from story.games.adventure.text import UI

join = UI["list_sep"].join

DEFAULT_PREMISE = PREMISE["default"]  # The premise used when there's no genre pack to draw from and the player typed nothing


def memory_text(state: AdventureState) -> str:
    """/state: the bags, facts, key events and summary, one section each (see memory_section); empty sections are left out."""
    item = UI["memory_item"].format
    if state.solo:
        bags = [item(item=i) for i in state.characters[0].inventory]
    else:
        bags = [UI["memory_named_bag"].format(name=c.name, items=join(c.inventory)) for c in state.characters if c.inventory]
    sections = {
        "memory_bags": bags,
        "memory_facts": [item(item=f) for f in state.facts],
        "memory_events": [item(item=e) for e in state.key_events],
        "memory_summary": [state.summary] if state.summary else [],
    }
    text = "\n\n".join(UI["memory_section"].format(title=UI[key], body="\n".join(lines)) for key, lines in sections.items() if lines)
    return text or UI["memory_nothing"]


def ending_record(state: AdventureState) -> str:
    """The journey record at the ending. The in-game time is only revealed here."""
    days = (state.minutes or 0) // DAY + 1
    record = UI["record"].format(turns=state.turn, days=days) + "\n"
    fallen = [c.name for c in state.characters if not c.alive]
    if state.solo:
        record += UI["record_dead"] if fallen else UI["record_alive"]
    elif len(fallen) == len(state.characters):
        record += UI["record_all_fallen"]
    elif fallen:
        record += UI["record_some_fallen"].format(names=join(fallen))
    else:
        record += UI["record_all_alive"]
    if state.key_events:
        events = "\n".join(UI["record_event"].format(event=e) for e in state.key_events[-5:])
        record += "\n\n" + UI["record_events"].format(events=events)
    return record


# ---------- Changes between turns ----------

Snapshot = tuple[dict[str, str], Counter]  # (condition name → severity, item counts in the bag)


def snapshot(who: Character) -> Snapshot:
    return {c.name: c.severity for c in who.conditions}, Counter(who.inventory)


def change_groups(before: Snapshot, who: Character) -> ChangeGroups:
    """Compare a character's conditions and bag before and after a turn and list the changes. Returns only non-empty groups."""
    old_conds, old_items = before
    new_conds, new_items = snapshot(who)
    rank, w = SEVERITY_ORDER.index, lambda v: word("severity", v)
    def added(n: str, v: str) -> str:
        return UI["condition"].format(name=n, severity=w(v))

    def moved(n: str, v: str) -> str:
        return UI["condition_change"].format(name=n, old=w(old_conds[n]), new=w(v))

    groups: ChangeGroups = [
        (UI["change_new"], [(added(n, v), v) for n, v in new_conds.items() if n not in old_conds]),
        (UI["change_worse"], [(moved(n, v), "bad") for n, v in new_conds.items()
                              if n in old_conds and rank(v) > rank(old_conds[n])]),
        (UI["change_better"], [(moved(n, v), "good") for n, v in new_conds.items()
                               if n in old_conds and rank(v) < rank(old_conds[n])]),
        (UI["change_healed"], [(n, "good") for n in old_conds if n not in new_conds]),
        (UI["change_gained"], [(n, "plain") for n in (new_items - old_items).elements()]),
        (UI["change_lost"], [(n, "muted") for n in (old_items - new_items).elements()]),
    ]
    return [(label, items) for label, items in groups if items]
