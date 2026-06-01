"""
PDF Form Filler — fills CRA AcroForm PDFs using verified field IDs.

Key discovery: CRA forms use hierarchical XFA-style field names.
pypdf 6.x's update_page_form_field_values() accepts both the short leaf
name AND the full qualified dotted path. We always use the full path so
that duplicate leaf names (e.g. Address[0] in Section1 and Section4 of
NR6, or Slip1Name1[0] in both NR4 slips) resolve to the right widget.

Field IDs below were extracted with pypdf.PdfReader.get_fields() from the
actual CRA PDFs — they are not guesses.
"""

from pathlib import Path
import pypdf

FORMS_DIR  = Path(__file__).parent / "forms"
OUTPUT_DIR = Path(__file__).parent / "generated_forms"
OUTPUT_DIR.mkdir(exist_ok=True)
_DATA_FILE = Path(__file__).parent / "data" / "base_year_data.json"


# ---------------------------------------------------------------------------
# Core helper
# ---------------------------------------------------------------------------

def _fill(template_path: Path, updates: dict, output_path: Path) -> Path:
    """
    Fill a PDF form and write to output_path.

    updates: {full_qualified_field_name: string_value}
    Uses auto_regenerate=False to avoid appearance-stream errors on CRA's
    hybrid XFA/AcroForm PDFs; Adobe Reader and Preview re-render on open.
    """
    reader = pypdf.PdfReader(str(template_path))
    writer = pypdf.PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        writer.update_page_form_field_values(page, updates, auto_regenerate=False)
    with open(output_path, "wb") as fh:
        writer.write(fh)
    return output_path


def _fmt(value, decimals=2) -> str:
    """Format a numeric value as a string with no trailing '.00' for whole numbers."""
    try:
        n = float(value)
        return str(int(n)) if n == int(n) else f"{n:.{decimals}f}"
    except (TypeError, ValueError):
        return str(value) if value is not None else ""


# ---------------------------------------------------------------------------
# NR6 — Non-Resident Withholding Tax (Section 216 election)
# One NR6 per non-resident owner; we generate one per owner.
# ---------------------------------------------------------------------------

