(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.TWXCodec = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var META_MAP = new WeakMap();
  var OBJ_TOKENS_MAP = new WeakMap();
  var ARR_TOKENS_MAP = new WeakMap();

  function isPlainObject(v) {
    return v !== null && typeof v === "object" && !Array.isArray(v) && Object.prototype.toString.call(v) === "[object Object]";
  }
  function has(v, k) {
    return v !== null && typeof v === "object" && Object.prototype.hasOwnProperty.call(v, k);
  }
  function fail(msg) {
    throw new Error(msg);
  }

  function hasUnpairedSurrogate(str) {
    if (typeof str !== "string") return false;
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      if (c >= 0xD800 && c <= 0xDBFF) {
        if (i + 1 >= str.length) return true;
        var d = str.charCodeAt(i + 1);
        if (d < 0xDC00 || d > 0xDFFF) return true;
        i++;
      } else if (c >= 0xDC00 && c <= 0xDFFF) {
        return true;
      }
    }
    return false;
  }

  function assertNoUnpairedSurrogates(val, seen) {
    seen = seen || new WeakSet();
    if (typeof val === "string") {
      if (hasUnpairedSurrogate(val)) fail("유효하지 않은 유니코드 대리쌍이 포함되어 있습니다.");
      return;
    }
    if (val === null || typeof val !== "object") return;
    if (seen.has(val)) return;
    seen.add(val);
    if (Array.isArray(val)) {
      var akeys = Object.keys(val);
      for (var i = 0; i < akeys.length; i++) {
        var ak = akeys[i];
        if (hasUnpairedSurrogate(ak)) fail("유효하지 않은 유니코드 대리쌍이 포함되어 있습니다.");
        var ad = Object.getOwnPropertyDescriptor(val, ak);
        var av = (ad && Object.prototype.hasOwnProperty.call(ad, "value")) ? ad.value : val[ak];
        assertNoUnpairedSurrogates(av, seen);
      }
      return;
    }
    if (isPlainObject(val)) {
      var keys = Object.keys(val);
      for (var j = 0; j < keys.length; j++) {
        var k = keys[j];
        if (hasUnpairedSurrogate(k)) fail("유효하지 않은 유니코드 대리쌍이 포함되어 있습니다.");
        var desc = Object.getOwnPropertyDescriptor(val, k);
        var v = (desc && Object.prototype.hasOwnProperty.call(desc, "value")) ? desc.value : val[k];
        assertNoUnpairedSurrogates(v, seen);
      }
    }
  }

  function detectKind(data) {
    if (isPlainObject(data)) {
      if (has(data, "m_PropertyGroupsNodeList") || has(data, "m_strPlayerName") || has(data, "m_BackpackList")) return "save";
      if (has(data, "achiFinishList") || has(data, "finishGuidList") || has(data, "iMasterLevelCount")) return "round";
      if (has(data, "guid") && (has(data, "openTalentList") || has(data, "openChestList") || has(data, "developQuestList"))) return "guid";
    }
    if (Array.isArray(data) && (data.length === 0 || (data[0] && typeof data[0] === "object" && has(data[0], "m_bHaveData")))) {
      return "title";
    }
    return fail("지원하지 않는 세이브 데이터 형식입니다.");
  }

  function parseJsonLossless(rawText) {
    if (typeof rawText !== "string") rawText = String(rawText);
    var hasBom = rawText.charCodeAt(0) === 0xFEFF;
    var text = hasBom ? rawText.slice(1) : rawText;
    if (text.charCodeAt(0) === 0xFEFF) fail("이중 UTF-8 BOM은 허용되지 않습니다.");
    var trailingNewline = text.endsWith("\r\n") ? "\r\n" : (text.endsWith("\n") ? "\n" : "");
    var i = 0;
    var rawTokens = new Map();

    function perr() { return fail("세이브 JSON 구문이 올바르지 않습니다."); }
    function esc(s) { return s.replace(/~/g, "~0").replace(/\//g, "~1"); }
    function ws() {
      while (i < text.length) {
        var c = text.charCodeAt(i);
        if (c === 32 || c === 9 || c === 10 || c === 13) i++;
        else break;
      }
    }
    function pstring() {
      var start = i;
      if (text.charCodeAt(i) !== 34) perr();
      i++;
      var out = "";
      while (i < text.length) {
        var c = text.charCodeAt(i++);
        if (c === 34) {
          if (hasUnpairedSurrogate(out)) fail("유효하지 않은 유니코드 대리쌍이 포함되어 있습니다.");
          return { value: out, raw: text.slice(start, i) };
        }
        if (c === 92) {
          if (i >= text.length) perr();
          var e = text.charAt(i++);
          if (e === '"') out += '"';
          else if (e === "\\") out += "\\";
          else if (e === "/") out += "/";
          else if (e === "b") out += "\b";
          else if (e === "f") out += "\f";
          else if (e === "n") out += "\n";
          else if (e === "r") out += "\r";
          else if (e === "t") out += "\t";
          else if (e === "u") {
            var hex = text.slice(i, i + 4);
            if (!/^[0-9a-fA-F]{4}$/.test(hex)) perr();
            var cu = parseInt(hex, 16);
            if (cu >= 0xD800 && cu <= 0xDBFF) {
              if (text.slice(i + 4, i + 6) !== "\\u") fail("유효하지 않은 유니코드 대리쌍 이스케이프입니다.");
              var lowHex = text.slice(i + 6, i + 10);
              if (!/^[0-9a-fA-F]{4}$/.test(lowHex)) fail("유효하지 않은 유니코드 대리쌍 이스케이프입니다.");
              var lowCu = parseInt(lowHex, 16);
              if (lowCu < 0xDC00 || lowCu > 0xDFFF) fail("유효하지 않은 유니코드 대리쌍 이스케이프입니다.");
              out += String.fromCharCode(cu, lowCu);
              i += 10;
            } else if (cu >= 0xDC00 && cu <= 0xDFFF) {
              fail("유효하지 않은 유니코드 대리쌍 이스케이프입니다.");
            } else {
              out += String.fromCharCode(cu);
              i += 4;
            }
          } else perr();
        } else if (c < 0x20) {
          perr();
        } else {
          out += String.fromCharCode(c);
        }
      }
      return perr();
    }
    function pnumber() {
      var start = i;
      if (text.charCodeAt(i) === 45) i++;
      if (text.charCodeAt(i) === 48) i++;
      else if (text.charCodeAt(i) >= 49 && text.charCodeAt(i) <= 57) {
        while (text.charCodeAt(i) >= 48 && text.charCodeAt(i) <= 57) i++;
      } else perr();
      if (text.charCodeAt(i) === 46) {
        i++;
        if (!(text.charCodeAt(i) >= 48 && text.charCodeAt(i) <= 57)) perr();
        while (text.charCodeAt(i) >= 48 && text.charCodeAt(i) <= 57) i++;
      }
      var c = text.charCodeAt(i);
      if (c === 69 || c === 101) {
        i++;
        c = text.charCodeAt(i);
        if (c === 43 || c === 45) i++;
        if (!(text.charCodeAt(i) >= 48 && text.charCodeAt(i) <= 57)) perr();
        while (text.charCodeAt(i) >= 48 && text.charCodeAt(i) <= 57) i++;
      }
      var raw = text.slice(start, i);
      return { value: Number(raw), raw: raw };
    }
    function plit(lit, val) {
      if (text.slice(i, i + lit.length) !== lit) perr();
      i += lit.length;
      return { value: val, raw: lit };
    }
    function bindLosslessArray(v, arrItems) {
      var metaObj = { origLen: v.length, synced: true, items: arrItems };
      ARR_TOKENS_MAP.set(v, metaObj);
      var methods = ["splice", "push", "pop", "shift", "unshift", "reverse", "sort"];
      for (var mi = 0; mi < methods.length; mi++) {
        (function (method) {
          Object.defineProperty(v, method, {
            value: function () {
              if (this !== v) {
                return Array.prototype[method].apply(this, arguments);
              }
              if (!metaObj.synced || this.length !== arrItems.length) {
                metaObj.synced = false;
                return Array.prototype[method].apply(this, arguments);
              }
              if (method === "splice") {
                if (arguments.length === 0) {
                  // no-op on arrItems
                } else if (arguments.length === 1) {
                  Array.prototype.splice.call(arrItems, arguments[0]);
                } else {
                  var mArgs = [arguments[0], arguments[1]];
                  for (var ai = 2; ai < arguments.length; ai++) {
                    mArgs.push(null);
                  }
                  Array.prototype.splice.apply(arrItems, mArgs);
                }
              } else if (method === "push") {
                for (var pi = 0; pi < arguments.length; pi++) {
                  arrItems.push(null);
                }
              } else if (method === "pop") {
                arrItems.pop();
              } else if (method === "shift") {
                arrItems.shift();
              } else if (method === "unshift") {
                if (arguments.length > 0) {
                  var uArgs = [];
                  for (var ui = 0; ui < arguments.length; ui++) {
                    uArgs.push(null);
                  }
                  Array.prototype.unshift.apply(arrItems, uArgs);
                }
              } else if (method === "reverse") {
                arrItems.reverse();
              } else if (method === "sort") {
                metaObj.synced = false;
                return Array.prototype.sort.apply(this, arguments);
              }
              return Array.prototype[method].apply(this, arguments);
            },
            writable: true,
            configurable: true,
            enumerable: false
          });
        })(methods[mi]);
      }
    }
    function pvalue(ptr) {
      ws();
      var c = text.charAt(i), t, v;
      if (c === "{") {
        i++;
        v = {};
        var objTokens = new Map();
        OBJ_TOKENS_MAP.set(v, objTokens);
        ws();
        if (text.charAt(i) === "}") { i++; return { value: v, raw: null }; }
        while (true) {
          ws();
          if (text.charAt(i) !== '"') perr();
          t = pstring();
          var key = t.value;
          ws();
          if (text.charAt(i) !== ":") perr();
          i++;
          var child = pvalue(ptr + "/" + esc(key));
          if (child.raw !== null) objTokens.set(key, { value: child.value, raw: child.raw });
          else objTokens.delete(key);
          Object.defineProperty(v, key, {
            value: child.value,
            writable: true,
            enumerable: true,
            configurable: true
          });
          ws();
          var d = text.charAt(i);
          if (d === ",") { i++; continue; }
          if (d === "}") { i++; break; }
          perr();
        }
        return { value: v, raw: null };
      }
      if (c === "[") {
        i++;
        v = [];
        var arrItems = [];
        ws();
        if (text.charAt(i) === "]") {
          i++;
          bindLosslessArray(v, arrItems);
          return { value: v, raw: null };
        }
        var n = 0;
        while (true) {
          var elem = pvalue(ptr + "/" + n++);
          v.push(elem.value);
          arrItems.push(elem.raw !== null ? { value: elem.value, raw: elem.raw } : null);
          ws();
          var a = text.charAt(i);
          if (a === ",") { i++; continue; }
          if (a === "]") { i++; break; }
          perr();
        }
        bindLosslessArray(v, arrItems);
        return { value: v, raw: null };
      }
      if (c === '"') { t = pstring(); rawTokens.set(ptr, { value: t.value, raw: t.raw }); return t; }
      if (c === "-" || (c >= "0" && c <= "9")) { t = pnumber(); rawTokens.set(ptr, { value: t.value, raw: t.raw }); return t; }
      if (c === "t") { t = plit("true", true); rawTokens.set(ptr, { value: t.value, raw: t.raw }); return t; }
      if (c === "f") { t = plit("false", false); rawTokens.set(ptr, { value: t.value, raw: t.raw }); return t; }
      if (c === "n") { t = plit("null", null); rawTokens.set(ptr, { value: t.value, raw: t.raw }); return t; }
      return perr();
    }

    var rootRes = pvalue("");
    var root = rootRes.value;
    ws();
    if (i !== text.length) perr();
    var meta = { hasBom: hasBom, trailingNewline: trailingNewline, rawTokens: rawTokens };
    if (root && typeof root === "object") {
      META_MAP.set(root, meta);
    }
    return { data: root, meta: meta };
  }

  function encodeJsonFxString(str) {
    str = String(str);
    if (hasUnpairedSurrogate(str)) fail("유효하지 않은 유니코드 대리쌍은 직렬화할 수 없습니다.");
    var out = '"';
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      if (c === 34) out += '\\"';
      else if (c === 92) out += "\\\\";
      else if (c === 8) out += "\\b";
      else if (c === 12) out += "\\f";
      else if (c === 10) out += "\\n";
      else if (c === 13) out += "\\r";
      else if (c === 9) out += "\\t";
      else if (c === 0x3C) out += "\\u003C";
      else if (c < 0x20 || c > 0x7E) out += "\\u" + c.toString(16).toUpperCase().padStart(4, "0");
      else out += str[i];
    }
    return out + '"';
  }

  function serializeJsonLossless(data, metaOverride) {
    var meta = metaOverride || (data && typeof data === "object" && META_MAP.get(data)) || { hasBom: false, trailingNewline: "", rawTokens: new Map() };
    var rt = meta.rawTokens;
    function isPrim(v) { return v === null || typeof v === "string" || typeof v === "number" || typeof v === "boolean"; }
    function isSafePrim(v) { return isPrim(v) && !hasUnpairedSurrogate(v); }
    function isSafeRawToken(tok, v) {
      return tok && typeof tok.raw === "string" && isSafePrim(v) && Object.is(tok.value, v) && !hasUnpairedSurrogate(tok.raw);
    }
    function encPrim(val) {
      if (val === null) return "null";
      if (typeof val === "string") return encodeJsonFxString(val);
      if (typeof val === "number") {
        if (!Number.isFinite(val)) fail("유효하지 않은 수치(NaN/Infinity)는 직렬화할 수 없습니다.");
        return String(val);
      }
      if (typeof val === "boolean") return String(val);
      return fail("지원하지 않는 JSON 값입니다.");
    }
    function enc(val) {
      if (Array.isArray(val)) {
        var at = ARR_TOKENS_MAP.get(val);
        var parts = [];
        if (at && at.synced && Array.isArray(at.items) && val.length === at.items.length) {
          for (var i = 0; i < val.length; i++) {
            var elem = val[i];
            if (isSafeRawToken(at.items[i], elem)) {
              parts.push(at.items[i].raw);
            } else {
              parts.push(enc(elem));
            }
          }
        } else if (at && Array.isArray(at.items)) {
          var used = new Array(at.items.length);
          var cursor = 0;
          for (var i = 0; i < val.length; i++) {
            var elem = val[i];
            var matchedRaw = null;
            if (isSafePrim(elem)) {
              var foundK = -1;
              for (var step = 0; step < at.items.length; step++) {
                var k = (cursor + step) % at.items.length;
                if (!used[k] && isSafeRawToken(at.items[k], elem)) {
                  foundK = k;
                  break;
                }
              }
              if (foundK >= 0) {
                used[foundK] = true;
                if (foundK >= cursor) cursor = foundK + 1;
                matchedRaw = at.items[foundK].raw;
              }
            }
            parts.push(matchedRaw !== null ? matchedRaw : enc(elem));
          }
        } else {
          for (var i = 0; i < val.length; i++) {
            parts.push(enc(val[i]));
          }
        }
        return "[" + parts.join(",") + "]";
      }
      if (val !== null && typeof val === "object") {
        var ot = OBJ_TOKENS_MAP.get(val);
        var keys = Object.keys(val), out = [];
        for (var j = 0; j < keys.length; j++) {
          var k = keys[j];
          var desc = Object.getOwnPropertyDescriptor(val, k);
          var pv = (desc && Object.prototype.hasOwnProperty.call(desc, "value")) ? desc.value : val[k];
          var tok = ot && isSafePrim(pv) ? ot.get(k) : null;
          var encodedVal = isSafeRawToken(tok, pv) ? tok.raw : enc(pv);
          out.push(encodeJsonFxString(k) + ":" + encodedVal);
        }
        return "{" + out.join(",") + "}";
      }
      return encPrim(val);
    }
    var rootOut;
    if (rt && rt.has("") && isSafeRawToken(rt.get(""), data)) {
      rootOut = rt.get("").raw;
    } else {
      rootOut = enc(data);
    }
    return (meta.hasBom ? "\uFEFF" : "") + rootOut + (meta.trailingNewline || "");
  }

  function validateData(data, expectedKind) {
    assertNoUnpairedSurrogates(data);
    var kind = detectKind(data);
    if (expectedKind && kind !== expectedKind) fail("예상한 세이브 형식(" + expectedKind + ")과 일치하지 않습니다.");
    function reqInt(v, min, max, label) {
      if (!Number.isInteger(v) || v < min || v > max) fail(label + " 수치 범위가 올바르지 않습니다.");
    }
    function reqStr(v, label, nonEmpty) {
      if (typeof v !== "string" || (nonEmpty && !v.length)) fail(label + " 문자열 값이 올바르지 않습니다.");
    }
    function reqArr(v, label) {
      if (!Array.isArray(v)) fail(label + " 목록 형식이 올바르지 않습니다.");
    }
    if (kind === "save") {
      reqInt(data.m_iMoney, 0, 999999999, "금전(m_iMoney)");
      reqInt(data.m_iYear, 1, 20, "연도(m_iYear)");
      reqInt(data.m_iMonth, 1, 12, "월(m_iMonth)");
      reqInt(data.m_iMonthInterval, 0, 4, "순(m_iMonthInterval)");
      reqInt(data.m_iNowTime, 1, 12, "시진(m_iNowTime)");
      reqInt(data.m_iPhysical, 0, 999, "체력(m_iPhysical)");
      reqInt(data.m_iMood, 0, 999, "기분(m_iMood)");
      if (has(data, "m_iBattleDifficulty")) reqInt(data.m_iBattleDifficulty, 0, 3, "전투 난이도(m_iBattleDifficulty)");
      reqStr(data.m_strPlayerName, "이름(m_strPlayerName)");
      reqStr(data.m_strPlayerLastName, "성(m_strPlayerLastName)");
      reqArr(data.m_PropertyGroupsNodeList, "속성 그룹(m_PropertyGroupsNodeList)");
      data.m_PropertyGroupsNodeList.forEach(function (g, gi) {
        if (!g || typeof g !== "object" || Array.isArray(g)) fail("속성 그룹[" + gi + "] 객체 오류");
        reqInt(g.m_iType, 0, 99, "속성 그룹 종류");
        reqArr(g.m_GroupsNodwList, "속성 노드 목록(m_GroupsNodwList)");
        g.m_GroupsNodwList.forEach(function (n, ni) {
          var p = "속성[" + gi + ":" + ni + "]";
          if (!n || typeof n !== "object" || Array.isArray(n)) fail(p + " 객체 오류");
          reqInt(n.m_iValue, 0, Number.MAX_SAFE_INTEGER, p + ".m_iValue");
          reqInt(n.m_iIndex, 0, Number.MAX_SAFE_INTEGER, p + ".m_iIndex");
          reqInt(n.m_iExp, 0, Number.MAX_SAFE_INTEGER, p + ".m_iExp");
          reqInt(n.m_iMax, 0, Number.MAX_SAFE_INTEGER, p + ".m_iMax");
        });
      });
      reqArr(data.m_PlayerRoutineNodeList, "보유 투로(m_PlayerRoutineNodeList)");
      data.m_PlayerRoutineNodeList.forEach(function (n, idx) {
        var p = "투로[" + idx + "]";
        if (!n || typeof n !== "object" || Array.isArray(n)) fail(p + " 객체 오류");
        reqInt(n.m_iRoutineID, 1, Number.MAX_SAFE_INTEGER, p + ".m_iRoutineID");
        reqInt(n.m_iLV, 1, 10, p + ".m_iLV");
        reqInt(n.m_iAccumulationExp, 0, Number.MAX_SAFE_INTEGER, p + ".m_iAccumulationExp");
      });
      reqArr(data.m_PlayerNeigongNodeList, "보유 심법(m_PlayerNeigongNodeList)");
      data.m_PlayerNeigongNodeList.forEach(function (n, idx) {
        var p = "심법[" + idx + "]";
        if (!n || typeof n !== "object" || Array.isArray(n)) fail(p + " 객체 오류");
        reqInt(n.m_iNeigongID, 1, Number.MAX_SAFE_INTEGER, p + ".m_iNeigongID");
        reqInt(n.m_iLV, 1, 10, p + ".m_iLV");
        reqInt(n.m_iAccumulationExp, 0, Number.MAX_SAFE_INTEGER, p + ".m_iAccumulationExp");
      });
      reqArr(data.m_BackpackList, "행낭(m_BackpackList)");
      data.m_BackpackList.forEach(function (n, idx) {
        var p = "행낭[" + idx + "]";
        if (!n || typeof n !== "object" || Array.isArray(n)) fail(p + " 객체 오류");
        reqInt(n.m_iAmount, 1, Number.MAX_SAFE_INTEGER, p + ".m_iAmount");
        var d = n._ItemDataNode;
        if (!d || typeof d !== "object" || Array.isArray(d)) fail(p + "._ItemDataNode 객체 오류");
        reqInt(d.m_iItemID, 1, Number.MAX_SAFE_INTEGER, p + ".m_iItemID");
        reqArr(d.m_ItmeEffectNodeList, p + ".m_ItmeEffectNodeList");
      });
      reqArr(data.m_NpcFriendlyNodeList, "우호도(m_NpcFriendlyNodeList)");
      data.m_NpcFriendlyNodeList.forEach(function (n, idx) {
        var p = "우호도[" + idx + "]";
        if (!n || typeof n !== "object" || Array.isArray(n)) fail(p + " 객체 오류");
        reqInt(n.m_iNpcID, 1, Number.MAX_SAFE_INTEGER, p + ".m_iNpcID");
        reqInt(n.m_iFriendly, -1, 999, p + ".m_iFriendly");
      });
      if (has(data, "m_teamMemberList")) {
        reqArr(data.m_teamMemberList, "동행 대원(m_teamMemberList)");
        if (data.m_teamMemberList.length > 9) {
          fail("동행 대원(m_teamMemberList)은 최대 9명까지 편성할 수 있습니다.");
        }
        data.m_teamMemberList.forEach(function (cid, idx) {
          reqInt(cid, 1, Number.MAX_SAFE_INTEGER, "동행 대원 번호");
        });
      }
    } else if (kind === "round") {
      reqInt(data.iMasterLevelCount, 0, Number.MAX_SAFE_INTEGER, "iMasterLevelCount");
      reqInt(data.iProLevelCount, 0, Number.MAX_SAFE_INTEGER, "iProLevelCount");
      reqInt(data.iNormalLevelCount, 0, Number.MAX_SAFE_INTEGER, "iNormalLevelCount");
      reqInt(data.iStartBegger, 0, Number.MAX_SAFE_INTEGER, "iStartBegger");
      reqArr(data.achiFinishList, "achiFinishList");
      reqArr(data.achiCountList, "achiCountList");
      data.achiCountList.forEach(function (n, idx) {
        var p = "achiCountList[" + idx + "]";
        if (!n || typeof n !== "object" || Array.isArray(n)) fail(p + " 객체 오류");
        reqInt(n.m_iID, 1, Number.MAX_SAFE_INTEGER, p + ".m_iID");
        reqInt(n.m_iNow, 0, Number.MAX_SAFE_INTEGER, p + ".m_iNow");
      });
    } else if (kind === "guid") {
      reqStr(data.guid, "guid", true);
      reqInt(data.iDifficulty, 0, 3, "iDifficulty");
      reqArr(data.openTalentList, "openTalentList");
      reqArr(data.openChestList, "openChestList");
    } else if (kind === "title") {
      reqArr(data, "title");
      if (data.length < 1 || data.length > 20) fail("세이브 타이틀 배열 길이가 올바르지 않습니다.");
      data.forEach(function (n, idx) {
        if (!n || typeof n !== "object" || Array.isArray(n) || typeof n.m_bHaveData !== "boolean") {
          fail("타이틀[" + idx + "].m_bHaveData 값이 올바르지 않습니다.");
        }
      });
    }
    return { ok: true, kind: kind };
  }

  function companionTitleTarget(saveFileName) {
    var base = String(saveFileName || "").replace(/^.*[/\\]/, "");
    var m = base.match(/^Save(0|[1-9]|1[0-9])\.Save$/i);
    if (m) return { titleFile: "SaveTitle.SaveTitle", index: +m[1] };
    m = base.match(/^AutomaticSave(0|[1-9]|1[0-9])\.Save$/i);
    if (m) return { titleFile: "SaveAutomaticTitle.SaveTitle", index: +m[1] };
    m = base.match(/^AutomaticDSave(0|[1-9]|1[0-9])\.Save$/i);
    if (m) return { titleFile: "SaveAutomaticDTitle.SaveTitle", index: +m[1] };
    return null;
  }

  function syncSaveTitleSlot(titleArray, slotIndex, saveData) {
    if (!Array.isArray(titleArray) || !Number.isInteger(slotIndex) || slotIndex < 0 || slotIndex >= titleArray.length) {
      fail("세이브 타이틀 슬롯 인덱스가 올바르지 않습니다.");
    }
    var t = titleArray[slotIndex];
    if (!t || typeof t !== "object" || Array.isArray(t)) fail("세이브 타이틀 항목 객체가 올바르지 않습니다.");
    saveData = saveData || {};
    var intervals = ["초", "상순", "중순", "하순", "말"];
    var scene = String(saveData.m_strSceneName || "Develop");
    t.m_bHaveData = true;
    t.m_strPlayerName = String(saveData.m_strPlayerLastName || "") + String(saveData.m_strPlayerName || "");
    t.m_strPlaceName = scene;
    t.m_strYear = String(saveData.m_iYear || 1);
    t.m_strPlayerIconName = String(saveData.m_PlayerIconID || "900005");
    if (scene === "Develop") {
      t.m_strTime = "";
      t.m_strMonth = String(saveData.m_iMonth || 1) + "월\r" + (intervals[saveData.m_iMonthInterval || 0] || "초") + "\r";
    }
    if (!t.m_strTrueTime) t.m_strTrueTime = "12\uFF1A00";
    if (!t.m_strTrueYear) t.m_strTrueYear = "2026/11/18";
    return titleArray;
  }

  function simulateCombatDamage(opts) {
    opts = opts || {};
    var atk = Math.max(0, Number(opts.playerAttack !== undefined ? opts.playerAttack : opts.atk) || 0);
    var def = Math.max(0, Number(opts.targetDefense !== undefined ? opts.targetDefense : opts.def) || 0);
    var lv = Math.min(10, Math.max(1, Math.round(Number(opts.routineLevel !== undefined ? opts.routineLevel : opts.lv) || 10)));
    var skillDamage = Math.max(0, Number(opts.skillDamage) || 0);
    var bonusPercent = Number(opts.bonusPercent) || 0;
    var outOfSp = Boolean(opts.outOfSp);
    var ignoreDefense = Boolean(opts.ignoreDefense);
    var isCrit = Boolean(opts.isCrit !== undefined ? opts.isCrit : opts.critical);
    var atkBonus = Math.min(1000, atk) * 0.3 + (atk <= 10000 ? Math.sqrt(atk) * 10 : 0);
    var routineScale = lv * 0.1;
    var baseRaw = (skillDamage * routineScale + atkBonus) * (1 + bonusPercent * 0.01) * (outOfSp ? 0.1 : 1.0);
    var defRatio = ignoreDefense ? 0 : (Math.sqrt(def) * 0.01 + Math.min(1000, def) * 0.0003);
    var reductionPercent = Math.min(100, Math.round(defRatio * 10000) / 100);
    function applyMitigation(raw) {
      if (!ignoreDefense && defRatio >= 1.0) return 1;
      return Math.max(1, Math.round(raw * (ignoreDefense ? 1.0 : (1.0 - defRatio))));
    }
    var normalDamage = applyMitigation(baseRaw);
    var critMinDamage = applyMitigation(baseRaw * 1.5);
    var critMaxDamage = applyMitigation(baseRaw * 2.0);
    var critAvgDamage = applyMitigation(baseRaw * 1.75);
    return {
      routineScale: routineScale,
      playerAttackBonus: Math.round(atkBonus * 100) / 100,
      defRatio: Math.round(defRatio * 10000) / 10000,
      reductionPercent: reductionPercent,
      normalDamage: normalDamage,
      critMinDamage: critMinDamage,
      critMaxDamage: critMaxDamage,
      critAvgDamage: critAvgDamage,
      selectedDamage: isCrit ? critAvgDamage : normalDamage
    };
  }

  function expectedSlotKind(fileName) {
    var base = String(fileName || "").replace(/^.*[/\\]/, "");
    var m = base.match(/^(?:Save|AutomaticSave|AutomaticDSave)(0|[1-9]|1[0-9])\.Save$/i);
    if (m) return "save";
    if (/^Round\.dat$/i.test(base)) return "round";
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(base)) return "guid";
    if (/\.SaveTitle$/i.test(base)) return "title";
    return null;
  }

  return {
    detectKind: detectKind,
    expectedSlotKind: expectedSlotKind,
    parseJsonLossless: parseJsonLossless,
    encodeJsonFxString: encodeJsonFxString,
    serializeJsonLossless: serializeJsonLossless,
    validateData: validateData,
    companionTitleTarget: companionTitleTarget,
    syncSaveTitleSlot: syncSaveTitleSlot,
    simulateCombatDamage: simulateCombatDamage
  };
});
