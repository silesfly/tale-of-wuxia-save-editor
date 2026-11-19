(function (window) {
  "use strict";

  var catalog = window.TWX_CATALOG || {};
  var codec = window.TWXCodec;
  var core = window.TWXEditorCore;

  var state = {
    kind: "save",
    rawText: "",
    data: null,
    beforeSnap: null,
    meta: null,
    fileName: "Save0.Save",
    slot: "",
    slotReqSeq: 0,
    sessionRevision: 0,
    slots: [],
    backups: [],
    bridgeConnected: false,
    bridgeToken: "",
    theme: "auto",
    activeTab: 0,
    itemQuery: "",
    itemKind: "all",
    npcQuery: "",
    achQuery: "",
    baseSha256: ""
  };

  function $(id) { return document.getElementById(id); }
  function clear(node) { if (node) node.replaceChildren(); }

  function el(tag, props, kids) {
    var n = document.createElement(tag);
    if (props) {
      Object.keys(props).forEach(function (k) {
        var v = props[k];
        if (v == null || v === false) return;
        if (k === "className") n.className = v;
        else if (k === "text") n.textContent = String(v);
        else if (k === "value") n.value = String(v);
        else if (k === "checked") n.checked = Boolean(v);
        else if (k === "hidden") n.hidden = Boolean(v);
        else if (k.indexOf("on") === 0 && typeof v === "function") {
          n.addEventListener(k.slice(2).toLowerCase(), v);
        } else {
          n.setAttribute(k, v === true ? "" : String(v));
        }
      });
    }
    if (kids) {
      (Array.isArray(kids) ? kids : [kids]).forEach(function (c) {
        if (c == null || c === false) return;
        n.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
      });
    }
    return n;
  }

  function fieldWrap(labelText, inputNode) {
    return el("label", { className: "field" }, [el("span", { text: labelText }), inputNode]);
  }

  function tableRegion(ariaLabel, headers, rowNodes) {
    var theadRow = el("tr", null, headers.map(function (h) { return el("th", { text: h }); }));
    var tbody = el("tbody", null, rowNodes);
    return el("div", { className: "table-wrap", role: "region", tabindex: "0", "aria-label": ariaLabel }, [
      el("table", null, [el("thead", null, [theadRow]), tbody])
    ]);
  }

  function makeSelect(options, currentVal, onChange) {
    var s = el("select", { onChange: onChange });
    (options || []).forEach(function (o) {
      var opt = el("option", { value: o.id, text: o.name });
      if (String(o.id) === String(currentVal)) opt.selected = true;
      s.appendChild(opt);
    });
    return s;
  }

  function setNotice(msg, level) {
    var bar = $("notice-bar");
    if (!bar) return;
    bar.dataset.level = level || "info";
    bar.textContent = msg || "";
  }

  function clonePlain(obj) {
    return obj == null ? null : JSON.parse(JSON.stringify(obj));
  }

  function applyTheme(choice) {
    var root = document.documentElement;
    var meta = document.querySelector('meta[name="color-scheme"]');
    if (choice === "light" || choice === "dark") {
      root.dataset.theme = choice;
      if (meta) meta.setAttribute("content", choice);
    } else {
      delete root.dataset.theme;
      if (meta) meta.setAttribute("content", "light dark");
    }
    var btns = document.querySelectorAll("[data-theme-choice]");
    for (var i = 0; i < btns.length; i++) {
      var c = btns[i].getAttribute("data-theme-choice");
      btns[i].setAttribute("aria-pressed", c === choice ? "true" : "false");
    }
  }

  function initTheme() {
    var saved = "auto";
    try { saved = localStorage.getItem("twx-theme") || "auto"; } catch (e) {}
    if (saved !== "light" && saved !== "dark") saved = "auto";
    state.theme = saved;
    applyTheme(saved);
    var btns = document.querySelectorAll("[data-theme-choice]");
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener("click", function () {
        var c = this.getAttribute("data-theme-choice") || "auto";
        state.theme = c;
        try { localStorage.setItem("twx-theme", c); } catch (e) {}
        applyTheme(c);
      });
    }
  }

  function switchTab(idx, moveFocus) {
    state.activeTab = idx;
    for (var i = 0; i <= 5; i++) {
      var b = $("tab-btn-" + i);
      var p = $("tab-panel-" + i);
      var active = i === idx;
      if (b) {
        b.setAttribute("aria-selected", active ? "true" : "false");
        b.tabIndex = active ? 0 : -1;
        if (active && moveFocus) {
          b.focus();
          b.scrollIntoView({ block: "nearest", inline: "nearest" });
        }
      }
      if (p) p.hidden = !active;
    }
    renderActiveTab();
  }

  function initTabs() {
    for (var i = 0; i <= 5; i++) {
      (function (idx) {
        var btn = $("tab-btn-" + idx);
        if (!btn) return;
        btn.addEventListener("click", function () { switchTab(idx, false); });
        btn.addEventListener("keydown", function (e) {
          var next = idx;
          if (e.key === "ArrowRight") next = (idx + 1) % 6;
          else if (e.key === "ArrowLeft") next = (idx + 5) % 6;
          else if (e.key === "Home") next = 0;
          else if (e.key === "End") next = 5;
          else return;
          e.preventDefault();
          switchTab(next, true);
        });
      })(i);
    }
    document.addEventListener("input", function (e) {
      var target = e.target;
      if (!target || !target.closest) return;
      if (!target.closest('[id^="tab-panel-"]')) return;
      if (target.type === "search") return;
      if (target.id && target.id.indexOf("sim-") === 0) return;
      state.sessionRevision = (state.sessionRevision || 0) + 1;
    }, true);
    document.addEventListener("change", function (e) {
      var target = e.target;
      if (!target || !target.closest) return;
      if (!target.closest('[id^="tab-panel-"]')) return;
      if (target.type === "search") return;
      if (target.id && target.id.indexOf("sim-") === 0) return;
      state.sessionRevision = (state.sessionRevision || 0) + 1;
    }, true);
  }

  function openConfirmModal(titleText, diffRows, onConfirm) {
    var dlg = $("modal-dialog");
    var titleEl = $("modal-title");
    var bodyEl = $("modal-body");
    var cancelBtn = $("modal-cancel");
    var confirmBtn = $("modal-confirm");
    if (!dlg || !bodyEl) return;
    if (titleEl) titleEl.textContent = titleText || "변경 사항 확인";
    clear(bodyEl);

    var rows = (diffRows && diffRows.length ? diffRows : [{ label: "대상 슬롯", before: state.slot || state.fileName, after: "무손실 검증 완료" }]).map(function (r) {
      return el("tr", null, [
        el("td", { text: r.label || "" }),
        el("td", { text: r.before !== undefined ? String(r.before) : "" }),
        el("td", { text: r.after !== undefined ? String(r.after) : "" })
      ]);
    });
    bodyEl.appendChild(tableRegion("변경 항목 표", ["항목", "변경 전", "변경 후"], rows));

    function cleanup() {
      if (cancelBtn) cancelBtn.removeEventListener("click", onCancel);
      if (confirmBtn) confirmBtn.removeEventListener("click", onOk);
      dlg.removeEventListener("click", onBackdrop);
      dlg.removeEventListener("close", onClose);
    }
    function onCancel() { cleanup(); if (dlg.open) dlg.close("cancel"); dlg.returnValue = ""; }
    function onOk() {
      cleanup();
      if (dlg.open) dlg.close("confirm");
      dlg.returnValue = "";
      if (typeof onConfirm === "function") onConfirm();
    }
    function onBackdrop(e) { if (e.target === dlg) onCancel(); }
    function onClose() { dlg.returnValue = ""; cleanup(); }

    if (cancelBtn) cancelBtn.addEventListener("click", onCancel);
    if (confirmBtn) confirmBtn.addEventListener("click", onOk);
    dlg.addEventListener("click", onBackdrop);
    dlg.addEventListener("close", onClose);
    dlg.returnValue = "";
    dlg.showModal();
  }

  function bridgeHeaders(isJson) {
    var h = {};
    if (state.bridgeToken) h["X-TWX-Token"] = state.bridgeToken;
    if (isJson) h["Content-Type"] = "application/json";
    return h;
  }

  function decodeUtf8Strict(buf) {
    return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(new Uint8Array(buf));
  }

  function isInitialAutoLoadEligible(autoGuard) {
    return Boolean(autoGuard) &&
      state.sessionRevision === autoGuard.expectedRev &&
      !state.slot &&
      JSON.stringify(state.data) === autoGuard.expectedSnapJson;
  }

  function probeBridge(autoLoadInitial, expectedRev, expectedSnapJson) {
    var isLocalHttp = location.protocol === "http:" && (location.hostname === "127.0.0.1" || location.hostname === "localhost");
    var badge = $("status-badge");
    if (!isLocalHttp) {
      if (badge) badge.textContent = "오프라인 파일 모드";
      return;
    }
    var metaTok = document.querySelector('meta[name="twx-bridge-token"]');
    state.bridgeToken = metaTok ? (metaTok.getAttribute("content") || "") : "";
    var autoGuard = autoLoadInitial ? { expectedRev: expectedRev, expectedSnapJson: expectedSnapJson } : null;

    fetch("/api/slots", { headers: bridgeHeaders(false) })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (j) {
        state.bridgeConnected = true;
        state.slots = (j && j.slots) || [];
        if (badge) badge.textContent = "서버 연결됨";
        var bar = $("bridge-bar");
        if (bar) bar.hidden = false;
        var sel = $("slot-select");
        if (sel) {
          clear(sel);
          sel.appendChild(el("option", { value: "", text: "-- 로컬/예시 편집 (슬롯 미연결) --" }));
          state.slots.forEach(function (s) {
            sel.appendChild(el("option", { value: s.slot, text: s.label || s.slot }));
          });
          if (isInitialAutoLoadEligible(autoGuard)) {
            if (state.slots.length > 0) {
              var target = state.slots[0].slot;
              syncSaveBindingUI();
              loadBridgeSlot(target, autoGuard);
            } else {
              sel.value = "";
              state.slot = "";
              state.baseSha256 = "";
              syncSaveBindingUI();
              setNotice("연결된 세이브 폴더에 아직 슬롯 파일이 없습니다.", "info");
            }
          } else if (autoLoadInitial) {
            if (state.slot && !state.slots.some(function (x) { return x.slot === state.slot; })) {
              state.slot = "";
              state.baseSha256 = "";
              state.backups = [];
              if (state.activeTab === 5) renderTab5();
            }
            sel.value = state.slot || "";
            syncSaveBindingUI();
            if (state.slot && state.slots.some(function (x) { return x.slot === state.slot; })) {
              fetchBackups(state.slot, state.slotReqSeq);
            }
          } else {
            if (state.slot && state.slots.some(function (x) { return x.slot === state.slot; })) {
              sel.value = state.slot;
              syncSaveBindingUI();
              fetchBackups(state.slot, state.slotReqSeq);
              setNotice("슬롯 목록을 새로고침했습니다 (" + state.slots.length + "개).", "info");
            } else if (state.slot) {
              state.slot = "";
              state.baseSha256 = "";
              state.backups = [];
              syncSaveBindingUI();
              if (state.activeTab === 5) renderTab5();
              setNotice("현재 연결된 슬롯이 목록에 없어 연결을 해제했습니다.", "info");
            } else {
              sel.value = "";
              syncSaveBindingUI();
              setNotice("슬롯 목록을 새로고침했습니다 (" + state.slots.length + "개).", "info");
            }
          }
        }
      })
      .catch(function () {
        state.bridgeConnected = false;
        state.slot = "";
        state.baseSha256 = "";
        syncSaveBindingUI();
        if (badge) badge.textContent = "오프라인 파일 모드";
      });
  }

  function syncSaveBindingUI() {
    var sel = $("slot-select");
    if (sel) sel.value = state.slot || "";
    var bSave = $("btn-save");
    if (bSave) bSave.disabled = !(state.bridgeConnected && state.slot);
  }

  function loadBridgeSlot(slotName, autoGuard) {
    var seq = ++state.slotReqSeq;
    if (!autoGuard) {
      state.sessionRevision = (state.sessionRevision || 0) + 1;
    }
    if (!slotName) {
      state.slot = "";
      state.baseSha256 = "";
      state.backups = [];
      syncSaveBindingUI();
      if (state.activeTab === 5) renderTab5();
      return;
    }
    fetch("/api/load?slot=" + encodeURIComponent(slotName), { headers: bridgeHeaders(false) })
      .then(function (r) {
        if (!r.ok) throw new Error("슬롯 읽기 실패 (" + r.status + ")");
        var sha = (r.headers && r.headers.get("X-TWX-Sha256")) || "";
        return r.arrayBuffer().then(function (buf) {
          return { raw: decodeUtf8Strict(buf), sha: sha };
        });
      })
      .then(function (payload) {
        if (seq !== state.slotReqSeq) return;
        if (autoGuard && !isInitialAutoLoadEligible(autoGuard)) {
          syncSaveBindingUI();
          return;
        }
        if (loadRawText(payload.raw, slotName, slotName, seq, payload.sha)) {
          fetchBackups(slotName, seq);
        }
      })
      .catch(function (err) {
        if (seq !== state.slotReqSeq) return;
        if (autoGuard && !isInitialAutoLoadEligible(autoGuard)) {
          syncSaveBindingUI();
          return;
        }
        syncSaveBindingUI();
        setNotice("슬롯을 불러오지 못했습니다: " + err.message, "error");
      });
  }

  function fetchBackups(slotName, expectedSeq) {
    if (!state.bridgeConnected || !slotName) return;
    var reqSeq = expectedSeq != null ? expectedSeq : state.slotReqSeq;
    fetch("/api/backups?slot=" + encodeURIComponent(slotName), { headers: bridgeHeaders(false) })
      .then(function (r) { return r.ok ? r.json() : { backups: [] }; })
      .then(function (j) {
        if (state.slot !== slotName || state.slotReqSeq !== reqSeq) return;
        state.backups = (j && j.backups) || [];
        if (state.activeTab === 5) renderTab5();
      })
      .catch(function () {
        if (state.slot !== slotName || state.slotReqSeq !== reqSeq) return;
        state.backups = [];
        if (state.activeTab === 5) renderTab5();
      });
  }

  function restoreBackup(targetSlot, backupFile) {
    if (!state.bridgeConnected || !targetSlot || state.slot !== targetSlot || !backupFile) return;
    var reqSeq = state.slotReqSeq;
    fetch("/api/restore", {
      method: "POST",
      headers: bridgeHeaders(true),
      body: JSON.stringify({ slot: targetSlot, backup: backupFile })
    })
      .then(function (r) {
        if (r.status === 409) throw new Error("협객풍운전 실행 중에는 복원할 수 없습니다.");
        if (!r.ok) throw new Error("복원 요청 실패 (" + r.status + ")");
        return r.json();
      })
      .then(function () {
        if (state.slot !== targetSlot || state.slotReqSeq !== reqSeq) return;
        setNotice("백업 복원이 완료되었습니다: " + backupFile, "ok");
        loadBridgeSlot(targetSlot);
      })
      .catch(function (err) {
        setNotice("복원 실패: " + err.message, "error");
      });
  }

  function loadRawText(rawText, fileName, boundSlot, providedSeq, providedBaseSha, isInitialDemo) {
    var targetSlot = typeof boundSlot === "string" ? boundSlot : "";
    if (providedSeq == null) {
      state.slotReqSeq = (state.slotReqSeq || 0) + 1;
    }
    try {
      var parsed = codec.parseJsonLossless(rawText);
      var expKind = targetSlot && codec.expectedSlotKind ? codec.expectedSlotKind(targetSlot) : undefined;
      var v = codec.validateData(parsed.data, expKind || undefined);
      if (isInitialDemo !== true) {
        state.sessionRevision = (state.sessionRevision || 0) + 1;
      }
      state.slot = targetSlot;
      state.baseSha256 = targetSlot ? String(providedBaseSha || "") : "";
      state.backups = [];
      state.kind = v.kind;
      state.rawText = rawText;
      state.data = parsed.data;
      state.meta = parsed.meta;
      state.beforeSnap = clonePlain(parsed.data);
      if (fileName) state.fileName = fileName;
      syncSaveBindingUI();
      setNotice("불러오기 완료: " + state.fileName + " (" + v.kind + ")", "ok");
      if ((v.kind === "round" || v.kind === "guid") && state.activeTab !== 5) {
        renderSummaryStrip();
        renderPresetsBar();
        switchTab(5, false);
      } else {
        renderAll();
      }
      return true;
    } catch (err) {
      syncSaveBindingUI();
      setNotice("파일 검증 실패: " + (err && err.message ? err.message : String(err)), "error");
      return false;
    }
  }

  function renderSummaryStrip() {
    var box = $("summary-strip");
    if (!box || !state.data) return;
    clear(box);
    var s = core.summarizeSave(state.data, catalog);
    box.appendChild(el("div", { className: "summary-item" }, [
      el("span", { className: "k", text: "현재 파일 · 주인공" }),
      el("span", { className: "v", text: state.fileName + " · " + (s.headline || "") })
    ]));
    (s.details || []).forEach(function (d) {
      box.appendChild(el("div", { className: "summary-item" }, [
        el("span", { className: "k", text: d.label }),
        el("span", { className: "v", text: d.value })
      ]));
    });
  }

  function renderPresetsBar() {
    var bar = $("presets-bar");
    if (!bar || !state.data) return;
    clear(bar);
    (core.PRESETS || []).filter(function (p) { return p.kind === state.kind; }).forEach(function (p) {
      bar.appendChild(el("button", {
        type: "button",
        className: "preset-button",
        "data-preset-id": p.id,
        title: p.desc,
        text: p.name,
        onClick: function () {
          state.sessionRevision = (state.sessionRevision || 0) + 1;
          core.applyPreset(state.data, p.id, catalog);
          setNotice("원클릭 프리셋 적용 완료: " + p.name, "ok");
          renderAll();
        }
      }));
    });
  }

  function commitIntInput(inp, minVal, maxVal, fallback, syncDom) {
    if (!inp) return fallback;
    var vn = typeof inp.valueAsNumber === "number" ? inp.valueAsNumber : NaN;
    var raw = String(inp.value == null ? "" : inp.value).trim();
    var n = !Number.isNaN(vn) ? vn : (raw === "" ? NaN : Number(raw));
    var v = (Number.isFinite(n) && Number.isInteger(n)) ? (Object.is(n, -0) ? 0 : n) : fallback;
    if (minVal != null && v < minVal) v = minVal;
    if (maxVal != null && v > maxVal) v = maxVal;
    if (syncDom) inp.value = String(v);
    return v;
  }

  function renderTab0() {
    var p = $("tab-panel-0");
    if (!p) return;
    clear(p);
    var d = state.data;
    if (state.kind !== "save") {
      p.appendChild(el("div", { className: "card" }, [
        el("h3", { text: "비캐릭터 데이터 안내" }),
        el("p", { text: "현재 열린 파일(" + state.fileName + ")은 전역 업적(Round.dat) 또는 회차(GUID) 파일입니다. 상단 '업적 · 회차 · 백업' 탭에서 편집하세요." })
      ]));
      return;
    }
    var intervalOpts = (catalog.timeIntervals || []).map(function (nm, i) { return { id: i, name: nm }; });
    var identityCard = el("div", { className: "card" }, [
      el("h3", { text: "인물 신상 · 금전 · 일정" }),
      el("div", { className: "grid" }, [
        fieldWrap("성 (성씨)", el("input", {
          type: "text", value: core.displayPlayerStr(d.m_strPlayerLastName),
          onChange: function () { d.m_strPlayerLastName = core.encodePlayerStr(this.value, d.m_strPlayerLastName); renderSummaryStrip(); }
        })),
        fieldWrap("이름 (명)", el("input", {
          type: "text", value: core.displayPlayerStr(d.m_strPlayerName),
          onChange: function () { d.m_strPlayerName = core.encodePlayerStr(this.value, d.m_strPlayerName); renderSummaryStrip(); }
        })),
        fieldWrap("보유 금전 (전)", el("input", {
          id: "f-money",
          type: "number", min: 0, max: 999999999, value: d.m_iMoney,
          onInput: function () { d.m_iMoney = commitIntInput(this, 0, 999999999, 0, false); renderSummaryStrip(); },
          onChange: function () { d.m_iMoney = commitIntInput(this, 0, 999999999, 0, true); renderSummaryStrip(); }
        })),
        fieldWrap("연도 (1~20년)", el("input", {
          type: "number", min: 1, max: 20, value: d.m_iYear,
          onChange: function () { d.m_iYear = commitIntInput(this, 1, 20, 1, true); renderSummaryStrip(); }
        })),
        fieldWrap("월 (1~12월)", el("input", {
          type: "number", min: 1, max: 12, value: d.m_iMonth,
          onChange: function () { d.m_iMonth = commitIntInput(this, 1, 12, 1, true); renderSummaryStrip(); }
        })),
        fieldWrap("순 (초~말)", makeSelect(intervalOpts, d.m_iMonthInterval, function () {
          d.m_iMonthInterval = parseInt(this.value, 10) || 0; renderSummaryStrip();
        })),
        fieldWrap("시진", makeSelect(catalog.shichen || [], d.m_iNowTime, function () {
          d.m_iNowTime = parseInt(this.value, 10) || 1;
        })),
        fieldWrap("현재 장소", makeSelect(catalog.maps || [], d.m_strSceneName, function () {
          d.m_strSceneName = this.value; renderSummaryStrip();
        })),
        fieldWrap("전투 난이도", makeSelect(catalog.difficulties || [], d.m_iBattleDifficulty != null ? d.m_iBattleDifficulty : 1, function () {
          d.m_iBattleDifficulty = parseInt(this.value, 10) || 0;
        })),
        fieldWrap("육성 체력 (0~10)", el("input", {
          type: "number", min: 0, max: 999, value: d.m_iPhysical,
          onChange: function () { d.m_iPhysical = commitIntInput(this, 0, 999, 0, true); }
        })),
        fieldWrap("기분 (0~6)", el("input", {
          type: "number", min: 0, max: 999, value: d.m_iMood,
          onChange: function () { d.m_iMood = commitIntInput(this, 0, 999, 0, true); }
        }))
      ])
    ]);

    var combatSpecs = [
      ["m_iAttack", "기본 공격력"], ["m_iDefense", "기본 방어력"],
      ["m_iCritical", "기본 폭격률(%)"], ["m_iDodge", "기본 회피율(%)"],
      ["m_iConter", "기본 반격률(%)"], ["m_iDefendCritical", "폭격 저항(%)"],
      ["m_iDefendConter", "반격 저항(%)"]
    ];
    var combatCard = el("div", { className: "card" }, [
      el("h3", { text: "전투 기초 공방 수치" }),
      el("div", { className: "grid" }, combatSpecs.map(function (sp) {
        return fieldWrap(sp[1], el("input", {
          type: "number", min: 0, max: 99999, value: d[sp[0]] || 0,
          onChange: function () { d[sp[0]] = commitIntInput(this, 0, 99999, 0, true); }
        }));
      }))
    ]);
    p.appendChild(identityCard);
    p.appendChild(combatCard);
  }

  function renderTab1() {
    var p = $("tab-panel-1");
    if (!p) return;
    clear(p);
    if (state.kind !== "save") {
      p.appendChild(el("div", { className: "card" }, [el("p", { text: "캐릭터 세이브(.Save) 파일에서만 능력치와 천부를 편집할 수 있습니다." })]));
      return;
    }
    var d = state.data;
    var talCard = el("div", { className: "card" }, [
      el("h3", { text: "3대 천부(재능) 및 칭호" }),
      el("div", { className: "grid" }, [1, 2, 3].map(function (slotNo) {
        var key = "m_iTalent" + slotNo + "ID";
        var opts = (catalog.talents || []).filter(function (t) { return t.slot === slotNo; }).map(function (t) {
          return { id: t.id, name: t.name + " — " + (t.tip || "").slice(0, 32) };
        });
        return fieldWrap("제" + slotNo + "천부", makeSelect(opts, d[key], function () { d[key] = parseInt(this.value, 10) || 0; }));
      }).concat([
        fieldWrap("장착 칭호", makeSelect([{ id: 0, name: "칭호 없음" }].concat(catalog.titles || []), d.m_iTitleID || 0, function () {
          var tid = parseInt(this.value, 10) || 0;
          d.m_iTitleID = tid;
          if (tid > 0 && Array.isArray(d.m_TitleIDList) && d.m_TitleIDList.indexOf(tid) < 0) d.m_TitleIDList.push(tid);
        }))
      ]))
    ]);
    p.appendChild(talCard);

    (catalog.propertyGroups || []).forEach(function (grp) {
      var grid = el("div", { className: "grid" });
      (grp.attrs || []).forEach(function (attr) {
        var node = core.getPropertyNode(d, grp.type, attr.index) || { m_iValue: 0, m_iExp: 0, m_iMax: attr.max };
        var valIn = el("input", {
          type: "number", min: 0, max: Math.max(99999, node.m_iValue || 0), value: node.m_iValue,
          onChange: function () {
            var cur = core.getPropertyNode(d, grp.type, attr.index);
            var v = commitIntInput(this, 0, 99999, cur ? Number(cur.m_iValue || 0) : 0, true);
            core.setPropertyValue(d, grp.type, attr.index, v);
          }
        });
        var expIn = el("input", {
          type: "number", min: 0, max: Math.max(9999999, node.m_iExp || 0), value: node.m_iExp,
          onChange: function () {
            var cur = core.getPropertyNode(d, grp.type, attr.index);
            var e = commitIntInput(this, 0, 9999999, cur ? Number(cur.m_iExp || 0) : 0, true);
            core.setPropertyValue(d, grp.type, attr.index, undefined, e);
          }
        });
        grid.appendChild(el("div", { className: "field" }, [
          el("span", { text: attr.name + " (상한 " + attr.max + " · 수치 / 경험치)" }),
          el("div", { className: "row-inline" }, [valIn, expIn])
        ]));
      });
      p.appendChild(el("div", { className: "card" }, [el("h3", { text: grp.name }), grid]));
    });
  }

  function renderTab2() {
    var p = $("tab-panel-2");
    if (!p) return;
    clear(p);
    var d = state.data || {};

    var simCard = el("div", { className: "card", id: "combat-sim-card" }, [el("h3", { text: "REA 역공학 전투 피해 계산기" })]);
    var iSkill = el("input", { id: "sim-skill-dmg", type: "number", min: 0, value: 550 });
    var iLv = el("input", { id: "sim-routine-lv", type: "number", min: 1, max: 10, value: 10 });
    var iAtk = el("input", { id: "sim-atk", type: "number", min: 0, value: d.m_iAttack != null ? d.m_iAttack : 350 });
    var iDef = el("input", { id: "sim-def", type: "number", min: 0, value: 300 });
    var iBonus = el("input", { id: "sim-bonus-pct", type: "number", value: 0 });
    var cPierce = el("input", { id: "sim-ignore-def", type: "checkbox" });
    var cOutSp = el("input", { id: "sim-out-sp", type: "checkbox" });
    var simOut = el("div", { id: "sim-result", className: "summary-item" });

    function updateSim() {
      var r = codec.simulateCombatDamage({
        skillDamage: parseFloat(iSkill.value) || 0,
        routineLevel: commitIntInput(iLv, 1, 10, 10, false),
        playerAttack: parseFloat(iAtk.value) || 0,
        targetDefense: parseFloat(iDef.value) || 0,
        bonusPercent: parseFloat(iBonus.value) || 0,
        ignoreDefense: cPierce.checked,
        outOfSp: cOutSp.checked
      });
      simOut.textContent = "예상 일반 피해: " + r.normalDamage.toLocaleString("ko-KR") +
        " | 폭격(치명) 범위: " + r.critMinDamage.toLocaleString("ko-KR") + " ~ " + r.critMaxDamage.toLocaleString("ko-KR") +
        " | 적 방어 감쇠율: " + r.reductionPercent + "% (공격력 보정 +" + r.playerAttackBonus + ")";
    }
    [iSkill, iLv, iAtk, iDef, iBonus, cPierce, cOutSp].forEach(function (inp) {
      inp.addEventListener("input", updateSim);
      inp.addEventListener("change", updateSim);
    });
    simCard.appendChild(el("div", { className: "grid" }, [
      fieldWrap("초식 기본 위력", iSkill),
      fieldWrap("투로 성급 (1~10성)", iLv),
      fieldWrap("공격자 공격력", iAtk),
      fieldWrap("방어자 방어력", iDef),
      fieldWrap("피해 증폭 합산(%)", iBonus)
    ]));
    simCard.appendChild(el("div", { className: "toolbar" }, [
      el("label", { className: "check-line" }, [cPierce, "방어 무시(관통 초식)"]),
      el("label", { className: "check-line" }, [cOutSp, "내력 고갈 상태(위력 10%)"])
    ]));
    simCard.appendChild(simOut);
    updateSim();
    p.appendChild(simCard);

    if (state.kind !== "save") return;

    var rChoices = (catalog.routines || []).filter(function (x) { return x.playerUsable; }).map(function (x) {
      return { id: x.id, name: x.name + " (#" + x.id + ")" };
    });
    var rAddSel = makeSelect(rChoices, rChoices[0] ? rChoices[0].id : 70001);
    var rAddLv = el("input", { type: "number", min: 1, max: 10, value: 10 });
    var rActiveOpts = [{ id: 0, name: "장착 안 함" }].concat((d.m_PlayerRoutineNodeList || []).map(function (n) {
      return { id: n.m_iRoutineID, name: n.m_strRoutineName + " (" + n.m_iLV + "성)" };
    }));

    var rRows = (d.m_PlayerRoutineNodeList || []).map(function (n) {
      return el("tr", null, [
        el("td", { text: n.m_iRoutineID }),
        el("td", { text: n.m_strRoutineName }),
        el("td", null, [el("input", {
          type: "number", min: 1, max: 10, value: n.m_iLV,
          onChange: function () { core.addOrUpdateRoutine(d, n.m_iRoutineID, commitIntInput(this, 1, 10, 1, true), catalog); renderTab2(); }
        })]),
        el("td", null, [el("input", {
          type: "number", min: 0, max: 999999999, value: n.m_iAccumulationExp,
          onChange: function () { n.m_iAccumulationExp = commitIntInput(this, 0, 999999999, 0, true); }
        })]),
        el("td", null, [el("button", {
          type: "button", className: "btn", text: "삭제",
          onClick: function () { core.removeRoutine(d, n.m_iRoutineID); renderSummaryStrip(); renderTab2(); }
        })])
      ]);
    });
    p.appendChild(el("div", { className: "card" }, [
      el("h3", { text: "보유 투로(초식) 편집" }),
      el("div", { className: "row-inline" }, [
        fieldWrap("현재 장착 투로", makeSelect(rActiveOpts, d.m_iRoutineID || 0, function () { d.m_iRoutineID = parseInt(this.value, 10) || 0; })),
        fieldWrap("습득할 투로 선택", rAddSel),
        fieldWrap("성급(1~10)", rAddLv),
        el("button", { type: "button", className: "btn btn-primary", text: "투로 추가·갱신", onClick: function () {
          core.addOrUpdateRoutine(d, parseInt(rAddSel.value, 10), commitIntInput(rAddLv, 1, 10, 10, true), catalog);
          renderSummaryStrip(); renderTab2();
        } })
      ]),
      tableRegion("보유 투로 목록 표", ["번호", "투로명", "성급(1~10)", "누적 경험치", "관리"], rRows)
    ]));

    var ngChoices = (catalog.neigongs || []).filter(function (x) { return x.playerUsable; }).map(function (x) {
      return { id: x.id, name: x.name + " (#" + x.id + ")" };
    });
    var ngAddSel = makeSelect(ngChoices, ngChoices[0] ? ngChoices[0].id : 60001);
    var ngAddLv = el("input", { type: "number", min: 1, max: 10, value: 10 });
    var ngActiveOpts = [{ id: 0, name: "장착 안 함" }].concat((d.m_PlayerNeigongNodeList || []).map(function (n) {
      return { id: n.m_iNeigongID, name: n.m_strNeigongName + " (" + n.m_iLV + "성)" };
    }));
    var ngRows = (d.m_PlayerNeigongNodeList || []).map(function (n) {
      return el("tr", null, [
        el("td", { text: n.m_iNeigongID }),
        el("td", { text: n.m_strNeigongName }),
        el("td", null, [el("input", {
          type: "number", min: 1, max: 10, value: n.m_iLV,
          onChange: function () { core.addOrUpdateNeigong(d, n.m_iNeigongID, commitIntInput(this, 1, 10, 1, true), catalog); renderTab2(); }
        })]),
        el("td", null, [el("input", {
          type: "number", min: 0, max: 999999999, value: n.m_iAccumulationExp,
          onChange: function () { n.m_iAccumulationExp = commitIntInput(this, 0, 999999999, 0, true); }
        })]),
        el("td", null, [el("button", {
          type: "button", className: "btn", text: "삭제",
          onClick: function () { core.removeNeigong(d, n.m_iNeigongID); renderSummaryStrip(); renderTab2(); }
        })])
      ]);
    });
    p.appendChild(el("div", { className: "card" }, [
      el("h3", { text: "보유 내공 심법 편집" }),
      el("div", { className: "row-inline" }, [
        fieldWrap("현재 운행 심법", makeSelect(ngActiveOpts, d.m_iNeigongID || 0, function () { d.m_iNeigongID = parseInt(this.value, 10) || 0; })),
        fieldWrap("습득할 심법 선택", ngAddSel),
        fieldWrap("성급(1~10)", ngAddLv),
        el("button", { type: "button", className: "btn btn-primary", text: "심법 추가·갱신", onClick: function () {
          core.addOrUpdateNeigong(d, parseInt(ngAddSel.value, 10), commitIntInput(ngAddLv, 1, 10, 10, true), catalog);
          renderSummaryStrip(); renderTab2();
        } })
      ]),
      tableRegion("보유 내공 심법 목록 표", ["번호", "심법명", "성급(1~10)", "누적 경험치", "관리"], ngRows)
    ]));
  }

  function renderTab3() {
    var p = $("tab-panel-3");
    if (!p) return;
    clear(p);
    if (state.kind !== "save") {
      p.appendChild(el("div", { className: "card" }, [el("p", { text: "캐릭터 세이브(.Save) 파일에서만 행낭과 장비를 편집할 수 있습니다." })]));
      return;
    }
    var d = state.data;
    var allItems = catalog.items || [];
    var eqOpts = function (eqType) {
      return [{ id: 0, name: "장착 없음" }].concat(allItems.filter(function (it) {
        return it.kind === 1 && it.itemType === eqType;
      }).map(function (it) { return { id: it.id, name: it.name + " (#" + it.id + ")" }; }));
    };
    p.appendChild(el("div", { className: "card" }, [
      el("h3", { text: "현재 착용 장비" }),
      el("div", { className: "grid" }, [
        fieldWrap("무기", makeSelect(eqOpts(1), d.m_iWeaponsID || 0, function () { d.m_iWeaponsID = parseInt(this.value, 10) || 0; })),
        fieldWrap("갑옷(방어구)", makeSelect(eqOpts(2), d.m_iEquipID || 0, function () { d.m_iEquipID = parseInt(this.value, 10) || 0; })),
        fieldWrap("장신구", makeSelect(eqOpts(3), d.m_iAccessoriesID || 0, function () { d.m_iAccessoriesID = parseInt(this.value, 10) || 0; }))
      ])
    ]));

    var qLower = (state.itemQuery || "").toLowerCase();
    var filtered = allItems.filter(function (it) {
      if (state.itemKind !== "all" && String(it.kind) !== state.itemKind) return false;
      if (qLower && it.name.toLowerCase().indexOf(qLower) < 0 && String(it.id).indexOf(qLower) < 0) return false;
      return true;
    }).slice(0, 250);
    var kindOpts = [{ id: "all", name: "전체 분류" }].concat(Object.keys(catalog.itemKinds || {}).map(function (k) {
      return { id: k, name: catalog.itemKinds[k] };
    }));
    var searchIn = el("input", {
      type: "search", placeholder: "물품 이름·번호 검색", value: state.itemQuery,
      onChange: function () { state.itemQuery = this.value; renderTab3(); }
    });
    var addSel = makeSelect(filtered.map(function (it) { return { id: it.id, name: it.name + " (#" + it.id + ")" }; }), filtered[0] ? filtered[0].id : 100001);
    var qtyIn = el("input", { type: "number", min: 1, max: 99999, value: 10 });

    var bpRows = (d.m_BackpackList || []).map(function (entry, idx) {
      var node = entry._ItemDataNode || {};
      return el("tr", null, [
        el("td", { text: node.m_iItemID || 0 }),
        el("td", { text: node.m_strItemName || "-" }),
        el("td", null, [el("input", {
          type: "number", min: 1, max: 99999, value: entry.m_iAmount || 1,
          onChange: function () { entry.m_iAmount = commitIntInput(this, 1, 99999, 1, true); }
        })]),
        el("td", null, [el("button", {
          type: "button", className: "btn", text: "삭제",
          onClick: function () { core.removeBackpackIndex(d, idx); renderSummaryStrip(); renderTab3(); }
        })])
      ]);
    });

    p.appendChild(el("div", { className: "card" }, [
      el("h3", { text: "행낭 물품 추가 및 보유 목록 (" + (d.m_BackpackList || []).length + "종)" }),
      el("div", { className: "row-inline" }, [
        fieldWrap("분류 필터", makeSelect(kindOpts, state.itemKind, function () { state.itemKind = this.value; renderTab3(); })),
        fieldWrap("검색어 (입력 후 엔터)", searchIn),
        fieldWrap("추가할 물품", addSel),
        fieldWrap("수량", qtyIn),
        el("button", { type: "button", className: "btn btn-primary", text: "행낭에 추가", onClick: function () {
          if (!addSel.value) return;
          core.addOrUpdateBackpackItem(d, parseInt(addSel.value, 10), commitIntInput(qtyIn, 1, 99999, 1, true), catalog);
          renderSummaryStrip(); renderTab3();
        } })
      ]),
      tableRegion("보유 행낭 물품 표", ["물품 번호", "물품명", "보유 수량", "관리"], bpRows)
    ]));
  }

  function renderTab4() {
    var p = $("tab-panel-4");
    if (!p) return;
    clear(p);
    if (state.kind !== "save") {
      p.appendChild(el("div", { className: "card" }, [el("p", { text: "캐릭터 세이브(.Save) 파일에서만 인물 우호도와 동료를 편집할 수 있습니다." })]));
      return;
    }
    var d = state.data;
    var fMap = {};
    (d.m_NpcFriendlyNodeList || []).forEach(function (n) { fMap[n.m_iNpcID] = n.m_iFriendly; });
    var nq = (state.npcQuery || "").toLowerCase();
    var npcRows = (catalog.npcs || []).filter(function (npc) {
      return !nq || npc.name.toLowerCase().indexOf(nq) >= 0 || (npc.title || "").toLowerCase().indexOf(nq) >= 0;
    }).map(function (npc) {
      var cur = fMap[npc.id] !== undefined ? fMap[npc.id] : -1;
      return el("tr", null, [
        el("td", { text: npc.id }),
        el("td", { text: npc.name + (npc.title ? " · " + npc.title : "") }),
        el("td", null, [el("input", {
          type: "number", min: -1, max: 100, value: cur,
          onChange: function () { core.setNpcFriendship(d, npc.id, commitIntInput(this, -1, 100, 0, true)); }
        })])
      ]);
    });

    p.appendChild(el("div", { className: "card" }, [
      el("h3", { text: "등장 인물 우호도 편집 (-1: 미대면 / 100: 생사고락)" }),
      el("div", { className: "row-inline" }, [
        fieldWrap("인물 이름·별호 검색", el("input", {
          type: "search", value: state.npcQuery, placeholder: "이름 검색 후 엔터",
          onChange: function () { state.npcQuery = this.value; renderTab4(); }
        })),
        el("button", { type: "button", className: "btn btn-primary", text: "전원 호감도 100 달성", onClick: function () {
          state.sessionRevision = (state.sessionRevision || 0) + 1;
          core.applyPreset(d, "max_friendship", catalog);
          setNotice("모든 주요 인물의 호감도를 100으로 설정했습니다.", "ok");
          renderTab4();
        } })
      ]),
      tableRegion("등장 인물 우호도 표", ["번호", "이름 · 별호", "우호도 (-1~100)"], npcRows)
    ]));

    var team = Array.isArray(d.m_teamMemberList) ? d.m_teamMemberList : [];
    var compChoices = (catalog.companions || []).map(function (c) {
      return { id: c.charId, name: c.name + " (기혈 " + c.hp + " · #" + c.charId + ")" };
    });
    var compSel = makeSelect(compChoices, compChoices[0] ? compChoices[0].id : 10001401);
    var teamRows = team.map(function (cid, idx) {
      var found = (catalog.companions || []).find(function (c) { return c.charId === cid; });
      return el("tr", null, [
        el("td", { text: cid }),
        el("td", { text: found ? found.name : ("전투 단위 #" + cid) }),
        el("td", null, [el("button", {
          type: "button", className: "btn", text: "제외",
          onClick: function () {
            if (Array.isArray(d.m_teamMemberList)) {
              d.m_teamMemberList.splice(idx, 1);
              renderTab4();
            }
          }
        })])
      ]);
    });
    p.appendChild(el("div", { className: "card" }, [
      el("h3", { text: "동행 대원 편성 (" + team.length + " / 9명)" }),
      el("div", { className: "row-inline" }, [
        fieldWrap("추가할 동료 선택", compSel),
        el("button", { type: "button", className: "btn btn-primary", text: "대원에 추가", onClick: function () {
          try {
            core.addTeamMember(d, parseInt(compSel.value, 10));
            renderTab4();
          } catch (err) {
            setNotice(err.message, "error");
          }
        } })
      ]),
      tableRegion("동행 대원 목록 표", ["전투 번호", "인물명", "관리"], teamRows)
    ]));
  }

  function renderTab5() {
    var p = $("tab-panel-5");
    if (!p) return;
    clear(p);
    var d = state.data;

    if (state.kind === "round") {
      var aq = (state.achQuery || "").toLowerCase();
      var fin = d.achiFinishList || (d.achiFinishList = []);
      var cnt = d.achiCountList || (d.achiCountList = []);
      var achRows = (catalog.achievements || []).filter(function (a) {
        return !aq || a.name.toLowerCase().indexOf(aq) >= 0 || a.desc.toLowerCase().indexOf(aq) >= 0;
      }).map(function (a) {
        var done = fin.indexOf(a.id) >= 0;
        return el("tr", null, [
          el("td", null, [el("input", {
            type: "checkbox", checked: done,
            onChange: function () {
              var pos = fin.indexOf(a.id);
              if (this.checked && pos < 0) {
                fin.push(a.id);
                var cn = cnt.find(function (x) { return x.m_iID === a.id; });
                if (cn) cn.m_iNow = Math.max(cn.m_iNow || 0, a.targetCount || 1);
                else cnt.push({ m_iID: a.id, m_iNow: a.targetCount || 1 });
              } else if (!this.checked && pos >= 0) {
                fin.splice(pos, 1);
              }
              renderSummaryStrip();
            }
          })]),
          el("td", { text: a.id }),
          el("td", { text: a.name }),
          el("td", { text: a.desc })
        ]);
      });
      p.appendChild(el("div", { className: "card" }, [
        el("h3", { text: "전역 다회차 클리어 횟수 및 공식 업적 164종 (Round.dat)" }),
        el("div", { className: "grid" }, [
          fieldWrap("일대종사 클리어 횟수", el("input", { type: "number", min: 0, max: 999999999, value: d.iMasterLevelCount || 0, onChange: function () { d.iMasterLevelCount = commitIntInput(this, 0, 999999999, 0, true); renderSummaryStrip(); } })),
          fieldWrap("숙련자 클리어 횟수", el("input", { type: "number", min: 0, max: 999999999, value: d.iProLevelCount || 0, onChange: function () { d.iProLevelCount = commitIntInput(this, 0, 999999999, 0, true); renderSummaryStrip(); } })),
          fieldWrap("초심자 클리어 횟수", el("input", { type: "number", min: 0, max: 999999999, value: d.iNormalLevelCount || 0, onChange: function () { d.iNormalLevelCount = commitIntInput(this, 0, 999999999, 0, true); renderSummaryStrip(); } })),
          fieldWrap("거지 엔딩 횟수", el("input", { type: "number", min: 0, max: 999999999, value: d.iStartBegger || 0, onChange: function () { d.iStartBegger = commitIntInput(this, 0, 999999999, 0, true); } })),
          fieldWrap("업적 검색", el("input", { type: "search", value: state.achQuery, placeholder: "업적명·조건 검색 후 엔터", onChange: function () { state.achQuery = this.value; renderTab5(); } }))
        ]),
        tableRegion("공식 업적 164종 표", ["달성", "번호", "업적명", "해금 조건"], achRows)
      ]));
    } else if (state.kind === "guid") {
      var talList = d.openTalentList || (d.openTalentList = []);
      var chList = d.openChestList || (d.openChestList = []);
      p.appendChild(el("div", { className: "card" }, [
        el("h3", { text: "회차 고유 기록 편집 (" + d.guid + ")" }),
        fieldWrap("회차 난이도", makeSelect(catalog.difficulties || [], d.iDifficulty || 0, function () { d.iDifficulty = parseInt(this.value, 10) || 0; })),
        tableRegion("회차 개방 천부 표", ["개방", "번호", "천부명"], (catalog.talents || []).map(function (t) {
          return el("tr", null, [
            el("td", null, [el("input", { type: "checkbox", checked: talList.indexOf(t.id) >= 0, onChange: function () {
              var idx = talList.indexOf(t.id);
              if (this.checked && idx < 0) talList.push(t.id);
              else if (!this.checked && idx >= 0) talList.splice(idx, 1);
              renderSummaryStrip();
            } })]),
            el("td", { text: t.id }),
            el("td", { text: t.name })
          ]);
        })),
        tableRegion("회차 보물상자 111개 표", ["개봉", "상자 코드", "위치 · 보상"], (catalog.chests || []).map(function (c) {
          return el("tr", null, [
            el("td", null, [el("input", { type: "checkbox", checked: chList.indexOf(c.id) >= 0, onChange: function () {
              var idx = chList.indexOf(c.id);
              if (this.checked && idx < 0) chList.push(c.id);
              else if (!this.checked && idx >= 0) chList.splice(idx, 1);
              renderSummaryStrip();
            } })]),
            el("td", { text: c.id }),
            el("td", { text: c.name })
          ]);
        }))
      ]));
    } else if (state.kind === "save") {
      var btnMap = {};
      (catalog.developBtns || []).forEach(function (b) { btnMap[b.id] = b.name; });
      var devRows = (d.m_DevelopBtnStatusList || []).map(function (b) {
        return el("tr", null, [
          el("td", null, [el("input", { type: "checkbox", checked: Boolean(b.m_bStatus), onChange: function () { b.m_bStatus = this.checked; } })]),
          el("td", { text: b.m_iBtnID }),
          el("td", { text: btnMap[b.m_iBtnID] || ("육성 명령 #" + b.m_iBtnID) })
        ]);
      });
      p.appendChild(el("div", { className: "card" }, [
        el("h3", { text: "육성 행동 명령 개방 상태" }),
        tableRegion("육성 행동 개방 표", ["활성", "명령 번호", "행동명"], devRows)
      ]));
    }

    var bakCard = el("div", { className: "card" }, [el("h3", { text: "자동 백업 목록 및 복원" })]);
    if (!state.bridgeConnected) {
      bakCard.appendChild(el("p", { text: "로컬 브리지 서버(serve 또는 Windows 실행 파일) 연결 시 자동 생성된 .bak 백업 목록을 조회하고 즉시 복원할 수 있습니다." }));
    } else {
      var bakRows = (state.backups || []).map(function (b) {
        var bName = typeof b === "string" ? b : (b.name || "");
        var bSize = typeof b === "object" && b && b.size != null ? (b.size.toLocaleString("ko-KR") + " B") : "-";
        var boundSlot = state.slot;
        return el("tr", null, [
          el("td", { text: bName }),
          el("td", { text: bSize }),
          el("td", null, [el("button", { type: "button", className: "btn", text: "이 백업으로 복원", onClick: function () { restoreBackup(boundSlot, bName); } })])
        ]);
      });
      bakCard.appendChild(tableRegion("백업 파일 목록 표", ["백업 파일명", "크기", "복원"], bakRows));
    }
    p.appendChild(bakCard);
  }

  function renderActiveTab() {
    if (!state.data) return;
    if (state.activeTab === 0) renderTab0();
    else if (state.activeTab === 1) renderTab1();
    else if (state.activeTab === 2) renderTab2();
    else if (state.activeTab === 3) renderTab3();
    else if (state.activeTab === 4) renderTab4();
    else if (state.activeTab === 5) renderTab5();
  }

  function renderAll() {
    renderSummaryStrip();
    renderPresetsBar();
    renderActiveTab();
  }

  function initToolbar() {
    var fi = $("file-input");
    if (fi) {
      fi.addEventListener("change", function (e) {
        var f = e.target.files && e.target.files[0];
        if (!f) return;
        state.sessionRevision = (state.sessionRevision || 0) + 1;
        var rd = new FileReader();
        rd.onload = function (ev) {
          var buf = ev.target.result || new ArrayBuffer(0);
          try {
            var text = decodeUtf8Strict(buf);
            loadRawText(text, f.name);
          } catch (err) {
            syncSaveBindingUI();
            setNotice("유효하지 않은 UTF-8 인코딩 파일입니다. 현재 편집 상태를 유지합니다.", "error");
          }
        };
        rd.onerror = function () {
          setNotice("파일을 읽지 못했습니다.", "error");
        };
        rd.readAsArrayBuffer(f);
      });
    }
    var bDemoSave = $("btn-demo-save");
    if (bDemoSave) {
      bDemoSave.addEventListener("click", function () {
        var demo = core.createDemoSave(catalog);
        loadRawText(codec.serializeJsonLossless(demo), "Save0.Save");
      });
    }
    var bDemoRound = $("btn-demo-round");
    if (bDemoRound) {
      bDemoRound.addEventListener("click", function () {
        var round = core.createDemoRound(catalog);
        loadRawText(codec.serializeJsonLossless(round), "Round.dat");
      });
    }
    var bDownload = $("btn-download");
    if (bDownload) {
      bDownload.addEventListener("click", function () {
        if (!state.data) return;
        try {
          codec.validateData(state.data);
          var out = codec.serializeJsonLossless(state.data, state.meta);
          var outBytes = new TextEncoder().encode(out);
          var url = URL.createObjectURL(new Blob([outBytes], { type: "application/json;charset=utf-8" }));
          var a = el("a", { href: url, download: state.fileName || "Save0.Save" });
          document.body.appendChild(a);
          a.click();
          a.remove();
          setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
          setNotice("세이브 파일 내려받기를 완료했습니다: " + (state.fileName || "Save0.Save"), "ok");
        } catch (err) {
          setNotice("내려받기 검증 실패: " + err.message, "error");
        }
      });
    }
    var bLoadSlot = $("btn-load-slot");
    if (bLoadSlot) {
      bLoadSlot.addEventListener("click", function () {
        var sel = $("slot-select");
        if (sel && sel.value) loadBridgeSlot(sel.value);
      });
    }
    var bRefresh = $("btn-refresh-slots");
    if (bRefresh) bRefresh.addEventListener("click", function () { probeBridge(false); });

    var bSave = $("btn-save");
    if (bSave) {
      bSave.addEventListener("click", function () {
        if (!state.data || !state.bridgeConnected || !state.slot) return;
        try {
          codec.validateData(state.data);
        } catch (err) {
          setNotice("유효성 검증 실패: " + err.message, "error");
          return;
        }
        var targetSlot = state.slot;
        var targetSeq = state.slotReqSeq;
        var targetBaseSha = state.baseSha256 || "";
        var serialized = codec.serializeJsonLossless(state.data, state.meta);
        var snapAtConfirm = clonePlain(state.data);
        var diffs = core.computeDiffSummary(state.beforeSnap, state.data);
        openConfirmModal("슬롯 백업 및 저장 확인 (" + targetSlot + ")", diffs, function () {
          if (!state.bridgeConnected || !targetSlot || state.slot !== targetSlot || state.slotReqSeq !== targetSeq || (state.baseSha256 || "") !== targetBaseSha) {
            setNotice("확인 중 활성 슬롯 상태가 변경되어 저장을 취소했습니다.", "error");
            return;
          }
          fetch("/api/save", {
            method: "POST",
            headers: bridgeHeaders(true),
            body: JSON.stringify({ slot: targetSlot, text: serialized, baseSha256: targetBaseSha })
          })
            .then(function (r) {
              if (r.status === 409) {
                return r.json().catch(function () { return {}; }).then(function (eb) {
                  if (eb && eb.error === "CONFLICT_MODIFIED") {
                    setNotice("다른 창이나 외부에서 슬롯이 먼저 변경되었습니다. 슬롯을 다시 불러온 뒤 저장하세요.", "error");
                  } else {
                    setNotice("협객풍운전 실행 중에는 저장할 수 없습니다. 게임을 종료한 뒤 다시 시도하세요.", "error");
                  }
                  return null;
                });
              }
              if (!r.ok) throw new Error("저장 요청 실패 (" + r.status + ")");
              return r.json();
            })
            .then(function (res) {
              if (!res) return;
              if (state.slot === targetSlot && state.slotReqSeq === targetSeq) {
                state.beforeSnap = snapAtConfirm;
                if (res && res.sha256) state.baseSha256 = String(res.sha256);
              }
              setNotice("백업 생성 및 슬롯 저장이 완료되었습니다.", "ok");
              fetchBackups(targetSlot, targetSeq);
            })
            .catch(function (err) {
              setNotice("저장 실패: " + err.message, "error");
            });
        });
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    initTheme();
    initTabs();
    initToolbar();
    var demo = core.createDemoSave(catalog);
    loadRawText(codec.serializeJsonLossless(demo), "Save0.Save", "", null, "", true);
    var bootRev = state.sessionRevision;
    var bootSnapJson = JSON.stringify(state.data);
    probeBridge(true, bootRev, bootSnapJson);
    window.__TWX_APP__ = {
      getState: function () { return state; },
      loadRawText: loadRawText
    };
  });
})(window);
