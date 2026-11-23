guide("furnace-progress"): the fuel and progress values of an open furnace window.

These properties are on the object bot.openFurnace resolves with. Six of them are null
and the two total...Seconds ones undefined until the server sends the matching value.
They change only while the window is open. Writing them does nothing to the game.

furnace.totalFuel             ticks the fuel item now burning lasts in all
furnace.totalFuelSeconds      totalFuel * 0.05
furnace.fuel                  0 to 1: ticks of burning left / totalFuel
furnace.fuelSeconds           fuel * totalFuelSeconds: seconds of burning left
furnace.totalProgress         ticks one item takes to smelt
furnace.totalProgressSeconds  totalProgress * 0.05
furnace.progress              0 to 1: ticks smelted so far on the current item /
                              totalProgress
furnace.progressSeconds       totalProgressSeconds * (1 - progress): seconds left for the
                              current item

How they update.
  The server sends window property packets for the open furnace; each carries one
  property number and one value:
    0  ticks of burning left   sets fuel and fuelSeconds
    1  total burn ticks        sets totalFuel and totalFuelSeconds
    2  ticks smelted so far    sets progress and progressSeconds
    3  total smelt ticks       sets totalProgress and totalProgressSeconds
  Property 0 arriving while totalFuel is null or 0 sets fuel and fuelSeconds to 0.
  Property 2 arriving while totalProgress is null or 0 sets progress and progressSeconds
  to 0. A packet for another window id is ignored.

furnace 'update' event        no arguments
  Emitted after each of these packets for this furnace, once per packet.

The packet listener is removed when the window emits 'close'; furnace.close() emits it.
One item smelts in 10 seconds.
