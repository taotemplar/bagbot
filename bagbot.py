import asyncio
import logging
import argparse
import time
import websockets
import traceback
import json
from typing import List, Dict, Tuple

import bittensor as bt
from bittensor.core.async_subtensor import get_async_subtensor
import async_substrate_interface

import printHelpers
import bagbot_settings
from decimal import Decimal, getcontext
getcontext().prec = 16 #Precision for price stuff

from rich.console import Console
console = Console()

class InvalidSettings(Exception): pass

# Configure logging.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler('staking.log')#,
#        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def parseArgs():
    parser = argparse.ArgumentParser(description="A basic bittensor alpha bot")
    parser.add_argument( "--nocheck", action="store_true", help="Don't check settings before starting the bot (boolean flag)"
    )

    # Parse arguments
    args = parser.parse_args()
    return args


rao_to_tao = lambda rao : int(rao)/1000000000.0


async def my_async_subtensor(*args, **kwargs):
    attempts = 0
    while attempts < 15:
        try:
            return await get_async_subtensor(*args, **kwargs)
        except (websockets.exceptions.InvalidStatus, AttributeError) as e:
            logger.error(f'Invalid status err {str(e)}, retrying')
            attempts += 1
            if attempts >= 14:
                raise
            await asyncio.sleep(attempts*2)

