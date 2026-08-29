"""Proxy de retrocompatibilidad hacia scripts/db/seed/seed_data.py."""

from .seed.seed_data import (
    run_full_seed,
    seed_categories,
    seed_products,
    seed_users,
)

if __name__ == "__main__":
    run_full_seed()
