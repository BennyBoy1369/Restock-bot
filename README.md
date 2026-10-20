# Pokemon Restock Bot

Texts you when Pokemon cards restock at **Target, Walmart, Best Buy, Costco, or Sam's Club within 13 miles of West Bloomfield**.

| Store | Where the data comes from |
|---|---|
| Best Buy | Official Best Buy API: real in-store stock and price per store |
| Target | target.com's store-availability data: stock, price, distance |
| Walmart | walmart.com online stock (best effort), plus community reports for in-store |
| Costco, Sam's Club | Community reports only (Reddit). Neither store puts in-store stock online. |

Anything outside the radius is ignored. Community reports only count if they name a nearby town.
Texts are marked **REPORT:** when they come from people instead of a store's own data, so treat those as tips.

## Running it on GitHub (PC can stay off)

The `.github/workflows/restock.yml` file makes GitHub run a check about every 5 minutes for free.
Your ntfy topic and Best Buy key go in the repo's **Settings → Secrets and variables → Actions**
as `NTFY_TOPIC` and `BESTBUY_API_KEY`, never in `config.yaml`. The repo must be **public**
(public repos get unlimited free Actions minutes). Walmart is turned off there because it blocks GitHub.
GitHub pauses schedules after 60 days with no changes to the repo. If you get that email, click
**Enable workflow** on the Actions tab.

### Extra sources

- **Slickdeals:** the official front-page feed catches Pokémon deals at Walmart.com, Costco.com, SamsClub.com, Target.com, and BestBuy.com. These texts say **ONLINE DEAL** because they're website deals, not in-store.
- **Reddit:** the bot reads new posts **and comments**. Without a Reddit app it reads anonymously, and if Reddit blocks it, the log says
  *"Reddit blocked every request this run."* To fix that for good:
  1. Since November 2025, Reddit approves new API apps by hand. Submit a request through Reddit's Developer Support form under their Responsible Builder Policy. Describe it as a personal, read-only script that checks a few subreddits for Pokémon restock posts.
  2. Once approved, go to **reddit.com/prefs/apps**, click **create app**, choose **script**, and use `http://localhost:8080` as the redirect URI.
  3. Add GitHub secrets `REDDIT_CLIENT_ID` (the code under the app name), `REDDIT_CLIENT_SECRET`, and `REDDIT_USERNAME` (your Reddit name).

## 1. Install on a PC (one time)

1. Install **Python 3** from python.org. On Windows, check **"Add Python to PATH."**
2. Unzip this folder somewhere, e.g. `Documents\restock-bot`.
3. Open a terminal in that folder and run:
   ```
   pip install -r requirements.txt
   python restock_bot.py --selftest
   ```
   It should end with "Self-test passed."

## 2. Get a Best Buy key (free, 2 minutes)

Sign up at **developer.bestbuy.com**, copy your API key, and paste it into `config.yaml` under `bestbuy: api_key:`.

## 3. Set up texting

In `config.yaml`, set `texting: method:` to one of these:

- **`email` (free):** emails your carrier's text address from a Gmail account.
  - In Gmail, turn on 2-Step Verification, then create an **App password** (Google Account → Security → App passwords). Put it in `gmail_app_password`.
  - Set `to_address` to your number at your carrier's gateway, e.g. `2485551234@tmomail.net` (T-Mobile) or `2485551234@vtext.com` (Verizon).
  - Some carriers have shut these gateways down (AT&T did). If test texts never arrive, use ntfy or Twilio.
- **`ntfy` (free, most reliable free option):** install the **ntfy** app, subscribe to the topic name in `config.yaml`, and you'll get instant notifications. These aren't SMS, but they work the same way.
- **`twilio` (real SMS):** make an account at twilio.com and buy a number (about $1–2/month plus pennies per text). US carriers require Twilio's texting registration, which takes a few days.

Test it:
```
python restock_bot.py --test-text
```

## 4. Run it

```
python restock_bot.py
```
Leave the window open. It checks every 5 minutes and texts you only when something **newly** comes into stock, with a maximum of 6 texts per hour.

To start it automatically when your PC boots (Windows), make a shortcut to `start_bot.bat` and put it in the Startup folder. Press Win+R, type `shell:startup`, and drop the shortcut in.

## Changing things

Everything is in `config.yaml`:

- `radius_miles`: how far is too far
- `stores`: which stores to watch (you can add `"Meijer"` or `"GameStop"` to `community: stores:` too)
- `check_every_minutes`: don't go below 3, or stores may block you
- `target: tcins`: exact Target item numbers to always watch (the number after `A-` in a Target product URL)

## Fixing Target

If the log keeps saying Target checks failed, Target probably changed its website key.
1. Open any product page on target.com in Chrome.
2. Press F12, go to the **Network** tab, and reload.
3. Filter for `redsky`, click a request, and copy the `key=` value from its URL.
4. Paste it into `config.yaml` → `target: web_key:`.

## Limits

- No bot can see in-store stock at Costco or Sam's Club; those alerts depend on someone posting about it.
- Walmart often blocks automated checks. The bot pauses Walmart for an hour when that happens instead of hammering the site.
- Target and Walmart checks use the stores' public website data, not official APIs, so they can stop working when the sites change.
