"""
Email handler for the rental tax automation pipeline.

Two pipeline modes require different email requests:

  mode="nr6"     (November)
    Asks for ESTIMATED figures for the UPCOMING year.
    Used to fill NR6 election forms before January 1.

  mode="returns" (January)
    Asks for FINAL ACTUAL figures for the JUST-CLOSED year.
    Used to fill NR4, T776, and T1159 for the completed tax year.

Reply format (same structure for both modes, order-insensitive):

    RENTAL_INCOME: 28800
    PROPERTY_TAXES: 3200
    INSURANCE: 1800
    MORTGAGE_INTEREST: 12500
    REPAIRS_MAINTENANCE: 2100
    MANAGEMENT_FEES: 2880
    UTILITIES: 1400
    ADVERTISING: 300
    OTHER_EXPENSES: 0
"""

import imaplib
import json
import os
import re
import smtplib
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

# ── Reply key → data-dict path (section.field) ──────────────────────────────
REPLY_FIELD_MAP = {
    "RENTAL_INCOME":    ("annual_income", "rental_income"),
    "OTHER_INCOME":     ("annual_income", "other_income"),
    "ADVERTISING":      ("annual_expenses", "advertising"),
    "INSURANCE":        ("annual_expenses", "insurance"),
    "MORTGAGE_INTEREST":("annual_expenses", "mortgage_interest"),
    "OFFICE_EXPENSES":  ("annual_expenses", "office_expenses"),
    "PROFESSIONAL_FEES":("annual_expenses", "professional_fees"),
    "MANAGEMENT_FEES":  ("annual_expenses", "management_fees"),
    "REPAIRS_MAINTENANCE":("annual_expenses", "repairs_maintenance"),
    "SALARIES":         ("annual_expenses", "salaries"),
    "PROPERTY_TAXES":   ("annual_expenses", "property_taxes"),
    "TRAVEL":           ("annual_expenses", "travel"),
    "UTILITIES":        ("annual_expenses", "utilities"),
    "OTHER_EXPENSES":   ("annual_expenses", "other_expenses"),
}

# Subject prefixes — used to match replies in IMAP search
_SUBJECT = {
    "nr6":     "NR6 ELECTION DATA",
    "returns": "TAX RETURN DATA",
}


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------

def test_connection() -> bool:
    """
    Verify SMTP (sending) and IMAP (reading) both work.
    Sends a test email to OWNER_EMAIL_1 so you can confirm delivery.
    Returns True if both pass, False if either fails.
    """
    import smtplib, imaplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    sender   = os.environ.get("EMAIL_SENDER", "")
    password = os.environ.get("EMAIL_PASSWORD", "")
    owner1   = os.environ.get("OWNER_EMAIL_1", sender)

    # ── Check .env is populated ──────────────────────────────────────────────
    print("\n── Checking .env variables ──")
    missing = [k for k in ("EMAIL_SENDER", "EMAIL_PASSWORD", "OWNER_EMAIL_1", "OWNER_EMAIL_2")
               if not os.environ.get(k)]
    if missing:
        print(f"  MISSING: {', '.join(missing)}")
        print("  Fill in .env before running the pipeline.")
        return False
    print(f"  EMAIL_SENDER  : {sender}")
    print(f"  OWNER_EMAIL_1 : {os.environ.get('OWNER_EMAIL_1')}")
    print(f"  OWNER_EMAIL_2 : {os.environ.get('OWNER_EMAIL_2')}")
    print(f"  AGENT_EMAIL   : {os.environ.get('AGENT_EMAIL', '(not set)')}")
    print("  All required variables present.")

    # ── Test SMTP ────────────────────────────────────────────────────────────
    print("\n── Testing SMTP (sending) ──")
    try:
        smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port   = int(os.environ.get("SMTP_PORT", "587"))
        conn = smtplib.SMTP(smtp_server, smtp_port)
        conn.ehlo(); conn.starttls(); conn.login(sender, password)

        msg = MIMEMultipart()
        msg["From"]    = sender
        msg["To"]      = owner1
        msg["Subject"] = "Rental Tax Agent — connection test"
        msg.attach(MIMEText(
            "This is an automated test email from your rental tax agent.\n"
            "If you received this, SMTP is working correctly.\n", "plain"))
        conn.sendmail(sender, [owner1], msg.as_string())
        conn.quit()
        print(f"  SMTP OK — test email sent to {owner1}")
        print(f"  Check your inbox at {owner1} to confirm delivery.")
    except Exception as e:
        print(f"  SMTP FAILED: {e}")
        if "Username and Password" in str(e) or "535" in str(e):
            print("  → Wrong App Password. Re-generate it in your Google Account.")
        elif "IMAP" in str(e) or "534" in str(e):
            print("  → Gmail is blocking the login. Make sure you used an App Password.")
        return False

    # ── Test IMAP ────────────────────────────────────────────────────────────
    print("\n── Testing IMAP (reading) ──")
    try:
        imap_server = os.environ.get("IMAP_SERVER", "imap.gmail.com")
        imap_port   = int(os.environ.get("IMAP_PORT", "993"))
        conn = imaplib.IMAP4_SSL(imap_server, imap_port)
        conn.login(sender, password)
        conn.select("INBOX")
        _, data = conn.search(None, "ALL")
        count = len(data[0].split()) if data[0] else 0
        conn.logout()
        print(f"  IMAP OK — inbox accessible ({count} messages found)")
    except Exception as e:
        print(f"  IMAP FAILED: {e}")
        if "AUTHENTICATE" in str(e) or "AUTHENTICATIONFAILED" in str(e):
            print("  → IMAP not enabled. Go to Gmail Settings → Forwarding and POP/IMAP → Enable IMAP.")
        return False

    print("\n  All checks passed. The pipeline is ready to run.")
    return True


