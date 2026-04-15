import os
import re
import json
import time
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
TO_EMAIL = os.getenv("TO_EMAIL", "").strip()
FROM_EMAIL = os.getenv("FROM_EMAIL", "").strip()

SEARCH_URL = os.getenv("SEARCH_URL", "").strip()

KEYWORD = os.getenv("KEYWORD", "nintendo switch").strip().lower()
LOCATION = os.getenv("LOCATION", "hamar").strip().lower()
MAX_PRICE = int(os.getenv("MAX_PRICE", "2500"))

CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "1800"))

SEEN_FILE = Path("seen.json")


def load_seen():
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_seen(seen):
    SEEN_FILE.write_text(
        json.dumps(sorted(list(seen)), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def send_email(subject, html):
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "kjop-og-salg-scanner/1.0",
    }
    payload = {
        "from": FROM_EMAIL,
        "to": [TO_EMAIL],
        "subject": subject,
        "html": html,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    print("EMAIL STATUS:", response.status_code)
    print("EMAIL RESPONSE:", response.text)


def parse_price(text):
    if not text:
        return None

    cleaned = (
        text.replace("\xa0", " ")
        .replace("kr", "")
        .replace(",", " ")
        .replace(".", " ")
    )

    matches = re.findall(r"\d[\d\s]*", cleaned)
    candidates = []

    for match in matches:
        digits = re.sub(r"\D", "", match)
        if digits:
            value = int(digits)
            if 50 <= value <= 500000:
                candidates.append(value)

    return candidates[0] if candidates else None


def text_or_empty(locator):
    try:
        return locator.inner_text(timeout=1000).strip()
    except Exception:
        return ""


def href_or_empty(locator):
    try:
        href = locator.get_attribute("href", timeout=1000)
        return href.strip() if href else ""
    except Exception:
        return ""


def normalize_url(url):
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return f"https://www.finn.no{url}"
    return url


def fetch_listings():
    listings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # Prøv flere vanlige annonse-kort mønstre
        candidate_selectors = [
            "article",
            "[data-testid='search-result']",
            "[data-testid='ad-card']",
            "a[href*='/recommerce/forsale/item/']",
            "a[href*='/bap/forsale/ad.html']",
        ]

        cards = []
        for selector in candidate_selectors:
            found = page.locator(selector)
            count = found.count()
            if count > 0:
                cards = [found.nth(i) for i in range(min(count, 50))]
                print(f"Bruker selector: {selector} ({count} treff)")
                break

        if not cards:
            print("Fant ingen annonsekort.")
            browser.close()
            return []

        for card in cards:
            try:
                title = ""
                price_text = ""
                location = ""
                url = ""

                # Lenke
                link_locator = card.locator("a[href]").first
                url = href_or_empty(link_locator)
                url = normalize_url(url)

                # Tittel
                title_selectors = [
                    "h2",
                    "h3",
                    "[data-testid='headline']",
                    "[data-testid='ad-title']",
                ]
                for sel in title_selectors:
                    txt = text_or_empty(card.locator(sel).first)
                    if txt:
                        title = txt
                        break

                # Hvis selve kortet er lenken, prøv tekst derfra
                if not title:
                    txt = text_or_empty(card)
                    if txt:
                        title = txt.split("\n")[0].strip()

                # Pris
                price_selectors = [
                    "[data-testid='price']",
                    "[data-testid='ad-price']",
                    "span",
                    "div",
                ]
                for sel in price_selectors:
                    txt = text_or_empty(card.locator(sel).first)
                    value = parse_price(txt)
                    if value:
                        price_text = txt
                        break

                price = parse_price(price_text or text_or_empty(card))

                # Sted
                card_text = text_or_empty(card)
                location_match = re.search(
                    r"\b(Hamar|Stange|Brumunddal|Ringsaker|Løten|Innlandet|Oslo|Trondheim)\b",
                    card_text,
                    flags=re.IGNORECASE,
                )
                if location_match:
                    location = location_match.group(1)

                # Minimumskrav
                if not title or not url:
                    continue

                listings.append(
                    {
                        "title": title.strip(),
                        "price": price,
                        "location": location.strip(),
                        "url": url.strip(),
                    }
                )

            except Exception as e:
                print("Feil ved parsing av kort:", str(e))

        browser.close()

    print(f"Fant {len(listings)} annonser totalt")
    return listings


def matches_rules(listing):
    title = (listing.get("title") or "").lower()
    location = (listing.get("location") or "").lower()
    price = listing.get("price")

    if KEYWORD not in title:
        return False

    if price is None or price > MAX_PRICE:
        return False

    if LOCATION and LOCATION not in location:
        return False

    return True


def listing_id(listing):
    return listing.get("url", "").strip()


def build_email_html(listing):
    return f"""
    <h2>Ny annonse funnet</h2>
    <p><strong>Tittel:</strong> {listing['title']}</p>
    <p><strong>Pris:</strong> {listing['price'] if listing['price'] else 'Ukjent'} kr</p>
    <p><strong>Sted:</strong> {listing['location'] if listing['location'] else 'Ukjent'}</p>
    <p><a href="{listing['url']}">Åpne annonse</a></p>
    """


def check_listings():
    seen = load_seen()

    try:
        listings = fetch_listings()

        matched = 0
        sent = 0

        for listing in listings:
            if not matches_rules(listing):
                continue

            matched += 1
            lid = listing_id(listing)

            if not lid or lid in seen:
                continue

            subject = f"Treff: {listing['title']} – {listing['price']} kr"
            html = build_email_html(listing)
            send_email(subject, html)

            seen.add(lid)
            sent += 1

        save_seen(seen)
        print(f"Matched: {matched}, sendt: {sent}")

    except Exception as e:
        print("FEIL I CHECK_LISTINGS:", str(e))


if __name__ == "__main__":
    if not SEARCH_URL:
        raise ValueError("SEARCH_URL mangler")

    while True:
        check_listings()
        time.sleep(CHECK_INTERVAL_SECONDS)