class BittensorUtility():


    def __init__(self, args):
        self.args = args
        self.current_stake_info = {}
        self.tick = 0


    async def setupWallet(self):
        with open(bagbot_settings.WALLET_PW_FILE, 'r') as f:
            wallet_pw = f.read().strip()

        self.wallet = bt.wallet(name=bagbot_settings.WALLET_NAME)
        self.wallet.create_if_non_existent()
        self.wallet.coldkey_file.save_password_to_env(wallet_pw)
        self.wallet.unlock_coldkey()


    async def setupSubtensor(self):
        while True:
            try:
                self.sub = await get_async_subtensor("finney")

                break
            except (asyncio.exceptions.TimeoutError, ConnectionResetError) as e:
                logger.error(e)
                logger.error(f'{str(e)}having trouble starting up... try again')
                await asyncio.sleep(3)


    async def setup(self):
        await self.setupWallet()
        await self.setupSubtensor()
        logger.info('Started')


    async def refresh_subnet_grid(self):
        self.subnet_grids = bagbot_settings.SUBNET_SETTINGS
        self.validateGrid()

    def validateGrid(self):
        for subnet_id in self.subnet_grids:
            if not self.subnet_grids[subnet_id].get('sell_lower'):
                raise InvalidSettings(f'"sell_lower" missing for subnet {subnet_id} in bagbot_settings.SUBNET_SETTINGS')
            if not self.subnet_grids[subnet_id].get('buy_upper'):
                raise InvalidSettings(f'"buy_upper" missing for subnet {subnet_id} in bagbot_settings.SUBNET_SETTINGS')
            if not self.subnet_grids[subnet_id].get('max_alpha'):
                raise InvalidSettings(f'"max_alpha" missing for subnet {subnet_id} in bagbot_settings.SUBNET_SETTINGS')
            if self.subnet_grids[subnet_id]['buy_upper'] > self.subnet_grids[subnet_id]['sell_lower']:
                raise InvalidSettings(f'"buy_upper" is higher than "sell_lower" for subnet {subnet_id} in bagbot_settings.SUBNET_SETTINGS')
            if not isinstance(subnet_id, int):
                raise InvalidSettings(f'subnet {subnet_id} must be an integer in bagbot_settings.SUBNET_SETTINGS.  Strings or other objects are not allowed')
            if subnet_id == 0:
                raise InvalidSettings(f'No support for {subnet_id} in bagbot_settings.SUBNET_SETTINGS.')




    def sendNotification(self, msg):
        logger.info(msg)
        #TODO Add Alerting code below:


    async def get_subnet_stats(self) -> Tuple[Dict[int, Dict], Dict[int, int]]:
        all_subnets = None
        attempts = 0
        while all_subnets is None:
            try:
                all_subnets = await self.sub.all_subnets()
            except (AttributeError, websockets.exceptions.InvalidStatus):
                if attempts > 5:
                    self.sendNotification(errMsg)
                    logger.error(traceback.format_exc())
                errMsg = 'Fetching subnets data from substrate had a problem... retrying'
                logger.error(errMsg)

                await asyncio.sleep(3)

                try:
                    await self.sub.close()
                except asyncio.exceptions.TimeoutError:
                    logger.error('Closing subtensor timeout')
                self.sub = await my_async_subtensor("finney")
                attempts += 1

        stats = {}
        for subnet in all_subnets:
            netuid = subnet.netuid

            price = float(subnet.price)
            if price <= 0:
                continue
            name = str(subnet.subnet_name) if hasattr(subnet, "subnet_name") else ""
            stats[netuid] = {
                "name": name,
                "price": price,
                "tao_in": subnet.tao_in.tao,
                "alpha_in": subnet.alpha_in.tao,
            }
        return stats



    async def refresh_stats(self, hotkeys):
        try:
            self.stats = await self.get_subnet_stats()
        except Exception as e:
            logger.error(traceback.format_exc())
            raise

        for hotkey in hotkeys:
            self.current_stake_info[hotkey] = await self.sub.get_stake_for_coldkey_and_hotkey(
                hotkey_ss58=hotkey,
                coldkey_ss58=self.wallet.coldkey.ss58_address
            )

        self.balance = float(await self.sub.get_balance(address=self.wallet.coldkey.ss58_address))

        sumStakedValue = 0
        tickLog = []

        for hotkey in hotkeys:
            for subnet_netuid in self.current_stake_info[hotkey]:
                if subnet_netuid in self.current_stake_info[hotkey] and self.current_stake_info[hotkey][subnet_netuid].stake.rao == 0: continue
                sumStakedValue += rao_to_tao(self.current_stake_info[hotkey][subnet_netuid].stake.rao) * self.stats[subnet_netuid]['price']
                tickLog.append( f'sn{subnet_netuid}: {rao_to_tao(self.current_stake_info[hotkey][subnet_netuid].stake.rao):.1f}' )

        logger.info('{' + f'wallet_value:"{sumStakedValue:.2f} + {self.balance:.2f}", ' + ', '.join(tickLog) + '}')

        await self.refresh_subnet_grid()


    async def run(self):
        await self.setup()

        while True:
            self.tick += 1
            start = time.time()
            try:
                await self.refresh_stats([bagbot_settings.STAKE_ON_VALIDATOR])


                printHelpers.print_table_rich(self, console, self.current_stake_info, list(bagbot_settings.SUBNET_SETTINGS.keys()), self.stats, self.balance, self.subnet_grids)
                if self.tick == 1 and not self.args.nocheck:
                    loop = asyncio.get_event_loop()
                    user_input = await loop.run_in_executor(None, input, "Should the bot proceed? (Y/N): ")
                    if user_input.lower() != 'y':
                        print('Exiting...')
                        return

                for subnet_netuid in bagbot_settings.SUBNET_SETTINGS:
                    await self.do_available_trades(subnet_netuid)

                logging.info(f'Finished tick {self.tick} in {time.time() - start:.2f} seconds')
                #return
                try:
                    await self.sub.wait_for_block()
                except (OSError, KeyError):
                    await asyncio.sleep(12) #if error with waiting for block, just wait approx 1 block and try again

            except asyncio.exceptions.CancelledError:
                logger.info(f'Asyncio exception, retrying...')
                await asyncio.sleep(3)
            except async_substrate_interface.errors.SubstrateRequestException:
                logger.info(f'substrate request exception, retrying...')
                await asyncio.sleep(3)
            except ConnectionResetError:
                logger.info(f'connection reset, retrying...')
                await asyncio.sleep(3)
            except websockets.exceptions.InvalidStatus:
                self.sub = await my_async_subtensor("finney")
                logger.info(f'potential server error, retrying...')
            except asyncio.exceptions.TimeoutError:
                logger.info(f'timeout error... retrying...')
                await asyncio.sleep(3)
            finally:
                try:
                    await self.sub.close()
                except asyncio.exceptions.TimeoutError:
                    logger.error('Closing subtensor timeout')


    def determine_buy_at_for_amount(self, subnet_settings, alpha_amount):
        if 'buy_upper' not in subnet_settings:
            return None
        buy_upper = subnet_settings['buy_upper']
        if 'buy_lower' not in subnet_settings or alpha_amount == 0:
            return buy_upper
        buy_lower = subnet_settings['buy_lower']
        buy_at = buy_upper
        price_reduction_per_alpha = (buy_upper - buy_lower) / subnet_settings['max_alpha']
        for i in range(int(alpha_amount)):
            buy_at -= price_reduction_per_alpha
        return buy_at

    def determine_sell_at_for_amount(self, subnet_settings, alpha_amount):
        if 'sell_lower' not in subnet_settings:
            return None
        sell_lower = subnet_settings['sell_lower']
        if 'sell_upper' not in subnet_settings or alpha_amount == 0:
            return sell_lower
        sell_upper = subnet_settings['sell_upper']
        sell_at = sell_upper
        sell_price_reduction_per_alpha = (sell_upper - sell_lower) / subnet_settings['max_alpha']
        for i in range(int(alpha_amount)):
            sell_at -= sell_price_reduction_per_alpha
        return sell_at



    def get_subnet_buy_threshold(self, subnet_netuid):
        current_stake_amt = self.my_current_stake(subnet_netuid)
        if self.subnet_grids.get(subnet_netuid,{}).get('buy_upper') is not None:
            return self.determine_buy_at_for_amount(self.subnet_grids.get(subnet_netuid,{}), current_stake_amt)
        return None


    def get_subnet_sell_threshold(self, subnet_netuid):
        current_stake_amt = self.my_current_stake(subnet_netuid)
        if self.subnet_grids.get(subnet_netuid,{}).get('sell_lower') is not None:
            return self.determine_sell_at_for_amount(self.subnet_grids.get(subnet_netuid,{}), current_stake_amt)
        """
        baseline = self.subnet_grids.get(subnet_netuid,{}).get('sell_lower')
        return baseline
        """


    def my_current_stake(self, subnet_netuid):
        total_stake = 0
        for hotkey in self.current_stake_info:
            stake_obj = self.current_stake_info[hotkey].get(subnet_netuid)
            total_stake += (float(stake_obj.stake) if stake_obj is not None else 0.0)
        return total_stake


    def determineHotKey(self, unstake_amt, subnet_netuid):
        for hotkey in self.current_stake_info:
            stake_obj = self.current_stake_info[hotkey].get(subnet_netuid)
            stake = (float(stake_obj.stake) if stake_obj is not None else 0.0)
            if stake > 0:
                return hotkey
        return None


    def determineSlippage(self, token_amount, token_in_pool):
        slippage = (token_amount/(token_in_pool+token_amount)) * 100.0
        return slippage


    def determineTokenBuyAmount(self, max_token_per_buy, token_in_pool):
        max_amount_with_max_slippage = (token_in_pool*(bagbot_settings.MAX_SLIPPAGE_PERCENT_PER_BUY/100.0)) / (1 - (bagbot_settings.MAX_SLIPPAGE_PERCENT_PER_BUY/100.0))
        return min(max_token_per_buy, max_amount_with_max_slippage)



    def constructBuy(self, subnet_netuid):
        current_stake_amt = self.my_current_stake(subnet_netuid)
        buy_threshold = self.get_subnet_buy_threshold(subnet_netuid)

        goal_amount_to_buy = self.subnet_grids[subnet_netuid].get('buy_tao_amount_override', bagbot_settings.MAX_TAO_PER_BUY)
        if self.balance > goal_amount_to_buy:

            if subnet_netuid in self.stats and self.stats[subnet_netuid]['price'] < buy_threshold and current_stake_amt < self.subnet_grids[subnet_netuid]['max_alpha']:
                logger.info(f'''Want to buy sn{subnet_netuid} at price {self.stats[subnet_netuid]['price']} because it's lower than my threshold: {buy_threshold}, currently have {current_stake_amt} alpha in it''')

                tao_amount = self.determineTokenBuyAmount(goal_amount_to_buy, self.stats[subnet_netuid]['tao_in'])
                slippage = self.determineSlippage(tao_amount, self.stats[subnet_netuid]['tao_in'])
                if slippage > bagbot_settings.MAX_SLIPPAGE_PERCENT_PER_BUY:
                    raise Exception(f'Should never get here, stopping before purchasing too much slippage: {slippage}, max slippage per buy/sell: {bagbot_settings.MAX_SLIPPAGE_PERCENT_PER_BUY}')
                tao_amount = bt.utils.balance.tao(tao_amount)
                trade = {
                    'hotkey':bagbot_settings.STAKE_ON_VALIDATOR,
                    'netuid':subnet_netuid,
                    'tao_amount':tao_amount,
                    'buy_threshold':buy_threshold,
                    'calculated_slippage':slippage,
                    'max_slippage':bagbot_settings.MAX_SLIPPAGE_PERCENT_PER_BUY / 100.0
                }
                logger.info(f"About to stake {tao_amount} to {subnet_netuid} with expected slippage of {slippage:.4f}%")
                return trade
        else:
            logger.info(f'Not enough balance to stake: {self.balance:.2f}')
        return None

    def constructSell(self, subnet_netuid):
        current_stake_amt = self.my_current_stake(subnet_netuid)
        sell_threshold = self.get_subnet_sell_threshold(subnet_netuid)

        if subnet_netuid in self.stats and \
            self.stats[subnet_netuid]['price'] > sell_threshold and \
            self.my_current_stake(subnet_netuid) > 0:

            unstake_target = bagbot_settings.MAX_TAO_PER_SELL / self.stats[subnet_netuid]['price']
            my_current_alpha = float(self.my_current_stake(subnet_netuid))
            max_alpha_possible_to_sell = min(my_current_alpha, unstake_target)
            alpha_to_sell = self.determineTokenBuyAmount(max_alpha_possible_to_sell, self.stats[subnet_netuid]['alpha_in'])
            alpha_amount = bt.utils.balance.tao(alpha_to_sell, subnet_netuid)

            hotkey = self.determineHotKey(alpha_to_sell, subnet_netuid)
            approx_tao = float(Decimal(self.stats[subnet_netuid]['price']) * Decimal(alpha_to_sell))

            if approx_tao > bagbot_settings.MAX_TAO_PER_SELL:
                raise Exception(f'Should never get here, stopping before selling too much. approx_tao: {approx_tao}, max tao per sell: {bagbot_settings.MAX_TAO_PER_SELL}, price x alpha: {self.stats[subnet_netuid]["price"]} x {alpha_to_sell}')

            slippage = self.determineSlippage(alpha_to_sell, self.stats[subnet_netuid]['alpha_in'])
            if slippage > bagbot_settings.MAX_SLIPPAGE_PERCENT_PER_BUY:
                raise Exception(f'Should never get here, stopping before selling too much, slippage: {slippage}, max slippage per buy/sell: {bagbot_settings.MAX_SLIPPAGE_PERCENT_PER_BUY}')

            logger.info(f"About to unstake {alpha_to_sell} alpha (~{approx_tao} TAO) in sn{subnet_netuid} on hotkey {hotkey} with expected slippage of {slippage:.4f}%")

            trade = {
                'hotkey':hotkey,
                'netuid':subnet_netuid,
                'alpha_amount':alpha_amount,
                'max_slippage':bagbot_settings.MAX_SLIPPAGE_PERCENT_PER_BUY / 100.0,
                'sell_threshold':sell_threshold,
                'calculated_slippage':slippage,
                'approx_tao': approx_tao,
            }
            return trade

        return None


    async def do_available_trades(self, subnet_netuid):

        buyTrade = self.constructBuy(subnet_netuid)
        if buyTrade:
            try:
                stake_result = await self.sub.add_stake(
                    wallet=self.wallet,
                    hotkey_ss58=buyTrade['hotkey'],
                    netuid=buyTrade['netuid'],
                    amount=buyTrade['tao_amount'],
                    rate_tolerance=buyTrade['max_slippage'],
                    wait_for_inclusion=False,
                    wait_for_finalization=False,
                    safe_staking=True,
                    allow_partial_stake=False
                )
                print(f'after buy {str(buyTrade)}')
                if stake_result is True:
                    logger.info(f"Staked {float(buyTrade['tao_amount'])} TAO to subnet {buyTrade['netuid']} ({str(stake_result)})")
                else:
                    logger.info(f"Failed to stake {float(buyTrade['tao_amount'])} TAO to subnet {buyTrade['netuid']} ({str(stake_result)})")
            except Exception as e:
                print(f'ERROR staking')
                logger.error(traceback.format_exc())
                logger.error(f"Failed to stake on subnet {buyTrade['netuid']}: {e}")

        sellTrade = self.constructSell(subnet_netuid)
        if sellTrade:
            try:
                unstake_result = await self.sub.unstake(
                    wallet=self.wallet,
                    hotkey_ss58=sellTrade['hotkey'] ,
                    netuid=sellTrade['netuid'],
                    amount=sellTrade['alpha_amount'],
                    rate_tolerance=sellTrade['max_slippage'],
                    wait_for_inclusion=True,
                    wait_for_finalization=False,
                    safe_staking=True,
                    allow_partial_stake=False
                )
                print(f'after sell {str(sellTrade)}')
                if unstake_result is True:
                    logger.info(f"Unstaked {float(sellTrade['alpha_amount'])} stake units from sn{sellTrade['netuid']} (approx. {sellTrade['approx_tao']:.4f} TAO value) at price: {self.stats[subnet_netuid]['price']}.  my threshold = {sellTrade['sell_threshold']}")
                else:
                    logger.info(f"Failed to unstake {str(sellTrade)}  sn{subnet_netuid} ({str(unstake_result)})")
            except asyncio.exceptions.CancelledError as e:
                print(f'ERROR unstaking - cancelled error')
                logger.error(traceback.format_exc())
                logger.error(f"Failed to unstake from subnet {subnet_netuid}: {e}")
            except Exception as e:
                print(f'ERROR unstaking')
                logger.error(traceback.format_exc())
                logger.error(f"Failed to unstake from subnet {subnet_netuid}: {e}")


if __name__ == "__main__":
    args = parseArgs()
    binterface = BittensorUtility(args)
    try:
        asyncio.run(binterface.run())
    except KeyboardInterrupt:
        logger.info("Service stopped by user.")
    except Exception as e:
        logger.error(traceback.format_exc())
        logger.critical(f"Critical error: {e}")
        print(traceback.format_exc())
        binterface.sendNotification(f"Bittensor interface Broke: {e}")