# ---------------------------------------------------------------------------
# SMTP helpers
# ---------------------------------------------------------------------------

def _smtp_connection():
    """Return an authenticated SMTP connection using env-var credentials."""
    server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    sender = os.environ["EMAIL_SENDER"]
    password = os.environ["EMAIL_PASSWORD"]

    conn = smtplib.SMTP(server, port)
    conn.ehlo()
    conn.starttls()
    conn.login(sender, password)
    return conn


def send_reminder(tax_year: int, recipients: list, mode: str = "nr6") -> str:
    """
    Send a data-request email and return its Message-ID.

    mode="nr6"     — November. Asks for ESTIMATED figures for the upcoming
                     year so we can fill the NR6 election forms.
    mode="returns" — January. Asks for FINAL ACTUAL figures for the just-
                     closed year so we can fill T776 and T1159.
    """
    sender  = os.environ["EMAIL_SENDER"]
    prefix  = _SUBJECT[mode]
    subject = f"{prefix} — {tax_year}"

    if mode == "nr6":
        purpose = (
            f"to complete the NR6 Section 216 election forms for {tax_year}.\n"
            f"These are ESTIMATES — they set the withholding level for {tax_year}.\n"
            f"Your actual figures will be confirmed in January {tax_year + 1}.\n"
            f"\n"
            f"The NR6 must reach CRA before January 1, {tax_year}.\n"
            f"Reply as soon as possible so we have time to submit."
        )
        forms_note = "NR6 × 2 (Section 216 election forms for both owners)"
    else:
        purpose = (
            f"to complete your {tax_year} tax returns (T776 + T1159).\n"
            f"These are FINAL ACTUAL figures — the {tax_year} year is now closed.\n"
            f"Returns are due June 30, {tax_year + 1}. Any balance owing is due April 30, {tax_year + 1}."
        )
        forms_note = f"NR4, T776 × 2, T1159 × 2 (tax returns for {tax_year})"

    body = f"""\
Hi,

We need your {tax_year} rental figures {purpose}

Please reply with the amounts below. Leave zeros for categories that don't apply.
Do not change the key names.

---
RENTAL_INCOME: [gross rent {"estimated for" if mode == "nr6" else "actually received in"} {tax_year}]
PROPERTY_TAXES: [{"estimated" if mode == "nr6" else "actual"} property tax]
INSURANCE: [{"estimated" if mode == "nr6" else "actual"} insurance premiums]
MORTGAGE_INTEREST: [{"estimated" if mode == "nr6" else "actual"} mortgage interest]
REPAIRS_MAINTENANCE: [{"estimated" if mode == "nr6" else "actual"} repairs and maintenance]
MANAGEMENT_FEES: [{"estimated" if mode == "nr6" else "actual"} property management fees]
UTILITIES: [{"estimated" if mode == "nr6" else "actual"} utilities]
ADVERTISING: [{"estimated" if mode == "nr6" else "actual"} advertising costs]
OTHER_EXPENSES: [any other deductible expenses]
---

Once we receive your reply the agent will:
  • Fill {forms_note}
  • Email the completed PDFs to both owners

This email was sent automatically by the rental tax automation agent.
"""

    msg = MIMEMultipart()
    msg["From"]    = sender
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with _smtp_connection() as conn:
        conn.sendmail(sender, recipients, msg.as_string())

    message_id = msg.get("Message-ID", "")
    print(f"[{mode}] Reminder sent to {recipients}")
    return message_id


