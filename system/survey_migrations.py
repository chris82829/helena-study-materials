"""Idempotent questionnaire migrations: V13 seven-point items plus deprecated V12 columns.

Run: python survey_migrations.py /path/to/surveys.sqlite3
Versioned JSON is the sole write source. Generated SQL columns expose ratings without
copying them; missing and explicitly unassessable ratings are NULL, never zero.
"""
from __future__ import annotations

import argparse
from pathlib import Path

USEFULNESS_ITEMS = ('usefulness_effective', 'usefulness_speed', 'usefulness_overall')


def migrate_v12(db):
    """Caller owns the transaction; safe repeatedly on existing or new stores."""
    for table in ('survey_responses', 'survey_drafts'):
        columns = {row[1] for row in db.execute(f'PRAGMA table_xinfo({table})')}
        if not columns:
            continue
        for name in USEFULNESS_ITEMS:
            if name in columns:
                continue
            db.execute(f'''ALTER TABLE {table} ADD COLUMN {name} INTEGER
                GENERATED ALWAYS AS (CASE
                    WHEN json_extract(answers_json, '$.version') = 'helena-v12'
                      AND json_type(answers_json, '$.{name}') = 'integer'
                    THEN json_extract(answers_json, '$.{name}') ELSE NULL END) VIRTUAL
                CHECK ({name} IS NULL OR {name} BETWEEN 1 AND 5)''')


def migrate_v13(db):
    """Expose the current seven-point item ratings; JSON is the only write source."""
    import json
    definition = json.loads(Path(__file__).with_name('survey_definition_v13.json').read_text())
    scales = [field for group in [definition['demographics'], *definition['categories']]
              for field in group['fields'] if field['kind'] == 'scale']
    for table in ('survey_responses', 'survey_drafts'):
        columns = {row[1] for row in db.execute(f'PRAGMA table_xinfo({table})')}
        for field in scales:
            name = field['name']
            if name in columns:
                continue
            assert name.replace('_', '').isalnum()
            db.execute(f"""ALTER TABLE {table} ADD COLUMN {name} INTEGER
                GENERATED ALWAYS AS (CASE
                    WHEN json_extract(answers_json, '$.version') = 'helena-v13'
                      AND json_type(answers_json, '$.{name}') = 'integer'
                    THEN json_extract(answers_json, '$.{name}') ELSE NULL END) VIRTUAL
                CHECK ({name} IS NULL OR {name} BETWEEN 1 AND 7)""")


def migrate_v14(db):
    """Expose the current seven-point item ratings; JSON is the only write source."""
    import json
    definition = json.loads(Path(__file__).with_name('survey_definition_v14.json').read_text())
    scales = [field for group in [definition['demographics'], *definition['categories']]
              for field in group['fields'] if field['kind'] == 'scale']
    for table in ('survey_responses', 'survey_drafts'):
        columns = {row[1] for row in db.execute(f'PRAGMA table_xinfo({table})')}
        for field in scales:
            item = field['name']
            name = 'v14_' + item
            if name in columns:
                continue
            assert name.replace('_', '').isalnum()
            db.execute(f"""ALTER TABLE {table} ADD COLUMN {name} INTEGER
                GENERATED ALWAYS AS (CASE
                    WHEN json_extract(answers_json, '$.version') = 'helena-v14'
                      AND json_type(answers_json, '$.{item}') = 'integer'
                    THEN json_extract(answers_json, '$.{item}') ELSE NULL END) VIRTUAL
                CHECK ({name} IS NULL OR {name} BETWEEN 1 AND 7)""")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    args = parser.parse_args()
    # Initialize empty DBs and run the exact migration used during application startup.
    from survey_store import SurveyStore
    SurveyStore(args.database)
    print('V14 migration applied; versioned seven-point columns available; historical data unchanged.')


if __name__ == '__main__':
    main()
