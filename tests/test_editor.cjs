"use strict";

const assert = require("assert");
const TWX_CATALOG = require("../src/catalog-data.js");
const TWXCodec = require("../src/twx-codec.js");
const EditorCore = require("../src/editor-core.js");

function runTests() {
  // 1) Catalog counts & pure Korean checks
  assert.strictEqual(TWX_CATALOG.items.length, 830);
  assert.strictEqual(TWX_CATALOG.routines.length, 362);
  assert.strictEqual(TWX_CATALOG.neigongs.length, 146);
  assert.strictEqual(TWX_CATALOG.npcs.length, 47);
  assert.strictEqual(TWX_CATALOG.talents.length, 25);
  assert.strictEqual(TWX_CATALOG.titles.length, 42);
  assert.strictEqual(TWX_CATALOG.achievements.length, 164);
  assert.strictEqual(TWX_CATALOG.maps.length, 34);
  assert.strictEqual(TWX_CATALOG.propertyGroups.length, 5);
  const totalAttrs = TWX_CATALOG.propertyGroups.reduce((acc, g) => acc + g.attrs.length, 0);
  assert.strictEqual(totalAttrs, 41);
  assert.strictEqual(TWX_CATALOG.chests.length, 111);
  assert.strictEqual(TWX_CATALOG.developBtns.length, 71);

  const catJson = JSON.stringify(TWX_CATALOG);
  assert.strictEqual(/[\u4E00-\u9FFF\u3400-\u4DBF]/.test(catJson), false, "Catalog must contain 0 Hanzi");
  assert.strictEqual(/[\u3040-\u30FF]/.test(catJson), false, "Catalog must contain 0 Kana");
  assert.strictEqual(/<color=|<\/color>/i.test(catJson), false, "Catalog must contain 0 rich-text color tags");

  // 2) Lossless JsonFx codec roundtrip & partial edit preservation
  const rawJson = '\uFEFF{"m_iMoney":1000,"m_fSmall":30e-4,"m_fRatio":2.67857671,"m_sName":"\\uB3D9\\uBC29\\r","m_sHtml":"\\u003Cbr>"}\r\n';
  const parsed = TWXCodec.parseJsonLossless(rawJson);
  assert.strictEqual(parsed.meta.hasBom, true);
  assert.strictEqual(parsed.meta.trailingNewline, "\r\n");
  assert.strictEqual(TWXCodec.serializeJsonLossless(parsed.data, parsed.meta), rawJson);

  parsed.data.m_iMoney = 9999999;
  parsed.data.m_sHtml = "<p>신규</p>";
  const modOut = TWXCodec.serializeJsonLossless(parsed.data, parsed.meta);
  assert.ok(modOut.includes('"m_iMoney":9999999'));
  assert.ok(modOut.includes('"m_fSmall":30e-4'), "Untouched scientific notation must stay verbatim");
  assert.ok(modOut.includes('"m_fRatio":2.67857671'), "Untouched float token must stay verbatim");
  assert.ok(modOut.includes('"m_sHtml":"\\u003Cp>\\uC2E0\\uADDC\\u003C/p>"'), "JsonFx < and uppercase \\uXXXX escaping");

  // 3) Player string trailing \r helper
  assert.strictEqual(EditorCore.displayPlayerStr("미명\r"), "미명");
  assert.strictEqual(EditorCore.encodePlayerStr("미명", "미명\r"), "미명\r");
  assert.strictEqual(EditorCore.encodePlayerStr("소하", "미명\r"), "소하");

  // 4) Demo generators & 4-schema validation
  const demoSave = EditorCore.createDemoSave();
  const demoRound = EditorCore.createDemoRound();
  const demoGuid = EditorCore.createDemoGuid();
  assert.deepStrictEqual(TWXCodec.validateData(demoSave), { ok: true, kind: "save" });
  assert.deepStrictEqual(TWXCodec.validateData(demoRound), { ok: true, kind: "round" });
  assert.deepStrictEqual(TWXCodec.validateData(demoGuid), { ok: true, kind: "guid" });

  // Negative validation cases
  const negMoney = JSON.parse(JSON.stringify(demoSave));
  negMoney.m_iMoney = -5;
  assert.throws(() => TWXCodec.validateData(negMoney), /금전/);

  const badYear = JSON.parse(JSON.stringify(demoSave));
  badYear.m_iYear = -1;
  assert.throws(() => TWXCodec.validateData(badYear), /연도/);

  const badRoutineLv = JSON.parse(JSON.stringify(demoSave));
  badRoutineLv.m_PlayerRoutineNodeList[0].m_iLV = -1;
  assert.throws(() => TWXCodec.validateData(badRoutineLv), /m_iLV/);

  const badBackpackAmt = JSON.parse(JSON.stringify(demoSave));
  badBackpackAmt.m_BackpackList[0].m_iAmount = -1;
  assert.throws(() => TWXCodec.validateData(badBackpackAmt), /m_iAmount/);

  // Real-save DLL edge values must pass load/save validation
  const dllEdgeSave = JSON.parse(JSON.stringify(demoSave));
  dllEdgeSave.m_iYear = 25;
  dllEdgeSave.m_iNowTime = 0;
  dllEdgeSave.m_iPhysical = -5;
  dllEdgeSave.m_iMood = -5;
  dllEdgeSave.m_iBattleDifficulty = 8;
  dllEdgeSave.m_PropertyGroupsNodeList[0].m_GroupsNodwList[0].m_iValue = -10;
  dllEdgeSave.m_PlayerRoutineNodeList[0].m_iLV = 0;
  dllEdgeSave.m_PlayerNeigongNodeList[0].m_iLV = 0;
  dllEdgeSave.m_BackpackList[0].m_iAmount = 0;
  dllEdgeSave.m_NpcFriendlyNodeList[0].m_iFriendly = -50;
  dllEdgeSave.m_teamMemberList = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  assert.deepStrictEqual(TWXCodec.validateData(dllEdgeSave), { ok: true, kind: "save" });

  // 5) All 8 presets across save / round / guid
  assert.strictEqual(EditorCore.PRESETS.length, 8);
  for (const preset of EditorCore.PRESETS) {
    const target =
      preset.kind === "save"
        ? EditorCore.createDemoSave()
        : preset.kind === "round"
        ? EditorCore.createDemoRound()
        : EditorCore.createDemoGuid();
    const res = EditorCore.applyPreset(target, preset.id);
    assert.strictEqual(res.applied, preset.id);
    assert.strictEqual(TWXCodec.validateData(target).kind, preset.kind);
  }

  // 6) Item / Routine / Neigong / AbilityBook / Friendship helpers
  const workSave = EditorCore.createDemoSave();
  const addedItem = EditorCore.addOrUpdateBackpackItem(workSave, 100001, 7);
  assert.strictEqual(addedItem.m_iAmount, 7);
  assert.strictEqual(addedItem._ItemDataNode.m_iItemID, 100001);
  assert.ok(Array.isArray(addedItem._ItemDataNode.m_ItmeEffectNodeList));
  const beforeLen = workSave.m_BackpackList.length;
  EditorCore.removeBackpackIndex(workSave, beforeLen - 1);
  assert.strictEqual(workSave.m_BackpackList.length, beforeLen - 1);

  EditorCore.addOrUpdateRoutine(workSave, 70002, 9);
  assert.ok(workSave.m_PlayerRoutineNodeList.some((r) => r.m_iRoutineID === 70002 && r.m_iLV === 9));
  EditorCore.addOrUpdateNeigong(workSave, 60002, 10);
  assert.ok(workSave.m_PlayerNeigongNodeList.some((n) => n.m_iNeigongID === 60002 && n.m_iLV === 10));
  assert.ok(workSave.m_MartialIDList.length > 0, "AbilityBookData m_MartialIDList must sync");
  EditorCore.setNpcFriendship(workSave, 100002, 100);
  assert.ok(workSave.m_NpcFriendlyNodeList.some((f) => f.m_iNpcID === 100002 && f.m_iFriendly === 100));
  assert.strictEqual(TWXCodec.validateData(workSave).ok, true);

  // 7) Companion .SaveTitle sync
  assert.deepStrictEqual(TWXCodec.companionTitleTarget("Save0.Save"), { titleFile: "SaveTitle.SaveTitle", index: 0 });
  assert.deepStrictEqual(TWXCodec.companionTitleTarget("AutomaticSave3.Save"), { titleFile: "SaveAutomaticTitle.SaveTitle", index: 3 });
  assert.deepStrictEqual(TWXCodec.companionTitleTarget("AutomaticDSave4.Save"), { titleFile: "SaveAutomaticDTitle.SaveTitle", index: 4 });
  assert.strictEqual(TWXCodec.companionTitleTarget("Round.dat"), null);

  const titleArr = [{ m_bHaveData: false, m_strPlayerName: "", m_strPlaceName: "" }];
  TWXCodec.syncSaveTitleSlot(titleArr, 0, demoSave);
  assert.strictEqual(titleArr[0].m_bHaveData, true);
  assert.strictEqual(TWXCodec.validateData(titleArr).kind, "title");

  // 8) REA combat damage simulator
  const simNormal = TWXCodec.simulateCombatDamage({
    playerAttack: 1000,
    targetDefense: 400,
    routineLevel: 10,
    skillDamage: 500,
    bonusPercent: 20,
    outOfSp: false,
    ignoreDefense: false,
    isCrit: false
  });
  const simCrit = TWXCodec.simulateCombatDamage({
    playerAttack: 1000,
    targetDefense: 400,
    routineLevel: 10,
    skillDamage: 500,
    bonusPercent: 20,
    outOfSp: false,
    ignoreDefense: false,
    isCrit: true
  });
  const simIgnoreDef = TWXCodec.simulateCombatDamage({
    playerAttack: 1000,
    targetDefense: 400,
    routineLevel: 10,
    skillDamage: 500,
    bonusPercent: 20,
    outOfSp: false,
    ignoreDefense: true,
    isCrit: false
  });
  const simNoSp = TWXCodec.simulateCombatDamage({
    playerAttack: 1000,
    targetDefense: 400,
    routineLevel: 10,
    skillDamage: 500,
    bonusPercent: 20,
    outOfSp: true,
    ignoreDefense: false,
    isCrit: false
  });
  assert.ok(simCrit.selectedDamage > simNormal.selectedDamage);
  assert.strictEqual(simIgnoreDef.defRatio, 0);
  assert.ok(simIgnoreDef.normalDamage > simNormal.normalDamage);
  assert.ok(simNoSp.normalDamage < simNormal.normalDamage);

  // 9) Slot schema guard & per-object raw token preservation across array splice
  assert.strictEqual(TWXCodec.expectedSlotKind("Save0.Save"), "save");
  assert.strictEqual(TWXCodec.expectedSlotKind("Round.dat"), "round");
  assert.strictEqual(TWXCodec.expectedSlotKind("362d07a4-5ce8-4d7b-878e-7955e689f209"), "guid");
  assert.strictEqual(TWXCodec.expectedSlotKind("362d07a4-5ce8-4d7b-878e-7955e689f209.Save"), null);
  assert.strictEqual(TWXCodec.expectedSlotKind("SaveTitle.SaveTitle"), "title");
  assert.throws(() => TWXCodec.validateData(demoSave, TWXCodec.expectedSlotKind("Round.dat")));

  const bigNumParsed = TWXCodec.parseJsonLossless('{"items":[{"v":9007199254740992},{"v":9007199254740993}]}');
  bigNumParsed.data.items.splice(0, 1);
  assert.strictEqual(
    TWXCodec.serializeJsonLossless(bigNumParsed.data, bigNumParsed.meta),
    '{"items":[{"v":9007199254740993}]}',
    "Deleting array element 0 must preserve surviving element 1 raw integer token"
  );

  // 10) Primitive array splice preserving 9007199254740993 & EditorCore.addTeamMember / validateData companion limit
  const talentParsed = TWXCodec.parseJsonLossless('{"guid":"00000000-0000-4000-8000-000000000001","iDifficulty":1,"openTalentList":[101,9007199254740993],"openChestList":[]}');
  talentParsed.data.openTalentList.splice(0, 1);
  const serializedTalent = TWXCodec.serializeJsonLossless(talentParsed.data, talentParsed.meta);
  assert.ok(serializedTalent.includes("[9007199254740993]"), "openTalentList splice must preserve 9007199254740993 integer token");

  const dupTalentParsed = TWXCodec.parseJsonLossless('{"guid":"00000000-0000-4000-8000-000000000001","iDifficulty":1,"openTalentList":[9007199254740992,9007199254740993],"openChestList":[]}');
  dupTalentParsed.data.openTalentList.splice(0, 1);
  assert.strictEqual(
    TWXCodec.serializeJsonLossless(dupTalentParsed.data, dupTalentParsed.meta),
    '{"guid":"00000000-0000-4000-8000-000000000001","iDifficulty":1,"openTalentList":[9007199254740993],"openChestList":[]}',
    "Splicing duplicate IEEE-754 Number 9007199254740992 at index 0 must preserve surviving 9007199254740993 token"
  );
  dupTalentParsed.data.openTalentList.unshift(55);
  dupTalentParsed.data.openTalentList.push(77);
  assert.strictEqual(
    TWXCodec.serializeJsonLossless(dupTalentParsed.data, dupTalentParsed.meta),
    '{"guid":"00000000-0000-4000-8000-000000000001","iDifficulty":1,"openTalentList":[55,9007199254740993,77],"openChestList":[]}',
    "unshift + push around surviving >53-bit integer must preserve index-aligned raw token"
  );

  const teamSave = EditorCore.createDemoSave();
  teamSave.m_teamMemberList = [];
  for (let i = 0; i < 9; i++) {
    EditorCore.addTeamMember(teamSave, 100 + i);
  }
  assert.strictEqual(teamSave.m_teamMemberList.length, 9);
  TWXCodec.validateData(teamSave);

  assert.throws(() => {
    EditorCore.addTeamMember(teamSave, 199);
  }, /최대 9명/);

  teamSave.m_teamMemberList.push(200);
  assert.strictEqual(teamSave.m_teamMemberList.length, 10);
  assert.deepStrictEqual(TWXCodec.validateData(teamSave), { ok: true, kind: "save" });
  teamSave.m_teamMemberList.push(-1);
  assert.throws(() => {
    TWXCodec.validateData(teamSave);
  }, /동행 대원/);

  // 11) WeakMap metadata isolation: __twxMeta / __twxObjTokens / __twxArrTokens / __proto__ / constructor / hasOwnProperty
  (function () {
    const baseRaw = TWXCodec.serializeJsonLossless(EditorCore.createDemoSave());
    const specialTail =
      ',"__twxMeta":{"keep":true,"big":9007199254740993}' +
      ',"__twxObjTokens":[1,9007199254740993]' +
      ',"__twxArrTokens":"literal_str"' +
      ',"__proto__":{"safe":1}' +
      ',"constructor":{"ver":9007199254740993}' +
      ',"hasOwnProperty":9007199254740993}\r\n';
    const rawSpecial = "\uFEFF" + baseRaw.replace(/\}$/, specialTail);
    const specialParsed = TWXCodec.parseJsonLossless(rawSpecial);
    assert.deepStrictEqual(TWXCodec.validateData(specialParsed.data, "save"), { ok: true, kind: "save" });

    const roundtripNoMetaArg = TWXCodec.serializeJsonLossless(specialParsed.data);
    const roundtripWithMetaArg = TWXCodec.serializeJsonLossless(specialParsed.data, specialParsed.meta);
    assert.strictEqual(roundtripNoMetaArg, rawSpecial);
    assert.strictEqual(roundtripWithMetaArg, rawSpecial);
    assert.strictEqual(Buffer.compare(Buffer.from(roundtripNoMetaArg, "utf8"), Buffer.from(rawSpecial, "utf8")), 0);
    assert.strictEqual(Buffer.compare(Buffer.from(roundtripWithMetaArg, "utf8"), Buffer.from(rawSpecial, "utf8")), 0);

    specialParsed.data.m_iMoney = 777777;
    const editedSpecial = TWXCodec.serializeJsonLossless(specialParsed.data);
    assert.ok(editedSpecial.includes('"m_iMoney":777777'));
    assert.ok(editedSpecial.includes('"__twxMeta":{"keep":true,"big":9007199254740993}'));
    assert.ok(editedSpecial.includes('"__twxObjTokens":[1,9007199254740993]'));
    assert.ok(editedSpecial.includes('"__twxArrTokens":"literal_str"'));
    assert.ok(editedSpecial.includes('"__proto__":{"safe":1}'));
    assert.ok(editedSpecial.includes('"constructor":{"ver":9007199254740993}'));
    assert.ok(editedSpecial.includes('"hasOwnProperty":9007199254740993'));
    assert.deepStrictEqual(TWXCodec.validateData(TWXCodec.parseJsonLossless(editedSpecial).data, "save"), { ok: true, kind: "save" });
  })();

  // 12) Surrogate pair & double UTF-8 BOM guards
  assert.throws(() => TWXCodec.parseJsonLossless('{"m_strPlayerName":"\\uD800"}'));
  assert.throws(() => TWXCodec.parseJsonLossless('{"m_strPlayerName":"\\uDC00"}'));
  assert.throws(() => TWXCodec.parseJsonLossless('{"m_strPlayerName":"\\uD800\\u0041"}'));
  assert.throws(() => TWXCodec.parseJsonLossless('{"\\uD800":1}'));
  assert.throws(() => TWXCodec.parseJsonLossless('{"m_strPlayerName":"' + String.fromCharCode(0xD800) + '"}'));
  assert.throws(() => TWXCodec.parseJsonLossless('{"' + String.fromCharCode(0xDC00) + '":1}'));
  assert.throws(() => TWXCodec.parseJsonLossless("\uFEFF\uFEFF{\"m_iMoney\":1}"));

  const loneHighValueSave = EditorCore.createDemoSave();
  loneHighValueSave.m_strPlayerName = String.fromCharCode(0xD800);
  assert.throws(() => TWXCodec.validateData(loneHighValueSave, "save"));
  assert.throws(() => TWXCodec.serializeJsonLossless(loneHighValueSave));

  const loneHighKeySave = EditorCore.createDemoSave();
  loneHighKeySave[String.fromCharCode(0xD800)] = 1;
  assert.throws(() => TWXCodec.validateData(loneHighKeySave, "save"));
  assert.throws(() => TWXCodec.serializeJsonLossless(loneHighKeySave));

  const validSurrogatePairJson = '{"m_strVersion":"1.0.3.1","m_strPlayerName":"\\uD83D\\uDE00\\r","m_strPlayerLastName":"\\uB3D9\\r","m_PlayerIconID":"900005","m_iMoney":1,"m_iYear":1,"m_iMonth":1,"m_iMonthInterval":0,"m_iNowTime":1,"m_iPhysical":10,"m_iMood":4,"m_iBattleDifficulty":1,"m_strSceneName":"Develop","m_PropertyGroupsNodeList":[],"m_PlayerRoutineNodeList":[],"m_PlayerNeigongNodeList":[],"m_BackpackList":[],"m_NpcFriendlyNodeList":[]}';
  const validSurrogatePairParsed = TWXCodec.parseJsonLossless(validSurrogatePairJson);
  assert.deepStrictEqual(TWXCodec.validateData(validSurrogatePairParsed.data, "save"), { ok: true, kind: "save" });
  assert.strictEqual(Buffer.compare(Buffer.from(TWXCodec.serializeJsonLossless(validSurrogatePairParsed.data), "utf8"), Buffer.from(validSurrogatePairJson, "utf8")), 0);
  assert.strictEqual(TWXCodec.encodeJsonFxString("\uD83D\uDE00\r"), '"\\uD83D\\uDE00\\r"');

  // 13) Experience-only / value-only property edits preserve sibling values > 99,999 and raw tokens
  const propSeedJson = TWXCodec.serializeJsonLossless(EditorCore.createDemoSave())
    .replace('"m_iValue":80,"m_iIndex":0,"m_iExp":0', '"m_iValue":120000,"m_iIndex":0,"m_iExp":0')
    .replace('"m_iValue":150,"m_iIndex":1,"m_iExp":0', '"m_iValue":1.2E+5,"m_iIndex":1,"m_iExp":0')
    .replace('"m_iValue":75,"m_iIndex":2,"m_iExp":0', '"m_iValue":75,"m_iIndex":2,"m_iExp":2.5E+6');
  assert.ok(propSeedJson.includes('"m_iValue":1.2E+5'));
  assert.ok(propSeedJson.includes('"m_iExp":2.5E+6'));
  const propParsed = TWXCodec.parseJsonLossless(propSeedJson);
  EditorCore.setPropertyValue(propParsed.data, 0, 0, undefined, 54321);
  EditorCore.setPropertyValue(propParsed.data, 0, 1, undefined, 65432);
  EditorCore.setPropertyValue(propParsed.data, 0, 2, 321);
  const propOut = TWXCodec.serializeJsonLossless(propParsed.data);
  assert.ok(propOut.includes('"m_iValue":120000,"m_iIndex":0,"m_iExp":54321'));
  assert.ok(propOut.includes('"m_iValue":1.2E+5,"m_iIndex":1,"m_iExp":65432'));
  assert.ok(propOut.includes('"m_iValue":321,"m_iIndex":2,"m_iExp":2.5E+6'));

  // 14) computeDiffSummary surfaces concrete value/experience deltas for m_PropertyGroupsNodeList
  const diffBefore = EditorCore.createDemoSave();
  const diffAfter = JSON.parse(JSON.stringify(diffBefore));
  EditorCore.setPropertyValue(diffAfter, 0, 0, undefined, 100000);
  const propDiffs = EditorCore.computeDiffSummary(diffBefore, diffAfter);
  const propRow = propDiffs.find((r) => r.label === "41종 능력치·기예");
  assert.ok(propRow && propRow.before.includes("[0:0] 80/0") && propRow.after.includes("[0:0] 80/100000"));

  console.log("[PASS] test_editor.cjs: all assertions succeeded.");
}

if (require.main === module) {
  runTests();
}

module.exports = { runTests };