# ---------------------------------------------------------------------------
# IMAP polling
# ---------------------------------------------------------------------------

def _imap_connection():
    """Return an authenticated IMAP4_SSL connection."""
    server = os.environ.get("IMAP_SERVER", "imap.gmail.com")
    port = int(os.environ.get("IMAP_PORT", "993"))
    user = os.environ["EMAIL_SENDER"]
    password = os.environ["EMAIL_PASSWORD"]

    conn = imaplib.IMAP4_SSL(server, port)
    conn.login(user, password)
    return conn


# Nudge schedule: (after_hours, urgent, subject_prefix, one_line_message)
# Sent once each, only if no reply has arrived yet.
# Spread across a 30-day window.
_NUDGE_SCHEDULE = [
    (5  * 24, False, "Reminder",
              "We sent you a data request 5 days ago and haven't heard back yet."),
    (10 * 24, False, "Following up",
              "Still waiting — 10 days have passed since we sent the request."),
    (20 * 24, False, "Please reply soon",
              "20 days in — please reply as soon as you can. Time is getting short."),
    (29 * 24, True,  "URGENT: Last day tomorrow",
              "Tomorrow is the final day of the 30-day window. If we don't receive your "
              "reply by end of day, the forms will not be filled automatically this cycle."),
]


def _send_nudge(
    tax_year: int,
    mode: str,
    recipients: list,
    message: str,
    urgent: bool,
    subject_prefix: str,
) -> None:
    """Send a single follow-up nudge email."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    sender  = os.environ["EMAIL_SENDER"]
    urgency = "⚠️ " if urgent else ""
    subject = f"{urgency}{subject_prefix}: {_SUBJECT[mode]} — {tax_year}"

    form_desc = "NR6 election forms" if mode == "nr6" else "T776 and T1159 tax returns"
    body = f"""\
Hi,

{message}

To trigger the automatic form filling, simply reply to the original email
with your figures in this format:

RENTAL_INCOME: [amount]
PROPERTY_TAXES: [amount]
INSURANCE: [amount]
MORTGAGE_INTEREST: [amount]
REPAIRS_MAINTENANCE: [amount]
MANAGEMENT_FEES: [amount]
UTILITIES: [amount]
ADVERTISING: [amount]
OTHER_EXPENSES: [amount]

We need these figures to fill your {form_desc} for {tax_year}.

