"""Sends the alert text. Pick one method in config.yaml -> texting.method:

  twilio  - real SMS from a Twilio number (most reliable, small monthly cost)
  email   - free: emails your carrier's email-to-text address via Gmail
  ntfy    - free push notification to the ntfy phone app (not SMS, but instant)
  console - just prints (for testing)
"""
import logging
import smtplib
from email.message import EmailMessage

import requests

log = logging.getLogger("notify")


def send(cfg, body):
    t = cfg["texting"]
    method = t.get("method", "console")
    try:
        if method == "twilio":
            tw = t["twilio"]
            r = requests.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{tw['account_sid']}/Messages.json",
                auth=(tw["account_sid"], tw["auth_token"]),
                data={"From": tw["from_number"], "To": t["to_number"], "Body": body[:1500]},
                timeout=20,
            )
            r.raise_for_status()
        elif method == "email":
            em = t["email"]
            msg = EmailMessage()
            msg["From"] = em["gmail_address"]
            msg["To"] = em["to_address"]
            msg["Subject"] = ""
            msg.set_content(body[:600])  # carrier gateways cut long texts
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
                s.login(em["gmail_address"], em["gmail_app_password"])
                s.send_message(msg)
        elif method == "ntfy":
            r = requests.post(f"https://ntfy.sh/{t['ntfy']['topic']}",
                              data=body.encode("utf-8"),
                              headers={"Title": "Pokemon restock", "Priority": "high"},
                              timeout=20)
            r.raise_for_status()
        else:
            print("\n----- TEXT -----\n" + body + "\n----------------")
        return True
    except Exception as e:  # never crash the bot over a failed text
        log.error("Sending alert via %s failed: %s", method, e)
        return False