def fill_nr6(data: dict, owner_key: str = "owner_1") -> Path:
    """
    Fill NR6 for a single owner.

    Section 1 = non-resident's info
    Section 2 = rental property financials (up to 2 properties)
    Section 3 = non-resident's signature block
    Section 4 = withholding agent's info
    """
    owner = data[owner_key]
    agent = data["withholding_agent"]
    prop = data["property"]
    tax_year = str(data["tax_year"])
    income = data["annual_income"]
    expenses = data["annual_expenses"]

    total_expenses = sum(expenses.values())
    net_income = income["rental_income"] - total_expenses
    owner_share = owner["ownership_pct"] / 100
    gross_share = income["rental_income"] * owner_share
    expenses_share = total_expenses * owner_share
    net_share = net_income * owner_share

    updates = {
        # ── Section 1: Non-resident identification ──────────────────────
        "form1[0].Page1[0].Tax_Year[0]":
            tax_year,
        "form1[0].Page1[0].Section1_sf[0].First_Name[0]":
            owner["first_name"],
        "form1[0].Page1[0].Section1_sf[0].Last_Name[0]":
            owner["last_name"],
        "form1[0].Page1[0].Section1_sf[0].Address[0]":
            owner["mailing_address"],
        "form1[0].Page1[0].Section1_sf[0].City[0]":
            owner["city"],
        "form1[0].Page1[0].Section1_sf[0].Country[0]":
            owner["country"],
        # SIN lives inside a comb sub-field
        "form1[0].Page1[0].Section1_sf[0].SIN_grp[0].SIN[0].SIN_Comb[0]":
            owner["sin"].replace("-", ""),
        # Fiscal year start YYYYMM (January of tax year)
        "form1[0].Page1[0].Section1_sf[0].DateYYYYMM_Comb_Top[0].DateYYYYMM_Comb[0]":
            f"{tax_year}01",

        # ── Section 2: Rental property details (Property 1) ─────────────
        "form1[0].Page1[0].Section2_sf[0].Address1[0]":
            prop["address"],
        "form1[0].Page1[0].Section2_sf[0].City1[0]":
            prop["city"],
        "form1[0].Page1[0].Section2_sf[0].Province1[0]":
            prop["province"],
        "form1[0].Page1[0].Section2_sf[0].PostalCode1[0]":
            prop["postal_code"],
        "form1[0].Page1[0].Section2_sf[0].Gross_Rents1[0]":
            _fmt(gross_share),
        "form1[0].Page1[0].Section2_sf[0].Total_Expenses1[0]":
            _fmt(expenses_share),
        "form1[0].Page1[0].Section2_sf[0].Net_Income1[0]":
            _fmt(net_share),
        # Totals row
        "form1[0].Page1[0].Section2_sf[0].Total_Gross_Rents[0]":
            _fmt(gross_share),
        "form1[0].Page1[0].Section2_sf[0].Total_Total_Expenses[0]":
            _fmt(expenses_share),
        "form1[0].Page1[0].Section2_sf[0].Total_Net_Income[0]":
            _fmt(net_share),

        # ── Section 3: Non-resident declaration ─────────────────────────
        "form1[0].Page1[0].Section3_sf[0].NonResident_Sig[0]":
            f"{owner['first_name']} {owner['last_name']}",
        "form1[0].Page1[0].Section3_sf[0].Date_Signature[0]":
            tax_year + "-12-01",

        # ── Section 4: Withholding agent ────────────────────────────────
        "form1[0].Page1[0].Section4_sf[0].Name[0]":
            agent["name"],
        "form1[0].Page1[0].Section4_sf[0].Address[0]":
            agent["address"],
        "form1[0].Page1[0].Section4_sf[0].City[0]":
            agent["city"],
        "form1[0].Page1[0].Section4_sf[0].Province[0]":
            agent["province"],
        "form1[0].Page1[0].Section4_sf[0].PostalCode[0]":
            agent["postal_code"],
        "form1[0].Page1[0].Section4_sf[0].PhoneNumber[0]":
            agent["phone"],
        # Agent's business number (BN)
        "form1[0].Page1[0].Section4_sf[0].RentalPayment[0].BusinessNumber_Comb_Contiguous_EN[0].BusinessNumber[0]":
            agent["business_number"],
        # Non-resident tax account number (NR account)
        "form1[0].Page1[0].Section4_sf[0].Non-Res_TaxNum[0].NR_Field[0].Non-Res_Number[0]":
            owner["nr_account_pt1"],
        "form1[0].Page1[0].Section4_sf[0].Non-Res_TaxNum[0].NR_Field[0].Non-Res_Number2[0]":
            owner["nr_account_pt2"],
        "form1[0].Page1[0].Section4_sf[0].Date_Signature[0]":
            tax_year + "-12-01",
    }

    suffix = "1" if owner_key == "owner_1" else "2"
    out = OUTPUT_DIR / f"NR6_{tax_year}_owner{suffix}.pdf"
    return _fill(FORMS_DIR / "nr6-fill-23e.pdf", updates, out)


# ---------------------------------------------------------------------------
# NR4 — Statement of Amounts Paid to Non-Residents
# Filed by the withholding agent. Slip1 = Owner 1, Slip2 = Owner 2.
# Both slips share identical leaf /T names; we use full qualified paths.
# ---------------------------------------------------------------------------

