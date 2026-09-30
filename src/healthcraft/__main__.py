"""Allow running healthcraft as a module: python -m healthcraft."""

from healthcraft.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
