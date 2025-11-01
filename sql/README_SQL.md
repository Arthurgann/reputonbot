# SQL Migrations — ReputonBot v0.1.1

This folder contains the *schema freeze* for the stable backend **v0.1.1**.
The goal is **reliability**: capture the exact tables and indexes currently used by the app.

> ⚠️ This migration does **not** introduce new structures — it only formalizes what is already live in code.

## Files
- `001_v0.1.1.sql` — creates/ensures tables:  
  `platform_rules`, `interactions`, `chat_state`, `rate_limits`, `request_cache`, and `schema_version`.

## How to apply

### Option A — Supabase SQL editor
1. Open **Supabase → SQL**.
2. Paste the contents of `001_v0.1.1.sql`.
3. Run. You should see either `CREATE TABLE IF NOT EXISTS` or `CREATE INDEX IF NOT EXISTS` messages.

### Option B — psql (direct Postgres access)
```bash
# Replace placeholders with your actual values
export PGHOST=<host>
export PGPORT=<port>
export PGDATABASE=<db>
export PGUSER=<user>
export PGPASSWORD=<password>

psql "host=$PGHOST port=$PGPORT dbname=$PGDATABASE user=$PGUSER password=$PGPASSWORD sslmode=require" \
  -v ON_ERROR_STOP=1 \
  -f sql/001_v0.1.1.sql
```

## Post-apply maintenance (performance)
After the first deployment or any heavy data import, run:
```sql
REINDEX TABLE CONCURRENTLY interactions;
REINDEX TABLE CONCURRENTLY rate_limits;
REINDEX TABLE CONCURRENTLY request_cache;
ANALYZE;
```
> In Supabase, run these from the SQL editor (transactions are managed by PostgREST).

## Expected indexes
- `interactions_by_user_time (telegram_id, created_at DESC)`
- `rate_limits_updated_at_idx (updated_at DESC)`
- `request_cache_expires_idx (expires_at)`

## Version marker
Upon success, the migration inserts a row into `schema_version`:
```sql
insert into schema_version(version) values ('001_v0.1.1') on conflict do nothing;
```
You can list applied versions via:
```sql
select * from schema_version order by applied_at desc;
```

## Rollback
This migration is idempotent (uses `IF NOT EXISTS`). Rollback is usually unnecessary.  
If you **must** drop objects, do it explicitly and carefully in a separate file (not recommended in prod).

---

**Checklist**
- [ ] Run `001_v0.1.1.sql` in Supabase.
- [ ] Execute the `REINDEX CONCURRENTLY` + `ANALYZE` block once.
- [ ] Confirm the row exists in `schema_version`.
- [ ] Proceed to P2/Step 2 (HTTP client reuse + A/B timing).

