"""
Deadline reminders for the rental tax pipeline.

Two distinct responsibilities:
  1. check_and_send_deadline_reminders()
       Called daily (launchd: com.rentaltax.reminders.plist).
       Sends emails when we're within the warning window of each CRA deadline.
       Attaches the relevant pre-filled PDF if it exists.

  2. send_monthly_agent_reminder()
       Called on the 15th of each month by the same daily plist.
       Reminds the withholding agent to remit 25 % of net rental income to CRA.

Deadline calendar for Section 216 non-resident rental property:

  Jan  1   NR6 due      — non-resident must file before first rent payment
  Mar 31   NR4 due      — withholding agent files information return + summary
  Apr 30   Balance due  — pay any tax owing to avoid interest
  Jun 30   T1159 due    — Section 216 income tax return (each non-resident)
  15th/mo  Remittance   — agent remits 25 % of net income within 15 days of
                          each rental payment month

US-side obligations (outside CRA scope — consult a cross-border accountant):
  • IRS Schedule E  — report Canadian rental income on US return
  • IRS Form 1116   — claim foreign tax credit for CRA taxes paid
  • FinCEN 114 (FBAR) — if Canadian bank account > USD 10,000 at any point
"""

import json
import os
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data" / "base_year_data.json"
OUTPUT_DIR = BASE_DIR / "generated_forms"
LOG_FILE = BASE_DIR / "logs" / "reminders.json"

# (name, month, day, warn_days, who_receives, attach_form_keys)
DEADLINES = [
    ("NR6",         1,  1,  45, "owners",  ["NR6_owner1", "NR6_owner2"]),
    ("NR4",         3, 31,  30, "agent",   ["NR4"]),
    ("TAX_PAYMENT", 4, 30,  30, "owners",  []),
    ("T1159",       6, 30,  30, "owners",  ["T1159_owner1", "T1159_owner2"]),
]

DESCRIPTIONS = {
    "NR6":         "NR6 (Section 216 election) is due before January 1 — submit to CRA before the first rental payment.",
    "NR4":         "NR4 information return is due March 31 — withholding agent must file with CRA and give copies to owners.",
    "TAX_PAYMENT": "Any remaining 2025 tax balance is due April 30. Pay now to avoid daily interest.",
    "T1159":       "T1159 (Section 216 income tax return) is due June 30 — each owner files their own return.",
}


# ---------------------------------------------------------------------------
# State helpers (avoid sending the same reminder twice in one year)
# ---------------------------------------------------------------------------

def _load_log() -> list:
    if LOG_FILE.exists():
        with open(LOG_FILE) as f:
            return json.load(f)
    return []


def _save_log(records: list) -> None:
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "w") as f:
        json.dump(records, f, indent=2, default=str)


def _already_sent(log: list, name: str, year: int) -> bool:
    return any(
        r["name"] == name and r["year"] == year and r["status"] == "sent"
        for r in log
    )


def _record(log: list, name: str, year: int, status: str) -> list:
    log.append({"name": name, "year": year, "status": status,
                 "ts": datetime.now().isoformat()})
    return log


# ---------------------------------------------------------------------------
# Deadline reminder
# ---------------------------------------------------------------------------

def check_and_send_deadline_reminders() -> int:
    """
    Check today against every deadline. Send an email if we're within the
    warning window and haven't already sent one this year.
    Returns the number of reminders sent.
    """
    from email_handler import send_reminder as _send  # reuse SMTP helper

    with open(DATA_FILE) as f:
        data = json.load(f)

    today = datetime.now()
    tax_year = today.year  # the year whose deadlines we're watching
    log = _load_log()
    sent = 0

    recipients_owners = [
        addr for addr in [
            os.environ.get("OWNER_EMAIL_1", ""),
            os.environ.get("OWNER_EMAIL_2", ""),
        ] if addr
    ]
    recipient_agent = [a for a in [os.environ.get("AGENT_EMAIL", "")] if a]

    for name, month, day, warn_days, who, form_keys in DEADLINES:
        deadline = datetime(tax_year, month, day)
        days_left = (deadline - today).days

        if not (0 <= days_left <= warn_days):
            continue
        if _already_sent(log, name, tax_year):
            continue

        recipients = recipients_owners if who == "owners" else recipient_agent
        if not recipients:
            continue

        # Gather existing PDF attachments
        pdf_paths = {}
        for key in form_keys:
            pattern = list(OUTPUT_DIR.glob(f"{key.replace('_', '_')}_{tax_year - 1}*.pdf"))
            if not pattern:
                pattern = list(OUTPUT_DIR.glob(f"*{tax_year - 1}*.pdf"))
            # Map form key → most recent matching PDF
            candidates = list(OUTPUT_DIR.glob(f"{'NR6' if 'NR6' in key else ('NR4' if 'NR4' in key else ('T776' if 'T776' in key else 'T1159'))}_{tax_year - 1}*.pdf"))
            if candidates:
                pdf_paths[key] = candidates[0]

        _send_deadline_email(
            name=name,
            description=DESCRIPTIONS.get(name, ""),
            days_left=days_left,
            recipients=recipients,
            pdf_paths=pdf_paths,
            tax_year=tax_year - 1,  # we're sending about last year's return
        )
        log = _record(log, name, tax_year, "sent")
        sent += 1

    # Monthly agent remittance reminder (15th of the month)
    if today.day == 15:
        prev_month = today.month - 1 if today.month > 1 else 12
        prev_year = today.year if today.month > 1 else today.year - 1
        key = f"AGENT_REMITTANCE_{prev_year}_{prev_month:02d}"
        if not _already_sent(log, key, tax_year) and recipient_agent:
            _send_monthly_agent_reminder(data, prev_month, prev_year, recipient_agent)
            log = _record(log, key, tax_year, "sent")
            sent += 1

    _save_log(log)
    return sent


