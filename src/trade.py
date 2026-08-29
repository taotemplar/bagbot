from decimal import Decimal
import logging
import asyncio
import traceback
import bittensor as bt

from settings_loader import bagbot_settings
rao_to_tao = lambda rao : int(rao)/1000000000.0

logger = logging.getLogger(__name__)


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
        # v11 Balance has no __float__; .amount is the unit-agnostic float.
        total_stake += (stake_obj.stake.amount if stake_obj is not None else 0.0)
    return total_stake


def determineHotKey(self, unstake_amt, subnet_netuid):
    # Prioritize the configured validator for this subnet
    configured_validator = self.get_subnet_setting(subnet_netuid, 'stake_on_validator', bagbot_settings.STAKE_ON_VALIDATOR)

    # First check if configured validator has stake
    if configured_validator in self.current_stake_info:
        stake_obj = self.current_stake_info[configured_validator].get(subnet_netuid)
        # v11 Balance has no __float__; .amount is the unit-agnostic float.
        stake = (stake_obj.stake.amount if stake_obj is not None else 0.0)
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
    min_tao_in_wallet = bagbot_settings.MIN_TAO_IN_WALLET

    # Get subnet-specific settings or fall back to global defaults
    max_tao_per_buy = self.get_subnet_setting(subnet_netuid, 'max_tao_per_buy', bagbot_settings.MAX_TAO_PER_BUY)
    max_slippage = self.get_subnet_setting(subnet_netuid, 'max_slippage_percent_per_buy', bagbot_settings.MAX_SLIPPAGE_PERCENT_PER_BUY)
    hotkey = self.get_subnet_setting(subnet_netuid, 'stake_on_validator', bagbot_settings.STAKE_ON_VALIDATOR)


    if self.balance > max_tao_per_buy:

        if subnet_netuid in self.stats and self.stats[subnet_netuid]['price'] < buy_threshold and current_stake_amt < self.subnet_grids[subnet_netuid]['max_alpha']:
            logger.info(f'''Want to buy sn{subnet_netuid} at price {self.stats[subnet_netuid]['price']} because it's lower than my threshold: {buy_threshold}, currently have {current_stake_amt} alpha in it''')

            tao_amount = self.determineTokenBuyAmount(max_tao_per_buy, self.stats[subnet_netuid]['tao_in'], max_slippage)
            slippage = self.determineSlippage(tao_amount, self.stats[subnet_netuid]['tao_in'])
            if min_tao_in_wallet >= (self.balance - max_tao_per_buy):
                print(f'Balance: {self.balance:.4f}. Too little TAO in wallet - skipping buy on sn{subnet_netuid}')
                return None
            if Decimal(slippage) > Decimal(max_slippage):
                raise Exception(f'Stopping before purchasing too much slippage: {Decimal(slippage)}, max slippage per buy/sell: {Decimal(max_slippage)}.  \nTO FIX: increase the max_tao_per_buy variable or increase max_slippage_percent_per_buy')
            tao_amount = bt.Balance.from_tao(tao_amount)
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
        alpha_keep = self.get_subnet_setting(subnet_netuid, 'alpha_keep', 0)

        if subnet_netuid in self.stats and \
            self.stats[subnet_netuid]['price'] > sell_threshold and \
            self.my_current_stake(subnet_netuid) > 0:

            unstake_target = max_tao_per_sell / self.stats[subnet_netuid]['price']
            my_current_alpha = float(self.my_current_stake(subnet_netuid))
            max_alpha_possible_to_sell = min(my_current_alpha - alpha_keep, unstake_target)
            alpha_to_sell = self.determineTokenBuyAmount(max_alpha_possible_to_sell, self.stats[subnet_netuid]['alpha_in'], max_slippage)
            if max_alpha_possible_to_sell <= 0.1:
                logger.info(f"Failed to sell, not enough alpha | sn{subnet_netuid} | alpha in bag:{float(my_current_alpha)} | alpha keep amount: {float(alpha_keep)}")
                print(f"Failed to sell, not enough alpha | sn{subnet_netuid} | alpha in bag: {float(my_current_alpha)} | alpha keep amount: {float(alpha_keep)}")
                return None
			# v11 removed Balance.set_unit(); from_alpha() is the direct replacement.
            alpha_amount = bt.Balance.from_alpha(alpha_to_sell, subnet_netuid)

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
            logger.info(f"Attempting to stake {buyTrade['tao_amount']} TAO to subnet {buyTrade['netuid']}")
            # v11: add_stake() is gone; submit an AddStake intent through the
            # plan/execute pipeline. wait_for_inclusion=False matches the old
            # fire-and-forget buy semantics (accepted as an execute() kwarg).
            stake_result = await asyncio.wait_for(
                self.sub.execute(
                    bt.AddStake(
                        hotkey_ss58=buyTrade['hotkey'],
                        netuid=buyTrade['netuid'],
                        amount_tao=buyTrade['tao_amount'],
                        slippage_protection=True,
                        rate_tolerance=buyTrade['max_slippage']
                    ),
                    self.wallet,
                    wait_for_inclusion=False,
                    wait_for_finalization=False
                ),
                timeout=45.0
            )
            print(f'after buy {str(buyTrade)}')
            #print(f'after buy {str(buyTrade)}: {str(stake_result)}')
            if stake_result is True or stake_result.__dict__.get('success') is True:
                logger.info(f"Staked {buyTrade['tao_amount']} TAO to subnet {buyTrade['netuid']} ({str(stake_result)})")
            else:
                logger.info(f"Failed to stake {buyTrade['tao_amount']} TAO to subnet {buyTrade['netuid']} ({str(stake_result)})")
        except asyncio.TimeoutError:
            logger.error(f"Timeout staking on subnet {buyTrade['netuid']} after 45s")
        except Exception as e:
            print(f'ERROR staking')
            logger.error(traceback.format_exc())
            logger.error(f"Failed to stake on subnet {buyTrade['netuid']}: {e}")

    sellTrade = self.constructSell(subnet_netuid)
    if sellTrade:
        try:
            logger.info(f"Attempting to unstake {sellTrade['alpha_amount']} alpha from subnet {sellTrade['netuid']}")
            # v11: unstake() is gone; submit a RemoveStake intent. The old call
            # waited for inclusion (not finalization) on sells — preserved here.
            unstake_result = await asyncio.wait_for(
                self.sub.execute(
                    bt.RemoveStake(
                        hotkey_ss58=sellTrade['hotkey'],
                        netuid=sellTrade['netuid'],
                        amount_alpha=sellTrade['alpha_amount'],
                        slippage_protection=True,
                        rate_tolerance=sellTrade['max_slippage']
                    ),
                    self.wallet,
                    wait_for_inclusion=True,
                    wait_for_finalization=False
                ),
                timeout=60.0
            )
            print(f'after sell {str(sellTrade)}')
            if unstake_result is True or getattr(unstake_result, 'success', False) is True:
                logger.info(f"Unstaked {sellTrade['alpha_amount']} stake units from sn{sellTrade['netuid']} (approx. {sellTrade['approx_tao']:.4f} TAO value) at price: {self.stats[subnet_netuid]['price']}.  my threshold = {sellTrade['sell_threshold']}")
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
