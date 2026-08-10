"""One-time setup: builds the ward+precinct -> City Council district crosswalk
table from Boston's official 2026/2027 Elected Officials roster
(boston.gov/sites/default/files/file/2026/01/2026-2027%20Elected%20Officials.pdf),
transcribed by district below. Each district's precinct ranges are expanded
into individual (ward, precinct) rows rather than stored as ranges, since
several wards (3, 4, 5, 8, 9, 18, 19, 20, 21) are split across multiple
districts by precinct - a ward-only mapping would misattribute exactly the
dense urban wards this project's data concentrates in.

Usage:
    python build_councilor_crosswalk.py
"""

import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def r(*args):
    """Expand a mix of ints and (start, end) tuples into a sorted set of ints."""
    out = set()
    for a in args:
        if isinstance(a, tuple):
            out.update(range(a[0], a[1] + 1))
        else:
            out.add(a)
    return out


# (district, councilor_name, councilor_email, {ward: {precincts}})
DISTRICTS = [
    (1, "Gabriela Coletta Zapata", "Gabriela.Coletta@boston.gov", {
        1: r((1, 14)),
        2: r((1, 8)),
        3: r(1, 2, 3, 4, 6, 11, 13),
    }),
    (2, "Edward M. Flynn", "Ed.Flynn@boston.gov", {
        3: r(7, 8, 12, 14),
        6: r((1, 12)),
        7: r((1, 7)),
        4: r(1, 2, 3),
        5: r(1, 13, 14),
        8: r(1),
        9: r(1),
    }),
    (3, "John FitzGerald", "John.FitzGerald@boston.gov", {
        7: r((8, 10)),
        13: r(3, (5, 10)),
        15: r(3, 4, (6, 9)),
        16: r((1, 12)) - {3},  # pct 3 carved out to District 4, see its explicit "Ward 16, Pct 3"
        17: r(13),
        1: r(15),
        8: r(2, 6),
        3: r((15, 16)),
    }),
    (4, "Brian Worrell", "Brian.Worrell@boston.gov", {
        14: r((1, 13)),
        15: r(1, 2, 5),
        16: r(3),
        17: r((1, 12), 14),
        18: r(1, 7),
        19: r(12),
    }),
    (5, "Enrique J. Pepén", "Enrique.Pepen@boston.gov", {
        18: r((5, 6), (8, 23), 20, 11, 22, (2, 4), 21),
        19: r((10, 11), 13),
        20: r(2, 4, 8, 9),
        14: r(14),
    }),
    (6, "Benjamin J. Weber", "Benjamin.Weber@boston.gov", {
        10: r((6, 9)),
        11: r((4, 10)),
        19: r((1, 9)),
        20: r(3, (5, 7), (10, 21)),
    }),
    (7, "Miniard Culpepper", "Miniard.Culpepper@boston.gov", {
        8: r((3, 5)),
        9: r((2, 7)),
        11: r((1, 3)),
        12: r((1, 9)),
        13: r(1, 2, 4),
        4: r(4, 7, 5, (8, 9), 11),
    }),
    (8, "Sharon Durkan", "Sharon.Durkan@boston.gov", {
        4: r(6, 10, 12),
        5: r((2, 12), 15),
        10: r((1, 5)),
        3: r(5, 9, 10, 17),
        21: r(1, 2),
    }),
    (9, "Liz Breadon", "Liz.Breadon@boston.gov", {
        21: r((3, 8), (9, 16)),
        22: r((1, 2), (3, 13)),
    }),
]


def main():
    conn = psycopg.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS boston_council_districts (
            ward              INTEGER NOT NULL,
            precinct          INTEGER NOT NULL,
            district          INTEGER NOT NULL,
            councilor_name    TEXT NOT NULL,
            councilor_email   TEXT NOT NULL,
            PRIMARY KEY (ward, precinct)
        )
    """)

    rows = []
    seen = {}
    for district, name, email, wards in DISTRICTS:
        for ward, precincts in wards.items():
            for pct in precincts:
                key = (ward, pct)
                if key in seen:
                    raise ValueError(f"Duplicate ward/precinct {key}: {seen[key]} and {district} both claim it")
                seen[key] = district
                rows.append((ward, pct, district, name, email))

    cur.execute("TRUNCATE boston_council_districts")
    cur.executemany(
        "INSERT INTO boston_council_districts (ward, precinct, district, councilor_name, councilor_email) "
        "VALUES (%s, %s, %s, %s, %s)",
        rows,
    )
    conn.commit()
    print(f"Inserted {len(rows)} ward/precinct -> district rows.")

    cur.execute("SELECT district, councilor_name, count(*) FROM boston_council_districts GROUP BY 1, 2 ORDER BY 1")
    for row in cur.fetchall():
        print(row)


if __name__ == "__main__":
    main()
