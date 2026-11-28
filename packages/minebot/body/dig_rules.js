// How long a block takes to break, and which tool breaks it fastest, as the 1.16.1 server
// decides it. minecraft-data's 1.16.1 tables disagree with the server for many blocks (for
// example it files leaves under "plant", so an axe looks four times faster on leaves, while
// the server gives axes nothing there and favours hoes, shears and swords). Breaking on the
// wrong timetable makes the body pick the wrong tool and stop a dig before the server
// finishes it.
//
// Such a table is read from the server itself: for every block its hardness,
// whether it needs the right tool to drop, and every item's destroy speed on it
// (Item.getDestroySpeed / isCorrectToolForDrops). Blocks that share the same tool speeds share
// one profile. Here those values replace the block material, the material speed table and the
// harvest tools in the registry, so prismarine-block's digTime (the server's formula:
// speed / hardness / (right tool ? 30 : 100), with efficiency, haste, fatigue, water and
// off-ground factors) give the server's answers.
// The table is not part of this package (it is read out of a game server its user owns): MINEBOT_DIG_RULES names
// the file where there is one for the version the server runs. Without one the registry stays as minecraft-data
// has it.
const rules = (() => {
  const file = process.env.MINEBOT_DIG_RULES
  if (!file) return null
  try { return JSON.parse(require('fs').readFileSync(file, 'utf8')) } catch (error) { return null }
})()

function applyServerDigRules (registry) {
  if (!rules) return
  const itemId = (name) => {
    const item = registry.itemsByName[name]
    if (!item) throw new Error(`dig rules: no item ${name} in the registry`)
    return item.id
  }
  const materials = {}
  for (const [profile, speeds] of Object.entries(rules.profiles)) {
    materials[profile] = {}
    for (const [name, speed] of Object.entries(speeds)) materials[profile][itemId(name)] = speed
  }
  // only the server's profiles remain, so no block can fall back to an old material's speeds
  for (const key of Object.keys(registry.materials)) delete registry.materials[key]
  Object.assign(registry.materials, materials)

  for (const block of registry.blocksArray) {
    const rule = rules.blocks[block.name]
    if (!rule) throw new Error(`dig rules: no server rule for block ${block.name}`)
    const [hardness, profile, tools] = rule
    block.hardness = hardness
    block.diggable = hardness >= 0
    block.material = profile
    if (tools) {
      block.harvestTools = {}
      for (const name of tools) block.harvestTools[itemId(name)] = true
    } else {
      delete block.harvestTools
    }
  }
}

module.exports = { applyServerDigRules }
