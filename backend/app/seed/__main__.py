"""`python -m app.seed` (used by `make seed`) — create tables if needed, then seed
tools + agents + templates into the configured database. Idempotent."""
from app.core.db import SessionLocal, init_db
from app.seed import run_seed


def main() -> None:
    init_db()
    with SessionLocal() as db:
        result = run_seed(db)
    print(f"seeded: {result}")


if __name__ == "__main__":
    main()
