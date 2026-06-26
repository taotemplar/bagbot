import asyncio
import logging
import websockets
import traceback
import json
import os
from typing import List, Dict, Tuple
from dotenv import load_dotenv
import bittensor as bt
from bittensor.core.async_subtensor import get_async_subtensor
import async_substrate_interface

import printHelpers
from decimal import Decimal, getcontext

import time
import sys

rao_to_tao = lambda rao : int(rao)/1000000000.0
getcontext().prec = 14 #Precision for price stuff

from rich.console import Console
#console = Console(width=160, force_terminal=True)

console = Console(
    width=160,
    force_terminal=True,
    color_system="truecolor",
    soft_wrap=True      # continue on next line
)

from settings_loader import bagbot_settings

class InternetIssueException(Exception): pass

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

def print_link(url: str, text: str | None = None) -> None:
    if text is None:
        text = url

    line = f"Taoflute Portfolio link: {url}"

    # Print through Rich console to ensure the link always wraps correctly
    console.print(
        line,
        soft_wrap=True,
        overflow="ignore",
        crop=False,
		no_wrap=True
    )
#def print_link(url: str, text: str | None = None) -> None:
	# if text is None:
		#    text = url
    # \x1b = ESC
	#print(f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\")

# async def my_async_subtensor(*args, **kwargs):
#     attempts = 0
#     while attempts < 20:
#         try:
#             return await get_async_subtensor(*args, **kwargs)
#         except (websockets.exceptions.InvalidStatus, AttributeError, asyncio.exceptions.TimeoutError) as e:
#             logger.error(f'Invalid status err {str(e)}, retrying')
#             attempts += 1
#             if attempts >= 19:
#                 raise
#             await asyncio.sleep(attempts*2)
async def my_async_subtensor(*args, **kwargs):
    last_exc = None
    for attempt in range(20):
        try:
            return await get_async_subtensor(*args, **kwargs)
        except (websockets.exceptions.InvalidStatus, AttributeError, asyncio.exceptions.TimeoutError, OSError) as e:
            last_exc = e
            logger.error(f'Connection err {str(e)}, retrying (attempt {attempt+1}/20)')
            await asyncio.sleep((attempt + 1) * 2)
    raise last_exc

class BittensorUtility():


    def __init__(self, args):
        self.args = args
        self.current_stake_info = {}
        self.tick = 0
        self.gridLoaded = False


    def get_subnet_setting(self, subnet_netuid, setting_name, default_value):
        """
        Get a setting for a subnet, allowing per-subnet overrides of global settings.

        Args:
            subnet_netuid: The subnet ID
            setting_name: The name of the setting to get
            default_value: The default (global) value if no override exists

        Returns:
            The subnet-specific override if it exists, otherwise the default value
        """
        if subnet_netuid in self.subnet_grids:
            return self.subnet_grids[subnet_netuid].get(setting_name, default_value)
        return default_value


    async def discover_all_validators_with_stake(self):
        """
        Query the blockchain to find ALL validators where this coldkey has stake.

        Returns:
            List of validator hotkeys that have stake from this coldkey, or None if discovery fails
        """
        try:
            # Try to get comprehensive stake info
            stake_info_list = await asyncio.wait_for(
                self.sub.get_stake_info_for_coldkey(
                    coldkey_ss58=self.wallet.coldkey.ss58_address
                ),
                timeout=30.0
            )

            validators = set()

            # Handle different return types
            if stake_info_list is None:
                logger.warning('get_stake_info_for_coldkey returned None')
                return None

            # If it's a list, iterate and extract hotkeys
            if isinstance(stake_info_list, list):
                for stake_info in stake_info_list:
                    hotkey = None
                    # Try different attribute names
                    if hasattr(stake_info, 'hotkey_ss58'):
                        hotkey = stake_info.hotkey_ss58
                    elif hasattr(stake_info, 'hotkey'):
                        hotkey = stake_info.hotkey

                    if hotkey:
                        validators.add(hotkey)
                        logger.debug(f'Found stake on validator {hotkey}')
            else:
                logger.warning(f'Unexpected return type from get_stake_info_for_coldkey: {type(stake_info_list)}')
                return None

            if len(validators) > 0:
                logger.info(f'Discovered {len(validators)} validators with stake from blockchain: {list(validators)}')
                return list(validators)
            else:
                logger.warning('No validators found with stake, falling back to configured validators')
                return None

        except (AttributeError, TypeError) as e:
            logger.warning(f'Error parsing stake info structure: {e}')
            logger.warning('Falling back to configured validators only')
            return None
        except asyncio.TimeoutError:
            logger.warning('Timeout discovering validators from blockchain')
            logger.warning('Falling back to configured validators only')
            return None
        except Exception as e:
            logger.warning(f'Could not discover validators from blockchain: {e}')
            logger.warning(traceback.format_exc())
            logger.warning('Falling back to configured validators only')
            return None

    def get_all_validators(self):
        """
        Collect all unique validator hotkeys from global setting and per-subnet overrides.

        Returns:
            List of unique validator hotkeys to query for stake info
        """
        validators = {bagbot_settings.STAKE_ON_VALIDATOR}

        # Check each subnet for validator overrides
        for subnet_config in self.subnet_grids.values():
            if 'stake_on_validator' in subnet_config:
                validators.add(subnet_config['stake_on_validator'])

        return list(validators)


