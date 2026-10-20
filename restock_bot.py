"""Pokemon card restock bot - texts you when stores near you restock.

Usage:
    python restock_bot.py              run forever (checks every few minutes)
    python restock_bot.py --once       one check, then exit
    python restock_bot.py --test-text  send a test text to make sure texting works
    python restock_bot.py --selftest   offline test with sample data
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

import yaml

import notify
from community import Reddit
from retailers import BestBuy, Target, Walmart

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
log = logging.getLogger("bot")


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Secrets can come from environment variables (GitHub Actions secrets)
    # so they never have to be written into the public config file.
    env = os.environ
    if env.get("TEXTING_METHOD"):
        cfg["texting"]["method"] = env["TEXTING_METHOD"]
    if env.get("NTFY_TOPIC"):
        cfg["texting"]["ntfy"]["topic"] = env["NTFY_TOPIC"]
    if env.get("BESTBUY_API_KEY"):
        cfg["bestbuy"]["api_key"] = env["BESTBUY_API_KEY"]
    if env.get("WALMART_ENABLED"):
        cfg["walmart"]["enabled"] = env["WALMART_ENABLED"].lower() == "true"
    return cfg


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    s.setdefault("in_stock", [])      # retailer keys in stock last check
    s.setdefault("reported", {})      # community post id -> time seen
    s.setdefault("sent_times", [])    # timestamps of texts, for rate limiting
    return s


def save_state(s):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f)
    os.replace(tmp, STATE_FILE)


def build_sources(cfg):
    want = set(cfg["stores"])
    sources = []
    if "Best Buy" in want:
        sources.append(BestBuy(cfg))
    if "Target" in want:
        sources.append(Target(cfg))
    if "Walmart" in want:
        sources.append(Walmart(cfg))
    sources.append(Reddit(cfg))  # covers Costco, Sam's Club, in-store reports
    return [s for s in sources if s.enabled()]


def format_text(items):
    items = sorted(items, key=lambda x: x["miles"])
    lines = ["Pokemon restock near you:"]
    for it in items[:5]:
        dist = "online" if it["miles"] == 0 else f"{it['miles']:.1f} mi"
        price = f" - {it['price']}" if it.get("price") else ""
        tag = "REPORT: " if it.get("report") else ""
        lines.append(f"- {tag}{it['store']} ({dist}): {it['product'][:70]}{price}")
    if len(items) > 5:
        lines.append(f"+{len(items) - 5} more")
    if items[0].get("url"):
        lines.append(items[0]["url"])
    return "\n".join(lines)


def run_cycle(cfg, sources, state):
    findings = []
    for src in sources:
        try:
            got = src.check()
            log.info("%s: %d hit(s) within %s mi", src.name, len(got), cfg["radius_miles"])
            findings += got
        except Exception as e:
            log.warning("%s check failed: %s", src.name, e)

    prev = set(state["in_stock"])
    now_keys = {f["key"] for f in findings if not f.get("report")}
    new = [f for f in findings if not f.get("report") and f["key"] not in prev]
    new += [f for f in findings if f.get("report") and f["key"] not in state["reported"]]

    state["in_stock"] = sorted(now_keys)
    for f in findings:
        if f.get("report"):
            state["reported"][f["key"]] = time.time()
    # forget community posts older than 3 days
    state["reported"] = {k: v for k, v in state["reported"].items() if time.time() - v < 3 * 86400}

    if new:
        state["sent_times"] = [t for t in state["sent_times"] if time.time() - t < 3600]
        if len(state["sent_times"]) >= cfg["texting"]["max_texts_per_hour"]:
            log.info("Hit max texts per hour; holding %d alert(s)", len(new))
            # don't mark them seen so they go out next hour
            state["in_stock"] = sorted(prev & now_keys)
            for f in new:
                state["reported"].pop(f["key"], None)
        elif notify.send(cfg, format_text(new)):
            state["sent_times"].append(time.time())
            log.info("Texted %d new restock(s)", len(new))
    save_state(state)
    return new


def selftest(cfg):
    """Offline check of the distance filter, report parsing and text format."""
    import community
    from geo import find_town
    home = tuple(cfg["home_latlon"])
    for town, should_pass in [("Novi", True), ("Southfield", True), ("Troy", True),
                              ("Southgate", False), ("Madison Heights", False), ("Canton", False)]:
        _, miles = find_town(f"Sam's in {town} dropped", home)
        ok = (miles <= cfg["radius_miles"]) == should_pass
        print(f"  {'OK ' if ok else 'BAD'} {town:16s} {miles:5.1f} mi -> {'alert' if miles <= cfg['radius_miles'] else 'ignore'}")
        assert ok

    r = community.Reddit(cfg)
    now = time.time()
    fake = [
        {"id": "a", "title": "Sam's Club Southfield just dropped Ascended ETBs $54.98", "selftext": "",
         "subreddit": "PokemonTCG", "created_utc": now, "permalink": "/r/x/a"},
        {"id": "b", "title": "Costco Novi has pokemon bundles on a pallet", "selftext": "",
         "subreddit": "PokemonTCG", "created_utc": now, "permalink": "/r/x/b"},
        {"id": "c", "title": "Southgate Sam's dropped ETBs", "selftext": "",
         "subreddit": "PokemonTCG", "created_utc": now, "permalink": "/r/x/c"},
        {"id": "d", "title": "Nothing at Target West Bloomfield today", "selftext": "pokemon",
         "subreddit": "PokemonTCG", "created_utc": now, "permalink": "/r/x/d"},
    ]
    r.posts = lambda: fake
    hits = r.check()
    ids = sorted(h["key"] for h in hits)
    print(f"  community reports kept: {ids} (expected reddit:a, reddit:b)")
    assert ids == ["reddit:a", "reddit:b"], ids
    hits.append({"source": "Target", "store": "Target Novi", "product": "Pokemon TCG Ascended Heroes Elite Trainer Box",
                 "price": "$59.99", "miles": 7.4, "url": "https://www.target.com/p/-/A-1", "key": "t"})
    print("\n" + format_text(hits))
    print("\nSelf-test passed.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--test-text", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    cfg = load_config(a.config)

    if a.selftest:
        return selftest(cfg)
    if a.test_text:
        ok = notify.send(cfg, "Restock bot test: texting works!")
        print("Sent." if ok else "Failed - check the log above and your texting settings.")
        return

    sources = build_sources(cfg)
    log.info("Watching %s within %s miles of %s", ", ".join(s.name for s in sources),
             cfg["radius_miles"], cfg["home_zip"])
    if not any(s.name == "Best Buy" for s in sources) and "Best Buy" in cfg["stores"]:
        log.warning("Best Buy is off until you add a free API key to config.yaml")

    state = load_state()
    while True:
        start = time.time()
        run_cycle(cfg, sources, state)
        if a.once:
            break
        wait = max(60, cfg["check_every_minutes"] * 60 - (time.time() - start))
        log.info("Next check at %s", datetime.fromtimestamp(time.time() + wait).strftime("%I:%M %p"))
        time.sleep(wait)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
