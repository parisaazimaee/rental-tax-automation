"""
Rental Tax Automation — main pipeline.

Two separate annual pipelines, each triggered by its own launchd agent:

  --renew-election   (launchd: November 1)
      Collects ESTIMATED figures for the UPCOMING year.
      Fills and emails NR6 × 2.
      CRA must receive the NR6 before January 1 of that year.
      Default year: current_year + 1

  --file-return      (launchd: January 15)
      Collects FINAL ACTUAL figures for the JUST-CLOSED year.
      Fills and emails NR4, T776 × 2, T1159 × 2.
      Returns due June 30; balance owing due April 30.
      Default year: current_year - 1

Other flags:
  --fill-only [--mode nr6|returns]   Fill PDFs from base data, no email
  --send-reminder [--mode nr6|returns]   Send the data-request email only
  --check-reminders                  Send any deadline reminders due today
  --year YYYY                        Override the year for any mode
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR  = Path(__file__).parent
DATA_FILE = BASE_DIR / "data" / "base_year_data.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_data(year=None) -> dict:
    with open(DATA_FILE) as f:
        data = json.load(f)
    if year is not None:
        data["tax_year"] = year
    return data


def _recipients(data: dict) -> list:
    return [a for a in [
        os.environ.get("OWNER_EMAIL_1", ""),
        os.environ.get("OWNER_EMAIL_2", ""),
    ] if a]


def _ts(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ---------------------------------------------------------------------------
# Shared pipeline steps
# ---------------------------------------------------------------------------

def step_send_reminder(data: dict, mode: str) -> None:
    from email_handler import send_reminder
    recipients = _recipients(data)
    if not recipients:
        _ts("ERROR: No recipient email addresses configured.")
        _ts("Set OWNER_EMAIL_1 and OWNER_EMAIL_2 in your .env file.")
        sys.exit(1)
    send_reminder(data["tax_year"], recipients, mode=mode)


def step_wait_and_parse(data: dict, mode: str) -> dict:
    """
    Poll for a reply. Returns updated data on success.
    Exits the process on timeout rather than silently using stale figures.
    """
    from email_handler import merge_reply_into_data, parse_reply, poll_for_reply
    _ts("Waiting for email reply (up to 30 days, with nudges on days 5/10/20/29)...")
    body = poll_for_reply(data["tax_year"], mode=mode, recipients=_recipients(data))
    if body is None:
        _ts("No reply received within 30 days. PDFs NOT filled.")
        _ts("When you're ready, reply to the original email then run:")
        _ts(f"  python3 main.py --process-reply --mode {mode}")
        sys.exit(0)
    parsed = parse_reply(body)
    _ts(f"Reply parsed: {len(parsed)} fields updated.")
    for k, v in parsed.items():
        _ts(f"  {k}: {v}")
    return merge_reply_into_data(data, parsed)


def run_process_reply(year=None, mode: str = "nr6") -> None:
    """
    Check the inbox right now for an existing reply and process it.
    Use this when you replied after the pipeline had already timed out.

    Does NOT re-send the reminder email.
    """
    from email_handler import check_inbox_now, merge_reply_into_data, parse_reply
    if mode == "nr6":
        year = year or (datetime.now().year + 1)
    else:
        year = year or (datetime.now().year - 1)

    data = load_data(year)
    _ts(f"Checking inbox for {mode} reply for year {data['tax_year']}...")
    body = check_inbox_now(data["tax_year"], mode=mode)
    if body is None:
        _ts("No reply found. Make sure you replied to the original reminder email.")
        _ts("The subject must contain the original subject line.")
        sys.exit(0)

    parsed = parse_reply(body)
    _ts(f"Reply parsed: {len(parsed)} fields updated.")
    for k, v in parsed.items():
        _ts(f"  {k}: {v}")
    data = merge_reply_into_data(data, parsed)
    pdf_paths = step_fill_forms(data, mode=mode)
    step_email_pdfs(data, pdf_paths, mode=mode)
    _ts("Done.")


def step_fill_forms(data: dict, mode: str) -> dict:
    from pdf_filler import fill_nr6_forms, fill_return_forms
    _ts(f"Filling {'NR6 election' if mode == 'nr6' else 'return'} forms for {data['tax_year']}...")
    results = fill_nr6_forms(data) if mode == "nr6" else fill_return_forms(data)
    for label, path in results.items():
        size = Path(path).stat().st_size
        _ts(f"  {label:20s} → {Path(path).name}  ({size:,} bytes)")
    return results


def step_email_pdfs(data: dict, pdf_paths: dict, mode: str) -> None:
    from email_handler import send_completed_pdfs
    recipients = _recipients(data)
    if not recipients:
        _ts("WARNING: No recipients configured; skipping email send.")
        return
    send_completed_pdfs(data["tax_year"], pdf_paths, recipients)


def step_check_reminders() -> None:
    from reminders import check_and_send_deadline_reminders
    n = check_and_send_deadline_reminders()
    _ts(f"Deadline reminders sent: {n}")


# ---------------------------------------------------------------------------
# Pipeline 1 — November: NR6 election for the UPCOMING year
# ---------------------------------------------------------------------------

def run_renew_election(year=None) -> None:
    """
    November pipeline.

    year defaults to current_year + 1 (the year being elected).
    Example: runs November 2025, generates NR6 for 2026.
    """
    if year is None:
        year = datetime.now().year + 1
    data = load_data(year)
    _ts(f"NR6 election pipeline — tax year {data['tax_year']}")
    _ts("(Estimated figures; actual figures collected in January.)")

    step_send_reminder(data, mode="nr6")
    data = step_wait_and_parse(data, mode="nr6")
    pdf_paths = step_fill_forms(data, mode="nr6")
    step_email_pdfs(data, pdf_paths, mode="nr6")

    _ts("NR6 election pipeline complete.")
    _ts(f"Submit NR6 forms to CRA before January 1, {data['tax_year']}.")


# ---------------------------------------------------------------------------
# Pipeline 2 — January: Tax returns for the JUST-CLOSED year
# ---------------------------------------------------------------------------

def run_file_return(year=None) -> None:
    """
    January pipeline.

    year defaults to current_year - 1 (the just-closed tax year).
    Example: runs January 2026, generates NR4/T776/T1159 for 2025.
    """
    if year is None:
        year = datetime.now().year - 1
    data = load_data(year)
    _ts(f"Tax return pipeline — tax year {data['tax_year']}")
    _ts("(Final actual figures for the completed tax year.)")

    step_send_reminder(data, mode="returns")
    data = step_wait_and_parse(data, mode="returns")
    pdf_paths = step_fill_forms(data, mode="returns")
    step_email_pdfs(data, pdf_paths, mode="returns")

    _ts("Tax return pipeline complete.")
    _ts(f"Balance owing due April 30, {data['tax_year'] + 1}.")
    _ts(f"T776 + T1159 filing due June 30, {data['tax_year'] + 1} (mail to CRA).")


# ---------------------------------------------------------------------------
# Utility modes
# ---------------------------------------------------------------------------

def run_fill_only(year=None, mode: str = "all") -> None:
    """Fill PDFs from base data without sending any email."""
    from pdf_filler import fill_all_forms, fill_nr6_forms, fill_return_forms

    if mode == "nr6":
        year = year or (datetime.now().year + 1)
        data = load_data(year)
        pdf_paths = fill_nr6_forms(data)
    elif mode == "returns":
        year = year or (datetime.now().year - 1)
        data = load_data(year)
        pdf_paths = fill_return_forms(data)
    else:
        data = load_data(year)
        pdf_paths = fill_all_forms(data)

    _ts(f"Tax year: {data['tax_year']}")
    for label, path in pdf_paths.items():
        size = Path(path).stat().st_size
        _ts(f"  {label:20s} → {Path(path).name}  ({size:,} bytes)")
    _ts(f"Done. Output: {BASE_DIR / 'generated_forms'}")


def run_send_reminder_only(year=None, mode: str = "nr6") -> None:
    if mode == "nr6":
        year = year or (datetime.now().year + 1)
    else:
        year = year or (datetime.now().year - 1)
    data = load_data(year)
    step_send_reminder(data, mode=mode)


def run_interactive() -> None:
    print("\n=== Rental Tax Automation ===")
    print("1. November: NR6 election for upcoming year (fill + email)")
    print("2. January:  Tax returns for just-closed year (fill + email)")
    print("3. Fill NR6 forms only (no email)")
    print("4. Fill return forms only (no email)")
    print("5. Process a reply that arrived late (check inbox now)")
    print("6. Check and send deadline reminders")
    print("7. Exit")

    choice = input("\nChoice: ").strip()
    dispatch = {
        "1": lambda: run_renew_election(),
        "2": lambda: run_file_return(),
        "3": lambda: run_fill_only(mode="nr6"),
        "4": lambda: run_fill_only(mode="returns"),
        "5": lambda: run_process_reply(mode=input("Mode (nr6/returns): ").strip() or "nr6"),
        "6": lambda: step_check_reminders(),
        "7": lambda: sys.exit(0),
    }
    fn = dispatch.get(choice)
    if fn:
        fn()
    else:
        print("Invalid choice.")
        run_interactive()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Rental Tax Automation Agent")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--renew-election", action="store_true",
                       help="November: NR6 for upcoming year (remind → wait → fill → send)")
    group.add_argument("--file-return", action="store_true",
                       help="January: NR4/T776/T1159 for just-closed year (remind → wait → fill → send)")
    group.add_argument("--fill-only", action="store_true",
                       help="Fill PDFs from base data; no email")
    group.add_argument("--send-reminder", action="store_true",
                       help="Send the data-request email only")
    group.add_argument("--check-reminders", action="store_true",
                       help="Send any CRA deadline reminders due today")
    group.add_argument("--process-reply", action="store_true",
                       help="Check inbox NOW for an existing reply and process it (no re-send)")
    group.add_argument("--test-connection", action="store_true",
                       help="Test SMTP + IMAP credentials and send a test email")

    parser.add_argument("--mode", choices=["nr6", "returns", "all"], default=None,
                        help="Which form set to target (for --fill-only / --send-reminder)")
    parser.add_argument("--year", type=int, default=None,
                        help="Override the tax year")

    args = parser.parse_args()

    if args.renew_election:
        run_renew_election(args.year)
    elif args.file_return:
        run_file_return(args.year)
    elif args.fill_only:
        run_fill_only(args.year, mode=args.mode or "all")
    elif args.send_reminder:
        run_send_reminder_only(args.year, mode=args.mode or "nr6")
    elif args.check_reminders:
        step_check_reminders()
    elif args.process_reply:
        run_process_reply(args.year, mode=args.mode or "nr6")
    elif args.test_connection:
        from email_handler import test_connection
        test_connection()
    else:
        run_interactive()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
