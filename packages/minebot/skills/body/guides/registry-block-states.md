guide("registry-block-states"): state ids, block properties, collision shapes.

State ids.
  Every variant of a block (a door open or closed, a crop at each age) has its own
  number, the state id. A block record owns the range minStateId to maxStateId;
  defaultState is one id of that range. A block without properties has one id
  (stone: 1 to 1). The ids of 1.16.1 run from 0 to 17103.
bot.registry.blocksByStateId[stateId] -> block record
  The record whose range holds that id; undefined above 17103.
  bot.registry.blocksByStateId[8303].name -> 'oak_slab'

The states field of a block record.
  An array of property descriptions, in a fixed order:
    { name, type: 'bool', num_values: 2 }
    { name, type: 'int', num_values: N }
    { name, type: 'enum', num_values: N, values: [strings] }
  oak_door: facing (enum north, south, west, east), half (enum upper, lower), hinge
  (enum left, right), open (bool), powered (bool). wheat: age (int, 8 values).
  The number of ids in the range is the product of all num_values.

From a state id to property values.
  n = stateId - minStateId. Take the properties from the LAST of the array to the first.
  For each: index = n % num_values, then n = floor(n / num_values).
    bool   index 0 is true, index 1 is false
    int    the value is the index (wheat age 0 to 7)
    enum   the value is values[index]
  oak_slab (minStateId 8300; type: top, bottom, double; waterlogged): id 8303 gives
  n = 3; waterlogged index 1, false; type index 1, 'bottom'. That is its defaultState.
  wheat (minStateId 3357): id 3357 + age. Age 7 is 3364.
  A Block object holds the result of this rule in block.getProperties().

From property values to a state id.
  stateId = minStateId + sum over the properties of index * weight, where the weight of
  the last property is 1 and each earlier property's weight is the product of the
  num_values of all properties after it.

bot.registry.blockCollisionShapes
  { blocks, shapes }
  blocks[name]   a shape number when every state of the block has the same shape
                 (stone: 1, air: 0), or an array of shape numbers, one for each state,
                 at index stateId - minStateId (oak_slab: [171, 171, 61, 61, 1, 1])
  shapes[number] an array of boxes; each box is [x0, y0, z0, x1, y1, z1] in block units
                 from the block's low corner. 272 shapes.
                   shapes[0]    []                        no collision
                   shapes[1]    [[0, 0, 0, 1, 1, 1]]      a full cube
                   shapes[61]   [[0, 0, 0, 1, 0.5, 1]]    a bottom slab
                   shapes[171]  [[0, 0.5, 0, 1, 1, 1]]    a top slab
                 A fence post with two arms has boxes that reach y 1.5.
  Water and lava have shape 0.
