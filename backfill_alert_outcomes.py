"""Backfill alert_outcomes rows for all alert_history records that lack one.

Fields copied from alert_history:
  opportunity_score, classification, target_bucket, risk_level
  entry_price  <- latest_close
  symbol, alerted_at

All hit_* flags are initialised to False. last_checked_at is left NULL so
the existing --check-outcomes job will pick them up and fill in real price data.

Usage:
  python backfill_alert_outcomes.py              # live run
  python backfill_alert_outcomes.py --dry-run    # preview only, no writes
"""

import argparse
import os
import sys
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ModuleNotFoundError:
    pass  # python-dotenv is optional; fall back to real env vars

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ModuleNotFoundError:
    print("ERROR: psycopg2-binary is required. Run: pip install psycopg2-binary")
    sys.exit(1)

BATCH_SIZE = 200


def _get_database_url() -> str:
    url = os.getenv("SUPABASE_DATABASE_URL", "").strip()
    if not url:
        print(
            "ERROR: SUPABASE_DATABASE_URL is not set.\n"
            "Set it in your .env file or as an environment variable."
        )
        sys.exit(1)
    if not url.startswith(("postgresql://", "postgres://")):
        print("ERROR: SUPABASE_DATABASE_URL must start with postgresql:// or postgres://")
        sys.exit(1)
    return url


def _connect(database_url: str):
    try:
        return psycopg2.connect(database_url)
    except Exception as exc:
        print(f"ERROR: Could not connect to Supabase: {exc}")
        sys.exit(1)


def _fetch_missing(conn) -> list[dict]:
    """Return alert_history rows that have no matching alert_outcomes row."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                ah.id              AS alert_id,
                ah.symbol,
                ah.alerted_at,
                ah.latest_close    AS entry_price,
                ah.opportunity_score,
                ah.classification,
                ah.target_bucket,
                ah.risk_level
            FROM alert_history ah
            LEFT JOIN alert_outcomes ao ON ao.alert_id = ah.id
            WHERE ao.alert_id IS NULL
            ORDER BY ah.alerted_at ASC, ah.id ASC
            """
        )
        return [dict(row) for row in cur.fetchall()]


def _count_existing_outcomes(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM alert_outcomes")
        return cur.fetchone()[0]


def _count_total_history(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM alert_history")
        return cur.fetchone()[0]


def _insert_batch(conn, rows: list[dict]) -> int:
    """Insert one batch of outcome stubs. Returns number of rows inserted."""
    if not rows:
        return 0

    values = [
        (
            row["alert_id"],
            row["symbol"],
            row["alerted_at"],
            row["entry_price"],   # May be None if latest_close was NULL
            row["opportunity_score"],
            row["classification"],
            row["target_bucket"],
            row["risk_level"],
            False,  # hit_5_pct
            False,  # hit_10_pct
            False,  # hit_20_pct
            False,  # hit_50_pct
            False,  # hit_100_pct
            # last_checked_at left NULL so --check-outcomes picks it up
        )
        for row in rows
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO alert_outcomes (
                alert_id,
                symbol,
                alerted_at,
                entry_price,
                opportunity_score,
                classification,
                target_bucket,
                risk_level,
                hit_5_pct,
                hit_10_pct,
                hit_20_pct,
                hit_50_pct,
                hit_100_pct
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (alert_id) DO NOTHING
            """,
            values,
        )
        return cur.rowcount


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill alert_outcomes for alert_history rows that lack one."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be inserted without writing anything.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N missing rows (useful for testing).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    database_url = _get_database_url()

    print("Connecting to Supabase...")
    conn = _connect(database_url)

    try:
        total_history = _count_total_history(conn)
        existing_outcomes = _count_existing_outcomes(conn)

        print(f"alert_history rows   : {total_history:,}")
        print(f"alert_outcomes rows  : {existing_outcomes:,}")
        print(f"Coverage before      : {existing_outcomes / max(total_history, 1) * 100:.1f}%")
        print()

        print("Finding alert_history rows with no outcome record...")
        missing = _fetch_missing(conn)

        if args.limit is not None:
            missing = missing[: args.limit]

        print(f"Missing outcome rows : {len(missing):,}")

        if not missing:
            print("Nothing to backfill — all alert_history rows already have outcomes.")
            return

        # Show a sample of what will be inserted.
        print()
        print("Sample of rows to be created (first 5):")
        for row in missing[:5]:
            score = row.get("opportunity_score") or "-"
            cls = row.get("classification") or "-"
            bucket = row.get("target_bucket") or "-"
            price = row.get("entry_price")
            price_str = f"{float(price):.6g}" if price is not None else "NULL"
            print(
                f"  {row['alert_id'][:40]:<40} "
                f"sym={row.get('symbol', '-'):<12} "
                f"score={score:<4} cls={cls:<20} "
                f"bucket={bucket:<30} entry={price_str}"
            )

        if args.dry_run:
            print()
            print(f"DRY RUN — {len(missing):,} rows would be inserted. No changes made.")
            return

        print()
        print(f"Inserting {len(missing):,} rows in batches of {BATCH_SIZE}...")

        total_inserted = 0
        batches = [missing[i: i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]

        for batch_num, batch in enumerate(batches, start=1):
            inserted = _insert_batch(conn, batch)
            conn.commit()
            total_inserted += inserted
            pct = batch_num / len(batches) * 100
            print(
                f"  Batch {batch_num}/{len(batches)} ({pct:.0f}%) — "
                f"inserted {inserted} rows (batch size {len(batch)})"
            )

        print()
        final_outcomes = _count_existing_outcomes(conn)
        final_coverage = final_outcomes / max(total_history, 1) * 100

        print(f"Done.")
        print(f"Rows inserted        : {total_inserted:,}")
        print(f"alert_outcomes rows  : {final_outcomes:,}")
        print(f"Coverage after       : {final_coverage:.1f}%")
        print()
        print(
            "Next step: run  python -m app.main --check-outcomes  to populate "
            "hit_* flags and max_high_after_alert for the new rows."
        )

    except KeyboardInterrupt:
        print("\nInterrupted — rolling back uncommitted batch.")
        conn.rollback()
    except Exception as exc:
        conn.rollback()
        print(f"ERROR: {exc}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
