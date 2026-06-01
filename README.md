# Rental Tax Automation

Automates the annual Canadian CRA filing cycle for non-resident rental property owners (Section 216 election). Set it up once, then it runs itself every year.

---

## How it works

Three launchd agents run on your Mac:

| Agent | When | What it does |
|---|---|---|
| `com.rentaltax.nr6` | Nov 1, 09:00 | Emails you for *estimated* next-year figures, fills NR6 x2, emails them back |
| `com.rentaltax.returns` | Jan 15, 09:00 | Emails you for *final* last-year figures, fills NR4 + T776 x2 + T1159 x2, emails them back |
| `com.rentaltax.reminders` | Daily, 09:05 | Sends deadline reminders and monthly remittance reminders to your agent |

You reply to an email with numbers. The forms fill themselves and land in your inbox.

---

## One-time setup

### 1. Install dependencies

```bash
python3 -m pip install pypdf python-dotenv
```

### 2. Create your credentials file

Create a file called `.env` in the project root (never commit this file):

```
EMAIL_SENDER=your-dedicated-address@gmail.com
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx
OWNER_EMAIL_1=parisa@example.com
OWNER_EMAIL_2=shahriar@example.com
AGENT_EMAIL=agent@example.com
```

`EMAIL_PASSWORD` must be a **Gmail App Password** — not your regular login password. Gmail blocks direct password login for apps. Steps:

