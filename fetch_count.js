#!/usr/bin/env node
/**
 * Load the public EVO visits page in a dedicated headless Chrome profile
 * and print the live club occupancy as JSON on stdout.
 * Does not call backend APIs; reads only the rendered location-now sentence.
 */
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const PAGE = "https://visits.evofitness.at/";
const CLUB_MATCH = process.env.EVO_CLUB_MATCH || "Bruno-Marek-Allee";
const CHROME = process.env.CHROME_PATH || "/usr/bin/google-chrome";
const NAV_TIMEOUT_MS = Number(process.env.EVO_NAV_TIMEOUT_MS || 30000);
const SENTENCE_TIMEOUT_MS = Number(process.env.EVO_SENTENCE_TIMEOUT_MS || 30000);

const LIVE_RE = /Momentan sind\s+(\d+)\s+Mitglieder im Club/i;
const LIVE_RE_EN = /(\d+)\s+people in the club right now/i;

function tmpProfile() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "evo-occ-chrome-"));
}

function killChromeForProfile(profile) {
  // Only processes that used this unique temp profile; never the desktop browser.
  try {
    spawnSync("pkill", ["-f", `user-data-dir=${profile}`], { stdio: "ignore" });
  } catch (_) {
    /* ignore */
  }
}

function parseLive(text) {
  if (!text) return null;
  const compact = String(text).replace(/\s+/g, " ").trim();
  let m = compact.match(LIVE_RE);
  if (m) return { count: Number(m[1]), sentence: m[0], locale: "de" };
  m = compact.match(LIVE_RE_EN);
  if (m) return { count: Number(m[1]), sentence: m[0], locale: "en" };
  return null;
}

