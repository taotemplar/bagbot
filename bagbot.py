import asyncio
import logging
import argparse
import traceback

from blockchain import BittensorUtility
rao_to_tao = lambda rao : int(rao)/1000000000.0

def parseArgs():
    parser = argparse.ArgumentParser(description="A basic bittensor alpha bot")
    parser.add_argument("--nocheck", action="store_true", help="Don't check settings before starting the bot (boolean flag)")
    args = parser.parse_args()
    return args

if __name__ == "__main__":
    args = parseArgs()
    binterface = BittensorUtility(args)
    try:
        asyncio.run(binterface.run())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Service stopped by user.")
    except Exception as e:
        logging.getLogger(__name__).error(traceback.format_exc())
        logging.getLogger(__name__).critical(f"Critical error: {e}")
        print(traceback.format_exc())
        binterface.sendNotification(f"Bittensor interface Broke: {e}")