guide("registry-version"): bot.registry version fields, version comparisons, supportFeature.

bot.registry.version         object:
  minecraftVersion   '1.16.1'
  majorVersion       '1.16'
  version            736, the protocol number
  dataVersion        2567
  type               'pc'
  version['>='](other), version['>'](other), version['<'](other), version['<='](other),
  version['=='](other) -> boolean
    other: a version string such as '1.16', '1.16.1', '1.17.1'. Compares the data
    version number of 1.16.1 with that of other. A string that is not a known version
    throws a RangeError "Version '<other>' not found in [...] for pc".
bot.registry.type            'pc'
bot.registry.isNewerOrEqualTo(other) -> boolean    version['>='](other)
bot.registry.isOlderThan(other) -> boolean         version['<'](other)

bot.version                  '1.16.1' (version.minecraftVersion)
bot.majorVersion             '1.16'
bot.protocolVersion          736

bot.registry.supportFeature(name) -> value
bot.supportFeature(name)     the same function
  Returns the value of a named feature for 1.16.1: true, false, or for five features a
  number or a string. A name that is not a feature gives false.
  Features with a value on 1.16.1:
    fishingBiteDelayMaxTicks 600, metadataIxOfItem 7, nbtNameForEnchant 'Enchantments',
    typeOfValueForEnchantLevel 'string', whereDurabilityIsSerialized 'Damage'
  Features that are true on 1.16.1 (every other of the 171 names is false):
    acknowledgePlayerDigging actionIdUsed allEntityEquipmentInOne attributeSnakeCase
    biomesSentSeparately blockPlaceHasInsideBlock blockSchemeIsFlat blockStateId
    booksUseStoredEnchantments clientboundChatHasSender creativeSleepNearMobs
    customChannelIdentifier difficultySentSeparately dimensionIsAString doublePosition
    editBookPacketUsesNbt effectAreNotPrefixed enderCrystalNameNoCapsWithUnderscore
    entityMCPrefixed entityMetadataSentSeparately entitySnakeCase explicitMaxDurability
    fireworkMetadataOptVarInt8 fireworkNameSingular fishingBobberCorrectlyNamed
    fixedPointDelta128 hasAttackCooldown hasDataCommand hasEditBookPacket hasElytraFlying
    hasExecuteCommand itemLoreIsAString itemSerializationAllowsPresent
    itemSerializationWillOnlyUsePresent itemsAreNotBlocks lightSentSeparately
    multiBlockChangeHasTrustEdges multiTypeSigns netherUpdateInventoryWindows
    noteBlockNameIsNoteBlock playsoundUsesResourceLocation quickMoveClickSendsEmptyItem
    respawnIsActionId saveDurabilityAsDamage selectingTradeMovesItems
    setPassengerStackEntity shieldSlot sneakUsesEntityAction
    spawnEggsHaveSpawnedEntityInName spawner tabCompleteHasAToolTip
    teamUsesChatComponents teleportUsesOwnPacket theFlattening theShulkerBoxes
    titleUsesLegacyPackets transactionPacketExists unloadChunkDirect updateViewPosition
    useItemWithOwnPacket usesBlockStates usesLoginPacket usesPalettedChunks
    village&pillageInventoryWindows

bot.registry.loadDimensionCodec(codec)
  The bot calls it with the dimension data of the login packet. It reads the entries
  'chat_type', 'dimension_type' and 'worldgen/biome'. The 1.16.1 login data has one
  entry, 'dimension', so the call changes no table.
bot.registry.writeDimensionCodec() -> object
  On 1.16.1 returns bot.registry.loginPacket.dimensionCodec.