This is an automated nudge from the rental tax agent.
"""
    msg = MIMEMultipart()
    msg["From"]    = sender
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    password    = os.environ["EMAIL_PASSWORD"]
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port   = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(smtp_server, smtp_port) as conn:
        conn.ehlo(); conn.starttls(); conn.login(sender, password)
        conn.sendmail(sender, recipients, msg.as_string())
    print(f"[{mode}] Nudge sent ({subject_prefix}) → {recipients}")


def poll_for_reply(
    tax_year: int,
    mode: str = "nr6",
    recipients: Optional[list] = None,
    check_interval_seconds: int = 300,
    timeout_hours: float = 720,   # 30 days
) -> Optional[str]:
    """
    Poll the inbox for a reply, sending escalating nudges if none arrives.

    Nudge schedule (sent once each, only while still waiting):
      Day  5 — gentle reminder
      Day 10 — following up
      Day 20 — please reply soon
      Day 29 — URGENT: last day tomorrow

    Returns the reply body on success, or None after 30 days with no reply.
    On timeout the caller exits cleanly — no stale data is used.

    If you reply after the process has already exited:
        python3 main.py --process-reply --mode nr6   (or --mode returns)
    """
    import email as email_lib

    max_checks   = int((timeout_hours * 3600) / check_interval_seconds)
    prefix       = _SUBJECT[mode]
    nudges_sent  = set()   # track which nudges have fired so each sends once

    print(
        f"[{mode}] Polling inbox for reply (every {check_interval_seconds//60} min, "
        f"up to {int(timeout_hours//24)} days, with nudges on days 5/10/20/29)..."
    )

    for attempt in range(max_checks):
        elapsed_hours = attempt * check_interval_seconds / 3600

        # Send any nudge whose threshold we've just crossed
        if recipients:
            for after_h, urgent, subj_prefix, message in _NUDGE_SCHEDULE:
                if elapsed_hours >= after_h and after_h not in nudges_sent:
                    nudges_sent.add(after_h)
                    try:
                        _send_nudge(tax_year, mode, recipients,
                                    message, urgent, subj_prefix)
                    except Exception as e:
                        print(f"[{mode}] Nudge send failed: {e}")

        # Check inbox (and spam/all mail) for reply
        try:
            conn = _imap_connection()
            our_addr = os.environ["EMAIL_SENDER"]
            for _, _, body in _search_folders(conn, prefix, tax_year, our_addr):
                if body and _has_reply_fields(body):
                    conn.logout()
                    print(f"[{mode}] Reply found after {elapsed_hours:.0f}h.")
                    return body
            conn.logout()
        except Exception as exc:
            print(f"[{mode}] IMAP poll error (attempt {attempt + 1}): {exc}")

        if attempt < max_checks - 1:
            time.sleep(check_interval_seconds)

    print(f"[{mode}] Timed out after 30 days. No reply received.")
    return None


def _extract_text_body(parsed_msg) -> str:
    """Return the plaintext body of a parsed email."""
    if parsed_msg.is_multipart():
        for part in parsed_msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(errors="replace")
    else:
        payload = parsed_msg.get_payload(decode=True)
        if payload:
            return payload.decode(errors="replace")
    return ""


def _has_reply_fields(body: str) -> bool:
    """Return True if the body contains at least one KEY: NUMBER line with an actual number."""
    return bool(re.search(r"^[A-Z_]+\s*:\s*\d", body, re.M | re.I))


def _decode_subject(raw_subject: str) -> str:
    """Decode a MIME-encoded email subject to plain text."""
    from email.header import decode_header
    parts = decode_header(raw_subject or "")
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def _search_folders(conn, prefix: str, tax_year: int, our_addr: str):
    """
    Search INBOX and Spam for a matching reply.

    Does NOT use IMAP server-side SUBJECT search because Gmail encodes
    non-ASCII characters (like the em dash in our subject) as MIME base64,
    which breaks server-side substring matching. Instead we fetch the last
    100 messages from each folder and decode subjects in Python.

    Yields (folder_name, parsed_message, body) for every candidate found.
    """
    import email as email_lib

    folders = ["INBOX", "[Gmail]/Spam"]

    for folder in folders:
        try:
            result, _ = conn.select(folder, readonly=True)
            if result != "OK":
                continue
            # Fetch ALL message IDs, then check only the most recent 100
            _, data = conn.search(None, "ALL")
            all_ids = data[0].split()
            recent  = all_ids[-100:] if len(all_ids) > 100 else all_ids

            for mid in reversed(recent):   # newest first
                _, msg_data = conn.fetch(mid, "(RFC822)")
                parsed = email_lib.message_from_bytes(msg_data[0][1])
                subj   = _decode_subject(parsed.get("Subject", ""))
                sender = parsed.get("From", "")

                # Must contain both the prefix and the year
                if prefix not in subj or str(tax_year) not in subj:
                    continue
                # Skip the original outgoing email we sent
                if our_addr.lower() in sender.lower() and "Re:" not in subj:
                    continue
                body = _extract_text_body(parsed)
                yield folder, parsed, body
        except Exception:
            continue  # folder doesn't exist or isn't accessible


def check_inbox_now(tax_year: int, mode: str = "nr6") -> Optional[str]:
    """
    Single-pass check across INBOX, Spam, and All Mail.
    Used by --process-reply when you reply after the pipeline has already exited.

    Prints debug info showing every matching email it finds, so you can see
    exactly what was received and whether the reply format was correct.
    """
    prefix   = _SUBJECT[mode]
    our_addr = os.environ["EMAIL_SENDER"]

    try:
        conn = _imap_connection()
    except Exception as exc:
        print(f"[{mode}] IMAP connection failed: {exc}")
        return None

    found_any = False
    result_body = None

    for folder, parsed, body in _search_folders(conn, prefix, tax_year, our_addr):
        found_any = True
        subj   = parsed.get("Subject", "")
        sender = parsed.get("From", "")
        has_fields = _has_reply_fields(body) if body else False

        print(f"\n  Found in [{folder}]:")
        print(f"    From   : {sender}")
        print(f"    Subject: {subj}")
        print(f"    Has KEY:VALUE fields: {'YES' if has_fields else 'NO'}")

        if not has_fields and body:
            # Show first 300 chars so user can see what was actually sent
            preview = body.strip()[:300].replace('\n', ' | ')
            print(f"    Body preview: {preview}")
            print(f"    --> Reply must contain lines like  RENTAL_INCOME: 28800")

        if has_fields and result_body is None:
            result_body = body

    conn.logout()

    if not found_any:
        print(f"\n[{mode}] No emails matching '{prefix}' found in any folder.")
        print("  Make sure you replied to the original reminder email")
        print(f"  (subject contained: {prefix} — {tax_year})")
        return None

    if result_body is None:
        print(f"\n[{mode}] Email(s) found but none contained the KEY: VALUE figures.")
        print("  Reply to the reminder email with lines exactly like:")
        print("    RENTAL_INCOME: 28800")
        print("    PROPERTY_TAXES: 3200")
        print("    (etc.)")
        return None

    print(f"\n[{mode}] Valid reply found — processing.")
    return result_body


# ---------------------------------------------------------------------------
# Reply parser
# ---------------------------------------------------------------------------

def parse_reply(reply_body: str) -> dict:
    """
    Extract KEY: VALUE pairs from the reply body and return a flat dict
    of {key: float} for all recognised keys.

    Unrecognised lines are silently ignored.
    """
    result = {}
    for line in reply_body.splitlines():
        # Match lines like "RENTAL_INCOME: 28800" (leading/trailing whitespace ok)
        m = re.match(r"^\s*([A-Z_]+)\s*:\s*([\d,.\-]+)", line.strip(), re.I)
        if m:
            key = m.group(1).upper()
            raw = m.group(2).replace(",", "")
            if key in REPLY_FIELD_MAP:
                try:
                    result[key] = float(raw)
                except ValueError:
                    pass
    return result


def merge_reply_into_data(base_data: dict, parsed_reply: dict) -> dict:
    """
    Return a copy of base_data with annual_income/annual_expenses updated
    from the parsed reply. Static fields (names, addresses, SINs) are
    never overwritten.
    """
    import copy
    data = copy.deepcopy(base_data)
    for key, value in parsed_reply.items():
        if key in REPLY_FIELD_MAP:
            section, field = REPLY_FIELD_MAP[key]
            data[section][field] = value
    return data


# ---------------------------------------------------------------------------
# Send completed PDFs
# ---------------------------------------------------------------------------

def send_completed_pdfs(
    tax_year: int,
    pdf_paths: dict,
    recipients: list[str],
) -> None:
    """
    Email the filled PDF files to all recipients.

    pdf_paths: {label: Path} as returned by pdf_filler.fill_all_forms()
    """
    sender = os.environ["EMAIL_SENDER"]
    subject = f"[COMPLETED] {tax_year} Rental Tax Forms — CRA Filing Package"

    form_list = "\n".join(
        f"  • {label}: {Path(p).name}" for label, p in pdf_paths.items()
    )
    body = f"""\
