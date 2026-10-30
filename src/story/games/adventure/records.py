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
    events = "\n".join(UI["memory_event"].format(event=e) for e in state.key_events) or UI["memory_no_events"]
    if state.solo:
        bags = UI["memory_bag"].format(items=join(state.characters[0].inventory) or UI["memory_empty_bag"])
    else:
        bags = "\n".join(UI["memory_named_bag"].format(name=c.name, items=join(c.inventory) or UI["memory_empty_bag"]) for c in state.characters)
    return UI["memory"].format(
        bags=bags,
        flags=join(state.flags) or UI["memory_no_flags"],
        events=events,
        summary=state.summary or UI["memory_no_summary"],
        turns=len(state.recent),
    )


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
