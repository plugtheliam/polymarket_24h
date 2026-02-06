"""Allow running as: python -m poly24h"""
from dotenv import load_dotenv

load_dotenv()

from poly24h.main import cli_main  # noqa: E402

if __name__ == "__main__":
    cli_main()
