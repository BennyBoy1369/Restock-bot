"""Checks retailer websites/APIs for Pokemon TCG stock at stores near home.

Each checker returns a list of Finding dicts:
    {source, store, product, price, miles, url, key}
`key` uniquely identifies "this product at this store" so the bot only texts
when it changes from not-in-stock to in-stock.
"""
import logging
import random
import re
import time
import uuid

import requests

log = logging.getLogger("retailers")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})
    return s


def looks_like_pokemon_tcg(name, cfg):
    n = name.lower()
    if "pok" not in n:
        return False
    if any(bad in n for bad in cfg["exclude_words"]):
        return False
    return any(w in n for w in cfg["product_words"])


def _fmt_price(p):
    try:
        return f"${float(p):.2f}"
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------- Best Buy
class BestBuy:
    """Official Best Buy Developer API (free key: developer.bestbuy.com)."""

    name = "Best Buy"

    def __init__(self, cfg):
        self.cfg = cfg
        self.key = cfg["bestbuy"].get("api_key", "").strip()
        self.s = _session()
        self._products = []
        self._products_at = 0

    def enabled(self):
        return self.cfg["bestbuy"].get("enabled", True) and bool(self.key)

    def _get(self, url, params):
        params = dict(params, apiKey=self.key, format="json")
        r = self.s.get(url, params=params, timeout=20)
        if r.status_code == 429:
            time.sleep(2)
            r = self.s.get(url, params=params, timeout=20)
        r.raise_for_status()
        time.sleep(0.25)  # stay well under 5 requests/sec
        return r.json()

    def products(self):
        # Refresh the product list every 6 hours; stock is checked every cycle.
        if self._products and time.time() - self._products_at < 6 * 3600:
            return self._products
        found = {}
        for term in self.cfg["bestbuy"]["search_terms"]:
            words = "&".join(f"search={w}" for w in term.split())
            url = f"https://api.bestbuy.com/v1/products(({words}))"
            data = self._get(url, {"show": "sku,name,salePrice,url", "pageSize": 100})
            for p in data.get("products", []):
                if looks_like_pokemon_tcg(p.get("name", ""), self.cfg):
                    found[p["sku"]] = p
        self._products = list(found.values())
        self._products_at = time.time()
        log.info("Best Buy: tracking %d Pokemon products", len(self._products))
        return self._products

    def check(self):
        out = []
        radius = self.cfg["radius_miles"]
        for p in self.products():
            url = f"https://api.bestbuy.com/v1/products/{p['sku']}/stores.json"
            try:
                data = self._get(url, {"postalCode": self.cfg["home_zip"]})
            except requests.RequestException as e:
                log.debug("Best Buy store lookup failed for %s: %s", p["sku"], e)
                continue
            for st in data.get("stores", []):
                miles = float(st.get("distance") or 999)
                if miles > radius:
                    continue
                store = f"Best Buy {st.get('name') or st.get('city', '')}".strip()
                out.append({
                    "source": "Best Buy",
                    "store": store,
                    "product": p["name"],
                    "price": _fmt_price(p.get("salePrice")),
                    "miles": miles,
                    "url": p.get("url"),
                    "key": f"bestbuy:{st.get('storeID')}:{p['sku']}",
                })
        return out


