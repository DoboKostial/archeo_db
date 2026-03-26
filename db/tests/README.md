DB template unit tests live here.

Run them from the repository root with:

```bash
python3 -m unittest discover -s db/tests -v
```

The tests are source-level checks for the SQL templates in `db/`. They do not start PostgreSQL.
