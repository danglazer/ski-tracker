import re
import json
import sys
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Memory-saving args for Chromium on small VMs
CHROMIUM_ARGS = [
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--no-sandbox",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    "--js-flags=--max-old-space-size=256",
]

TRACKED = {
    "snowbird": ["Mineral Basin", "Cirque Traverse", "High Baldy"],
    "solitude": ["Honeycomb Canyon", "Summit Express", "Highway to Heaven", "Fantasy Ridge", "Evergreen Peak"],
    "brighton": ["Milly Bowl", "Snake Bowl"],
    "snowbasin": ["Allen Peak Tram", "Strawberry Gondola", "Middle Bowl Cirque Gate", "Upper Mt Ogden Bowl Gate"],
}


def log(msg):
    print(msg, flush=True)


def normalize_status(raw):
    raw_lower = raw.strip().lower()
    if "open" in raw_lower:
        return "open"
    if "pending" in raw_lower:
        return "pending"
    return "closed"


def scrape_snowbird(page):
    """Snowbird: SVG fill colors #8BC53F=open, #D0021B=closed in td.name+td.status rows."""
    try:
        terrain_url = "https://www.snowbird.com/the-mountain/mountain-report/lift-trail-report/"
        conditions_url = "https://www.snowbird.com/the-mountain/mountain-report/current-conditions-weather/"

        name_map = {
            "mineral basin": "Mineral Basin",
            "cirque traverse": "Cirque Traverse",
            "high baldy": "High Baldy",
        }
        terrain_results = {t: "closed" for t in TRACKED["snowbird"]}

        log("[snowbird] Loading terrain page...")
        page.goto(terrain_url, timeout=60000)
        try:
            page.wait_for_selector("td.name", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(3000)

        terrain_data = page.evaluate("""
            () => {
                const rows = document.querySelectorAll('tr');
                const results = [];
                for (const row of rows) {
                    const nameCell = row.querySelector('td.name');
                    const statusCell = row.querySelector('td.status');
                    if (nameCell && statusCell) {
                        const name = nameCell.textContent.trim();
                        const paths = statusCell.querySelectorAll('path[fill]');
                        const fills = Array.from(paths)
                            .map(p => p.getAttribute('fill'))
                            .filter(f => f && f !== 'none' && f !== '#FFF' && f !== '#fff');
                        const isOpen = fills.includes('#8BC53F');
                        results.push({ name, isOpen });
                    }
                }
                return results;
            }
        """)

        for item in terrain_data:
            page_name = item["name"].lower()
            for key, tracked_name in name_map.items():
                if key in page_name:
                    terrain_results[tracked_name] = "open" if item["isOpen"] else "closed"

        log(f"[snowbird] Terrain done: {terrain_results}")

        snow_24hr = 0.0
        report_text = ""
        try:
            log("[snowbird] Loading conditions page...")
            page.goto(conditions_url, timeout=60000)
            page.wait_for_timeout(3000)
            text = page.inner_text("body")
            m = re.search(r"24[\s\-]*(?:Hour|Hr)[\s\-]*Snow\s*([\d.]+)", text, re.IGNORECASE)
            if m:
                snow_24hr = float(m.group(1))
            else:
                m2 = re.search(r"([\d.]+)\s*[\"″]\s*24", text)
                if m2:
                    snow_24hr = float(m2.group(1))
            # Extract narrative snow report
            try:
                report_text = page.evaluate("""
                    () => {
                        // Look for narrative/report sections
                        const selectors = [
                            '.conditions-report', '.morning-report', '.snow-report',
                            '[class*="report"]', '[class*="narrative"]', '[class*="condition"]'
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.textContent.trim().length > 50) {
                                return el.textContent.trim();
                            }
                        }
                        // Fallback: grab main content paragraphs
                        const paragraphs = document.querySelectorAll('p');
                        const texts = [];
                        for (const p of paragraphs) {
                            const t = p.textContent.trim();
                            if (t.length > 40 && !t.match(/^(\\d|copyright|©|privacy|cookie)/i)) {
                                texts.push(t);
                            }
                        }
                        return texts.slice(0, 5).join('\\n\\n');
                    }
                """)
            except Exception:
                pass
        except Exception as e:
            log(f"[snowbird] Failed to get snow data: {e}")

        log(f"[snowbird] Done. Snow: {snow_24hr}, Report: {len(report_text)} chars")
        return {
            "snow_24hr": snow_24hr,
            "report_text": report_text,
            "terrain": [{"name": n, "status": terrain_results[n]} for n in TRACKED["snowbird"]],
        }

    except Exception as e:
        log(f"[snowbird] Scraper error: {e}")
        return {"snow_24hr": 0.0, "terrain": []}


def scrape_brighton(page):
    """Brighton: JS-rendered, status via <img alt="Open"> or <img alt="Closed">."""
    try:
        url = "https://www.brightonresort.com/conditions"
        terrain_results = {t: "closed" for t in TRACKED["brighton"]}

        log("[brighton] Loading page...")
        page.goto(url, timeout=60000)
        try:
            page.wait_for_selector("text=Trail Status", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(3000)

        trail_data = page.evaluate("""
            () => {
                const results = {};
                const targets = ['Milly Bowl', 'Snake Bowl'];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const text = walker.currentNode.textContent.trim();
                    if (targets.includes(text)) {
                        let el = walker.currentNode.parentElement;
                        for (let i = 0; i < 10; i++) {
                            el = el.parentElement;
                            if (!el) break;
                            const imgs = el.querySelectorAll('img');
                            for (const img of imgs) {
                                if (img.alt === 'Open' || img.alt === 'Closed') {
                                    results[text] = img.alt.toLowerCase();
                                    break;
                                }
                            }
                            if (results[text]) break;
                        }
                    }
                }
                return results;
            }
        """)

        for trail_name, status in trail_data.items():
            if trail_name in terrain_results:
                terrain_results[trail_name] = normalize_status(status)

        log(f"[brighton] Terrain done: {terrain_results}")

        snow_24hr = 0.0
        report_text = ""
        try:
            text = page.inner_text("body")
            m = re.search(r"([\d.]+)[\"″\s]*Snow\s*24\s*Hrs", text, re.IGNORECASE)
            if m:
                snow_24hr = float(m.group(1))
            else:
                m2 = re.search(r"Snow\s*24\s*Hrs[.\s]*([\d.]+)", text, re.IGNORECASE)
                if m2:
                    snow_24hr = float(m2.group(1))
            # Extract narrative snow report
            try:
                report_text = page.evaluate("""
                    () => {
                        const selectors = [
                            '.conditions-report', '.morning-report', '.snow-report',
                            '[class*="report"]', '[class*="comment"]', '[class*="condition"]'
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.textContent.trim().length > 50) {
                                return el.textContent.trim();
                            }
                        }
                        const paragraphs = document.querySelectorAll('p');
                        const texts = [];
                        for (const p of paragraphs) {
                            const t = p.textContent.trim();
                            if (t.length > 40 && !t.match(/^(\\d|copyright|©|privacy|cookie)/i)) {
                                texts.push(t);
                            }
                        }
                        return texts.slice(0, 5).join('\\n\\n');
                    }
                """)
            except Exception:
                pass
        except Exception as e:
            log(f"[brighton] Failed to get snow data: {e}")

        log(f"[brighton] Done. Snow: {snow_24hr}, Report: {len(report_text)} chars")
        return {
            "snow_24hr": snow_24hr,
            "report_text": report_text,
            "terrain": [{"name": n, "status": terrain_results[n]} for n in TRACKED["brighton"]],
        }

    except Exception as e:
        log(f"[brighton] Scraper error: {e}")
        return {"snow_24hr": 0.0, "terrain": []}


def scrape_snowbasin():
    """Snowbasin: server-rendered HTML tables, no Playwright needed."""
    try:
        log("[snowbasin] Loading page...")
        url = "https://www.snowbasin.com/the-mountain/mountain-report/"
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        tracked_names = {t.lower(): t for t in TRACKED["snowbasin"]}
        terrain_results = {t: "closed" for t in TRACKED["snowbasin"]}

        rows = soup.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 2:
                row_text = " ".join(c.get_text(strip=True) for c in cells).lower()
                for key, name in tracked_names.items():
                    if key in row_text:
                        combined = " ".join(c.get_text(strip=True) for c in cells)
                        if re.search(r"(?:Lift|Trail)\s+Open", combined, re.IGNORECASE):
                            terrain_results[name] = "open"
                        elif re.search(r"(?:Lift|Trail)\s+Pending", combined, re.IGNORECASE):
                            terrain_results[name] = "pending"
                        else:
                            terrain_results[name] = "closed"

        page_text = soup.get_text()
        snow_24hr = 0.0
        m = re.search(r"24[\s\-]*(?:Hour|Hr|Hrs?)[\s\-]*(?:Snow(?:fall)?)?[:\s]*([\d.]+)", page_text, re.IGNORECASE)
        if m:
            snow_24hr = float(m.group(1))
        else:
            m2 = re.search(r"(?:New|Fresh)\s+Snow[:\s]*([\d.]+)", page_text, re.IGNORECASE)
            if m2:
                snow_24hr = float(m2.group(1))

        # Extract narrative snow report
        report_text = ""
        report_el = soup.find(class_=re.compile(r"report|narrative|condition|morning", re.IGNORECASE))
        if report_el and len(report_el.get_text(strip=True)) > 50:
            report_text = report_el.get_text(strip=True)
        else:
            paragraphs = soup.find_all("p")
            texts = []
            for p in paragraphs:
                t = p.get_text(strip=True)
                if len(t) > 40 and not re.match(r"^(\d|copyright|©|privacy|cookie)", t, re.IGNORECASE):
                    texts.append(t)
            report_text = "\n\n".join(texts[:5])

        log(f"[snowbasin] Done. Terrain: {terrain_results}, Snow: {snow_24hr}, Report: {len(report_text)} chars")
        return {
            "snow_24hr": snow_24hr,
            "report_text": report_text,
            "terrain": [{"name": n, "status": terrain_results[n]} for n in TRACKED["snowbasin"]],
        }

    except Exception as e:
        log(f"[snowbasin] Scraper error: {e}")
        return {"snow_24hr": 0.0, "terrain": []}


def scrape_solitude(page):
    """Solitude: JS-rendered Alterra/Ikon platform."""
    try:
        url = "https://www.solitudemountain.com/mountain-and-village/conditions-and-maps"
        tracked_names = {t.lower(): t for t in TRACKED["solitude"]}
        terrain_results = {t: "closed" for t in TRACKED["solitude"]}

        log("[solitude] Loading page...")
        page.goto(url, timeout=60000)
        try:
            page.wait_for_selector("text=Lifts", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(5000)

        content = page.content()
        text = page.inner_text("body")

        soup = BeautifulSoup(content, "html.parser")

        rows = soup.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                row_text = " ".join(c.get_text(strip=True) for c in cells).lower()
                for key, name in tracked_names.items():
                    if key in row_text:
                        combined = " ".join(c.get_text(strip=True) for c in cells)
                        terrain_results[name] = normalize_status(combined)

        for line in text.splitlines():
            line_stripped = line.strip()
            for key, name in tracked_names.items():
                if key in line_stripped.lower():
                    if re.search(r"\bopen\b", line_stripped, re.IGNORECASE):
                        terrain_results[name] = "open"
                    elif re.search(r"\bpending\b", line_stripped, re.IGNORECASE):
                        terrain_results[name] = "pending"

        elements = soup.find_all(["div", "li", "span", "button", "a"])
        for el in elements:
            el_text = el.get_text(strip=True)
            for key, name in tracked_names.items():
                if key in el_text.lower() and len(el_text) < 300:
                    after = el_text.lower().split(key)[-1][:80]
                    if "open" in after:
                        terrain_results[name] = "open"

        snow_24hr = 0.0
        m = re.search(r"24[\s\-]*(?:Hour|Hr|Hrs?)[\s\-]*(?:Snow(?:fall)?)?[:\s]*([\d.]+)", text, re.IGNORECASE)
        if m:
            snow_24hr = float(m.group(1))
        else:
            m2 = re.search(r"(?:New|Fresh)\s+Snow[:\s]*([\d.]+)", text, re.IGNORECASE)
            if m2:
                snow_24hr = float(m2.group(1))
            else:
                m3 = re.search(r"([\d.]+)[\"″\s]*(?:in)?\s*(?:new|last|24)", text, re.IGNORECASE)
                if m3:
                    snow_24hr = float(m3.group(1))

        # Extract narrative snow report
        report_text = ""
        try:
            report_text = page.evaluate("""
                () => {
                    const selectors = [
                        '.conditions-report', '.morning-report', '.snow-report',
                        '[class*="report"]', '[class*="narrative"]', '[class*="condition"]'
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.textContent.trim().length > 50) {
                            return el.textContent.trim();
                        }
                    }
                    const paragraphs = document.querySelectorAll('p');
                    const texts = [];
                    for (const p of paragraphs) {
                        const t = p.textContent.trim();
                        if (t.length > 40 && !t.match(/^(\\d|copyright|©|privacy|cookie)/i)) {
                            texts.push(t);
                        }
                    }
                    return texts.slice(0, 5).join('\\n\\n');
                }
            """)
        except Exception:
            pass

        log(f"[solitude] Done. Terrain: {terrain_results}, Snow: {snow_24hr}, Report: {len(report_text)} chars")
        return {
            "snow_24hr": snow_24hr,
            "report_text": report_text,
            "terrain": [{"name": n, "status": terrain_results[n]} for n in TRACKED["solitude"]],
        }

    except Exception as e:
        log(f"[solitude] Scraper error: {e}")
        return {"snow_24hr": 0.0, "terrain": []}


def scrape_all():
    """Scrape all resorts using ONE shared Chromium browser to save memory."""
    from playwright.sync_api import sync_playwright

    results = {}

    # Snowbasin doesn't need Playwright — do it first
    results["snowbasin"] = scrape_snowbasin()

    # Launch ONE browser for all Playwright resorts
    log("[scraper] Launching Chromium...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
            page = browser.new_page(user_agent=HEADERS["User-Agent"])

            # Scrape each resort one at a time, reusing the same page
            results["snowbird"] = scrape_snowbird(page)
            results["brighton"] = scrape_brighton(page)
            results["solitude"] = scrape_solitude(page)

            browser.close()
        log("[scraper] Chromium closed.")
    except Exception as e:
        log(f"[scraper] Chromium error: {e}")
        # Fill in missing resorts with empty data
        for resort in ["snowbird", "brighton", "solitude"]:
            if resort not in results:
                results[resort] = {"snow_24hr": 0.0, "terrain": []}

    return results


if __name__ == "__main__":
    results = scrape_all()
    print(json.dumps(results, indent=2))
