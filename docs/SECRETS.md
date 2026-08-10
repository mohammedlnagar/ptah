# Secrets and password storage

## Local development

Run the following command once from the repository root:

```bash
python scripts/bootstrap_local_env.py
```

The script creates a private `.env` file containing a randomly generated Django
secret. It refuses to overwrite an existing file and does not print the secret.
The repository's `.gitignore` excludes `.env`.

An empty `DATABASE_URL` selects local SQLite. To use PostgreSQL locally, replace it
with a URL supplied outside Git, for example through the database service's secret
manager.

## Production credentials

Database connection passwords cannot be stored as one-way hashes: Django must send
the real credential when it authenticates to PostgreSQL. Store `DATABASE_URL` in the
hosting platform's encrypted configuration or a secret manager. To rotate a leaked
password, create a new password at the database provider, update `DATABASE_URL`,
redeploy, verify connectivity, and revoke the old credential.

Set `SECRET_KEY` in the same secret store. `SECRET_KEY_FALLBACKS` supports a brief,
controlled key-rotation window, but a publicly exposed old key should normally be
revoked immediately instead of retained as a fallback.

## Application user passwords

New Django user passwords use Argon2id. Existing supported hashes remain verifiable
and Django upgrades an older hash when that user successfully logs in. Raw user
passwords must only pass through Django's `set_password()` or user-creation APIs and
must never be assigned directly to the model's `password` field.
