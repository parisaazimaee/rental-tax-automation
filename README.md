# 🍁 Rental Tax Automation

> Automates the annual Canadian CRA filing cycle for non-resident rental property owners (Section 216 election). Set it up once — it runs itself every year.

---

## How it works

The filing cycle has two data-collection moments — estimated figures collected in November for the NR6 election, and final actual figures collected in January for the annual return — plus a third agent that watches CRA deadlines daily in between.

```
  NOV 1                    JAN 15                   DAILY
     │                        │                       │
     ▼                        ▼                       ▼
┌─────────────┐        ┌─────────────┐        ┌─────────────┐
│  NR6 Agent  │        │Returns Agent│        │  Reminders  │
│             │        │             │        │    Agent    │
│ "Estimate   │        │ "Confirm    │        │             │
│  next year" │        │  last year" │        │ Deadline    │
│             │        │             │        │ + monthly   │
│ → NR6 ×2   │        │ → NR4       │        │ remittance  │
│             │        │ → T776 ×2   │        │ reminders   │
│             │        │ → T1159 ×2  │        │             │
└─────────────┘        └─────────────┘        └─────────────┘
       │                      │
       ▼                      ▼
  You reply to          You reply to
  an email with         an email with
  estimated figures     final actuals
       │                      │
       ▼                      ▼
  PDFs filled &         PDFs filled &
  emailed back          emailed back
  in minutes            in minutes
```

---

## CRA forms covered

| Form | Who files | Deadline | What it does |
|---|---|---|---|
| **NR6 ×2** | Each owner + agent | Before Jan 1 | Elects 25% withholding on *net* income instead of gross — re-filed every year |
| **NR4** | Withholding agent | March 31 | Reports gross income paid + tax withheld per owner; agent also files NR4 Summary electronically |
| **T776 ×2** | Each owner | With T1159 | Each owner's 50% share of income and expenses; co-owner listed in Part 2 |
| **T1159 ×2** | Each owner | June 30 | Section 216 income tax return — print and mail, no NETFILE |

> 📬 Mail T776 + T1159 to: **CRA International Tax Services Office, 2204 Walkley Road, Ottawa ON K1A 1A8**

> ⚠️ Balance owing is due **April 30**. The return itself is due June 30. Interest accrues daily from May 1.

---

## Annual calendar

```
NOVEMBER
  Nov  1  ──── 📧 NR6 agent fires: "estimate 2026 figures"
  Nov  6  ──── nudge: 5 days, still waiting
  Nov 11  ──── nudge: 10 days, following up
  Nov 21  ──── nudge: 20 days, please reply soon
  Nov 30  ──── 🚨 URGENT: tomorrow is the last day
  Dec  1  ──── window closes
  ─────────────────────────────────────────────────────────
  Any time Nov 1 – Dec 1: reply → NR6 ×2 emailed back ✅
  ─────────────────────────────────────────────────────────
  ~Nov 16 ──── 🔔 reminder: NR6 due in 45 days
  Jan  1  ──── ⚠️  DEADLINE: sign and mail NR6 to CRA

JANUARY
  Jan  1  ──── 📧 monthly remittance reminder to agent
  Jan 15  ──── 📧 returns agent fires: "confirm final 2025 figures"
  Jan 20  ──── nudge: 5 days
  Jan 25  ──── nudge: 10 days
  Feb  4  ──── nudge: 20 days
  Feb 13  ──── 🚨 URGENT: tomorrow is the last day
  Feb 14  ──── window closes
  ─────────────────────────────────────────────────────────
  Any time Jan 15 – Feb 14: reply → NR4 + T776 ×2 + T1159 ×2 emailed back ✅
  ─────────────────────────────────────────────────────────

FEBRUARY – JUNE
  15th/mo ──── 📧 remittance reminder to withholding agent
  ~Mar  1 ──── 🔔 reminder: NR4 due in 30 days
  Mar 31  ──── ⚠️  DEADLINE: agent files NR4 slips + NR4 Summary
  ~Apr  1 ──── 🔔 reminder: balance owing due in 30 days
  Apr 30  ──── ⚠️  DEADLINE: pay balance owing (interest starts May 1)
  ~Jun  1 ──── 🔔 reminder: T1159 due in 30 days
  Jun 30  ──── ⚠️  DEADLINE: mail T776 + T1159 to CRA

  🔁 November 1 — whole cycle repeats
```

---

## One-time setup

### 1. Install

```bash
python3 -m pip install pypdf python-dotenv
```

### 2. Create `.env`

