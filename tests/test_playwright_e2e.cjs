"use strict";

const assert = require("assert");
const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");
const { execFileSync, spawn } = require("child_process");
const { pathToFileURL } = require("url");

const TWXCodec = require("../src/twx-codec.js");
const EditorCore = require("../src/editor-core.js");

function loadPlaywright() {
  const candidates = [
    process.env.PLAYWRIGHT_MODULE_PATH,
    "playwright",
    path.join(os.homedir(), ".local/lib/node_modules/@playwright/mcp/node_modules/playwright"),
    path.join(os.homedir(), ".npm-global/lib/node_modules/playwright"),
    "/usr/lib/node_modules/playwright"
  ].filter(Boolean);
  for (const modPath of candidates) {
    try {
      return require(modPath);
    } catch {}
  }
  try {
    const globalRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
    const globalPw = path.join(globalRoot, "playwright");
    if (fs.existsSync(globalPw)) return require(globalPw);
  } catch {}
  throw new Error("Playwright 모듈을 찾을 수 없습니다.");
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function attachGuards(page, label) {
  const errors = [];
  const externalUrls = [];
  page.on("pageerror", (err) => errors.push(`[${label} pageerror] ${err.message || err}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`[${label} console.error] ${msg.text()}`);
  });
  page.on("request", (req) => {
    const url = req.url();
    if ((url.startsWith("http://") || url.startsWith("https://")) && !url.startsWith("http://127.0.0.1:")) {
      externalUrls.push(url);
    }
  });
  return { errors, externalUrls };
}

function startBridgeServer(pyScript, rootDir, port, extraEnv) {
  return new Promise((resolve, reject) => {
    const proc = spawn(
      "python3",
      ["-B", "-u", pyScript, "serve", "--root", rootDir, "--host", "127.0.0.1", "--port", String(port)],
      {
        stdio: ["ignore", "pipe", "pipe"],
        env: Object.assign({}, process.env, extraEnv || {})
      }
    );
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        proc.kill("SIGKILL");
        reject(new Error(`서버 기동 시간 초과:\n${stdout}\n${stderr}`));
      }
    }, 10000);

    proc.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
      const m = stdout.match(/http:\/\/127\.0\.0\.1:\d+\//);
      if (m && !settled) {
        settled = true;
        clearTimeout(timer);
        resolve({ proc, url: m[0] });
      }
    });
    proc.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });
    proc.on("exit", (code) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(new Error(`서버 조기 종료 (${code}):\n${stdout}\n${stderr}`));
      }
    });
  });
}

async function stopProcess(proc) {
  if (!proc || proc.killed) return;
  proc.kill("SIGTERM");
  await new Promise((resolve) => {
    const t = setTimeout(() => {
      try { proc.kill("SIGKILL"); } catch {}
      resolve();
    }, 2500);
    proc.once("exit", () => {
      clearTimeout(t);
      resolve();
    });
  });
}

async function runModeA(browser, distHtml) {
  const ctx = await browser.newContext({ acceptDownloads: true });
  const page = await ctx.newPage();
  const { errors, externalUrls } = attachGuards(page, "ModeA");
  try {
    await page.goto(pathToFileURL(distHtml).href, { waitUntil: "domcontentloaded" });

    assert.strictEqual((await page.locator("#status-badge").innerText()).trim(), "오프라인 파일 모드");
    assert.strictEqual(await page.locator('[role="tab"]').count(), 6);

    // Native <dialog> attributes check
    const dlgAttrs = await page.locator("#modal-dialog").evaluate((el) => ({
      role: el.getAttribute("role"),
      ariaModal: el.getAttribute("aria-modal")
    }));
    assert.strictEqual(dlgAttrs.role, null, "<dialog> must not set role=dialog");
    assert.strictEqual(dlgAttrs.ariaModal, null, "<dialog> must not set aria-modal");

    // Keyboard ARIA tabs navigation
    await page.locator("#tab-btn-0").focus();
    await page.keyboard.press("ArrowRight");
    assert.strictEqual(await page.locator("#tab-btn-1").getAttribute("aria-selected"), "true");
    assert.strictEqual(await page.locator("#tab-panel-0").evaluate((p) => p.hidden), true);
    assert.strictEqual(await page.locator("#tab-panel-1").evaluate((p) => p.hidden), false);

    // Combat simulator live calculation on tab 2 (lazy-rendered)
    await page.keyboard.press("ArrowRight");
    assert.strictEqual(await page.locator("#tab-btn-2").getAttribute("aria-selected"), "true");
    assert.strictEqual(await page.locator("#combat-sim-card").count(), 1);

    await page.keyboard.press("End");
    assert.strictEqual(await page.locator("#tab-btn-5").getAttribute("aria-selected"), "true");
    await page.keyboard.press("Home");
    assert.strictEqual(await page.locator("#tab-btn-0").getAttribute("aria-selected"), "true");

    // 3-state theme + <meta name="color-scheme"> sync
    await page.locator('[data-theme-choice="dark"]').click();
    assert.strictEqual(await page.locator("html").getAttribute("data-theme"), "dark");
    assert.strictEqual(await page.locator('meta[name="color-scheme"]').getAttribute("content"), "dark");

    // BOM file upload check via #file-input with demoNoTeam
    const demoNoTeam = EditorCore.createDemoSave();
    delete demoNoTeam.m_teamMemberList;
    await page.locator("#file-input").setInputFiles({
      name: "BomSave.Save",
      mimeType: "application/json",
      buffer: Buffer.concat([
        Buffer.from([0xEF, 0xBB, 0xBF]),
        Buffer.from(TWXCodec.serializeJsonLossless(demoNoTeam), "utf8")
      ])
    });
    const hasBom = await page.evaluate(() => window.__TWX_APP__.getState().meta.hasBom);
    assert.strictEqual(hasBom, true, "Loaded file with UTF-8 BOM must set meta.hasBom to true");

    await page.locator('[data-theme-choice="light"]').click();
    assert.strictEqual(await page.locator("html").getAttribute("data-theme"), "light");
    assert.strictEqual(await page.locator('meta[name="color-scheme"]').getAttribute("content"), "light");

    await page.locator('[data-theme-choice="auto"]').click();
    assert.strictEqual(await page.locator("html").getAttribute("data-theme"), null);
    assert.strictEqual(await page.locator('meta[name="color-scheme"]').getAttribute("content"), "light dark");

    // Pure Korean rendered text check across all 6 tabs
    for (let i = 0; i < 6; i++) {
      await page.locator(`#tab-btn-${i}`).click();
      const bodyText = await page.evaluate(() => document.body.innerText);
      assert.strictEqual(/[\u4E00-\u9FFF\u3400-\u4DBF]/.test(bodyText), false, `Hanzi found on tab ${i}`);
      assert.strictEqual(/[\u3040-\u30FF]/.test(bodyText), false, `Kana found on tab ${i}`);
    }

    assert.strictEqual(await page.evaluate(() => Object.prototype.hasOwnProperty.call(window.__TWX_APP__.getState().data, "m_teamMemberList")) === false, true, "Opening Tab 4 must not inject m_teamMemberList");

    // Click preset max_money and trigger download
    await page.locator('[data-preset-id="max_money"]').click();
    const [dl] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btn-download").click()
    ]);
    const dlBytes = fs.readFileSync(await dl.path());

    assert.strictEqual(dlBytes.length >= 6 && dlBytes[0] === 0xEF && dlBytes[1] === 0xBB && dlBytes[2] === 0xBF, true, "Single UTF-8 BOM preserved on Mode A download");
    assert.strictEqual(!(dlBytes[3] === 0xEF && dlBytes[4] === 0xBB && dlBytes[5] === 0xBF), true, "No double BOM");

    const dlParsed = TWXCodec.parseJsonLossless(dlBytes.toString("utf8"));
    assert.strictEqual(dlParsed.data.m_iMoney, 9999999);
    assert.strictEqual(Object.prototype.hasOwnProperty.call(dlParsed.data, "m_teamMemberList"), false);

    await page.locator("#tab-btn-0").click();
    assert.strictEqual(await page.locator("#tab-btn-0").getAttribute("aria-selected"), "true");

    // P1 #4: malformed UTF-8 upload must be rejected without mutating current state
    const badDemoA = EditorCore.createDemoSave();
    badDemoA.m_strPlayerName = "__BAD_UTF8__";
    const badJsonA = TWXCodec.serializeJsonLossless(badDemoA);
    const badIdxA = badJsonA.indexOf("__BAD_UTF8__");
    const badUtf8BufA = Buffer.concat([
      Buffer.from(badJsonA.slice(0, badIdxA), "utf8"),
      Buffer.from([0xFF, 0xFE]),
      Buffer.from(badJsonA.slice(badIdxA + "__BAD_UTF8__".length), "utf8")
    ]);
    await page.locator("#file-input").setInputFiles({ name: "BadUtf8.Save", mimeType: "application/json", buffer: badUtf8BufA });
    await page.waitForFunction(
      () => {
        const bar = document.getElementById("notice-bar");
        return bar && bar.dataset.level === "error" && bar.textContent.includes("UTF-8");
      },
      null,
      { timeout: 10000 }
    );
    assert.strictEqual(await page.locator("#notice-bar").evaluate((el) => el.dataset.level), "error");
    assert.strictEqual(await page.evaluate(() => window.__TWX_APP__.getState().data.m_iMoney), 9999999);
    assert.strictEqual(await page.evaluate(() => window.__TWX_APP__.getState().fileName), "BomSave.Save");

    const badSurrDemoA = EditorCore.createDemoSave();
    badSurrDemoA.m_strPlayerName = "__BAD_SURR_A__";
    const badSurrBufA = Buffer.from(TWXCodec.serializeJsonLossless(badSurrDemoA).replace("__BAD_SURR_A__", "\\uD800"), "utf8");
    await page.locator("#file-input").setInputFiles({
      name: "BadSurrogate.Save",
      mimeType: "application/json",
      buffer: badSurrBufA,
    });
    await page.waitForFunction(
      () => {
        const bar = document.getElementById("notice-bar");
        return bar && bar.dataset.level === "error" && !bar.textContent.includes("UTF-8");
      },
      null,
      { timeout: 10000 }
    );
    assert.strictEqual(await page.locator("#notice-bar").evaluate((el) => el.dataset.level), "error");
    assert.strictEqual(await page.evaluate(() => window.__TWX_APP__.getState().fileName), "BomSave.Save");
    assert.strictEqual(await page.evaluate(() => window.__TWX_APP__.getState().data.m_iMoney), 9999999);

    const prevPlayerName = EditorCore.displayPlayerStr(demoNoTeam.m_strPlayerLastName) + EditorCore.displayPlayerStr(demoNoTeam.m_strPlayerName);
    assert.notStrictEqual(prevPlayerName, "", "prevPlayerName must not be empty");
    const summaryTextAfterTab0 = await page.locator("#summary-strip").textContent();
    assert.ok(summaryTextAfterTab0.includes(prevPlayerName), "summary-strip must include prevPlayerName");

    await page.locator("#btn-demo-round").click();
    assert.strictEqual(await page.locator("#tab-btn-5").getAttribute("aria-selected"), "true");
    const summaryTextAfterRound = await page.locator("#summary-strip").textContent();
    assert.ok(summaryTextAfterRound.includes("Round.dat"), "summary-strip must include Round.dat");
    assert.strictEqual(summaryTextAfterRound.includes(prevPlayerName), false, "summary-strip must not include prevPlayerName");

    await page.locator("#presets-bar [data-preset-id]").first().click();
    const achiFinishListLength = await page.evaluate(() => window.__TWX_APP__.getState().data.achiFinishList.length);
    assert.ok(achiFinishListLength > 0, "achiFinishList must not be empty");
    await page.locator("#btn-demo-save").click();

    // V25: editing experience input in Tab 1 must preserve m_iValue > 99999 and its scientific raw token
    const highStatJson = TWXCodec.serializeJsonLossless(EditorCore.createDemoSave())
      .replace('"m_iValue":80,"m_iIndex":0,"m_iExp":0', '"m_iValue":1.2E+5,"m_iIndex":0,"m_iExp":0');
    await page.locator("#file-input").setInputFiles({
      name: "HighStat.Save",
      mimeType: "application/json",
      buffer: Buffer.from(highStatJson, "utf8")
    });
    await page.waitForFunction(
      () => window.__TWX_APP__ && window.__TWX_APP__.getState().fileName === "HighStat.Save",
      null,
      { timeout: 10000 }
    );
    await page.locator("#tab-btn-1").click();
    const firstExpInput = page.locator("#tab-panel-1 .row-inline input:nth-child(2)").first();
    await firstExpInput.fill("65432");
    await firstExpInput.dispatchEvent("change");
    const tab1ExpCheck = await page.evaluate(() => {
      const s = window.__TWX_APP__.getState().data;
      const out = window.TWXCodec.serializeJsonLossless(s);
      const n0 = s.m_PropertyGroupsNodeList[0].m_GroupsNodwList[0];
      return { val: n0.m_iValue, exp: n0.m_iExp, hasRaw: out.includes('"m_iValue":1.2E+5,"m_iIndex":0,"m_iExp":65432') };
    });
    assert.deepStrictEqual(tab1ExpCheck, { val: 120000, exp: 65432, hasRaw: true });

    assert.deepStrictEqual(externalUrls, [], "Mode A must make 0 external requests");
    assert.deepStrictEqual(errors, [], `Mode A errors: ${errors.join("\n")}`);
  } finally {
    await ctx.close();
  }
}

