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
from decimal import Decimal, getcontext
getcontext().prec = 16 #Precision for price stuff

from rich.console import Console
console = Console()

import ast
from pathlib import Path
import sys
from types import SimpleNamespace

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

def load_safe_python_settings():
    settings = {}

    # Determine where to look for the files (works in dev and when frozen with PyInstaller/Nuitka)
    exe_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(".")

    default_path = exe_dir / "bagbot_settings.py"
    overrides_path = exe_dir / "bagbot_settings_overrides.py"

    for path in [default_path, overrides_path]:
        is_default = (path == default_path)

        if not path.exists():
            if is_default:
                raise FileNotFoundError(f"CRITICAL: {path} is missing! Cannot continue.")
            else:
                print(f"Info: Optional overrides file not found (this is fine): {path}")
                continue  # overrides are optional

        source = path.read_text(encoding="utf-8")

        try:
            tree = ast.parse(source)  # mode='exec' by default → accepts real Python files
        except SyntaxError as e:
            raise SyntaxError(f"Invalid Python syntax in {path.name}: {e}") from e

        for node in tree.body:
            # Simple assignment: VAR = value
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and target.id.isidentifier():
                    name = target.id
                    try:
                        value = ast.literal_eval(node.value)
                        settings[name] = value
                    except (ValueError, SyntaxError):
                        print(f"Warning: Skipping unsafe or invalid value for '{name}' in {path.name}")

            # Allow top-level comments / docstrings / pass etc. → just ignore them
            # (optional) you can also support AnnAssign (typed vars) if you want:
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name = node.target.id
                if node.value:  # only if there's actually a value
                    try:
                        value = ast.literal_eval(node.value)
                        settings[name] = value
                    except (ValueError, SyntaxError):
                        print(f"Warning: Skipping unsafe annotated assignment '{name}' in {path.name}")

    return SimpleNamespace(**settings)