# ----------------------------------------------------------------------- Target
class Target:
    """Uses the same store-availability data target.com shows on product pages.
    Not an official API, so it can break if Target changes their site."""

    name = "Target"
    BASE = "https://redsky.target.com/redsky_aggregations/v1/web"

    def __init__(self, cfg):
        self.cfg = cfg
        self.key = cfg["target"]["web_key"]
        self.s = _session()
        self.s.headers.update({"Origin": "https://www.target.com", "Referer": "https://www.target.com/"})
        self.visitor = uuid.uuid4().hex.upper()
        self._products = {}
        self._products_at = 0

    def enabled(self):
        return self.cfg["target"].get("enabled", True)

    def products(self):
        if self._products and time.time() - self._products_at < 6 * 3600:
            return self._products
        found = {str(t): None for t in self.cfg["target"].get("tcins", [])}
        for term in self.cfg["target"]["search_terms"]:
            params = {
                "key": self.key, "channel": "WEB", "count": 24, "offset": 0,
                "keyword": term, "page": f"/s/{term}", "visitor_id": self.visitor,
                "platform": "desktop", "pricing_store_id": "1", "default_purchasability_filter": "true",
            }
            try:
                r = self.s.get(f"{self.BASE}/plp_search_v2", params=params, timeout=20)
                r.raise_for_status()
                items = (r.json().get("data", {}).get("search", {}).get("products", [])) or []
            except (requests.RequestException, ValueError) as e:
                log.warning("Target search failed (%s); using configured TCINs only", e)
                items = []
            for it in items:
                title = (it.get("item", {}).get("product_description", {}).get("title") or "")
                title = re.sub(r"&#\d+;", "", title)
                if looks_like_pokemon_tcg(title, self.cfg):
                    found[str(it.get("tcin"))] = {
                        "title": title,
                        "price": (it.get("price") or {}).get("current_retail"),
                    }
            time.sleep(1)
        self._products = found
        self._products_at = time.time()
        log.info("Target: tracking %d Pokemon products", len(found))
        return found

    def check(self):
        out = []
        radius = self.cfg["radius_miles"]
        for tcin, meta in self.products().items():
            params = {
                "key": self.key, "tcin": tcin, "nearby": self.cfg["home_zip"],
                "radius": int(radius) + 1, "limit": 20, "requested_quantity": 1,
                "include_only_available_stores": "true",
            }
            try:
                r = self.s.get(f"{self.BASE}/fiats_v1", params=params, timeout=20)
                r.raise_for_status()
                locs = r.json().get("data", {}).get("fulfillment_fiats", {}).get("locations", []) or []
            except (requests.RequestException, ValueError) as e:
                log.debug("Target stock lookup failed for %s: %s", tcin, e)
                continue
            finally:
                time.sleep(random.uniform(0.8, 1.6))
            for loc in locs:
                qty = loc.get("location_available_to_promise_quantity") or 0
                status = (loc.get("in_store_only") or {}).get("availability_status", "")
                if qty <= 0 and "IN_STOCK" not in status.upper():
                    continue
                miles = float(loc.get("distance") or 999)
                if miles > radius:
                    continue
                store_name = (loc.get("store") or {}).get("location_name") or loc.get("location_name") or ""
                title = (meta or {}).get("title") or f"Target item {tcin}"
                out.append({
                    "source": "Target",
                    "store": f"Target {store_name}".strip(),
                    "product": title,
                    "price": _fmt_price((meta or {}).get("price")),
                    "miles": miles,
                    "url": f"https://www.target.com/p/-/A-{tcin}",
                    "key": f"target:{loc.get('location_id')}:{tcin}",
                })
        return out


# ---------------------------------------------------------------------- Walmart
class Walmart:
    """Best effort. walmart.com aggressively blocks automated checks, so this
    reads the public search page and backs off for an hour when blocked.
    Walmart in-store restocks mostly come through the community source."""

    name = "Walmart"

    def __init__(self, cfg):
        self.cfg = cfg
        self.s = _session()
        self.s.headers.update({"Accept": "text/html,application/xhtml+xml"})
        self.blocked_until = 0

    def enabled(self):
        return self.cfg["walmart"].get("enabled", True)

    def check(self):
        if time.time() < self.blocked_until:
            return []
        out = []
        for term in self.cfg["walmart"]["search_terms"]:
            try:
                r = self.s.get("https://www.walmart.com/search", params={"q": term}, timeout=20)
            except requests.RequestException as e:
                log.debug("Walmart request failed: %s", e)
                return out
            if r.status_code != 200 or "__NEXT_DATA__" not in r.text:
                log.info("Walmart blocked the check; pausing Walmart for 1 hour")
                self.blocked_until = time.time() + 3600
                return out
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
            if not m:
                continue
            import json
            try:
                data = json.loads(m.group(1))
                stacks = data["props"]["pageProps"]["initialData"]["searchResult"]["itemStacks"]
            except (KeyError, ValueError, TypeError):
                continue
            for stack in stacks:
                for it in stack.get("items", []):
                    name = it.get("name") or ""
                    if not looks_like_pokemon_tcg(name, self.cfg):
                        continue
                    # Only first-party Walmart listings, not marketplace resellers
                    seller = (it.get("sellerName") or "Walmart.com").lower()
                    if "walmart" not in seller:
                        continue
                    if it.get("availabilityStatusV2", {}).get("value") != "IN_STOCK":
                        continue
                    price = (it.get("priceInfo") or {}).get("linePrice") or it.get("price")
                    out.append({
                        "source": "Walmart",
                        "store": "Walmart.com (online)",
                        "product": name,
                        "price": price if isinstance(price, str) else _fmt_price(price),
                        "miles": 0.0,
                        "url": "https://www.walmart.com" + (it.get("canonicalUrl") or ""),
                        "key": f"walmart:online:{it.get('usItemId') or name}",
                    })
            time.sleep(3)
        return out