def fill_nr4(data: dict) -> Path:
    """
    Fill NR4 with one slip per owner.
    Box 16 = gross income (each owner's share).
    Box 17 = non-resident tax withheld (25 % of gross).
    Income code 11 = rental income from real property.
    """
    agent = data["withholding_agent"]
    income = data["annual_income"]
    tax_year = str(data["tax_year"])

    def slip_updates(owner: dict, slip_prefix: str) -> dict:
        owner_share = owner["ownership_pct"] / 100
        gross = income["rental_income"] * owner_share
        withheld = round(gross * 0.25)
        p = slip_prefix  # e.g. "form1[0].Page1[0].Slip1[0]"
        return {
            f"{p}.Box10[0].Slip1Box10[0]": tax_year,
            f"{p}.PayersName[0].Slip1PayersName[0]": agent["name"],
            # Box 16 = gross income, Box 17 = tax withheld
            f"{p}.Income[0].Box16[0].Slip1Box16[0]": _fmt(gross),
            f"{p}.Income[0].Box17[0].Slip1Box17[0]": str(withheld),
            # Recipient identification
            f"{p}.IndividualInfo[0].Individual1[0].Slip1Name1[0]":
                owner["first_name"],
            f"{p}.IndividualInfo[0].Individual2[0].Slip1Name2[0]":
                owner["last_name"],
            f"{p}.IndividualInfo[0].Address[0].Slip1Address[0]":
                owner["mailing_address"],
            f"{p}.Name[0].Slip1Name[0]":
                f"{owner['last_name']}, {owner['first_name']}",
            # NR account number (two-part)
            f"{p}.NonResident[0].Slip1NonResident_PT1[0]":
                owner["nr_account_pt1"],
            f"{p}.NonResident[0].Slip1NonResident_PT2[0]":
                owner["nr_account_pt2"],
        }

    base = "form1[0].Page1[0]"
    updates = {}
    updates.update(slip_updates(data["owner_1"], f"{base}.Slip1[0]"))
    updates.update(slip_updates(data["owner_2"], f"{base}.Slip2[0]"))

    out = OUTPUT_DIR / f"NR4_{tax_year}.pdf"
    return _fill(FORMS_DIR / "nr4-fill-25e.pdf", updates, out)


# ---------------------------------------------------------------------------
# T776 — Statement of Real Estate Rentals (one per owner)
#
# CRA requires each co-owner to file their own T776 showing their
# proportional share of income and expenses, with the co-owner listed
# in Part 2. (Source: CRA T776 instructions; confirmed by research.)
#
# Field layout (verified against nr4-fill-25e.pdf field dump):
#   P1  = Part 1: filer identification (name, SIN, property address, dates)
#   P2  = Part 2: other co-owners table — inpt1=name, inpt2=SIN, inpt3=share%
#   P3  = Part 3: gross rents table (Row cells) + income calculation lines
#   P4  = Part 4: expense lines (inpt1=total, inpt2=personal, inpt3=rental net)
#
# Expense columns for 100% rental property: inpt1 == inpt3, inpt2 == 0.
# ---------------------------------------------------------------------------