bagbot_settings = load_safe_python_settings()

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
    while attempts < 20:
        try:
            return await get_async_subtensor(*args, **kwargs)
        except (websockets.exceptions.InvalidStatus, AttributeError, asyncio.exceptions.TimeoutError) as e:
            logger.error(f'Invalid status err {str(e)}, retrying')
            attempts += 1
            if attempts >= 19:
                raise
            await asyncio.sleep(attempts*2)

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


    async def setupWallet(self):
        wallet_pw = bagbot_settings.WALLET_PW

        self.wallet = bt.Wallet(name=bagbot_settings.WALLET_NAME)
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
            if not self.subnet_grids[subnet_id].get('buy_upper'):
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
        raise Exception("Too many attempts to refresh stats")


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
        await self.refresh_subnet_grid()  # Load subnet settings before first tick

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
                    user_input = await loop.run_in_executor(None, input, "Should the bot proceed? (Y/N): ")
                    if user_input.lower() != 'y':
                        print('Exiting...')
                        return

                logger.info(f'Tick {self.tick}: Checking trades')
                for subnet_netuid in bagbot_settings.SUBNET_SETTINGS:
                    await self.do_available_trades(subnet_netuid)

                logging.info(f'Finished tick {self.tick} in {time.time() - start:.2f} seconds')
                #return
                try:
                    logger.info(f'Tick {self.tick}: Waiting for next block')
                    await asyncio.wait_for(self.sub.wait_for_block(), timeout=30.0)
                except asyncio.TimeoutError:
                    logger.warning(f'Tick {self.tick}: wait_for_block timed out after 30s, reconnecting...')
                    await self.sub.close()
                    self.sub = await my_async_subtensor("finney")
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
            except (websockets.exceptions.InvalidStatus, async_substrate_interface.errors.SubstrateRequestException, websockets.exceptions.ConnectionClosedError) as e:
                logger.info(f'potential server error: {e}, reconnecting...')
                try:
                    await self.sub.close()
                except:
                    pass
                self.sub = await my_async_subtensor("finney")
            except asyncio.exceptions.TimeoutError:
                logger.warning(f'Timeout error in tick {self.tick}, reconnecting subtensor...')
                try:
                    await self.sub.close()
                except:
                    pass
                self.sub = await my_async_subtensor("finney")
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
        max_alpha = subnet_settings['max_alpha']

        # Get power curve setting (default to global setting)
        buy_zone_power = subnet_settings.get('buy_zone_power', bagbot_settings.BUY_ZONE_POWER)

        # Calculate position in the range (0 to 1)
        progress = min(alpha_amount / max_alpha, 1.0)

        # Apply power curve
        curve_value = progress ** buy_zone_power

        # Interpolate between buy_upper and buy_lower using the curve
        buy_at = buy_upper - (buy_upper - buy_lower) * curve_value

        return buy_at

    def determine_sell_at_for_amount(self, subnet_settings, alpha_amount):
        if 'sell_lower' not in subnet_settings:
            return None
        sell_lower = subnet_settings['sell_lower']
        if 'sell_upper' not in subnet_settings or alpha_amount == 0:
            return sell_lower
        sell_upper = subnet_settings['sell_upper']
        max_alpha = subnet_settings['max_alpha']

        # Get power curve setting (default to global setting)
        sell_zone_power = subnet_settings.get('sell_zone_power', bagbot_settings.SELL_ZONE_POWER)

        # Calculate position in the range (0 to 1)
        progress = min(alpha_amount / max_alpha, 1.0)

        # Apply power curve
        curve_value = progress ** sell_zone_power

        # Interpolate between sell_upper and sell_lower using the curve
        sell_at = sell_upper - (sell_upper - sell_lower) * curve_value

        return max(sell_lower, sell_at)



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
        # Prioritize the configured validator for this subnet
        configured_validator = self.get_subnet_setting(subnet_netuid, 'stake_on_validator', bagbot_settings.STAKE_ON_VALIDATOR)

        # First check if configured validator has stake
        if configured_validator in self.current_stake_info:
            stake_obj = self.current_stake_info[configured_validator].get(subnet_netuid)
            stake = (float(stake_obj.stake) if stake_obj is not None else 0.0)
            if stake > 0:
                return configured_validator

        # If configured validator has no stake, don't sell from other validators
        # (This prevents accidentally selling stake from validators the user doesn't want to trade on)
        logger.warning(f'Configured validator {configured_validator} has no stake for subnet {subnet_netuid}, cannot sell')
        return None


    def determineSlippage(self, token_amount, token_in_pool):
        slippage = (Decimal(token_amount)/(Decimal(token_in_pool)+Decimal(token_amount))) * Decimal('100.0')
        return slippage


    def determineTokenBuyAmount(self, max_token_per_buy, token_in_pool, max_slippage_percent):
        max_amount_with_max_slippage = (token_in_pool*(max_slippage_percent/100.0)) / (1 - (max_slippage_percent/100.0))
        return min(max_token_per_buy, max_amount_with_max_slippage)



    def constructBuy(self, subnet_netuid):
        current_stake_amt = self.my_current_stake(subnet_netuid)
        buy_threshold = self.get_subnet_buy_threshold(subnet_netuid)

        # Get subnet-specific settings or fall back to global defaults
        max_tao_per_buy = self.get_subnet_setting(subnet_netuid, 'max_tao_per_buy', bagbot_settings.MAX_TAO_PER_BUY)
        max_slippage = self.get_subnet_setting(subnet_netuid, 'max_slippage_percent_per_buy', bagbot_settings.MAX_SLIPPAGE_PERCENT_PER_BUY)
        hotkey = self.get_subnet_setting(subnet_netuid, 'stake_on_validator', bagbot_settings.STAKE_ON_VALIDATOR)

        if self.balance > max_tao_per_buy:

            if subnet_netuid in self.stats and self.stats[subnet_netuid]['price'] < buy_threshold and current_stake_amt < self.subnet_grids[subnet_netuid]['max_alpha']:
                logger.info(f'''Want to buy sn{subnet_netuid} at price {self.stats[subnet_netuid]['price']} because it's lower than my threshold: {buy_threshold}, currently have {current_stake_amt} alpha in it''')

                tao_amount = self.determineTokenBuyAmount(max_tao_per_buy, self.stats[subnet_netuid]['tao_in'], max_slippage)
                slippage = self.determineSlippage(tao_amount, self.stats[subnet_netuid]['tao_in'])
                if Decimal(slippage) > Decimal(max_slippage):
                    raise Exception(f'Stopping before purchasing too much slippage: {Decimal(slippage)}, max slippage per buy/sell: {Decimal(max_slippage)}.  \nTO FIX: increase the max_tao_per_buy variable or increase max_slippage_percent_per_buy')
                tao_amount = bt.utils.balance.tao(tao_amount)
                trade = {
                    'hotkey':hotkey,
                    'netuid':subnet_netuid,
                    'tao_amount':tao_amount,
                    'buy_threshold':buy_threshold,
                    'calculated_slippage':slippage,
                    'max_slippage':max_slippage / 100.0
                }
                logger.info(f"About to stake {tao_amount} to {subnet_netuid} with expected slippage of {slippage:.4f}%")
                return trade
        else:
            logger.info(f'Not enough balance to stake: {self.balance:.2f}')
        return None

    def constructSell(self, subnet_netuid):
        current_stake_amt = self.my_current_stake(subnet_netuid)
        sell_threshold = self.get_subnet_sell_threshold(subnet_netuid)

        # Get subnet-specific settings or fall back to global defaults
        max_tao_per_sell = self.get_subnet_setting(subnet_netuid, 'max_tao_per_sell', bagbot_settings.MAX_TAO_PER_SELL)
        max_slippage = self.get_subnet_setting(subnet_netuid, 'max_slippage_percent_per_buy', bagbot_settings.MAX_SLIPPAGE_PERCENT_PER_BUY)

        if subnet_netuid in self.stats and \
            self.stats[subnet_netuid]['price'] > sell_threshold and \
            self.my_current_stake(subnet_netuid) > 0:

            unstake_target = max_tao_per_sell / self.stats[subnet_netuid]['price']
            my_current_alpha = float(self.my_current_stake(subnet_netuid))
            max_alpha_possible_to_sell = min(my_current_alpha, unstake_target)
            alpha_to_sell = self.determineTokenBuyAmount(max_alpha_possible_to_sell, self.stats[subnet_netuid]['alpha_in'], max_slippage)
            alpha_amount = bt.utils.balance.tao(alpha_to_sell, subnet_netuid)

            hotkey = self.determineHotKey(alpha_to_sell, subnet_netuid)
            approx_tao = float(Decimal(self.stats[subnet_netuid]['price']) * Decimal(alpha_to_sell))

            if approx_tao > max_tao_per_sell:
                raise Exception(f'Stopping before selling too much. approx_tao: {approx_tao}, max tao per sell: {max_tao_per_sell}, price x alpha: {self.stats[subnet_netuid]["price"]} x {alpha_to_sell} \nTO FIX: increase the max_tao_per_sell variable or increase max_slippage_percent_per_buy')

            slippage = self.determineSlippage(alpha_to_sell, self.stats[subnet_netuid]['alpha_in'])
            if Decimal(slippage) > Decimal(max_slippage):
                raise Exception(f'Stopping before selling too much, slippage: {Decimal(slippage)}, max slippage per buy/sell: {Decimal(max_slippage)}  \nTO FIX: increase the max_tao_per_sell variable or increase max_slippage_percent_per_buy')

            logger.info(f"About to unstake {alpha_to_sell} alpha (~{approx_tao} TAO) in sn{subnet_netuid} on hotkey {hotkey} with expected slippage of {slippage:.4f}%")

            trade = {
                'hotkey':hotkey,
                'netuid':subnet_netuid,
                'alpha_amount':alpha_amount,
                'max_slippage':max_slippage / 100.0,
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
                logger.info(f"Attempting to stake {float(buyTrade['tao_amount'])} TAO to subnet {buyTrade['netuid']}")
                stake_result = await asyncio.wait_for(
                    self.sub.add_stake(
                        wallet=self.wallet,
                        hotkey_ss58=buyTrade['hotkey'],
                        netuid=buyTrade['netuid'],
                        amount=buyTrade['tao_amount'],
                        rate_tolerance=buyTrade['max_slippage'],
                        wait_for_inclusion=False,
                        wait_for_finalization=False,
                        safe_staking=True,
                        allow_partial_stake=False
                    ),
                    timeout=45.0
                )
                print(f'after buy {str(buyTrade)}')
                if stake_result is True:
                    logger.info(f"Staked {float(buyTrade['tao_amount'])} TAO to subnet {buyTrade['netuid']} ({str(stake_result)})")
                else:
                    logger.info(f"Failed to stake {float(buyTrade['tao_amount'])} TAO to subnet {buyTrade['netuid']} ({str(stake_result)})")
            except asyncio.TimeoutError:
                logger.error(f"Timeout staking on subnet {buyTrade['netuid']} after 45s")
            except Exception as e:
                print(f'ERROR staking')
                logger.error(traceback.format_exc())
                logger.error(f"Failed to stake on subnet {buyTrade['netuid']}: {e}")

        sellTrade = self.constructSell(subnet_netuid)
        if sellTrade:
            try:
                logger.info(f"Attempting to unstake {float(sellTrade['alpha_amount'])} alpha from subnet {sellTrade['netuid']}")
                unstake_result = await asyncio.wait_for(
                    self.sub.unstake(
                        wallet=self.wallet,
                        hotkey_ss58=sellTrade['hotkey'] ,
                        netuid=sellTrade['netuid'],
                        amount=sellTrade['alpha_amount'],
                        rate_tolerance=sellTrade['max_slippage'],
                        wait_for_inclusion=True,
                        wait_for_finalization=False,
                        safe_unstaking=True,
                        allow_partial_stake=False
                    ),
                    timeout=60.0
                )
                print(f'after sell {str(sellTrade)}')
                if unstake_result is True:
                    logger.info(f"Unstaked {float(sellTrade['alpha_amount'])} stake units from sn{sellTrade['netuid']} (approx. {sellTrade['approx_tao']:.4f} TAO value) at price: {self.stats[subnet_netuid]['price']}.  my threshold = {sellTrade['sell_threshold']}")
                else:
                    logger.info(f"Failed to unstake {str(sellTrade)}  sn{subnet_netuid} ({str(unstake_result)})")
            except asyncio.TimeoutError:
                msg = f"Timeout unstaking from subnet {subnet_netuid} after 60s"
                print(msg)
                logger.error(msg)
                self.sub = await my_async_subtensor("finney")
            except (asyncio.exceptions.CancelledError, asyncio.exceptions.InvalidStateError) as e:
                print(f'ERROR unstaking - {e}... continuing')
                logger.error(traceback.format_exc())
                logger.error(f"Failed to unstake from subnet {subnet_netuid}: {e}")
                self.sub = await my_async_subtensor("finney")
            except Exception as e:
                print(f'ERROR unstaking')
                logger.error(traceback.format_exc())
                logger.error(f"Failed to unstake from subnet {subnet_netuid}: {e}")
                raise


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
