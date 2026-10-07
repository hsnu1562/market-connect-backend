# PostgreSQL Phase 2/3 Integration Tests

These tests create the legacy pre-Alembic tables, run the real migration chain
from base through revision 09, and verify the revision-09 schema before testing
the 09 -> 10 -> 11 -> 12 transition. They also exercise PostgreSQL partial
indexes, row locking, unique constraints, foreign-key actions, final inventory
capacity contention, and final category-quota contention. They never read
`DATABASE_URL` as a fallback and create an isolated temporary schema inside the
configured test database. The harness never substitutes `alembic stamp` for
schema construction.

Use only a disposable database whose name contains `test`, `testing`, `tmp`,
`temporary`, `disposable`, `ci`, `sandbox`, or `staging`. The harness refuses a
target matching `DATABASE_URL` and requires an explicit destructive-test flag.

PowerShell:

```powershell
$env:TEST_DATABASE_URL = Read-Host "Disposable PostgreSQL TEST_DATABASE_URL"
$env:SPACIS_ALLOW_DESTRUCTIVE_POSTGRES_TESTS = "1"
python -m pytest -m postgres -q
```

Without `TEST_DATABASE_URL`, these tests skip cleanly.