async function readPage(page) {
  // Wait for the club dropdown to be populated inside the shadow DOM.
  await page.waitForFunction(
    () => {
      const host = document.querySelector("location-select");
      const opts = host && host.shadowRoot && host.shadowRoot.querySelectorAll("select option");
      return opts && opts.length > 1;
    },
    { timeout: SENTENCE_TIMEOUT_MS }
  );

  const club = await page.evaluate((needle) => {
    const select = document.querySelector("location-select").shadowRoot.querySelector("select");
    const opt = [...select.options].find((o) =>
      (o.textContent || "").replace(/\s+/g, " ").includes(needle)
    );
    if (!opt) {
      const names = [...select.options].map((o) => (o.textContent || "").trim()).filter(Boolean);
      throw new Error("club not in dropdown: " + names.join(" | "));
    }
    const already = select.value === opt.value && opt.selected;
    if (!already) {
      select.value = opt.value;
      opt.selected = true;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    return {
      name: (opt.textContent || "").replace(/\s+/g, " ").trim(),
      alreadySelected: already,
    };
  }, CLUB_MATCH);

  await page.waitForFunction(
    () => {
      const host = document.querySelector("location-now");
      const text = (host && host.shadowRoot && host.shadowRoot.textContent) || "";
      return (
        /Momentan sind\s+\d+\s+Mitglieder im Club/i.test(text) ||
        /\d+\s+people in the club right now/i.test(text)
      );
    },
    { timeout: SENTENCE_TIMEOUT_MS }
  );

  const raw = await page.evaluate(() => {
    const host = document.querySelector("location-now");
    const root = host && host.shadowRoot;
    const subtitle = root && root.querySelector(".donut-subtitle");
    const title = root && root.querySelector(".donut-title");
    return {
      subtitle: subtitle ? (subtitle.textContent || "").trim() : "",
      title: title ? (title.textContent || "").trim() : "",
      all: root ? (root.textContent || "").trim() : "",
      selected: (() => {
        const sel = document.querySelector("location-select");
        const s = sel && sel.shadowRoot && sel.shadowRoot.querySelector("select");
        if (!s || s.selectedIndex < 0) return "";
        return (s.options[s.selectedIndex].textContent || "").replace(/\s+/g, " ").trim();
      })(),
    };
  });

  const parsed = parseLive(raw.subtitle) || parseLive(raw.all);
  if (!parsed) {
    const err = new Error("live sentence not found");
    err.detail = raw;
    throw err;
  }
  if (!String(raw.selected).includes(CLUB_MATCH)) {
    throw new Error(`wrong club selected: ${raw.selected || "(none)"}`);
  }
  return { ...parsed, club: club.name || raw.selected, title: raw.title, alreadySelected: club.alreadySelected };
}

async function main() {
  if (!fs.existsSync(CHROME)) {
    throw new Error("chrome not found at " + CHROME);
  }
  const puppeteer = require("puppeteer-core");
  const profile = tmpProfile();
  const proxy = process.env.EVO_CHROME_PROXY || process.env.HTTPS_PROXY || process.env.https_proxy || "";
  const args = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--headless=new",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-sync",
    "--disable-background-networking",
    "--disable-default-apps",
    "--mute-audio",
    "--hide-scrollbars",
    "--window-size=1280,900",
    `--user-data-dir=${profile}`,
  ];
  if (proxy) {
    // Accept http://host:port or host:port
    const p = proxy.replace(/^https?:\/\//, "");
    args.push(`--proxy-server=http://${p}`);
  }

  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: CHROME,
      headless: true,
      dumpio: false,
      args,
      // Do not reuse or touch the desktop display / profile.
      env: { ...process.env, DISPLAY: "", TZ: process.env.TZ || "Europe/Vienna" },
    });
    const page = await browser.newPage();
    page.setDefaultNavigationTimeout(NAV_TIMEOUT_MS);
    await page.setViewport({ width: 1280, height: 900 });
    // Prefer the site default (de-AT); still accept English if the locale control differs.
    await page.setExtraHTTPHeaders({ "Accept-Language": "de-AT,de;q=0.9,en;q=0.5" });

    let lastErr;
    let mainStatus = null;
    page.on("response", (res) => {
      try {
        const u = res.url().split("#")[0];
        if (u === PAGE || u === PAGE.replace(/\/$/, "")) mainStatus = res.status();
      } catch (_) {
        /* ignore */
      }
    });
    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        await page.goto(PAGE, { waitUntil: "domcontentloaded", timeout: NAV_TIMEOUT_MS });
        const result = await readPage(page);
        const out = {
          ok: true,
          count: result.count,
          sentence: result.sentence,
          title: result.title || "",
          club: result.club,
          locale: result.locale,
          alreadySelected: result.alreadySelected,
          reloaded: attempt > 1,
          page: PAGE,
        };
        process.stdout.write(JSON.stringify(out) + "\n");
        return;
      } catch (e) {
        lastErr = e;
        process.stderr.write(`fetch_count attempt ${attempt} failed: ${e.message}\n`);
        if (attempt === 1) {
          // Same as a visitor refreshing a blank first paint.
          try {
            await page.reload({ waitUntil: "domcontentloaded", timeout: NAV_TIMEOUT_MS });
          } catch (re) {
            lastErr = re;
          }
        }
      }
    }
    let pageInfo;
    try {
      pageInfo = await page.evaluate(() => ({
        title: document.title,
        href: location.href,
        text: ((document.body && document.body.innerText) || "").replace(/\s+/g, " ").trim().slice(0, 600),
      }));
    } catch (_) {
      /* page may already be gone */
    }
    const shot = process.env.EVO_FAIL_SHOT;
    if (shot) {
      try {
        await page.screenshot({ path: shot, fullPage: true });
      } catch (_) {
        /* ignore */
      }
    }
    const fail = {
      ok: false,
      error: lastErr ? lastErr.message : "unknown",
      detail: Object.assign({}, (lastErr && lastErr.detail) || {}, {
        httpStatus: mainStatus,
        page: pageInfo,
      }),
    };
    process.stdout.write(JSON.stringify(fail) + "\n");
    process.exitCode = 2;
  } finally {
    if (browser) {
      try {
        await browser.close();
      } catch (_) {
        /* ignore */
      }
    }
    killChromeForProfile(profile);
    try {
      fs.rmSync(profile, { recursive: true, force: true });
    } catch (_) {
      /* ignore */
    }
  }
}

main().catch((e) => {
  process.stdout.write(JSON.stringify({ ok: false, error: e.message || String(e) }) + "\n");
  process.exit(1);
});
