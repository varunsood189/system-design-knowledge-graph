# Security & privacy (before pushing to GitHub)

## Never commit

- `.env`, `.env.local`, or any file containing real API keys
- `Untitled`, scratch notes, or editor dumps that may paste keys
- Personal machine paths, student IDs, or private repo URLs in docs
- Screenshots or logs that show `GEMINI_API_KEY` or other secrets

`.env` is listed in `.gitignore`. Use [`.env.example`](.env.example) with **empty** placeholders only.

## Safe to commit

- Source code, tests, `uv.lock`, `.env.example` (placeholders)
- `data/graph.json` — public blog-derived concepts only (no credentials)
- Documentation with generic examples (`your-key-here`, `https://example.com/...`)

## Pre-push checklist

```bash
# 1. Confirm .env is not tracked
git check-ignore -v .env
git status   # .env should not appear under "Changes to be committed"

# 2. Scan staged diff for accidental secrets
git diff --cached | grep -iE 'AIza[0-9A-Za-z_-]{10,}|sk-[a-zA-Z0-9]{10,}|api_key\s*=\s*[^<\s]' || echo "No obvious key patterns in staged diff"

# 3. Push only when clean
git push
```

If a key was ever committed, **rotate it** in the provider dashboard and rewrite git history or use GitHub secret scanning remediation — do not leave the old key active.
