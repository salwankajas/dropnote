# Contributing to Dropnote

Thanks for your interest in contributing. Dropnote is an early-stage prototype; please open an issue before starting a large change so we can agree on its scope.

## Development setup

1. Install Node.js 20 or later and Python 3.12 or later.
2. Install dependencies and configure a local admin account as described in [README.md](README.md).
3. Run the FastAPI service on port 8000 and Vite on port 5173.

## Before opening a pull request

- Keep changes focused and preserve the restrained, accessible interface.
- Do not commit `.env` files, credentials, database files, user data, or generated build artifacts.
- Add or update tests for backend behavior and security boundaries.
- Run the checks below from the repository root:

```bash
npm ci
npm run build
python -m py_compile server.py
python -m unittest discover -s tests -v
```

- Update documentation when setup, configuration, or user-visible behavior changes.
- Describe what changed, how you tested it, and any known limitations in the pull request.

## Security issues

Please do not include secrets, private invitation links, or personal data in a public issue. See [SECURITY.md](SECURITY.md) for reporting guidance.