Your {tax_year} CRA rental tax forms are ready.

Attached ({len(pdf_paths)} files):
{form_list}

Filing reminders:
  • NR6 (×2)    — submit to CRA by January 1, {tax_year + 1}
  • NR4          — issued by withholding agent; keep for your records
  • T776         — attach to T1159
  • T1159 (×2)  — file with CRA by June 30, {tax_year + 1}

Review all forms before submitting. Values were computed from the figures
you provided; consult a tax advisor for any questions.

This email was sent automatically by the rental tax automation agent.
"""

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    for label, pdf_path in pdf_paths.items():
        path = Path(pdf_path)
        if not path.exists():
            print(f"  WARNING: {path} not found, skipping attachment.")
            continue
        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{path.name}"',
        )
        msg.attach(part)

    with _smtp_connection() as conn:
        conn.sendmail(sender, recipients, msg.as_string())

    print(f"Completed forms sent to {recipients}.")


# ---------------------------------------------------------------------------
# Stand-alone test (dry-run — does not actually send email)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample_reply = """
Hi, here are the 2025 numbers:

RENTAL_INCOME: 29400
PROPERTY_TAXES: 3350
INSURANCE: 1850
MORTGAGE_INTEREST: 12200
REPAIRS_MAINTENANCE: 1900
MANAGEMENT_FEES: 2940
UTILITIES: 1500
ADVERTISING: 0
OTHER_EXPENSES: 200
"""
    parsed = parse_reply(sample_reply)
    print("Parsed reply fields:")
    for k, v in parsed.items():
        print(f"  {k}: {v}")

    data_path = Path(__file__).parent / "data" / "base_year_data.json"
    with open(data_path) as f:
        base = json.load(f)

    merged = merge_reply_into_data(base, parsed)
    print(f"\nMerged rental_income: {merged['annual_income']['rental_income']}")
    print(f"Merged property_taxes: {merged['annual_expenses']['property_taxes']}")
    print("parse_reply test passed.")
