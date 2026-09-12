#!/usr/bin/env python3
"""Export a size-bounded Prompt Workbench catalog from genai-tag-db-tools SQLite data."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return value or "unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path, help="Path to a genai-tag-db-tools SQLite database")
    parser.add_argument("--output", required=True, type=Path, help="Output catalog JSON path")
    parser.add_argument("--format", default="danbooru", dest="format_name", help="Source format to export")
    parser.add_argument("--language", default="ja", help="Preferred translation language")
    parser.add_argument("--limit", type=int, default=10_000, help="Maximum non-alias tags to export")
    parser.add_argument("--min-usage", type=int, default=0, help="Minimum usage count for an exported tag")
    parser.add_argument("--include-deprecated", action="store_true")
    parser.add_argument("--include-aliases", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=4 * 1024 * 1024)
    return parser.parse_args()


def translation_sql(language: str) -> tuple[str, tuple[str]]:
    return (
        """COALESCE(
            (SELECT translation FROM TAG_TRANSLATIONS tr
             WHERE tr.tag_id = t.tag_id AND tr.language = ? AND trim(tr.translation) <> ''
             ORDER BY tr.translation_id LIMIT 1),
            (SELECT translation FROM TAG_TRANSLATIONS tr
             WHERE tr.tag_id = t.tag_id AND trim(tr.translation) <> ''
             ORDER BY CASE WHEN tr.language = 'en' THEN 0 ELSE 1 END, tr.translation_id LIMIT 1),
            ''
        ) AS translation""",
        (language,),
    )


def export_catalog(args: argparse.Namespace) -> dict:
    if args.limit <= 0:
        raise ValueError("--limit must be positive")
    if args.min_usage < 0:
        raise ValueError("--min-usage must not be negative")
    uri = f"file:{args.database.resolve().as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        format_row = connection.execute(
            "SELECT format_id, format_name FROM TAG_FORMATS WHERE format_name = ?", (args.format_name,)
        ).fetchone()
        if format_row is None:
            raise ValueError(f"Unknown format: {args.format_name}")
        translation_sql_text, translation_params = translation_sql(args.language)
        deprecated_clause = "" if args.include_deprecated else "AND s.deprecated = 0"
        alias_clause = "AND s.alias = 0"
        rows = connection.execute(
            f"""
            SELECT s.tag_id, t.tag, t.source_tag, n.type_name,
                   COALESCE(u.count, 0) AS usage_count,
                   {translation_sql_text}, s.alias, s.deprecated
            FROM TAG_STATUS s
            JOIN TAGS t ON t.tag_id = s.tag_id
            JOIN TAG_TYPE_FORMAT_MAPPING m
              ON m.format_id = s.format_id AND m.type_id = s.type_id
            JOIN TAG_TYPE_NAME n ON n.type_name_id = m.type_name_id
            LEFT JOIN TAG_USAGE_COUNTS u
              ON u.tag_id = s.tag_id AND u.format_id = s.format_id
            WHERE s.format_id = ? {deprecated_clause} {alias_clause}
              AND COALESCE(u.count, 0) >= ?
            ORDER BY usage_count DESC, t.tag COLLATE NOCASE, s.tag_id
            LIMIT ?
            """,
            (*translation_params, format_row["format_id"], args.min_usage, args.limit),
        ).fetchall()
        format_label = str(format_row["format_name"])
        major_id = f"tagdb:format:{slug(format_label)}"
        by_type: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_type.setdefault(str(row["type_name"]), []).append(row)
        medium_categories = []
        for type_name in sorted(by_type, key=str.casefold):
            type_slug = slug(type_name)
            small_id = f"{major_id}:type:{type_slug}"
            tags = []
            for rank, row in enumerate(by_type[type_name], start=1):
                tag = {
                    "id": int(row["tag_id"]),
                    "name": str(row["tag"]),
                    "source_tag": str(row["source_tag"]),
                    "post_count": int(row["usage_count"] or 0),
                    "rank": rank,
                }
                translation = str(row["translation"] or "").strip()
                if translation:
                    tag["translation_ja"] = translation
                if args.include_aliases:
                    aliases = connection.execute(
                        """
                        SELECT t2.tag FROM TAG_STATUS a
                        JOIN TAGS t2 ON t2.tag_id = a.tag_id
                        WHERE a.format_id = ? AND a.preferred_tag_id = ?
                          AND a.alias = 1 AND a.deprecated = 0
                        ORDER BY t2.tag COLLATE NOCASE
                        """,
                        (format_row["format_id"], row["tag_id"]),
                    ).fetchall()
                    if aliases:
                        tag["aliases"] = [str(alias[0]) for alias in aliases]
                tags.append(tag)
            medium_categories.append(
                {
                    "id": f"{major_id}:medium:{type_slug}",
                    "label_en": type_name,
                    "label_ja": type_name,
                    "small_categories": [
                        {"id": small_id, "label_en": "Uncategorized", "label_ja": "未分類", "tags": tags}
                    ],
                }
            )
        return {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "sources": {"database": str(args.database), "format": format_label},
            "stats": {
                "tags": len(rows),
                "major_categories": 1,
                "medium_categories": len(medium_categories),
                "small_categories": len(medium_categories),
            },
            "major_categories": [
                {
                    "id": major_id,
                    "label_en": format_label,
                    "label_ja": format_label,
                    "medium_categories": medium_categories,
                }
            ],
        }
    finally:
        connection.close()


def main() -> None:
    args = parse_args()
    catalog = export_catalog(args)
    encoded = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    size = len(encoded.encode("utf-8"))
    if size > args.max_bytes:
        raise SystemExit(f"catalog is {size} bytes, above --max-bytes={args.max_bytes}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
    print(f"wrote {args.output} ({size} bytes, {catalog['stats']['tags']} tags)")


if __name__ == "__main__":
    main()



