"""Proxy ejecutor para scripts/db/seed/seed_data.py."""

from .seed.seed_data import run_full_seed

if __name__ == "__main__":
    run_full_seed()