def fill_t776(data: dict, owner_key: str = "owner_1") -> Path:
    """Fill T776 for one owner showing their ownership share of income/expenses."""
    owner     = data[owner_key]
    other_key = "owner_2" if owner_key == "owner_1" else "owner_1"
    other     = data[other_key]
    prop      = data["property"]
    exp       = data["annual_expenses"]
    income    = data["annual_income"]
    tax_year  = str(data["tax_year"])

    share           = owner["ownership_pct"] / 100
    gross_share     = income["rental_income"] * share
    exp_share       = {k: v * share for k, v in exp.items()}
    total_exp_share = sum(exp_share.values())
    net_share       = gross_share - total_exp_share

    def expense_row(line_id: str, amount: float) -> dict:
        prefix = f"form1[0].Page2[0].P4_sf[0].P4_Frm_sf[0].P4_Frm_{line_id}_sf[0]"
        amt = _fmt(amount)
        return {
            f"{prefix}.P4_Frm_{line_id}_inpt1[0]": amt,  # total (= net for pure rental)
            f"{prefix}.P4_Frm_{line_id}_inpt2[0]": "0",  # personal portion
            f"{prefix}.P4_Frm_{line_id}_inpt3[0]": amt,  # rental net
        }

    p1     = "form1[0].Page1[0].P1_sf[0].P1_Frm_sf[0]"
    p2     = "form1[0].Page1[0].P2_sf[0].P2_Frm_sf[0]"
    p3     = "form1[0].Page1[0].P3_sf[0].P3_Frm_sf[0]"
    p3_tbl = f"{p3}.P3_Frm_Table[0].P3_Frm_Row1_sf[0]"

    updates = {
        # ── Part 1: Filer identification ─────────────────────────────────
        # Ln1 = filer's name (first initial / last name)
        f"{p1}.P1_Frm_Ln1_sf[0].P1_Frm_Ln1_Grp1_inpt[0]":
            f"{owner['first_name_initial']}.",
        f"{p1}.P1_Frm_Ln1_sf[0].P1_Frm_Ln1_Grp2_grp[0].P1_Frm_Ln1_Grp2_inpt[0]":
            owner["last_name"],
        # Ln2 = fiscal period (YYYYMMDD from / to)
        f"{p1}.P1_Frm_Ln2_sf[0].P1_Frm_Ln2_inpt1[0]": f"{tax_year}0101",
        f"{p1}.P1_Frm_Ln2_sf[0].P1_Frm_Ln2_inpt2[0]": f"{tax_year}1231",
        # Ln3 = co-ownership indicator fields (co-owner name + filer's share %)
        f"{p1}.P1_Frm_Ln3_sf[0].P1_Frm_Ln3_Grp1_sf[0].P1_Frm_Ln3_Grp1_grp1[0].P1_Frm_Ln3_Grp1_grp1_inpt[0]":
            f"{other['first_name_initial']}.",
        f"{p1}.P1_Frm_Ln3_sf[0].P1_Frm_Ln3_Grp1_sf[0].P1_Frm_Ln3_Grp1_grp2[0].P1_Frm_Ln3_Grp1_grp2_inpt[0]":
            other["last_name"],
        f"{p1}.P1_Frm_Ln3_sf[0].P1_Frm_Ln3_Grp1_sf[0].P1_Frm_Ln3_Grp2_lbl1[0].P1_Frm_Ln3_Grp2_inpt1[0]":
            str(owner["ownership_pct"]),
        # Ln4 = rental property address (4 parts: street, city, province, postal)
        f"{p1}.P1_Frm_Ln4_sf[0].P1_Frm_Ln4_Grp1_inpt[0]":       prop["address"],
        f"{p1}.P1_Frm_Ln4_sf[0].P1_Frm_Ln4_Grp2[0].P1_Frm_Ln4_Grp2_inpt[0]": prop["city"],
        f"{p1}.P1_Frm_Ln4_sf[0].P1_Frm_Ln4_Grp3_inpt[0]":       prop["province"],
        f"{p1}.P1_Frm_Ln4_sf[0].P1_Frm_Ln4_Grp4[0].P1_Frm_Ln4_Grp4_inpt[0]": prop["postal_code"],
        # Ln5 = filer's SIN
        f"{p1}.P1_Frm_L5_sf[0].P1_Frm_Ln5_Grp1_inpt[0]":
            owner["sin"].replace("-", ""),

        # ── Part 2: Other co-owners (row 1 = the other owner) ────────────
        # inpt1 = name, inpt2 = SIN, inpt3 = their ownership %
        f"{p2}.P2_Frm_LnGrp1_sf[0].P2_Frm_LnGrp1_inpt1[0]":
            f"{other['first_name_initial']}. {other['last_name']}",
        f"{p2}.P2_Frm_LnGrp1_sf[0].P2_Frm_LnGrp1_inpt2[0]":
            other["sin"].replace("-", ""),
        f"{p2}.P2_Frm_LnGrp1_sf[0].P2_Frm_LnGrp1_inpt3[0]":
            str(other["ownership_pct"]),

        # ── Part 3: Rental property income table (one row = this property) ──
        # Cell1=address, Cell2=units rented, Cell3=filer's gross, Cell4=filer's net
        f"{p3_tbl}.P3_Frm_Row1_Cell1[0]":
            f"{prop['address']}, {prop['city']}, {prop['province']}",
        f"{p3_tbl}.P3_Frm_Row1_Cell2[0]": "1",
        f"{p3_tbl}.P3_Frm_Row1_Cell3[0]": _fmt(gross_share),
        f"{p3_tbl}.P3_Frm_Row1_Cell4[0]": _fmt(net_share),

        # ── Part 3: Income calculation lines (filer's share) ─────────────
        f"{p3}.P3_Frm_Ln8140_sf[0].Frm_Ln8140_inpt[0]":    _fmt(gross_share),
        f"{p3}.P3_Frm_Ln8230_sf[0].P3_Frm_Ln8230_inpt[0]": _fmt(total_exp_share),
        f"{p3}.P3_Frm_Ln8299_sf[0].P3_Frm_Ln8299_inpt[0]": _fmt(net_share),
    }

    # ── Part 4: Expenses — filer's proportional share ────────────────────
    updates.update(expense_row("Ln8521", exp_share["advertising"]))
    updates.update(expense_row("Ln8690", exp_share["insurance"]))
    updates.update(expense_row("Ln8710", exp_share["mortgage_interest"]))
    updates.update(expense_row("Ln8810", exp_share["office_expenses"]))
    updates.update(expense_row("Ln8860", exp_share["professional_fees"]))
    updates.update(expense_row("Ln8871", exp_share["management_fees"]))
    updates.update(expense_row("Ln8960", exp_share["repairs_maintenance"]))
    updates.update(expense_row("Ln9060", exp_share["salaries"]))
    updates.update(expense_row("Ln9180", exp_share["property_taxes"]))
    updates.update(expense_row("Ln9200", exp_share["travel"]))
    updates.update(expense_row("Ln9220", exp_share["utilities"]))
    updates.update(expense_row("Ln9270", exp_share["other_expenses"]))

    p4 = "form1[0].Page2[0].P4_sf[0].P4_Frm_sf[0]"
    updates.update({
        f"{p4}.P4_Frm_Ln9281_sf[0].P4_Frm_Ln9281_inpt1[0]": _fmt(total_exp_share),
        f"{p4}.P4_Frm_Ln9281_sf[0].P4_Frm_Ln9281_inpt2[0]": "0",
        f"{p4}.P4_Frm_Ln9281_sf[0].P4_Frm_Ln9281_inpt3[0]": _fmt(total_exp_share),
        f"{p4}.P4_Frm_Ln9365_sf[0].P4_Frm_Ln9365_inpt[0]":  _fmt(net_share),
    })

    suffix = "1" if owner_key == "owner_1" else "2"
    out = OUTPUT_DIR / f"T776_{tax_year}_owner{suffix}.pdf"
    return _fill(FORMS_DIR / "t776-fill-25e.pdf", updates, out)