async function runModeB(browser, pyScript) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "twx-e2e-"));
  const demoSave = EditorCore.createDemoSave();
  const demoRound = EditorCore.createDemoRound();
  fs.writeFileSync(path.join(tmpDir, "Save0.Save"), "\uFEFF" + TWXCodec.serializeJsonLossless(demoSave), "utf8");
  fs.writeFileSync(path.join(tmpDir, "Round.dat"), TWXCodec.serializeJsonLossless(demoRound), "utf8");

  const port = await getFreePort();
  const { proc, url } = await startBridgeServer(pyScript, tmpDir, port);
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const { errors, externalUrls } = attachGuards(page, "ModeB");

  try {
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () => {
        const b = document.getElementById("status-badge");
        const s = document.getElementById("slot-select");
        return b && b.textContent.trim() === "서버 연결됨" && s && s.options.length >= 2;
      },
      null,
      { timeout: 10000 }
    );
    await page.locator("#slot-select").selectOption("Save0.Save");
    await page.locator("#btn-load-slot").click();
    await page.waitForFunction(
      () => {
        const bar = document.getElementById("notice-bar");
        return bar && bar.textContent.includes("불러오기 완료: Save0.Save") && window.__TWX_APP__ && window.__TWX_APP__.getState().slot === "Save0.Save";
      },
      null,
      { timeout: 10000 }
    );
    assert.strictEqual(
      await page.evaluate(() => window.__TWX_APP__.getState().meta.hasBom),
      true,
      "Bridge /api/load must preserve UTF-8 BOM in meta.hasBom"
    );
    assert.strictEqual(
      Boolean(await page.evaluate(() => window.__TWX_APP__.getState().baseSha256)),
      true,
      "Bridge /api/load must populate state.baseSha256"
    );

    // P1 #3: late /api/slots resolution must not clobber a locally loaded startup save
    const pageLate = await ctx.newPage();
    const guardsLate = attachGuards(pageLate, "ModeB_Late");
    await pageLate.route("**/api/slots", async (route) => {
      await new Promise((r) => setTimeout(r, 400));
      await route.continue();
    });
    await pageLate.goto(url, { waitUntil: "domcontentloaded" });
    const localStartupDemo = EditorCore.createDemoSave();
    localStartupDemo.m_iMoney = 432100;
    const localStartupJson = TWXCodec.serializeJsonLossless(localStartupDemo);
    const localStartupBuf = Buffer.from(localStartupJson, "utf8");
    await pageLate.locator("#file-input").setInputFiles({ name: "LocalStartup.Save", mimeType: "application/json", buffer: localStartupBuf });
    await pageLate.waitForFunction(
      () => {
        const app = window.__TWX_APP__;
        return app && app.getState().data && app.getState().data.m_iMoney === 432100;
      },
      null,
      { timeout: 10000 }
    );
    await pageLate.waitForFunction(
      () => {
        const b = document.getElementById("status-badge");
        const s = document.getElementById("slot-select");
        return b && b.textContent.trim() === "서버 연결됨" && s && s.options.length >= 2;
      },
      null,
      { timeout: 10000 }
    );
    await new Promise((r) => setTimeout(r, 250));
    assert.strictEqual(await pageLate.evaluate(() => window.__TWX_APP__.getState().data.m_iMoney), 432100);
    assert.strictEqual(await pageLate.evaluate(() => window.__TWX_APP__.getState().slot), "");
    assert.strictEqual(await pageLate.locator("#slot-select").inputValue(), "");
    assert.strictEqual(await pageLate.locator("#btn-save").isDisabled(), true);
    assert.deepStrictEqual(guardsLate.externalUrls, []);
    assert.deepStrictEqual(guardsLate.errors, []);
    await pageLate.close();

    const pageLateLoad = await ctx.newPage();
    let loadIntercepted = 0;
    await pageLateLoad.route("**/api/load**", async (route) => {
      loadIntercepted += 1;
      await new Promise((r) => setTimeout(r, 450));
      await route.continue();
    });
    const guardsLateLoad = attachGuards(pageLateLoad, "ModeB_LateLoad");
    await pageLateLoad.goto(url, { waitUntil: "domcontentloaded" });
    await pageLateLoad.locator("#bridge-bar:not([hidden])").waitFor({ state: "visible", timeout: 10000 });
    await pageLateLoad.locator("#f-money").fill("765432");
    await pageLateLoad.locator("#f-money").dispatchEvent("change");
    await new Promise((r) => setTimeout(r, 700));
    assert.strictEqual(loadIntercepted >= 1, true);
    assert.strictEqual(await pageLateLoad.evaluate(() => window.__TWX_APP__.getState().data.m_iMoney), 765432);
    assert.strictEqual(await pageLateLoad.evaluate(() => window.__TWX_APP__.getState().slot), "");
    assert.strictEqual(await pageLateLoad.evaluate(() => window.__TWX_APP__.getState().baseSha256), "");
    assert.strictEqual(await pageLateLoad.locator("#slot-select").inputValue(), "");
    assert.strictEqual(await pageLateLoad.locator("#btn-save").isDisabled(), true);
    assert.deepStrictEqual(guardsLateLoad.externalUrls, []);
    assert.deepStrictEqual(guardsLateLoad.errors, []);
    await pageLateLoad.close();

    const page2 = await ctx.newPage();
    const guards2 = attachGuards(page2, "ModeB_Tab2");
    await page2.goto(url, { waitUntil: "domcontentloaded" });
    await page2.waitForFunction(
      () => {
        const b = document.getElementById("status-badge");
        const s = document.getElementById("slot-select");
        return b && b.textContent.trim() === "서버 연결됨" && s && s.options.length >= 2;
      },
      null,
      { timeout: 10000 }
    );
    await page2.locator("#slot-select").selectOption("Save0.Save");
    await page2.locator("#btn-load-slot").click();
    await page2.waitForFunction(
      () => {
        const bar = document.getElementById("notice-bar");
        return bar && bar.textContent.includes("불러오기 완료: Save0.Save") && window.__TWX_APP__ && window.__TWX_APP__.getState().slot === "Save0.Save";
      },
      null,
      { timeout: 10000 }
    );
    assert.strictEqual(
      Boolean(await page2.evaluate(() => window.__TWX_APP__.getState().baseSha256)),
      true,
      "Bridge /api/load must populate state.baseSha256 on second tab"
    );

    const baseShaBeforeRefresh = await page.evaluate(() => window.__TWX_APP__.getState().baseSha256);
    await page.locator('[data-preset-id="max_money"]').click();
    fs.writeFileSync(path.join(tmpDir, "Save1.Save"), TWXCodec.serializeJsonLossless(demoSave), "utf8");
    await page.locator("#btn-refresh-slots").click();
    await page.waitForFunction(
      () => Array.from(document.getElementById("slot-select").options).some((o) => o.value === "Save1.Save"),
      null,
      { timeout: 10000 }
    );
    assert.strictEqual(
      await page.evaluate(() => window.__TWX_APP__.getState().data.m_iMoney),
      9999999
    );
    assert.strictEqual(
      await page.evaluate(() => window.__TWX_APP__.getState().slot),
      "Save0.Save"
    );
    assert.strictEqual(
      await page.evaluate(() => window.__TWX_APP__.getState().baseSha256),
      baseShaBeforeRefresh
    );

    // P1 #4: malformed UTF-8 slot load must be rejected and state must remain intact
    const badSlotDemo = EditorCore.createDemoSave();
    badSlotDemo.m_strPlayerName = "__BAD_SLOT_UTF8__";
    const badSlotJson = TWXCodec.serializeJsonLossless(badSlotDemo);
    const badSlotIdx = badSlotJson.indexOf("__BAD_SLOT_UTF8__");
    const badUtf8SlotBuf = Buffer.concat([
      Buffer.from(badSlotJson.slice(0, badSlotIdx), "utf8"),
      Buffer.from([0xFF, 0xFE]),
      Buffer.from(badSlotJson.slice(badSlotIdx + "__BAD_SLOT_UTF8__".length), "utf8")
    ]);
    const badSlotPath = path.join(tmpDir, "Save3.Save");
    fs.writeFileSync(badSlotPath, badUtf8SlotBuf);
    await page.locator("#btn-refresh-slots").click();
    await page.waitForFunction(
      () => Array.from(document.getElementById("slot-select").options).some((o) => o.value === "Save3.Save"),
      null,
      { timeout: 10000 }
    );
    const errLenBeforeBadSlot = errors.length;
    await page.locator("#slot-select").selectOption("Save3.Save");
    await page.locator("#btn-load-slot").click();
    await page.waitForFunction(
      () => {
        const bar = document.getElementById("notice-bar");
        return bar && bar.dataset.level === "error" && bar.textContent.includes("슬롯을 불러오지 못했습니다");
      },
      null,
      { timeout: 10000 }
    );
    assert.strictEqual(await page.evaluate(() => window.__TWX_APP__.getState().slot), "Save0.Save");
    assert.strictEqual(await page.evaluate(() => window.__TWX_APP__.getState().data.m_iMoney), 9999999);
    assert.strictEqual(await page.evaluate(() => window.__TWX_APP__.getState().baseSha256), baseShaBeforeRefresh);
    assert.strictEqual(await page.locator("#slot-select").inputValue(), "Save0.Save");
    for (let i = errors.length - 1; i >= errLenBeforeBadSlot; i--) {
      if (errors[i].includes("console.error") && errors[i].includes("400")) {
        errors.splice(i, 1);
      }
    }
    fs.unlinkSync(badSlotPath);
    await page.locator("#btn-refresh-slots").click();
    await page.waitForFunction(
      () => !Array.from(document.getElementById("slot-select").options).some((o) => o.value === "Save3.Save"),
      null,
      { timeout: 10000 }
    );

    const badSurrSlotPath = path.join(tmpDir, "Save4.Save");
    const badSurrSlotDemo = EditorCore.createDemoSave();
    badSurrSlotDemo.m_strPlayerName = "__BAD_SLOT_SURR__";
    fs.writeFileSync(
      badSurrSlotPath,
      Buffer.from(TWXCodec.serializeJsonLossless(badSurrSlotDemo).replace("__BAD_SLOT_SURR__", "\\uD800"), "utf8")
    );
    await page.locator("#btn-refresh-slots").click();
    await page.waitForFunction(
      () => Array.from(document.getElementById("slot-select").options).some((o) => o.value === "Save4.Save"),
      null,
      { timeout: 10000 }
    );

    const errLenBeforeBadSurrSlot = errors.length;
    await page.locator("#slot-select").selectOption("Save4.Save");
    await page.locator("#btn-load-slot").click();
    await page.waitForFunction(
      () => { const bar = document.getElementById("notice-bar"); return bar && bar.dataset.level === "error"; },
      null,
      { timeout: 10000 }
    );

    assert.strictEqual(await page.locator("#notice-bar").evaluate((el) => el.dataset.level), "error");
    assert.strictEqual(await page.evaluate(() => window.__TWX_APP__.getState().slot), "Save0.Save");
    assert.strictEqual(await page.evaluate(() => window.__TWX_APP__.getState().data.m_iMoney), 9999999);
    assert.strictEqual(await page.evaluate(() => window.__TWX_APP__.getState().baseSha256), baseShaBeforeRefresh);
    assert.strictEqual(await page.locator("#slot-select").inputValue(), "Save0.Save");

    for (let i = errors.length - 1; i >= errLenBeforeBadSurrSlot; i--) {
      if (errors[i].includes("console.error") && errors[i].includes("400")) {
        errors.splice(i, 1);
      }
    }

    fs.unlinkSync(badSurrSlotPath);
    await page.locator("#btn-refresh-slots").click();
    await page.waitForFunction(
      () => !Array.from(document.getElementById("slot-select").options).some((o) => o.value === "Save4.Save"),
      null,
      { timeout: 10000 }
    );

    await page.locator("#btn-save").click();
    assert.strictEqual(await page.locator("#modal-dialog").evaluate((d) => d.open), true);
    await page.locator("#modal-confirm").click();
    assert.strictEqual(await page.locator("#modal-dialog").evaluate((d) => d.returnValue), "");

    await page.waitForFunction(
      () => {
        const bar = document.getElementById("notice-bar");
        return bar && bar.dataset.level === "ok" && bar.textContent.includes("슬롯 저장이 완료되었습니다");
      },
      null,
      { timeout: 10000 }
    );

    await page2.locator('[data-preset-id="max_friendship"]').click();
    await page2.locator("#btn-save").click();
    await page2.locator("#modal-confirm").click();
    await page2.waitForFunction(
      () => {
        const bar = document.getElementById("notice-bar");
        return bar && bar.dataset.level === "error" && bar.textContent.includes("먼저 변경되었습니다");
      },
      null,
      { timeout: 10000 }
    );

    const savedParsed = TWXCodec.parseJsonLossless(fs.readFileSync(path.join(tmpDir, "Save0.Save"), "utf8"));
    assert.strictEqual(savedParsed.meta.hasBom, true, "Saved Save0.Save must retain UTF-8 BOM");
    assert.strictEqual(savedParsed.data.m_iMoney, 9999999);
    assert.strictEqual(
      savedParsed.data.m_NpcFriendlyNodeList.length,
      demoSave.m_NpcFriendlyNodeList.length,
      "Second tab must not overwrite stale m_NpcFriendlyNodeList"
    );
    assert.strictEqual(
      savedParsed.data.m_NpcFriendlyNodeList.some((n) => n.m_iFriendly === 100),
      false,
      "Second tab stale save must not apply max_friendship"
    );

    assert.deepStrictEqual(guards2.externalUrls, [], "Mode B second tab must make 0 external requests");
    assert.deepStrictEqual(guards2.errors.filter((e) => !e.includes("409")), [], `Mode B second tab errors: ${guards2.errors.join("\n")}`);
    await page2.close();

    const baks = fs.readdirSync(path.join(tmpDir, "backups")).filter((f) => f.endsWith(".bak"));
    assert.ok(baks.length >= 1, "Expected .bak file in backups/");

    // V26: Mode B /api/load + /api/save must accept integral scientific-notation tokens and preserve raw tokens
    const sciSlotJson = TWXCodec.serializeJsonLossless(EditorCore.createDemoSave())
      .replace('"m_iValue":80,"m_iIndex":0,"m_iExp":0', '"m_iValue":1.2E+5,"m_iIndex":0,"m_iExp":0')
      .replace(/"m_iYear":\d+/, '"m_iYear":3E+0');
    assert.ok(sciSlotJson.includes('"m_iYear":3E+0'), "sciSlotJson must contain 3E+0");
    fs.writeFileSync(path.join(tmpDir, "Save5.Save"), sciSlotJson, "utf8");
    await page.locator("#btn-refresh-slots").click();
    await page.waitForFunction(
      () => Array.from(document.getElementById("slot-select").options).some((o) => o.value === "Save5.Save"),
      null,
      { timeout: 10000 }
    );
    await page.locator("#slot-select").selectOption("Save5.Save");
    await page.locator("#btn-load-slot").click();
    await page.waitForFunction(
      () => {
        const bar = document.getElementById("notice-bar");
        return bar && bar.dataset.level === "ok" && bar.textContent.includes("불러오기 완료: Save5.Save");
      },
      null,
      { timeout: 10000 }
    );
    await page.locator("#tab-btn-1").click();
    const modeBExpInput = page.locator("#tab-panel-1 .row-inline input:nth-child(2)").first();
    await modeBExpInput.fill("1e5");
    await modeBExpInput.dispatchEvent("change");
    assert.strictEqual(await modeBExpInput.inputValue(), "100000", "1e5 input must sync DOM value to 100000");
    await page.locator("#btn-save").click();
    assert.strictEqual(await page.locator("#modal-dialog").evaluate((d) => d.open), true);
    const modalText = await page.locator("#modal-body").textContent();
    assert.ok(modalText.includes("[0:0] 120000/0") && modalText.includes("[0:0] 120000/100000"), "Confirm modal must show concrete property delta");
    await page.locator("#modal-confirm").click();
    await page.waitForFunction(
      () => {
        const bar = document.getElementById("notice-bar");
        return bar && bar.dataset.level === "ok" && bar.textContent.includes("슬롯 저장이 완료되었습니다");
      },
      null,
      { timeout: 10000 }
    );
    const savedSciSlotRaw = fs.readFileSync(path.join(tmpDir, "Save5.Save"), "utf8");
    assert.ok(
      savedSciSlotRaw.includes('"m_iValue":1.2E+5,"m_iIndex":0,"m_iExp":100000'),
      "Mode B /api/save must preserve 1.2E+5 raw token while storing 1e5 as 100000"
    );
    assert.ok(savedSciSlotRaw.includes('"m_iYear":3E+0'), "Mode B /api/save must preserve 3E+0 raw token");

    // Loading demo data in Mode B must unbind state.slot and disable #btn-save
    await page.locator("#btn-demo-round").click();
    assert.strictEqual(await page.locator("#slot-select").inputValue(), "");
    assert.strictEqual(await page.locator("#btn-save").isDisabled(), true);
    assert.strictEqual(await page.evaluate(() => window.__TWX_APP__.getState().baseSha256), "");

    assert.deepStrictEqual(externalUrls, [], "Mode B must make 0 external requests");
    assert.deepStrictEqual(errors, [], `Mode B errors: ${errors.join("\n")}`);
  } finally {
    await ctx.close();
    await stopProcess(proc);
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

async function main() {
  const { chromium } = loadPlaywright();
  const repoRoot = path.resolve(__dirname, "..");
  const distHtml = path.join(repoRoot, "dist", "TaleOfWuxiaSaveEditor-v1.0.1.html");
  const pyScript = path.join(repoRoot, "twx_editor.py");

  const launchOpts = { headless: true };
  for (const bin of ["/opt/google/chrome/chrome", "/usr/bin/google-chrome"]) {
    if (fs.existsSync(bin)) {
      launchOpts.executablePath = bin;
      break;
    }
  }

  const browser = await chromium.launch(launchOpts);
  try {
    await runModeA(browser, distHtml);
    await runModeB(browser, pyScript);
    console.log("[PASS] test_playwright_e2e.cjs: Mode A + Mode B passed.");
  } finally {
    await browser.close();
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.error("[FAIL] test_playwright_e2e.cjs:", err);
    process.exit(1);
  });
}
