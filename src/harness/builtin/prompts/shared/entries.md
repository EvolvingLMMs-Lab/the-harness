Entries: parts of your work that run at the same time as your programs.

<!-- if: channels -->
  spawn(fn, name=None, claims=None)  run fn() beside your program as an entry on the channels
                                    it claims (CHANNELS: e.g. ["move"], ["look", "hands"]);
                                    returns its handle: .wait(timeout=None) returns what fn
                                    returned (raises its failure; None if cancelled or still
                                    running at the timeout), .cancel() stops it, .send(message)
                                    gives it a message, .state(), .status (running, done,
                                    failed, cancelled)
  claim(*channels), unclaim(*channels)   inside an entry: take channels for it, or let them go
  channels()                         who has each channel now
<!-- else -->
  spawn(fn, name=None)               run fn() beside your program as an entry; returns its
                                    handle: .wait(timeout=None) returns what fn returned (raises
                                    its failure; None if cancelled or still running at the
                                    timeout), .cancel() stops it, .send(message) gives it a
                                    message, .state(), .status (running, done, failed,
                                    cancelled)
<!-- end -->
  receive(timeout=None)              inside an entry's fn: the oldest message sent to it, or None
  entries(running=True)              the handles of the entries started so far

An entry you spawn keeps running after the program that started it ends; after each
program you read how your entries stand ("Entries: ..."). Each of your replies changes
<!-- if: channels -->
the set: spawn adds an entry, cancel() stops one, cancel() and spawn replace one.
Entries run at the same time, each on its own channels of the game's keys, mouse and
wheel (CHANNELS names them and what is on each). An entry claims the channels it uses
(spawn(..., claims=[...]) or claim()) and no other entry may use them until it lets them
go or ends; its inputs drive only those channels, so one entry walks while another turns
the view or swings. key_down(*keys, buttons=()) keeps keys and buttons down across
periods while that entry's code goes on, until key_up() or the entry's end; when an
entry ends, everything it held is let go. An entry that reaches for a channel another
entry has fails with a CHANNEL_CONFLICT event, which reaches you unless the program that
started it handles it. Use an entry for a part that must go on beside the rest: holding a
key down while other code steers, watching the state and reacting at once, a background
reading or computation.
An entry that fails reaches you as an ENTRY_FAILED event unless something waits for it.

For example, to keep moving forward while a lookout entry watches what the game reports
and another program goes on with the view:

<python>
def walk():
    key_down("w")
    while True:
        wait(1)
walker = spawn(walk, name="walk", claims=["move"])
def lookout():
    seen = get_state().get("hud")
    while get_state().get("hud") == seen:
        wait(0.2)
    return "the HUD changed"
watch = spawn(lookout, name="hud lookout")
</python>
<!-- else -->
the set: spawn adds an entry, cancel() stops one, cancel() and spawn replace one. Use an
entry for work that goes on beside your next steps in this workspace: watching for a
change (a download or an upload finishing, a page or a window updating) while you act,
waiting for something with a time limit, reading or computing in the background. Input
steps of different entries take turns on this screen, in the order the entries started,
so give an entry reading and waiting, and keep the clicking and typing in one place.
An entry that fails reaches you as an ENTRY_FAILED event unless something waits for it.
<!-- end -->
<!-- if: agents -->
Work that needs its own screen (another site, another document) goes to a sub-agent
instead: each delegate() is an entry too, with a workspace of its own, so several of them
work truly at the same time.
<!-- end -->
<!-- if: channels -->
<!-- else -->
<!-- if: desktop -->

For example, to hear when the window's title changes (a page or a dialog has loaded)
while your next programs go on:

<python>
def new_title(start=get_state().get("active_window")):
    while get_state().get("active_window") == start:
        wait(1)
    return get_state().get("active_window")
title_watch = spawn(new_title, name="title watcher")
</python>
<!-- end -->
<!-- end -->
