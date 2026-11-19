(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./twx-codec.js"), require("./catalog-data.js"));
  } else {
    root.TWXEditorCore = factory(root.TWXCodec, root.TWX_CATALOG);
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (TWXCodec, defaultCatalog) {
  "use strict";

  var GUID = "00000000-0000-4000-8000-000000000001";

  var MAX_TEAM_MEMBERS = 9;

  function addTeamMember(save, charId) {
    var cid = Number(charId);
    if (!Number.isInteger(cid) || cid < 1) throw new Error("동행 대원 번호가 올바르지 않습니다.");
    var team = save.m_teamMemberList || (save.m_teamMemberList = []);
    if (team.indexOf(cid) >= 0) return false;
    if (team.length >= MAX_TEAM_MEMBERS) throw new Error("동행 대원은 최대 9명까지만 편성할 수 있습니다.");
    team.push(cid);
    return true;
  }
  var ITEM_DEFAULTS = {
    m_iItemID: 0, m_strItemName: "", m_iItemKind: 0, m_iItemType: 0,
    m_strIcon: "i00001", m_strTip: "", m_iItemBuy: 0, m_iItemSell: 0,
    m_iItemStack: 0, m_iMixStack: 999, m_iItemUse: 0, m_iUseTime: 0,
    m_iAddType: 0, m_iUseMsgID: 0, m_iArtistryID: 0, m_iAmsType: 0,
    m_strNpcLikeList: [], m_UseLimitNodeList: [], m_ItmeEffectNodeList: [],
    m_strStatusTip: "0", m_iLock: 0
  };

  function cat(c) { return c || defaultCatalog || {}; }
  function clone(v) { return v == null ? v : JSON.parse(JSON.stringify(v)); }
  function clampi(v, a, b) {
    var n = Math.round(Number(v) || 0);
    return n < a ? a : (n > b ? b : n);
  }

  function displayPlayerStr(s) {
    return String(s == null ? "" : s).replace(/\r+$/g, "");
  }
  function encodePlayerStr(newVal, prevVal) {
    var clean = displayPlayerStr(newVal);
    if (typeof prevVal === "string" && /\r$/.test(prevVal) && displayPlayerStr(prevVal) === clean) {
      return clean + "\r";
    }
    return clean;
  }

  function findById(list, id, key) {
    var arr = Array.isArray(list) ? list : [];
    var target = Number(id);
    for (var i = 0; i < arr.length; i++) {
      if (arr[i] && Number(arr[i][key || "id"]) === target) return arr[i];
    }
    return null;
  }

  function makeItemNode(c, id) {
    var d = findById(cat(c).items, id, "id");
    var n = d && d.node ? clone(d.node) : clone(ITEM_DEFAULTS);
    n.m_iItemID = Number(id);
    if (!n.m_strItemName) n.m_strItemName = d ? d.name : ("물품 " + id);
    if (!Array.isArray(n.m_strNpcLikeList)) n.m_strNpcLikeList = [];
    if (!Array.isArray(n.m_UseLimitNodeList)) n.m_UseLimitNodeList = [];
    if (!Array.isArray(n.m_ItmeEffectNodeList)) n.m_ItmeEffectNodeList = [];
    if (n.m_strStatusTip == null) n.m_strStatusTip = "0";
    return n;
  }

  function curveMaxExp(c, curveId, lv) {
    var expMap = cat(c).routineExp || {};
    var full = Number(expMap[String(curveId || 3)]) || 55000;
    var level = clampi(lv, 1, 10);
    return level >= 10 ? full : Math.round((full * level * level) / 100);
  }

  function propertyGroup(save, type) {
    var arr = save.m_PropertyGroupsNodeList || (save.m_PropertyGroupsNodeList = []);
    var g = findById(arr, type, "m_iType");
    if (!g) {
      g = { m_iType: Number(type), m_GroupsNodwList: [] };
      arr.push(g);
    }
    if (!Array.isArray(g.m_GroupsNodwList)) g.m_GroupsNodwList = [];
    return g;
  }

  function getPropertyNode(save, gType, idx) {
    var g = findById(save.m_PropertyGroupsNodeList, gType, "m_iType");
    return g ? findById(g.m_GroupsNodwList, idx, "m_iIndex") : null;
  }

  function setPropertyValue(save, gType, idx, val, exp) {
    var g = propertyGroup(save, gType);
    var n = findById(g.m_GroupsNodwList, idx, "m_iIndex");
    if (!n) {
      n = { m_iValue: 0, m_iIndex: Number(idx), m_iExp: 0, m_iMax: gType === 0 && idx >= 5 ? 9999 : (gType === 0 && idx < 4 ? 500 : 100) };
      g.m_GroupsNodwList.push(n);
    }
    if (val !== undefined && val !== null) n.m_iValue = clampi(val, 0, 99999);
    if (exp !== undefined && exp !== null) n.m_iExp = clampi(exp, 0, 9999999);
    return n;
  }

  function syncMartialBook(save, linkId, c) {
    var books = (cat(c).abilityBooks || []).filter(function (b) { return String(b.link) === String(linkId); });
    if (!books.length) return;
    var mList = save.m_MartialIDList || (save.m_MartialIDList = []);
    books.forEach(function (b) {
      var grp = findById(mList, b.abilityType, "m_iType");
      if (!grp) {
        grp = { m_iType: b.abilityType, m_IDList: [], m_BookNodeList: [] };
        mList.push(grp);
      }
      if (!findById(grp.m_BookNodeList, b.id, "m_iID")) {
        grp.m_BookNodeList.push({
          m_iID: b.id,
          m_iAbilityType: b.abilityType,
          m_strAbilityID: b.name,
          m_strBookMsg: b.rawMsg || b.tip || "",
          m_strBookImage: b.image || "0",
          m_sValueLink: String(b.link),
          m_iSkillful: 0
        });
      }
    });
  }

  function addOrUpdateBackpackItem(save, itemId, amount, c) {
    var list = save.m_BackpackList || (save.m_BackpackList = []);
    var id = Number(itemId);
    var qty = clampi(amount == null ? 1 : amount, 1, 99999);
    for (var i = 0; i < list.length; i++) {
      if (list[i] && list[i]._ItemDataNode && Number(list[i]._ItemDataNode.m_iItemID) === id) {
        list[i].m_iAmount = clampi((list[i].m_iAmount || 0) + qty, 1, 99999);
        return list[i];
      }
    }
    var entry = { m_iAmount: qty, _ItemDataNode: makeItemNode(c, id) };
    list.push(entry);
    return entry;
  }

  function removeBackpackIndex(save, index) {
    if (save && Array.isArray(save.m_BackpackList)) save.m_BackpackList.splice(Number(index), 1);
  }

  function addOrUpdateRoutine(save, routineId, lv, c) {
    var list = save.m_PlayerRoutineNodeList || (save.m_PlayerRoutineNodeList = []);
    var id = Number(routineId);
    var d = findById(cat(c).routines, id, "id");
    var level = clampi(lv == null ? 10 : lv, 1, 10);
    var exp = curveMaxExp(c, d ? d.expCurve : 3, level);
    var existing = findById(list, id, "m_iRoutineID");
    if (existing) {
      existing.m_iLV = level;
      existing.m_iAccumulationExp = Math.max(existing.m_iAccumulationExp || 0, exp);
      return existing;
    }
    var entry = {
      m_iRoutineID: id,
      m_strRoutineName: d ? d.name : ("투로 " + id),
      m_iWearAmsType: d ? Number(d.wearAmsType || 1) : 1,
      m_iAccumulationExp: exp,
      m_iLV: level
    };
    list.push(entry);
    if (!save.m_iRoutineID) save.m_iRoutineID = id;
    syncMartialBook(save, id, c);
    return entry;
  }

  function removeRoutine(save, routineId) {
    if (!save || !Array.isArray(save.m_PlayerRoutineNodeList)) return;
    var id = Number(routineId);
    save.m_PlayerRoutineNodeList = save.m_PlayerRoutineNodeList.filter(function (x) { return Number(x.m_iRoutineID) !== id; });
    if (Number(save.m_iRoutineID) === id) {
      save.m_iRoutineID = save.m_PlayerRoutineNodeList[0] ? save.m_PlayerRoutineNodeList[0].m_iRoutineID : 0;
    }
  }

  function addOrUpdateNeigong(save, neigongId, lv, c) {
    var list = save.m_PlayerNeigongNodeList || (save.m_PlayerNeigongNodeList = []);
    var id = Number(neigongId);
    var d = findById(cat(c).neigongs, id, "id");
    var level = clampi(lv == null ? 10 : lv, 1, 10);
    var curve = d ? Number(d.expCurve || 1) : 1;
    var exp = curveMaxExp(c, curve, level);
    var existing = findById(list, id, "m_iNeigongID");
    if (existing) {
      existing.m_iLV = level;
      existing.m_iAccumulationExp = Math.max(existing.m_iAccumulationExp || 0, exp);
      return existing;
    }
    var entry = {
      m_iNeigongID: id,
      m_iLV: level,
      m_iAccumulationExp: exp,
      m_strStatusImage: (d && d.statusImage) || "NeigongImage22",
      m_strSelectImage: (d && d.selectImage) || "NeigongImage02",
      m_strNeigongName: d ? d.name : ("심법 " + id),
      m_iExp: curve
    };
    list.push(entry);
    if (!save.m_iNeigongID) save.m_iNeigongID = id;
    syncMartialBook(save, id, c);
    return entry;
  }

  function removeNeigong(save, neigongId) {
    if (!save || !Array.isArray(save.m_PlayerNeigongNodeList)) return;
    var id = Number(neigongId);
    save.m_PlayerNeigongNodeList = save.m_PlayerNeigongNodeList.filter(function (x) { return Number(x.m_iNeigongID) !== id; });
    if (Number(save.m_iNeigongID) === id) {
      save.m_iNeigongID = save.m_PlayerNeigongNodeList[0] ? save.m_PlayerNeigongNodeList[0].m_iNeigongID : 0;
    }
  }

  function setNpcFriendship(save, npcId, val) {
    var list = save.m_NpcFriendlyNodeList || (save.m_NpcFriendlyNodeList = []);
    var id = Number(npcId);
    var v = clampi(val, -1, 100);
    var existing = findById(list, id, "m_iNpcID");
    if (existing) {
      existing.m_iFriendly = v;
      return existing;
    }
    var entry = { m_iNpcID: id, m_iFriendly: v };
    list.push(entry);
    return entry;
  }

  function createDemoSave(c) {
    var cg = cat(c);
    var baseVals = [80, 150, 75, 120, 80, 2800, 1900];
    var groups = (cg.propertyGroups || []).map(function (g) {
      return {
        m_iType: g.type,
        m_GroupsNodwList: (g.attrs || []).map(function (a, idx) {
          var v = g.type === 0 ? (baseVals[idx] || 50) : 45;
          var e = g.type === 0 ? (idx === 4 ? 50000 : 0) : 12000;
          return { m_iValue: v, m_iIndex: a.index, m_iExp: e, m_iMax: a.max };
        })
      };
    });
    var save = {
      m_strVersion: "1.0.3.1",
      m_strPlayerName: "미명\r",
      m_strPlayerLastName: "동방\r",
      m_PlayerIconID: "900005",
      m_iMoney: 52500,
      m_strModelName: "Player",
      m_fTalkRange: 2, m_fStopRange: 0.1, m_fWalkRange: 0.1,
      m_fNowX: 0, m_fNowY: 0, m_fNowZ: 0,
      m_iNowTime: 5, m_fDir: 0, m_fNowTime: 8,
      m_strSceneName: "Develop",
      m_iFre: 0,
      m_iTalent1ID: 102, m_iTalent2ID: 213, m_iTalent3ID: 301,
      m_iPlayBout: 1, m_iMonth: 3, m_iMonthInterval: 1, m_iYear: 2, m_iSeason: 0,
      m_iPhysical: 10, m_iMood: 4, m_iPlotRound: 30,
      m_iAttack: 180, m_iDefense: 320, m_iCritical: 5, m_iDodge: 5, m_iConter: 5,
      m_iDefendCritical: 0, m_iDefendConter: 0,
      m_iEquipAddReal: 0, m_iEquipAddWushu: 0, m_iEquipAddEthics: 0, m_iEquipAddReputation: 0,
      m_iEquipAddSavvy: 0, m_iEquipAddHp: 0, m_iEquipAddMp: 0,
      m_iEquipAddAttack: 0, m_iEquipAddDefense: 0, m_iEquipAddCritical: 0,
      m_iEquipAddDodge: 0, m_iEquipAddConter: 0, m_iEquipDefendCritical: 0, m_iEquipDefendConter: 0,
      m_iEquipAddBuff: 0,
      m_PropertyGroupsNodeList: groups,
      m_BackpackList: [],
      m_CollectionList: [], m_QuestList: [], m_EventList: [],
      m_TitleIDList: [10001, 10002], m_iTitleID: 10002,
      m_iRoutineID: 70016, m_PlayerRoutineNodeList: [],
      m_PlayerNeigongNodeList: [], m_iNeigongID: 60001,
      m_DevelopQuestList: [], m_LotusBtnIDList: [],
      m_DevelopBtnStatusList: (cg.developBtns || []).slice(0, 38).map(function (b) {
        return { m_iBtnID: b.id, m_bStatus: true };
      }),
      m_YearCourdeNodeList: [1, 2, 3, 4, 5, 6].map(function (y) { return { m_iYear: y, m_CourdeNodeList: [] }; }),
      m_MartialIDList: [], m_AbilityIDList: [],
      m_iWeaponsID: 0, m_iEquipID: 0, m_iAccessoriesID: 0,
      m_NpcFriendlyNodeList: (cg.npcs || []).slice(0, 35).map(function (n, idx) {
        return { m_iNpcID: n.id, m_iFriendly: idx < 8 ? 50 : -1 };
      }),
      m_TreasureBoxIDList: ["M000501", "M000502"],
      m_iAutomaticIndex: 0, m_iAutomaticDIndex: 0,
      m_StoreDataNodeList: [],
      m_bInOutSideHouse: true,
      m_fInSideAbLi_r: 0, m_fInSideAbLi_g: 0, m_fInSideAbLi_b: 0, m_fInSideAbLi_a: 0,
      m_iMusicIndex: 0,
      m_teamMemberList: [10001401],
      m_TimeQuestList: [],
      m_iBattleArea: 0, m_iBattleDifficulty: 2,
      m_gGuid: GUID
    };
    addOrUpdateRoutine(save, 70001, 6, cg);
    addOrUpdateRoutine(save, 70014, 7, cg);
    addOrUpdateRoutine(save, 70016, 6, cg);
    addOrUpdateNeigong(save, 60001, 8, cg);
    addOrUpdateNeigong(save, 60003, 6, cg);
    [300009, 300005, 100359, 100051].forEach(function (iid, idx) {
      addOrUpdateBackpackItem(save, iid, idx === 3 ? 200 : 5, cg);
    });
    return save;
  }

  function createDemoRound() {
    return {
      finishGuidList: [],
      iMasterLevelCount: 1,
      iProLevelCount: 1,
      iNormalLevelCount: 1,
      iStartBegger: 0,
      achiFinishList: [10001, 30001],
      achiCountList: [{ m_iID: 10001, m_iNow: 1 }, { m_iID: 30001, m_iNow: 6 }]
    };
  }

  function createDemoGuid() {
    return {
      guid: GUID,
      iDifficulty: 2,
      openTalentList: [102, 213, 301],
      openChestList: ["M000501"],
      finishList: [],
      movieList: [],
      developQuestList: [],
      collectionQuestList: []
    };
  }

  var PRESETS = [
    { id: "max_money", kind: "save", name: "은전 최대 (9,999,999전)", desc: "보유 금전을 9,999,999전으로 설정합니다." },
    { id: "max_core_stats", kind: "save", name: "기본 속성·기혈·내력 만능", desc: "실전·무학·명성 500, 도덕·오성 100, 기혈·내력 9,999 및 전투 공방을 강화합니다." },
    { id: "max_martial_arts", kind: "save", name: "6대 기본공·10대 초식 숙련 100", desc: "기본공 6종과 초식 숙련 10종을 모두 100(최대 경험치)으로 완성합니다." },
    { id: "max_life_arts", kind: "save", name: "생산·문예 18대 기예 100", desc: "생산 기술 9종·문예 기예 9종을 100으로 완성하고 육성 행동을 개방합니다." },
    { id: "max_routines_neigongs", kind: "save", name: "보유 투로·심법 전원 10성 만렙", desc: "현재 습득한 모든 투로와 내공 심법을 10성 최대 경험치로 달성합니다." },
    { id: "max_friendship", kind: "save", name: "등장 인물 전원 생사고락 (호감도 100)", desc: "모든 주요 인물의 호감도를 100(생사고락)으로 설정합니다." },
    { id: "unlock_all_achievements", kind: "round", name: "전역 164종 업적·성당 특전 7점 해금", desc: "공식 업적 164종을 모두 완료하고 성당 다회차 특전 7점을 해금합니다." },
    { id: "unlock_guid_talents_chests", kind: "guid", name: "회차 천부·111개 보물상자 전체 개방", desc: "현재 회차의 모든 천부(25종)와 보물상자(111개)를 개방합니다." }
  ];

  function applyPreset(data, presetId, c) {
    var cg = cat(c);
    var p = PRESETS.find(function (x) { return x.id === presetId; });
    if (!p) throw new Error("알 수 없는 프리셋입니다: " + presetId);
    var kind = TWXCodec.detectKind(data);
    if (p.kind !== kind) throw new Error("현재 열린 세이브 종류에는 적용할 수 없는 프리셋입니다.");
    if (presetId === "max_money") {
      data.m_iMoney = 9999999;
    } else if (presetId === "max_core_stats") {
      var coreTargets = [500, 500, 100, 500, 100, 9999, 9999];
      for (var i = 0; i < coreTargets.length; i++) {
        setPropertyValue(data, 0, i, coreTargets[i], i === 4 ? 85700 : undefined);
      }
      data.m_iPhysical = 10;
      data.m_iMood = 5;
      data.m_iAttack = Math.max(Number(data.m_iAttack || 0), 500);
      data.m_iDefense = Math.max(Number(data.m_iDefense || 0), 800);
    } else if (presetId === "max_martial_arts") {
      [1, 2].forEach(function (gt) {
        propertyGroup(data, gt).m_GroupsNodwList.forEach(function (n) {
          n.m_iValue = Math.max(100, n.m_iMax || 100);
          n.m_iExp = Math.max(n.m_iExp || 0, 169700);
        });
      });
    } else if (presetId === "max_life_arts") {
      [3, 4].forEach(function (gt) {
        propertyGroup(data, gt).m_GroupsNodwList.forEach(function (n) {
          n.m_iValue = Math.max(100, n.m_iMax || 100);
          n.m_iExp = Math.max(n.m_iExp || 0, 85700);
        });
      });
      (data.m_DevelopBtnStatusList || []).forEach(function (b) { if (b) b.m_bStatus = true; });
    } else if (presetId === "max_routines_neigongs") {
      (data.m_PlayerRoutineNodeList || []).forEach(function (n) {
        var d = findById(cg.routines, n.m_iRoutineID, "id");
        n.m_iLV = 10;
        n.m_iAccumulationExp = Math.max(n.m_iAccumulationExp || 0, curveMaxExp(cg, d ? d.expCurve : 3, 10));
      });
      (data.m_PlayerNeigongNodeList || []).forEach(function (n) {
        n.m_iLV = 10;
        n.m_iAccumulationExp = Math.max(n.m_iAccumulationExp || 0, curveMaxExp(cg, n.m_iExp || 1, 10));
      });
    } else if (presetId === "max_friendship") {
      (data.m_NpcFriendlyNodeList || []).forEach(function (n) { if (n) n.m_iFriendly = 100; });
      (cg.npcs || []).forEach(function (n) { setNpcFriendship(data, n.id, 100); });
    } else if (presetId === "unlock_all_achievements") {
      var fin = data.achiFinishList || (data.achiFinishList = []);
      var cnt = data.achiCountList || (data.achiCountList = []);
      (cg.achievements || []).forEach(function (a) {
        var id = Number(a.id);
        if (fin.indexOf(id) < 0) fin.push(id);
        var cNode = findById(cnt, id, "m_iID");
        if (cNode) cNode.m_iNow = Math.max(cNode.m_iNow || 0, a.targetCount || 1);
        else cnt.push({ m_iID: id, m_iNow: a.targetCount || 1 });
      });
      data.iMasterLevelCount = Math.max(data.iMasterLevelCount || 0, 3);
      data.iProLevelCount = Math.max(data.iProLevelCount || 0, 2);
      data.iNormalLevelCount = Math.max(data.iNormalLevelCount || 0, 2);
      data.iStartBegger = Math.max(data.iStartBegger || 0, 1);
    } else if (presetId === "unlock_guid_talents_chests") {
      var tal = data.openTalentList || (data.openTalentList = []);
      var chs = data.openChestList || (data.openChestList = []);
      (cg.talents || []).forEach(function (t) { if (tal.indexOf(t.id) < 0) tal.push(t.id); });
      (cg.chests || []).forEach(function (ch) { if (chs.indexOf(ch.id) < 0) chs.push(ch.id); });
    }
    return { applied: presetId, kind: kind };
  }

  function summarizeSave(data, c) {
    var cg = cat(c);
    var kind = TWXCodec.detectKind(data);
    if (kind === "save") {
      var mapObj = (cg.maps || []).find(function (m) { return m.id === data.m_strSceneName; });
      return {
        kind: "save",
        headline: displayPlayerStr(data.m_strPlayerLastName) + displayPlayerStr(data.m_strPlayerName),
        details: [
          { label: "보유 금전", value: Number(data.m_iMoney || 0).toLocaleString("ko-KR") + "전" },
          { label: "일정", value: data.m_iYear + "년 " + data.m_iMonth + "월 " + ((cg.timeIntervals || [])[data.m_iMonthInterval || 0] || "초") },
          { label: "현재 장소", value: mapObj ? mapObj.name : String(data.m_strSceneName || "Develop") },
          { label: "무공·행낭", value: "투로 " + (data.m_PlayerRoutineNodeList || []).length + " · 심법 " + (data.m_PlayerNeigongNodeList || []).length + " · 물품 " + (data.m_BackpackList || []).length }
        ]
      };
    }
    if (kind === "round") {
      var temple = Math.min(7, (data.iMasterLevelCount || 0) + (data.iProLevelCount || 0) + (data.iNormalLevelCount || 0));
      return {
        kind: "round",
        headline: "전역 회차 · 업적 데이터 (Round.dat)",
        details: [
          { label: "달성 업적", value: (data.achiFinishList || []).length + " / " + (cg.achievements || []).length + "종" },
          { label: "성당 특전", value: temple + "점" }
        ]
      };
    }
    if (kind === "guid") {
      return {
        kind: "guid",
        headline: "회차 고유 기록 (" + data.guid + ")",
        details: [
          { label: "개방 천부", value: (data.openTalentList || []).length + "종" },
          { label: "개봉 상자", value: (data.openChestList || []).length + "개" }
        ]
      };
    }
    var activeSlots = (data || []).filter(function (s) { return s && s.m_bHaveData; }).length;
    return {
      kind: "title",
      headline: "세이브 슬롯 색인 (.SaveTitle)",
      details: [{ label: "기록된 슬롯", value: activeSlots + " / " + (data || []).length + "개" }]
    };
  }

  function computeDiffSummary(beforeObj, afterObj) {
    var rows = [];
    if (!beforeObj || !afterObj) return rows;
    var labels = {
      m_strPlayerLastName: "성", m_strPlayerName: "이름", m_iMoney: "금전",
      m_iYear: "연도", m_iMonth: "월", m_iMonthInterval: "순", m_iNowTime: "시진",
      m_iPhysical: "체력", m_iMood: "기분", m_strSceneName: "현재 장소",
      m_iAttack: "기본 공격력", m_iDefense: "기본 방어력", m_iTalent1ID: "제1천부",
      m_iTalent2ID: "제2천부", m_iTalent3ID: "제3천부", m_iTitleID: "칭호",
      m_iWeaponsID: "장착 무기", m_iEquipID: "장착 방어구", m_iAccessoriesID: "장착 장신구",
      m_PropertyGroupsNodeList: "41종 능력치·기예", m_PlayerRoutineNodeList: "보유 투로 목록",
      m_PlayerNeigongNodeList: "보유 심법 목록", m_BackpackList: "행낭 물품 목록",
      m_NpcFriendlyNodeList: "인물 호감도 목록", m_teamMemberList: "동료 편성",
      achiFinishList: "완료 업적 목록", achiCountList: "업적 진행도",
      openTalentList: "회차 개방 천부", openChestList: "회차 개봉 상자"
    };
    var keys = Object.keys(afterObj);
    for (var i = 0; i < keys.length && rows.length < 40; i++) {
      var k = keys[i];
      var bv = beforeObj[k], av = afterObj[k];
      if (JSON.stringify(bv) !== JSON.stringify(av)) {
        if (k === "m_PropertyGroupsNodeList" && Array.isArray(bv) && Array.isArray(av)) {
          var bMap = {}, bList = [], aList = [];
          bv.forEach(function (g) {
            if (!g || !Array.isArray(g.m_GroupsNodwList)) return;
            g.m_GroupsNodwList.forEach(function (n) {
              if (n) bMap[Number(g.m_iType) + ":" + Number(n.m_iIndex)] = n;
            });
          });
          av.forEach(function (g) {
            if (!g || !Array.isArray(g.m_GroupsNodwList)) return;
            g.m_GroupsNodwList.forEach(function (n) {
              if (!n) return;
              var gk = Number(g.m_iType) + ":" + Number(n.m_iIndex);
              var bn = bMap[gk];
              var bVal = bn ? Number(bn.m_iValue || 0) : 0;
              var bExp = bn ? Number(bn.m_iExp || 0) : 0;
              var aVal = Number(n.m_iValue || 0);
              var aExp = Number(n.m_iExp || 0);
              if (!bn || bVal !== aVal || bExp !== aExp) {
                bList.push("[" + gk + "] " + bVal + "/" + bExp);
                aList.push("[" + gk + "] " + aVal + "/" + aExp);
              }
            });
          });
          if (aList.length > 0) {
            var more = aList.length > 4 ? (" 외 " + (aList.length - 4) + "건") : "";
            rows.push({
              label: labels[k] || k,
              before: bList.slice(0, 4).join(", ") + more,
              after: aList.slice(0, 4).join(", ") + more
            });
            continue;
          }
        }
        rows.push({
          label: labels[k] || k,
          before: Array.isArray(bv) ? (bv.length + "개 항목") : (typeof bv === "object" && bv ? "객체" : displayPlayerStr(bv)),
          after: Array.isArray(av) ? (av.length + "개 항목") : (typeof av === "object" && av ? "객체" : displayPlayerStr(av))
        });
      }
    }
    return rows;
  }

  return {
    displayPlayerStr: displayPlayerStr,
    encodePlayerStr: encodePlayerStr,
    createDemoSave: createDemoSave,
    createDemoRound: createDemoRound,
    createDemoGuid: createDemoGuid,
    PRESETS: PRESETS,
    applyPreset: applyPreset,
    getPropertyNode: getPropertyNode,
    setPropertyValue: setPropertyValue,
    addOrUpdateBackpackItem: addOrUpdateBackpackItem,
    removeBackpackIndex: removeBackpackIndex,
    addOrUpdateRoutine: addOrUpdateRoutine,
    removeRoutine: removeRoutine,
    addOrUpdateNeigong: addOrUpdateNeigong,
    removeNeigong: removeNeigong,
    setNpcFriendship: setNpcFriendship,
    MAX_TEAM_MEMBERS: MAX_TEAM_MEMBERS,
    addTeamMember: addTeamMember,
    summarizeSave: summarizeSave,
    computeDiffSummary: computeDiffSummary
  };
});
