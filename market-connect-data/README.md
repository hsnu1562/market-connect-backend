# MarketConnect Prototype Data

This folder contains data extracted from `smart_market.zip`.

## Contents

- `db.sqlite3`: SQLite development database from the Django prototype.

## Current Role

Treat this database as sample/reference data only. It should not become the
production database and is intentionally ignored by the backend repository.

If data is needed later, inspect or export it explicitly into a documented seed
format.

## Keep / Remove Policy

- Keep locally: small sample databases that help explain the prototype.
- Commit instead: reviewed JSON or CSV fixtures with documented fields and no
  personal data.
- Remove: regenerated local databases, personal test data, or large database
  dumps unless the team explicitly needs them.
