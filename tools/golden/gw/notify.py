"""Telegram delivery.

Findings are batched into one message per run so a noisy morning does not turn
into twelve buzzes. High-scoring litter findings are sent as their own message
with a link, because those are the ones worth interrupting you for.
"""
import os
import html
import requests

API = "https://api.telegram.org/bot{token}/sendMessage"


def credentials(cfg):
    token = cfg.get("telegram", {}).get("bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = cfg.get("telegram", {}).get("chat_id") or os.environ.get("TELEGRAM_CHAT_ID", "")
    return token.strip(), str(chat).strip()


def send(cfg, text, silent=False):
    token, chat = credentials(cfg)
    if not token or not chat:
        print("[notify] Telegram not configured; message not sent:\n" + text)
        return False
    try:
        resp = requests.post(
            API.format(token=token),
            json={
                "chat_id": chat,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
                "disable_notification": silent,
            },
            timeout=20,
        )
        if resp.status_code != 200:
            print(f"[notify] Telegram returned {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except requests.RequestException as exc:
        print(f"[notify] Telegram unreachable: {exc}")
        return False


def _esc(s):
    return html.escape(str(s), quote=False)


def format_finding(f):
    head = {"litter": "LITTER", "event": "EVENT", "referral": "REFERRAL",
            "nudge": "FOLLOW UP", "ofa": "CLEARANCES"}.get(f["kind"], f["kind"].upper())
    return (
        f"<b>{_esc(head)} · {_esc(f['label'])}</b>\n"
        f"{_esc(f['excerpt'])}\n"
        f'<a href="{_esc(f["url"])}">{_esc(f["url"])}</a>'
    )


def dispatch(cfg, findings):
    """Send findings. Returns the ids that went out."""
    if not findings:
        return []

    threshold = cfg.get("watcher", {}).get("alert_threshold", 3)
    urgent = [f for f in findings if f["kind"] == "litter" and f["score"] >= threshold]
    rest = [f for f in findings if f not in urgent]
    sent = []

    for f in urgent:
        if send(cfg, "🐾 " + format_finding(f)):
            sent.append(f["id"])

    if rest:
        body = "\n\n".join(format_finding(f) for f in rest[:12])
        more = f"\n\n<i>+{len(rest) - 12} more on the dashboard</i>" if len(rest) > 12 else ""
        if send(cfg, body + more, silent=True):
            sent.extend(f["id"] for f in rest)

    return sent