1. Go to [myaccount.google.com](https://myaccount.google.com)
2. Click **Security** in the left sidebar
3. Under "How you sign in to Google", click **2-Step Verification** and enable it if not already on
4. Go back to Security, scroll down, click **App passwords**
5. Under "App name" type `rental-tax` and click **Create**
6. Copy the 16-character password (with spaces is fine) into `EMAIL_PASSWORD` in `.env`

Also enable IMAP so the agent can read replies:

1. Open Gmail in a browser while signed in as `EMAIL_SENDER`
2. Click the **gear icon** (top right) → **See all settings**
3. Click the **Forwarding and POP/IMAP** tab
4. Under "IMAP access", select **Enable IMAP**
5. Click **Save Changes**

### 3. Enter your real property data

Edit `data/base_year_data.json`. Replace every fake value with your real information.

- **Static fields** (set once, never asked again): names, SINs, DOBs, addresses, NR account numbers, withholding agent info, ownership %
- **Annual fields** (updated each year via email reply): `annual_income` and `annual_expenses`

Add this file to `.gitignore` once it contains real SINs.

### 4. Test it without sending any email

```bash
python3 main.py --fill-only --mode nr6      # NR6 forms for upcoming year
python3 main.py --fill-only --mode returns  # NR4/T776/T1159 for last year
```

Open a PDF from `generated_forms/` and confirm the fields look right.

### 5. Deploy the launchd agents

```bash
mkdir -p ~/Library/Logs/rentaltax
cp deploy/com.rentaltax.nr6.plist       ~/Library/LaunchAgents/
cp deploy/com.rentaltax.returns.plist   ~/Library/LaunchAgents/
cp deploy/com.rentaltax.reminders.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.rentaltax.nr6.plist
launchctl load ~/Library/LaunchAgents/com.rentaltax.returns.plist
launchctl load ~/Library/LaunchAgents/com.rentaltax.reminders.plist
```

Verify they registered: `launchctl list | grep rentaltax`

If you move the project folder or switch Python versions, update `ProgramArguments[0]` (python3 path) and `WorkingDirectory` in each of the three plist files.

---

## Full annual calendar

### November — NR6 election for next year

| Date | What happens | Auto? |
|---|---|---|
| Nov 1 | Agent emails you + Shahriar: *estimate 2026 income/expenses for NR6* | ✅ Auto |
| Nov 6 | Nudge if no reply: *5 days — still waiting* | ✅ Auto |
| Nov 11 | Nudge if no reply: *10 days — following up* | ✅ Auto |
| Nov 21 | Nudge if no reply: *20 days — please reply soon* | ✅ Auto |
| Nov 30 | URGENT if no reply: *tomorrow is the last day* | ✅ Auto |
| Dec 1 | 30-day window closes — pipeline exits if still no reply | — |
| **Any time Nov 1–Dec 1** | You reply → NR6 x2 filled and emailed back within minutes | ✅ Auto |
| ~Nov 16 | Reminder: NR6 due in 45 days (PDFs attached) | ✅ Auto |
| **Jan 1** | ⚠️ CRA deadline: sign and mail NR6 to CRA | 🖊️ You |

---

### January — Tax returns for the just-closed year

| Date | What happens | Auto? |
|---|---|---|
| Jan 1 | Monthly remittance reminder sent to withholding agent | ✅ Auto |
| Jan 15 | Agent emails you + Shahriar: *confirm final actual 2025 figures* | ✅ Auto |
| Jan 20 | Nudge if no reply: *5 days — still waiting* | ✅ Auto |
| Jan 25 | Nudge if no reply: *10 days — following up* | ✅ Auto |
| Feb 4 | Nudge if no reply: *20 days — please reply soon* | ✅ Auto |
| Feb 13 | URGENT if no reply: *tomorrow is the last day* | ✅ Auto |
| Feb 14 | 30-day window closes — pipeline exits if still no reply | — |
| **Any time Jan 15–Feb 14** | You reply → NR4 + T776 x2 + T1159 x2 filled and emailed back | ✅ Auto |

---

### February–June — Filing deadlines

| Date | What happens | Auto? |
|---|---|---|
| 15th of every month | Remittance reminder emailed to your withholding agent | ✅ Auto |
| ~Mar 1 | Reminder: NR4 due in 30 days | ✅ Auto |
| **Mar 31** | ⚠️ CRA deadline: withholding agent files NR4 slips + NR4 Summary | 🖊️ Agent |
| ~Apr 1 | Reminder: balance owing due in 30 days | ✅ Auto |
| **Apr 30** | ⚠️ CRA deadline: pay any balance owing — interest starts May 1 | 🖊️ You |
| ~Jun 1 | Reminder: T1159 due in 30 days (PDFs attached) | ✅ Auto |
| **Jun 30** | ⚠️ CRA deadline: print, sign, and mail T776 + T1159 to CRA (no NETFILE) | 🖊️ You |

---

Then **November 1** the whole cycle repeats for the next year.

**Replied after the window closed?** Run:
```bash
python3 main.py --process-reply --mode nr6      # NR6 forms
python3 main.py --process-reply --mode returns  # return forms
```
---

## CRA forms

| Form | Filed by | Deadline | Notes |
|---|---|---|---|
| NR6 x2 | Each owner + agent | Before Jan 1 | Re-filed every year; must be approved before first rent payment |
| NR4 slips | Withholding agent | March 31 | Agent also files NR4 Summary electronically via CRA My Business Account |
| T776 x2 | Each owner | With T1159 | Each owner's 50% share; Part 2 lists the co-owner |
| T1159 x2 | Each owner | June 30 | Print and mail — CRA does not accept NETFILE for Section 216 |

Mail T776 + T1159 to:
> CRA International Tax Services Office, 2204 Walkley Road, Ottawa ON K1A 1A8

Balance owing is due **April 30**. The return itself is due June 30. Interest accrues daily from May 1 even if you haven't filed yet.

---

## US-side obligations (file with IRS separately)

- Schedule E — report Canadian rental income on your 1040
- Form 1116 — claim foreign tax credit for CRA taxes paid
- FinCEN 114 (FBAR) — if any Canadian account exceeded USD 10,000 at any point

---

## One-time CRA registration

Both owners need a CRA Non-Resident (NR) account number before the first filing. Call CRA International Tax Services: 1-855-284-5946. Store the assigned numbers in `data/base_year_data.json` under `nr_account_pt1` and `nr_account_pt2`.

---

## Underused Housing Tax (UHT)

Eliminated for 2025+. If you have not filed UHT-2900 for 2022, 2023, or 2024, penalties may apply. Consult a cross-border tax accountant.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| PDF fields are blank | Check you installed `pypdf` not `PyPDF2`: `python3 -m pip show pypdf` |
| SMTPAuthenticationError | Use an App Password, not your Google account password |
| IMAP connection refused | Enable IMAP in Gmail settings (Forwarding and POP/IMAP) |
| Agent didn't fire | Mac must be on and logged in; verify with `launchctl list \| grep rentaltax` |
| Pipeline crashed | Check `~/Library/Logs/rentaltax/nr6-error.log` or `returns-error.log` |
| Test fire an agent now | `launchctl start com.rentaltax.nr6` |

---

## Manual commands

```bash
python3 main.py --fill-only --mode nr6       # fill NR6 PDFs, no email
python3 main.py --fill-only --mode returns   # fill return PDFs, no email
python3 main.py --renew-election             # full NR6 pipeline
python3 main.py --file-return                # full returns pipeline
python3 main.py --check-reminders            # send any reminders due today
python3 main.py --fill-only --year 2025      # override year

# Replied after the pipeline already timed out?
python3 main.py --process-reply --mode nr6      # check inbox + fill NR6 now
python3 main.py --process-reply --mode returns  # check inbox + fill returns now
```

### What happens if you reply late

The pipeline waits 14 days for a reply. If you reply within that window, forms fill automatically. If 14 days pass with no reply, the process exits cleanly without filling anything (it does not silently use stale data).

When you eventually reply — even weeks later — just run:
```bash
python3 main.py --process-reply --mode nr6
```
It checks your inbox once, finds the reply, fills the PDFs, and emails them. No need to re-send the reminder.
