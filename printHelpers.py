from typing import List, Dict, Tuple
import time
from rich.table import Table
from rich.panel import Panel
from rich import box
import bagbot_settings

def price_proximity_bar(buyprice, sellprice, currentprice, bar_width=20):
    """
    Generate an ASCII bar showing how close currentprice is to buyprice or sellprice,
    with the bar scaled to always include all three prices.

    Args:
        buyprice (float): The buy limit order price.
        sellprice (float): The sell limit order price.
        currentprice (float): The current market price.
        bar_width (int): The width of the ASCII bar in characters (default 20).

    Returns:
        None: Prints an ASCII bar and price info to the console.
    """
    # Determine the range to include all prices
    min_price = min(buyprice, sellprice, currentprice)
    max_price = max(buyprice, sellprice, currentprice)

    # Add padding (10% of the range or 0.1 minimum) for readability
    price_range = max_price - min_price
    padding = price_range * 0.1 if price_range > 0 else 0.1
    bar_min = min_price - padding
    bar_max = max_price + padding

    # Initialize the bar
    bar = ['-'] * bar_width

    # Calculate positions for buy, sell, and current prices
    def price_to_position(price):
        pos = int(((price - bar_min) / (bar_max - bar_min)) * bar_width)
        return max(0, min(pos, bar_width - 1))  # Clamp to valid range

    buy_pos = price_to_position(buyprice)
    sell_pos = price_to_position(sellprice)
    current_pos = price_to_position(currentprice)

    # Place markers, handling overlaps
    bar[current_pos] = '|'  # Current price marker
    if buy_pos == current_pos:
        bar[buy_pos] = 'X'  # Overlap of current and buy
    else:
        bar[buy_pos] = 'B'
    if sell_pos == current_pos:
        bar[sell_pos] = 'X'  # Overlap of current and sell
    elif sell_pos == buy_pos:
        bar[sell_pos] = 'Y'  # Overlap of buy and sell (rare, but possible if equal)
    else:
        bar[sell_pos] = 'S'

    # Convert bar to string
    bar_str = ''.join(bar)

    # Calculate proximity to closest limit order
    dist_to_buy = abs(currentprice - buyprice)
    dist_to_sell = abs(currentprice - sellprice)
    closest_dist = min(dist_to_buy, dist_to_sell)
    closest_price = buyprice if dist_to_buy < dist_to_sell else sellprice
    percentage = (closest_dist / max(abs(max_price - min_price), 0.01)) * 100

    return bar_str