```bash
EMAIL_SENDER=your-dedicated-address@gmail.com
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx    # Gmail App Password, not login password
OWNER_EMAIL_1=parisa@example.com
OWNER_EMAIL_2=shahriar@example.com
AGENT_EMAIL=agent@example.com
```

**Gmail App Password:** Google Account → Security → 2-Step Verification → App passwords → create one named `rental-tax`.

**Enable IMAP:** Gmail → Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP.

### 3. Add real property data

Edit `data/base_year_data.json`. Replace every fake value.

- **Static** (set once, never re-asked): names, SINs, DOBs, addresses, NR account numbers, agent info, ownership %
- **Annual** (updated via email reply): `annual_income` and `annual_expenses`

Add `data/base_year_data.json` to `.gitignore` once it has real SINs.

### 4. Test without email

```bash
python3 main.py --fill-only --mode nr6      # NR6 forms for upcoming year
python3 main.py --fill-only --mode returns  # NR4/T776/T1159 for last year
```

Open a PDF from `generated_forms/` to confirm fields are populated.

### 5. Deploy

```bash
mkdir -p ~/Library/Logs/rentaltax
cp deploy/com.rentaltax.nr6.plist       ~/Library/LaunchAgents/
cp deploy/com.rentaltax.returns.plist   ~/Library/LaunchAgents/
cp deploy/com.rentaltax.reminders.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.rentaltax.nr6.plist
launchctl load ~/Library/LaunchAgents/com.rentaltax.returns.plist
launchctl load ~/Library/LaunchAgents/com.rentaltax.reminders.plist
launchctl list | grep rentaltax    # should show 3 lines
```

---

## Manual commands

```bash
python3 main.py --fill-only --mode nr6       # fill NR6 PDFs, no email
python3 main.py --fill-only --mode returns   # fill return PDFs, no email
python3 main.py --renew-election             # full NR6 pipeline (send + wait + fill + email)
python3 main.py --file-return                # full returns pipeline
python3 main.py --send-reminder --mode nr6   # send email only, no waiting
python3 main.py --process-reply --mode nr6   # check inbox now + fill + email (late reply)
python3 main.py --check-reminders            # send any deadline reminders due today
python3 main.py --test-connection            # verify SMTP + IMAP credentials
python3 main.py --fill-only --year 2025      # override year on any command
```

---

## Project structure

```
rental_tax_automation/
├── data/
│   └── base_year_data.json   ← property + owner data (swap fake for real privately)
├── deploy/
│   ├── com.rentaltax.nr6.plist        ← Nov 1 at 09:00
│   ├── com.rentaltax.returns.plist    ← Jan 15 at 09:00
│   └── com.rentaltax.reminders.plist  ← daily at 09:05
├── forms/                    ← CRA PDF templates (originals, unmodified)
├── generated_forms/          ← output PDFs (git-ignored)
├── logs/                     ← reminder dedup log (git-ignored)
├── email_handler.py          ← SMTP send, IMAP poll, reply parse, PDF email
├── main.py                   ← CLI entry point
├── pdf_filler.py             ← fills all 4 CRA form types → 7 output PDFs
├── reminders.py              ← deadline + monthly remittance reminders
└── requirements.txt
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| PDF fields blank | You have `PyPDF2` not `pypdf` — run `python3 -m pip install pypdf` |
| `SMTPAuthenticationError` | Use a Gmail App Password, not your account password |
| `IMAP connection refused` | Gmail → Settings → Forwarding and POP/IMAP → Enable IMAP |
| Process-reply finds nothing | Reply may be in spam of the sender account; code searches INBOX + Spam |
| Agent didn't fire on schedule | Mac must be on and logged in; check `launchctl list \| grep rentaltax` |
| Pipeline crashed | Check `~/Library/Logs/rentaltax/nr6-error.log` |
| Test fire now | `launchctl start com.rentaltax.nr6` |

---

## US-side obligations

File separately with the IRS — not handled by this tool:

- **Schedule E** — report Canadian rental income on your 1040
- **Form 1116** — claim foreign tax credit for Canadian taxes paid
- **FinCEN 114 (FBAR)** — if any Canadian account exceeded USD 10,000 at any point

---

## Notes

**One-time CRA registration:** Both owners need a CRA Non-Resident (NR) account number before the first filing. Call CRA International Tax Services: 1-855-284-5946.

**Underused Housing Tax (UHT):** Eliminated for 2025+. If you haven't filed UHT-2900 for 2022–2024, penalties may still apply — consult a cross-border tax accountant.

**Replied after the window closed?**
```bash
python3 main.py --process-reply --mode nr6      # check inbox now, no re-send
python3 main.py --process-reply --mode returns
```
