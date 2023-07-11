# etl_demo

Install dependencies for development:

```bash
pip install -r requirements-dev.txt
```

Install pre-commit hooks:

```bash
pre-commit install
pre-commit autoupdate
pre-commit install-hooks
```

Test pre-commit hooks run:

```bash
pre-commit run --all-files -v
```

