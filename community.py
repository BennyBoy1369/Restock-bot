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
    """Reads new posts AND new comments. With an approved Reddit app
    (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET) it uses Reddit's official API,
    which GitHub's computers don't get blocked on. Without one it falls back
    to anonymous access and warns in the log when Reddit blocks it."""

    name = "Reddit"

    def __init__(self, cfg):
        self.cfg = cfg
        rc = cfg["community"].get("reddit", {}) or {}
        self.client_id = (rc.get("client_id") or "").strip()
        self.client_secret = (rc.get("client_secret") or "").strip()
        user = (rc.get("username") or "unknown").strip()
        self.s = requests.Session()
        # Reddit asks API users to identify themselves like this
        self.s.headers.update({"User-Agent": f"script:pokemon-restock-bot:1.1 (by /u/{user})"})
        self.token = None
        self.token_until = 0
        self.stats = {"ok": 0, "blocked": 0}
        self.stores = {k: re.compile(v, re.I) for k, v in STORE_PATTERNS.items()
                       if k in cfg["community"]["stores"]}

    def enabled(self):
        return self.cfg["community"].get("enabled", True)

    # ---- auth
    def _login(self):
        if not (self.client_id and self.client_secret):
            return False
        if self.token and time.time() < self.token_until:
            return True
        try:
            r = self.s.post("https://www.reddit.com/api/v1/access_token",
                            auth=(self.client_id, self.client_secret),
                            data={"grant_type": "client_credentials"}, timeout=20)
            r.raise_for_status()
            data = r.json()
            self.token = data["access_token"]
            self.token_until = time.time() + int(data.get("expires_in", 3600)) - 60
            return True
        except (requests.RequestException, ValueError, KeyError) as e:
            log.warning("Reddit login failed (%s) - using anonymous access", e)
            self.token = None
            return False

    def _fetch(self, path, params):
        authed = self._login()
        base = "https://oauth.reddit.com" if authed else "https://www.reddit.com"
        url = base + path + ("" if authed else ".json")
        headers = {"Authorization": f"bearer {self.token}"} if authed else {}
        try:
            r = self.s.get(url, params=dict(params, raw_json=1), headers=headers, timeout=20)
            if r.status_code != 200:
                self.stats["blocked"] += 1
                log.debug("Reddit %s -> %s", path, r.status_code)
                return []
            self.stats["ok"] += 1
            return [c["data"] for c in r.json().get("data", {}).get("children", [])]
        except (requests.RequestException, ValueError, KeyError) as e:
            self.stats["blocked"] += 1
            log.debug("Reddit fetch failed: %s", e)
            return []
        finally:
            time.sleep(1 if authed else 2)

    def posts(self):
        self.stats = {"ok": 0, "blocked": 0}
        items = []
        towns = " OR ".join(f'"{t}"' for t in self.cfg["community"]["search_towns"])
        q = f"(pokemon OR etb OR \"booster bundle\") ({towns})"
        items += self._fetch("/search", {"q": q, "sort": "new", "t": "day", "limit": 50})
        for sub in self.cfg["community"]["subreddits"]:
            items += self._fetch(f"/r/{sub}/new", {"limit": 50})
            # Comments are where a lot of "Sam's Novi just dropped" info lives
            items += self._fetch(f"/r/{sub}/comments", {"limit": 100})
        total = self.stats["ok"] + self.stats["blocked"]
        if total and self.stats["blocked"] == total:
            log.warning("Reddit blocked every request this run - Costco/Sam's reports "
                        "were NOT checked. Adding an approved Reddit app fixes this (see README).")
        elif self.stats["blocked"]:
            log.info("Reddit: %d of %d requests blocked", self.stats["blocked"], total)
        return items

    def check(self):
        out = []
        home = tuple(self.cfg["home_latlon"])
        radius = self.cfg["radius_miles"]
        max_age = self.cfg["community"]["max_age_hours"] * 3600
        for p in self.posts():
            if time.time() - p.get("created_utc", 0) > max_age:
                continue
            head = p.get("title") or (p.get("body") or "")[:120]
            text = f"{p.get('title', '')}\n{p.get('selftext', '')}\n{p.get('body', '')}"
            low = text.lower()
            if "pok" not in low and "etb" not in low:
                # comments often skip the word "pokemon" - accept them if the
                # subreddit itself is Pokemon-focused
                if not ("pok" in (p.get("subreddit") or "").lower() and p.get("body")):
                    continue
            store = next((name for name, rx in self.stores.items() if rx.search(text)), None)
            if not store or not RESTOCK_WORDS.search(text):
                continue
            if NEGATIVE_WORDS.search(head):
                continue  # "nothing at Target" style posts
            place = find_town(text, home)
            if not place or place[1] > radius:
                continue
            town, miles = place
            price = PRICE_RE.search(text)
            snippet = re.sub(r"\s+", " ", head)[:110]
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


# --------------------------------------------------------------------- Slickdeals
class Slickdeals:
    """Slickdeals' official front-page RSS feed. These are ONLINE deals
    (Walmart.com, Costco.com, SamsClub.com, Target.com, BestBuy.com), so
    distance doesn't apply - texts label them 'ONLINE DEAL'."""

    name = "Slickdeals"
    FEED = "https://feeds.feedburner.com/SlickdealsnetFP"

    def __init__(self, cfg):
        self.cfg = cfg
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "pokemon-restock-bot/1.1 (personal RSS reader)"})
        self.stores = {k: re.compile(v, re.I) for k, v in STORE_PATTERNS.items()
                       if k in cfg["stores"]}

    def enabled(self):
        return self.cfg.get("slickdeals", {}).get("enabled", True)

    def check(self):
        import xml.etree.ElementTree as ET
        from email.utils import parsedate_to_datetime
        try:
            r = self.s.get(self.FEED, timeout=20)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except (requests.RequestException, ET.ParseError) as e:
            log.warning("Slickdeals feed failed: %s", e)
            return []
        max_age = self.cfg["community"]["max_age_hours"] * 3600
        out = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            desc = item.findtext("description") or ""
            if "pok" not in title.lower():
                continue
            try:
                when = parsedate_to_datetime(item.findtext("pubDate")).timestamp()
                if time.time() - when > max_age:
                    continue
            except (TypeError, ValueError):
                pass
            text = f"{title}\n{desc}"
            store = next((n for n, rx in self.stores.items() if rx.search(text)), None)
            if not store:
                continue
            price = PRICE_RE.search(title)
            out.append({
                "source": "Slickdeals",
                "store": f"ONLINE DEAL {store}",
                "product": title[:110],
                "price": price.group(0).replace(" ", "") if price else None,
                "miles": 0.0,
                "url": (item.findtext("link") or "").strip(),
                "key": f"slickdeals:{item.findtext('guid') or title}",
                "report": True,
            })
        return out
