"""The safety layer: fixed rules every action of an identity passes before it runs. It is not
the agent's judgement and cannot be unlearned; what to do after a refusal is the agent's own
judgement (a refusal reaches it as the outcome "refused" with the reason).

    the desktop     its input is refused while the owner is using the desktop (the computer
                    package tells the owner's own input from the agent's; the rule is on for
                    every desktop task of an identity and cannot be turned off there)
    approval        sending, publishing, paying, deleting and steps that cannot be undone
                    run only with the owner's approval; logging in is always left to the
                    owner (refused)
    authority       anything beyond the authority of the turn is refused

Authority comes from where a turn came from, never from the prompt. There are two kinds of
people: the owner (the bound channel accounts and the local frontends) and everyone else
(people in groups, people who paired). A turn has the lowest authority of the sources that
triggered it:

    owner   the owner asked: anything in the places the owner connected
    own     it set out to do this itself: one level less, only where the place lets it act
            on its own (spaces.<place>.proactive = do), and only in the chat's own place
    other   someone else asked: only within the chat they are in (answering, summarising
            there); never the owner's computer, files or accounts, and no approvals

What counts as sending is declared by the environment's vocabulary (a verb's `effect`):
replying in the chat where it was asked is not sending; sending to someone new, forwarding,
pushing and publishing are."""

LEVELS = {"other": 0, "own": 1, "owner": 2}
APPROVE = ("send", "publish", "pay", "delete", "irreversible")
LOGIN = ("login", "credentials")
# The effects someone other than the owner may cause, in the chat they are in.
OTHERS_MAY = ("read", "change", "reply")
# How long the owner's own input keeps the desktop theirs.
OWNER_SECONDS = 2.0


def lowest(*levels) -> str:
    return min(levels, key=lambda level: LEVELS[level])


def check(*, level, effect, place_kind=None, proactive="do", own_place=True, owner_active=False,
          verb="", in_chat=True) -> tuple:
    """("allow" | "approve" | "refuse", reason): the fixed rules, in this order."""
    if level not in LEVELS:
        raise ValueError(f"a level is one of {', '.join(LEVELS)}")
    effect = (effect or "change").lower()
    if place_kind == "desktop" and owner_active and effect != "read":
        return "refuse", "the owner is using the desktop: its input is refused until they leave it"
    if effect in LOGIN:
        return "refuse", "logging in is left to the owner"
    if level == "other":
        if verb == "task":
            return "refuse", ("beyond its authority: someone other than the owner asked, and work on the owner's "
                              "computer, files or accounts is the owner's to ask for")
        if not in_chat or effect not in OTHERS_MAY or place_kind in ("folder", "desktop", "browser"):
            return "refuse", ("beyond its authority: someone other than the owner asked, and they can ask only for "
                              "things within the chat they are in")
    if level == "own":
        if not own_place:
            return "refuse", "beyond its authority: on its own it acts only in the chat's own place"
        if proactive != "do" and effect != "read":
            return "refuse", f"not on its own here: this place lets it {proactive or 'off'}, not act"
    if effect in APPROVE:
        if level == "other":
            return "refuse", "beyond its authority: only the owner can approve this, and the owner did not ask"
        return "approve", f"{verb or 'this action'} is {effect}: it runs only with the owner's approval"
    return "allow", ""


def turn_level(sources) -> str:
    """The authority of a turn from its sources: "owner", "own" or "other" each."""
    sources = list(sources) or ["own"]
    return lowest(*sources)
