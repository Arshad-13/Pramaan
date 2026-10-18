"""Build data/drugs.csv: the list of valid drug names used for spelling checks and autosuggest.

Usage:
    python scripts/build_drug_list.py            # offline: bundled seed only (default, deterministic)
    python scripts/build_drug_list.py --online   # also add generic names from openFDA (needs internet)

Output columns: name, generic, is_brand.
  - every generic in data/drug_reference.csv is included (is_brand=0);
  - common Indian brand names map to their generic (is_brand=1);
  - with --online, extra generics from openFDA are added when reachable; if the request fails the
    script silently keeps the offline list, so a fresh clone always works without internet.
Demo data only: not clinical guidance.
"""

from __future__ import annotations

import argparse
import csv
import json
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

# brand -> generic (must match a name in drug_reference.csv). Indian market brands, illustrative.
BRANDS: dict[str, str] = {
    "Dolo": "Paracetamol", "Crocin": "Paracetamol", "Calpol": "Paracetamol",
    "Brufen": "Ibuprofen", "Voveran": "Diclofenac", "Ecosprin": "Aspirin",
    "Augmentin": "Amoxicillin and Clavulanate", "Novamox": "Amoxicillin", "Mox": "Amoxicillin",
    "Azithral": "Azithromycin", "Zithromax": "Azithromycin", "Taxim-O": "Cefixime",
    "Ciplox": "Ciprofloxacin", "Flagyl": "Metronidazole", "Zyrtec": "Cetirizine",
    "Okacet": "Cetirizine", "Allegra": "Fexofenadine", "Montair": "Montelukast",
    "Asthalin": "Salbutamol", "Omez": "Omeprazole", "Pantop": "Pantoprazole",
    "Pan": "Pantoprazole", "Nexpro": "Esomeprazole", "Nexium": "Esomeprazole",
    "Razo": "Rabeprazole", "Emeset": "Ondansetron", "Domstal": "Domperidone",
    "Imodium": "Loperamide", "Glycomet": "Metformin", "Amaryl": "Glimepiride",
    "Atorva": "Atorvastatin", "Lipitor": "Atorvastatin", "Rosuvas": "Rosuvastatin",
    "Norvasc": "Amlodipine", "Amlokind": "Amlodipine", "Telma": "Telmisartan",
    "Losar": "Losartan", "Betaloc": "Metoprolol", "Aten": "Atenolol",
    "Lasix": "Furosemide", "Plavix": "Clopidogrel", "Wysolone": "Prednisolone",
    "Lyrica": "Pregabalin", "Nexito": "Escitalopram", "Tramazac": "Tramadol",
    "Alprax": "Alprazolam", "Restyl": "Alprazolam", "Calmpose": "Diazepam",
    "Rivotril": "Clonazepam", "Zolfresh": "Zolpidem",
}  # fmt: skip


def read_reference() -> list[str]:
    with open(DATA / "drug_reference.csv", newline="", encoding="utf-8") as handle:
        return [row["name"] for row in csv.DictReader(handle)]


def fetch_openfda(limit: int = 100) -> list[str]:
    url = f"https://api.fda.gov/drug/label.json?count=openfda.generic_name.exact&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310  # nosec B310
            payload = json.load(response)
    except Exception as exc:  # noqa: BLE001 - any failure means "stay offline"
        print(f"openFDA unavailable ({exc.__class__.__name__}); using the bundled list only.")
        return []
    names = [item["term"].title() for item in payload.get("results", [])]
    return [n for n in names if n.replace(" ", "").isalpha() and len(n) <= 40]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--online", action="store_true", help="also pull generic names from openFDA"
    )
    args = parser.parse_args()

    generics = read_reference()
    known = {g.lower() for g in generics}
    unknown_targets = {b: g for b, g in BRANDS.items() if g.lower() not in known}
    if unknown_targets:
        raise SystemExit(
            f"Brands map to generics missing from drug_reference.csv: {unknown_targets}"
        )

    rows: list[tuple[str, str, int]] = [(g, g, 0) for g in generics]
    rows += [(brand, generic, 1) for brand, generic in BRANDS.items()]
    if args.online:
        have = {r[0].lower() for r in rows}
        rows += [(n, n, 0) for n in fetch_openfda() if n.lower() not in have]

    rows.sort(key=lambda r: (r[0].lower(), r[1].lower()))
    out = DATA / "drugs.csv"
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["name", "generic", "is_brand"])
        writer.writerows(rows)
    print(f"Wrote {len(rows)} names ({len(generics)} generics, {len(BRANDS)} brands) to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