#    async def setupWallet(self):
#        wallet_pw = bagbot_settings.WALLET_PW
#
#        self.wallet = bt.Wallet(name=bagbot_settings.WALLET_NAME)
#        self.wallet.create_if_non_existent()
#        self.wallet.coldkey_file.save_password_to_env(wallet_pw)
#        self.wallet.unlock_coldkey()

    async def setupWallet(self):
        wallet_pw = os.environ.get('WALLET_PW')
        wallet_name = os.environ.get('WALLET_NAME')

        self.wallet = bt.Wallet(name=wallet_name)
        self.wallet.create_if_non_existent()
        self.wallet.coldkey_file.save_password_to_env(wallet_pw)
        self.wallet.unlock_coldkey()

    async def setupSubtensor(self):
        while True:
            try:
                self.sub = await my_async_subtensor("finney")

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
        if not self.gridLoaded:
            self.subnet_grids = bagbot_settings.SUBNET_SETTINGS
            self.validateGrid()
        self.gridLoaded = True

    def validateGrid(self):
        for subnet_id in self.subnet_grids:
            if (self.subnet_grids[subnet_id].get('sell_lower') or self.subnet_grids[subnet_id].get('sell_upper')) and self.subnet_grids[subnet_id].get('sell'):
                raise InvalidSettings(f'Do not mix and match [sell_lower + sell_upper] with [sell], pick one or the other.  Subnet {subnet_id} in bagbot_settings.SUBNET_SETTINGS: {self.subnet_grids[subnet_id]}')
            if (self.subnet_grids[subnet_id].get('buy_lower') or self.subnet_grids[subnet_id].get('buy_upper')) and self.subnet_grids[subnet_id].get('buy'):
                raise InvalidSettings(f'Do not mix and match [buy_lower + buy_upper] with [buy], pick one or the other.  Subnet {subnet_id} in bagbot_settings.SUBNET_SETTINGS')
            if not self.subnet_grids[subnet_id].get('sell_lower'):
                if self.subnet_grids[subnet_id].get('sell'):
                    self.subnet_grids[subnet_id]['sell_lower'] = self.subnet_grids[subnet_id]['sell']
                else:
                    raise InvalidSettings(f'"sell_lower" missing for subnet {subnet_id} in bagbot_settings.SUBNET_SETTINGS')
            if self.subnet_grids[subnet_id].get('buy_upper') is None:
                if self.subnet_grids[subnet_id].get('buy') is not None:
                    self.subnet_grids[subnet_id]['buy_upper'] = self.subnet_grids[subnet_id]['buy']
                else:
                    raise InvalidSettings(f'"buy_upper" missing for subnet {subnet_id} in bagbot_settings.SUBNET_SETTINGS')
            if self.subnet_grids[subnet_id].get('sell_upper') is not None and self.subnet_grids[subnet_id].get('sell_lower') is not None and \
               self.subnet_grids[subnet_id].get('sell_upper') < self.subnet_grids[subnet_id].get('sell_lower'):
                raise InvalidSettings(f'"sell_upper" is lower than "sell_lower" for subnet {subnet_id} in bagbot_settings.SUBNET_SETTINGS')
            if not self.subnet_grids[subnet_id].get('max_alpha'):
                raise InvalidSettings(f'"max_alpha" missing for subnet {subnet_id} in bagbot_settings.SUBNET_SETTINGS')
            if self.subnet_grids[subnet_id]['buy_upper'] > self.subnet_grids[subnet_id]['sell_lower']:
                raise InvalidSettings(f'"buy_upper" is higher than "sell_lower" for subnet {subnet_id} in bagbot_settings.SUBNET_SETTINGS')
            if not isinstance(subnet_id, int):
                raise InvalidSettings(f'subnet {subnet_id} must be an integer in bagbot_settings.SUBNET_SETTINGS.  Strings or other objects are not allowed')
            if subnet_id == 0:
                raise InvalidSettings(f'No support for {subnet_id} in bagbot_settings.SUBNET_SETTINGS.')

            # Validate power curve settings if present
            buy_zone_power = self.subnet_grids[subnet_id].get('buy_zone_power', bagbot_settings.BUY_ZONE_POWER)
            if buy_zone_power <= 0:
                raise InvalidSettings(f'"buy_zone_power" must be positive for subnet {subnet_id} (got {buy_zone_power})')

            sell_zone_power = self.subnet_grids[subnet_id].get('sell_zone_power', bagbot_settings.SELL_ZONE_POWER)
            if sell_zone_power <= 0:
                raise InvalidSettings(f'"sell_zone_power" must be positive for subnet {subnet_id} (got {sell_zone_power})')




    def sendNotification(self, msg):
        logger.info(msg)

    async def get_subnet_stats(self) -> Tuple[Dict[int, Dict], Dict[int, int]]:
        all_subnets = None
        attempts = 0

        while all_subnets is None and attempts < 10:
            try:
                all_subnets = await self.sub.all_subnets()
                break  # Success

            except Exception as e:
                attempts += 1
                logger.error(f'Fetching subnets data failed (attempt {attempts}/10): {e}')

                if attempts > 5:
                    self.sendNotification(f"Failed to fetch subnets after {attempts} attempts: {e}")

                await asyncio.sleep(3)

                try:
                    await self.sub.close()
                except:
                    pass

                try:
                    self.sub = await my_async_subtensor("finney")
                except Exception as reconnect_err:
                    logger.error(f'Reconnection failed: {reconnect_err}')
                    # Keep retrying if reconnection fails
                    continue

        if all_subnets is None:
            raise Exception(f"Failed to fetch subnets after {attempts} attempts. Last error: {e}")

        # Build stats
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


    async def get_stake_for_hotkey(self, hotkey):
        attempts = 10
        for i in range(attempts):
            try:
                retval = await asyncio.wait_for(
                            self.sub.get_stake_for_coldkey_and_hotkey(
                                hotkey_ss58=hotkey,
                                coldkey_ss58=self.wallet.coldkey.ss58_address
                            ),
                            timeout=20.0
                        )
                return retval
            except asyncio.exceptions.TimeoutError:
                logger.info('Timeout fetching hotkey stake')
                await asyncio.sleep(10)
        raise InternetIssueException("Too many attempts to refresh stats")


    async def refresh_stats(self, hotkeys):

        try:
            logger.info('Fetching subnet stats')
            self.stats = await asyncio.wait_for(self.get_subnet_stats(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.error('Timeout fetching subnet stats after 30s')
            raise
        except Exception as e:
            logger.error(traceback.format_exc())
            raise

        for hotkey in hotkeys:
            logger.info(f'Fetching stake info for {hotkey}')
            self.current_stake_info[hotkey] = await self.get_stake_for_hotkey(hotkey)

        logger.info('Fetching wallet balance')
        self.balance = float(await asyncio.wait_for(
            self.sub.get_balance(address=self.wallet.coldkey.ss58_address),
            timeout=20.0
        ))

        sumStakedValue = 0
        tickLog = []

        for hotkey in hotkeys:
            for subnet_netuid in self.current_stake_info[hotkey]:
                if subnet_netuid in self.current_stake_info[hotkey] and self.current_stake_info[hotkey][subnet_netuid].stake.rao == 0: continue
                sumStakedValue += rao_to_tao(self.current_stake_info[hotkey][subnet_netuid].stake.rao) * self.stats[subnet_netuid]['price']
                tickLog.append( f'sn{subnet_netuid}: {rao_to_tao(self.current_stake_info[hotkey][subnet_netuid].stake.rao):.1f}' )

        logger.info('{' + f'wallet_value:"{sumStakedValue:.2f} + {self.balance:.2f}", ' + ', '.join(tickLog) + '}')



    async def run(self):
        await self.setup()
        await self.refresh_subnet_grid()  # Load settings before first tick

        while True:
            self.tick += 1
            start = time.time()
            try:
                logger.info(f'Starting tick {self.tick}')
                # Try to discover ALL validators with stake from blockchain
                discovered_validators = await self.discover_all_validators_with_stake()

                if discovered_validators:
                    # Use discovered validators for comprehensive stake info
                    all_validators = discovered_validators
                    logger.info(f'Using discovered validators for stake queries: {all_validators}')
                else:
                    # Fall back to configured validators only
                    all_validators = self.get_all_validators()
                    logger.info(f'Using configured validators for stake queries: {all_validators}')

                await self.refresh_stats(all_validators)

                logger.info(f'Tick {self.tick}: Printing table')
                printHelpers.print_table_rich(self, console, self.current_stake_info, list(bagbot_settings.SUBNET_SETTINGS.keys()), self.stats, self.balance, self.subnet_grids)
                if self.tick == 1 and not self.args.nocheck:
                    loop = asyncio.get_event_loop()
                    allSubnetParams = '&var-target_subnets='.join([str(k) for k in self.subnet_grids])
                    print(f"Link to portfolio on taoflute: https://taoflute.com/d/5c216965-b99b-4d82-8b31-931bb3d71567/subnets-overview?orgId=1&var-target_subnets={allSubnetParams}\n")
                    user_input = await loop.run_in_executor(None, input, "Should the bot proceed? (Y/N): ")
                    if user_input.lower() != 'y':
                        print('Exiting...')
                        return
                allSubnetParams = '&var-target_subnets='.join([str(k) for k in self.subnet_grids])
                print_link(f"https://taoflute.com/d/5c216965-b99b-4d82-8b31-931bb3d71567/subnets-overview?orgId=1&var-target_subnets={allSubnetParams}", 'Taoflute Portfolio link')
                logger.info(f'Tick {self.tick}: Checking trades')

                for subnet_netuid in bagbot_settings.SUBNET_SETTINGS:
                    await self.do_available_trades(subnet_netuid)

                logging.info(f'Finished tick {self.tick} in {time.time() - start:.2f} seconds')                
                try:
                    logger.info(f'Tick {self.tick}: Waiting for next block')
                    await asyncio.wait_for(self.sub.wait_for_block(), timeout=30.0)
                except (asyncio.TimeoutError, OSError):
                    logger.warning(f'Tick {self.tick}: CONNECTION ERROR (wait_for_block timed out), reconnecting...')
                    try:
                        await self.sub.close()
                    except:
                        pass
                    self.sub = await my_async_subtensor("finney")
                except KeyError:
                    await asyncio.sleep(12) #if error with waiting for block try again after approx 1 block

            except InternetIssueException:
                logger.warning(f'Some internet issue must be happening, pausing for 1 minute...')
                await asyncio.sleep(60)
            except asyncio.exceptions.CancelledError:
                logger.info(f'Asyncio exception, retrying...')
                await asyncio.sleep(3)
            except async_substrate_interface.errors.SubstrateRequestException:
                logger.info(f'substrate request exception, retrying...')
                await asyncio.sleep(3)
            except ConnectionResetError:
                logger.info(f'connection reset, retrying...')
                await asyncio.sleep(3)
            except (websockets.exceptions.InvalidStatus, async_substrate_interface.errors.SubstrateRequestException, websockets.exceptions.ConnectionClosedError) as e:
                logger.info(f'potential server error: {e}, reconnecting...')
                try:
                    await self.sub.close()
                except:
                    pass
                self.sub = await my_async_subtensor("finney")
            except OSError as e:
                logger.critical(f'Could not reconnect after 20 attempts: {e}. Shutting down.')
                return
            except asyncio.exceptions.TimeoutError:
                logger.warning(f'Timeout error in tick {self.tick}, reconnecting subtensor...')
                try:
                    await self.sub.close()
                except:
                    pass
                self.sub = await my_async_subtensor("finney")
                await asyncio.sleep(3)

from trade import (
    determine_buy_at_for_amount, determine_sell_at_for_amount,
    get_subnet_buy_threshold, get_subnet_sell_threshold,
    my_current_stake, determineHotKey, determineSlippage,
    determineTokenBuyAmount, constructBuy, constructSell,
    do_available_trades
)

BittensorUtility.determine_buy_at_for_amount = determine_buy_at_for_amount
BittensorUtility.determine_sell_at_for_amount = determine_sell_at_for_amount
BittensorUtility.get_subnet_buy_threshold = get_subnet_buy_threshold
BittensorUtility.get_subnet_sell_threshold = get_subnet_sell_threshold
BittensorUtility.my_current_stake = my_current_stake
BittensorUtility.determineHotKey = determineHotKey
BittensorUtility.determineSlippage = determineSlippage
BittensorUtility.determineTokenBuyAmount = determineTokenBuyAmount
BittensorUtility.constructBuy = constructBuy
BittensorUtility.constructSell = constructSell
BittensorUtility.do_available_trades = do_available_trades