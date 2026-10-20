"""Start The 420 Lab Discord bot."""
import logging
import os
from dotenv import load_dotenv


def main():
    load_dotenv()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set DISCORD_TOKEN as a private environment variable.")
    if os.getenv("DISCORD_GUILD_ID", "") and not os.getenv("DISCORD_GUILD_ID", "").isdigit():
        raise SystemExit("DISCORD_GUILD_ID must be a numeric guild ID.")
    from lab.bot import bot
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