# ---------------------------------------------------------------------------
# T1159 — Income Tax Return for Electing Under Section 216
# One per non-resident owner.
# ---------------------------------------------------------------------------

def fill_t1159(data: dict, owner_key: str = "owner_1") -> Path:
    """
    Fill T1159 for a single owner.

    Line 12599 = gross rental income (owner's share).
    Line 12600 = net rental income (owner's share).
    Lines 8–14 of the federal tax chart are left blank for the taxpayer
    to complete (they depend on applicable treaty rates / other income).
    """
    owner = data[owner_key]
    income = data["annual_income"]
    expenses = data["annual_expenses"]
    tax_year = str(data["tax_year"])

    owner_share = owner["ownership_pct"] / 100
    gross = income["rental_income"] * owner_share
    net = (income["rental_income"] - sum(expenses.values())) * owner_share

    base_id = "form1[0].Page1[0].Identification_sf[0]"
    base_inc = "form1[0].Page1[0].Income_sf[0]"

    updates = {
        # ── Identification ───────────────────────────────────────────────
        f"{base_id}.ID_FirstNameInitial[0]":
            f"{owner['first_name_initial']}.",
        f"{base_id}.ID_LastName[0]":
            owner["last_name"],
        f"{base_id}.Address_sf[0].ID_MailingAddress[0]":
            owner["mailing_address"],
        f"{base_id}.Address_sf[0].ID_City[0]":
            owner["city"],
        f"{base_id}.Address_sf[0].ID_Country[0]":
            owner["country"],
        # SIN — 9-digit comb field
        f"{base_id}.NumericField_Comb9_CaptionTop[0].NumericField_Comb9_CaptionTop_Field[0]":
            owner["sin"].replace("-", ""),
        # Date of birth YYYYMMDD
        f"{base_id}.DateYYYYMMDD_Comb_Top[0].DateYYYYMMDD_Comb[0]":
            owner["dob"],

        # ── Income ───────────────────────────────────────────────────────
        # Line 12599: gross rental income
        f"{base_inc}.Rental_sf[0].Line12599_sf[0].GrossAmount_inpt[0]":
            _fmt(gross),
        # Line 12600: net rental income
        f"{base_inc}.Rental_sf[0].Line12600_sf[0].Net_Amount_inpt[0]":
            _fmt(net),
        # Line 1: total income (same as net rental for Section 216 return)
        f"{base_inc}.Line1_sf[0].TotalIncomeAmount_inpt[0]":
            _fmt(net),

        # ── Deductions → taxable income ──────────────────────────────────
        f"form1[0].Page1[0].deductions_sf[0].Line7_sf[0].Line26000_TaxableIncome_inpt[0]":
            _fmt(net),

        # ── Certification ────────────────────────────────────────────────
        f"form1[0].Page2[0].Cert2_sf[0].NameOfPreparer[0]":
            f"{owner['first_name']} {owner['last_name']}",
        f"form1[0].Page2[0].Certi_sf[0].Date[0]":
            tax_year + "-06-30",
    }

    suffix = "1" if owner_key == "owner_1" else "2"
    out = OUTPUT_DIR / f"T1159_{tax_year}_owner{suffix}.pdf"
    return _fill(FORMS_DIR / "t1159-fill-25e.pdf", updates, out)


