"""Community restock reports from Reddit - covers stores that don't publish
in-store stock online (Costco, Sam's Club, in-store Walmart, Meijer...).

A post/comment becomes an alert only if it mentions ALL of:
  * a store you track (Costco, Sam's, Target, ...)
  * a restock word (restock, dropped, pallet, in stock, ETB, ...)
  * a known town that is inside your radius
"""
import logging
import re
import time

import requests

from geo import find_town

log = logging.getLogger("community")

STORE_PATTERNS = {
    "Costco": r"\bcostco\b",
    "Sam's Club": r"\bsam'?s(?: club)?\b|\bsams\b",
    "Target": r"\btarget\b",
    "Walmart": r"\bwal-?mart\b",
    "Best Buy": r"\bbest ?buy\b",
    "Meijer": r"\bmeijer\b",
    "GameStop": r"\bgame ?stop\b",
    "Kroger": r"\bkroger\b",
}

RESTOCK_WORDS = re.compile(
    r"\b(restock\w*|dropp?(ed|ing)?|drop|pallets?|in stock|just got|stocked|"
    r"shelves?|etbs?|booster bundles?|bundles?|tins?|blisters?|"
    r"upc|spc|collection box(es)?|has (some|a lot|tons))\b",
    re.I,
)
NEGATIVE_WORDS = re.compile(r"\b(nothing|no stock|empty|wiped|sold out|dead)\b", re.I)
PRICE_RE = re.compile(r"\$\s?\d{1,4}(?:\.\d{2})?")


class Reddit:
    name = "Reddit"

    def __init__(self, cfg):
        self.cfg = cfg
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "pokemon-restock-bot/1.0 (personal use)"})
        self.stores = {k: re.compile(v, re.I) for k, v in STORE_PATTERNS.items()
                       if k in cfg["community"]["stores"]}

    def enabled(self):
        return self.cfg["community"].get("enabled", True)

    def _fetch(self, url, params):
        try:
            r = self.s.get(url, params=params, timeout=20)
            if r.status_code != 200:
                log.debug("Reddit %s -> %s", url, r.status_code)
                return []
            return [c["data"] for c in r.json().get("data", {}).get("children", [])]
        except (requests.RequestException, ValueError, KeyError) as e:
            log.debug("Reddit fetch failed: %s", e)
            return []
        finally:
            time.sleep(2)  # be polite; unauthenticated Reddit is rate-limited

    def posts(self):
        items = []
        towns = " OR ".join(f'"{t}"' for t in self.cfg["community"]["search_towns"])
        q = f"(pokemon OR etb OR \"booster bundle\") ({towns})"
        items += self._fetch("https://www.reddit.com/search.json",
                             {"q": q, "sort": "new", "t": "day", "limit": 50})
        for sub in self.cfg["community"]["subreddits"]:
            items += self._fetch(f"https://www.reddit.com/r/{sub}/new.json", {"limit": 50})
        return items

    def check(self):
        out = []
        home = tuple(self.cfg["home_latlon"])
        radius = self.cfg["radius_miles"]
        max_age = self.cfg["community"]["max_age_hours"] * 3600
        for p in self.posts():
            if time.time() - p.get("created_utc", 0) > max_age:
                continue
            text = f"{p.get('title', '')}\n{p.get('selftext', '')}"
            low = text.lower()
            if "pok" not in low and "etb" not in low:
                continue
            store = next((name for name, rx in self.stores.items() if rx.search(text)), None)
            if not store or not RESTOCK_WORDS.search(text):
                continue
            if NEGATIVE_WORDS.search(p.get("title", "")):
                continue  # "nothing at Target" style posts
            place = find_town(text, home)
            if not place or place[1] > radius:
                continue
            town, miles = place
            price = PRICE_RE.search(text)
            snippet = re.sub(r"\s+", " ", p.get("title") or p.get("selftext") or "")[:110]
            out.append({
                "source": f"Reddit r/{p.get('subreddit', '?')}",
                "store": f"{store} {town.title()}",
                "product": snippet,
                "price": price.group(0).replace(" ", "") if price else None,
                "miles": miles,
                "url": "https://reddit.com" + p.get("permalink", ""),
                "key": f"reddit:{p.get('id')}",
                "report": True,
            })
        return out