def _send_deadline_email(
    name: str,
    description: str,
    days_left: int,
    recipients: list,
    pdf_paths: dict,
    tax_year: int,
) -> None:
    import smtplib
    from email import encoders
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    sender = os.environ["EMAIL_SENDER"]
    subject = f"[ACTION] CRA Deadline: {name} — {days_left} days remaining"
    body = f"""\
CRA filing reminder for tax year {tax_year}.

{description}

Days remaining: {days_left}

{_filing_calendar()}

This email was sent automatically by the rental tax automation agent.
Review all attached forms before signing or submitting.
"""
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    for key, path in pdf_paths.items():
        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{Path(path).name}"')
        msg.attach(part)

    password = os.environ["EMAIL_PASSWORD"]
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(smtp_server, smtp_port) as conn:
        conn.ehlo()
        conn.starttls()
        conn.login(sender, password)
        conn.sendmail(sender, recipients, msg.as_string())

    print(f"Deadline reminder sent: {name} → {recipients}")


def _send_monthly_agent_reminder(
    data: dict,
    month: int,
    year: int,
    recipients: list,
) -> None:
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from calendar import month_name

    agent = data["withholding_agent"]
    income = data["annual_income"]
    expenses = data["annual_expenses"]
    monthly_gross = income["rental_income"] / 12
    monthly_net = (income["rental_income"] - sum(expenses.values())) / 12
    withholding = monthly_net * 0.25

    sender = os.environ["EMAIL_SENDER"]
    subject = f"CRA Remittance Due: 25% withholding for {month_name[month]} {year}"
    body = f"""\
Hi {agent['name']},

This is your monthly reminder to remit non-resident withholding tax to CRA.

  Period:        {month_name[month]} {year}
  Due date:      15th of next month
  Gross rent:    ${monthly_gross:,.0f}
  Est. expenses: ${(monthly_gross - monthly_net):,.0f}
  Net income:    ${monthly_net:,.0f}
  Withholding (25%): ${withholding:,.0f}

How to remit:
  1. Log in to CRA My Business Account
  2. Select "Make a payment" → Non-resident withholding
  3. Reference the owners' NR account numbers

Property: {data['property']['address']}, {data['property']['city']}, {data['property']['province']}

This email was sent automatically by the rental tax automation agent.
"""
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    password = os.environ["EMAIL_PASSWORD"]
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(smtp_server, smtp_port) as conn:
        conn.ehlo()
        conn.starttls()
        conn.login(sender, password)
        conn.sendmail(sender, recipients, msg.as_string())

    from calendar import month_name as mn
    print(f"Monthly agent reminder sent for {mn[month]} {year}")


def _filing_calendar() -> str:
    return """\
Annual filing calendar (Section 216 election):
  Jan  1   NR6 due       — submit before first rent payment each year
  Mar 31   NR4 due       — withholding agent files with CRA
  Apr 30   Balance due   — pay any tax owing to avoid interest
  Jun 30   T1159 due     — Section 216 income tax return (per owner)
  15th/mo  Remittance    — agent remits 25 % of net income monthly

US obligations (outside CRA scope — file with IRS):
  Schedule E   — report Canadian rental income
  Form 1116    — claim foreign tax credit for CRA taxes paid
  FinCEN 114   — FBAR if Canadian accounts > USD 10,000"""


# ---------------------------------------------------------------------------
# Stand-alone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Reminders module loaded. Deadlines:")
    for name, month, day, warn_days, who, _ in DEADLINES:
        print(f"  {name:12s} {month:02d}/{day:02d}  warn={warn_days}d  to={who}")
    print("\nTo run daily check: python reminders.py (needs EMAIL_* env vars)")