# ---------------------------------------------------------------------------
# Focused pipeline entry points (used by the two launchd agents)
# ---------------------------------------------------------------------------

def fill_nr6_forms(data: dict) -> dict:
    """
    November pipeline — NR6 election forms only.

    data["tax_year"] should be the UPCOMING year (the year being elected).
    The amounts in data are ESTIMATES for that upcoming year.
    """
    return {
        "NR6_owner1": fill_nr6(data, "owner_1"),
        "NR6_owner2": fill_nr6(data, "owner_2"),
    }


def fill_return_forms(data: dict) -> dict:
    """
    January pipeline — NR4, T776, T1159 for the JUST-CLOSED year.

    data["tax_year"] should be LAST year.
    T776 net income feeds into T1159; review T776 before submitting T1159.
    NR4 slips (Slip1 / Slip2) are issued by the withholding agent; the agent
    must also file the NR4 Summary electronically via CRA My Business Account.
    """
    return {
        "NR4":          fill_nr4(data),
        "T776_owner1":  fill_t776(data, "owner_1"),
        "T776_owner2":  fill_t776(data, "owner_2"),
        "T1159_owner1": fill_t1159(data, "owner_1"),
        "T1159_owner2": fill_t1159(data, "owner_2"),
    }


def fill_all_forms(data: dict) -> dict:
    """Convenience: fill all 7 forms in one call (used by --fill-only)."""
    return {**fill_nr6_forms(data), **fill_return_forms(data)}


# ---------------------------------------------------------------------------
# Stand-alone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    data_path = _DATA_FILE
    with open(data_path) as f:
        data = json.load(f)

    print("Filling forms...")
    results = fill_all_forms(data)
    for name, path in results.items():
        size = Path(path).stat().st_size
        print(f"  {name:20s} → {path}  ({size:,} bytes)")

    # Verify values were written
    print("\nVerifying field values (spot-check)...")
    import pypdf

    # NR6 spot-check
    r = pypdf.PdfReader(str(results["NR6_owner1"]))
    fields = r.get_fields()
    for k in ["form1[0].Page1[0].Tax_Year[0]",
              "form1[0].Page1[0].Section1_sf[0].First_Name[0]",
              "form1[0].Page1[0].Section2_sf[0].Gross_Rents1[0]"]:
        print(f"  NR6  {k.split('.')[-1]:30s} = {fields.get(k, {}).get('/V', '(not found)')!r}")

    # T776 owner1 spot-check — gross and net should be 50% of total
    r2 = pypdf.PdfReader(str(results["T776_owner1"]))
    f2 = r2.get_fields()
    for k in ["form1[0].Page1[0].P3_sf[0].P3_Frm_sf[0].P3_Frm_Ln8140_sf[0].Frm_Ln8140_inpt[0]",
              "form1[0].Page1[0].P3_sf[0].P3_Frm_sf[0].P3_Frm_Ln8299_sf[0].P3_Frm_Ln8299_inpt[0]",
              "form1[0].Page1[0].P2_sf[0].P2_Frm_sf[0].P2_Frm_LnGrp1_sf[0].P2_Frm_LnGrp1_inpt2[0]"]:
        print(f"  T776 {k.split('.')[-1]:30s} = {f2.get(k, {}).get('/V', '(not found)')!r}")