def print_table_rich(
    botInstance,
    console,
    stake_info: Dict,
    allowed_subnets: List[int],
    stats: Dict[int, Dict],
    balance: float,
    subnet_grids: Dict[int, Dict]
):
    """
    Print a Rich table
    """

    timestamp = int(time.time())
    total_stake_value = 0.0

    table = Table(title="Staking Allocations", header_style="bold white on dark_blue", box=box.SIMPLE_HEAVY)
    table.add_column("Subnet", justify="right", style="bright_cyan")
    table.add_column("Name", justify="left", style="white")
    table.add_column("Alpha", justify="right", style="magenta")
    table.add_column("Max Alpha", justify="right", style="magenta")
    table.add_column("% Filled", justify="right", style="magenta")
    table.add_column("TAO Value", justify="right", style="yellow")
    table.add_column("Buy Lower", justify="right", style="grey66")
    table.add_column("Curr Buy", justify="right", style="bright_green")
    table.add_column("Buy Upper", justify="right", style="grey66")
    table.add_column("Price", justify="right", style="bright_cyan")
    table.add_column("Sell Lower", justify="right", style="grey66")
    table.add_column("Curr Sell", justify="right", style="bright_red")
    table.add_column("Sell Upper", justify="right", style="grey66")
    table.add_column("Price Proximity", justify="right", style="white")

    for netuid in stake_info[bagbot_settings.STAKE_ON_VALIDATOR]:
        stake_amt = botInstance.my_current_stake(netuid)

        if netuid in stats:
            price = float(stats[netuid]["price"])
            name = stats[netuid].get("name", "")
        else:
            price = 0.0
            name = ""

        # Get previous average delta; if none, use the current delta.

        buy_threshold = botInstance.get_subnet_buy_threshold(netuid)
        sell_threshold = botInstance.get_subnet_sell_threshold(netuid)

        if stake_amt == 0 and buy_threshold is None:
            continue


        stake_value = stake_amt * price
        total_stake_value += stake_value
        prox_bar = ''
        try:
            if buy_threshold is not None and sell_threshold is not None:
                prox_bar = price_proximity_bar(buy_threshold, sell_threshold, price)
            elif buy_threshold and sell_threshold is None:
                prox_bar = price_proximity_bar(buy_threshold, 1, price)
            elif buy_threshold is None and sell_threshold:
                prox_bar = price_proximity_bar(0, sell_threshold, price)
        except:
            print(traceback.format_exc())
            print(f'Trouble with the proximity bar, skipping for {netuid}')

        probably_buying = False
        if buy_threshold and buy_threshold > price:
            probably_buying = True

        probably_selling = False
        if sell_threshold and sell_threshold < price:
            probably_selling = True


        buy_threshold = f"{buy_threshold:.6f}" if buy_threshold else ''
        sell_threshold = f"{sell_threshold:.6f}" if sell_threshold else ''
        high_buy = botInstance.determine_buy_at_for_amount(botInstance.subnet_grids.get(netuid,{}), 0) or ''
        high_buy = f"{high_buy:.4f}" if high_buy else ''

        low_buy = None
        if botInstance.subnet_grids.get(netuid,{}).get('buy_upper'):
            low_buy = botInstance.determine_buy_at_for_amount(botInstance.subnet_grids.get(netuid,{}), botInstance.subnet_grids.get(netuid,{}).get('max_alpha'))
        low_buy = f"{low_buy:.4f}" if low_buy else ''

        high_sell = bagbot_settings.SUBNET_SETTINGS.get(netuid,{}).get('sell_upper') or bagbot_settings.SUBNET_SETTINGS.get(netuid,{}).get('sell_lower') or ''
        high_sell = f"{high_sell:.4f}" if high_sell else ''
        low_sell = None
        if botInstance.subnet_grids.get(netuid,{}).get('sell_lower'):
            low_sell = botInstance.determine_sell_at_for_amount(botInstance.subnet_grids.get(netuid,{}), botInstance.subnet_grids.get(netuid,{}).get('max_alpha'))
        low_sell = f"{low_sell:.4f}" if low_sell else ''

        max_stake_amt = botInstance.subnet_grids.get(netuid,{}).get('max_alpha',0)
        stake_amount_str = f"{stake_amt:.0f}"
        max_stake_str = f"{max_stake_amt:.0f}" if max_stake_amt > 0 else ''
        stake_perc_filled = str(int(stake_amt*100.0/max_stake_amt)) + '%' if max_stake_amt > 0 else ''
        table.add_row(
            str(netuid),
            name,
            f"{stake_amount_str}",
            f"{max_stake_str}",
            f"{stake_perc_filled}",
            f"{stake_value:.2f}",
            f"{low_buy}",
            f"{buy_threshold}",
            f"{high_buy}",
            f"{price:.5f}{'b' if probably_buying else ''}{'s' if probably_selling else ''}",
            f"{low_sell}",
            f"{sell_threshold}",
            f"{high_sell}",
            f"{prox_bar}"
        )

    summary = (
        f"[bold cyan]Balance:[/bold cyan] {balance:.4f} TAO    "
        f"[bold cyan]Stake Value:[/bold cyan] {total_stake_value:.4f} TAO"
    )
    console.print(Panel(summary, style="bold white"))
    console.print(table)


