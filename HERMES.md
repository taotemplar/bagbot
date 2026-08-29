# HERMES.md — Bagbot Active Development Summary

Status: working tree on `main`, uncommitted edits ready for the `dev` branch push.
Full migration details: `MIGRATION_STATUS.md`.

## 1. Bittensor v11 Migration (v10 → v11.x)

- Rewrote `src/blockchain.py` + `src/trade.py` for bittensor **11.1.0**.
- Key API swaps:
  - `get_async_subtensor()` → `bt.Client(network)` + `await client.connect()`
  - `sub.all_subnets()` → `bt_runtime_apis.SubnetInfoRuntimeApi.get_all_dynamic_info` (raw dicts, parsed to the old stats shape)
  - `float(Balance)` removed in v11 → use `.stake.amount` (unit-agnostic) in `my_current_stake`/`determineHotKey`
  - `Balance.set_unit()` → `bt.Balance.from_alpha(x, netuid)`
  - `sub.add_stake()` / `sub.unstake()` → `bt.AddStake` / `bt.RemoveStake` intents via `sub.execute(intent, wallet)`; old wait_for_inclusion/finalization semantics preserved via execute kwargs
  - `create_if_non_existent()` → guard `coldkey_file.exists_on_device()` + `create_new_coldkey()`
  - `get_stake_info_for_coldkey()` → `staking.positions(coldkey_ss58=)`, filtered by hotkey
  - `get_balance()` → `balances.get(address=)`, read `.tao`
- `requirements.txt`: removed superseded `bittensor-cli` + `bittensor-wallet` (single `bittensor` package).
- Full-run smoke passed: 9+ consecutive clean ticks (`python3 bagbot.py --nocheck`, empty wallet). Real trading gated on funding the wallet + one live buy/sell.

## 2. alpha_keep feature

- **Purpose:** hold a floor of alpha per subnet that the bot will never sell, no matter the price.
- Now **per-subnet overridable** via `SUBNET_SETTINGS['alpha_keep']` (e.g. sn20 = 25), with global default hardcoded to 0 (was global `ALPHA_KEEP`, removed from settings).
- `constructSell` (trade.py:161-169): `alpha_keep = get_subnet_setting(netuid, 'alpha_keep', 0)`; caps `max_alpha_possible_to_sell = min(current_alpha - alpha_keep, unstake_target)`. Sells below floor return `None` with a logged "not enough alpha" guard.
- New tests: `testSellBelowAlphaKeep` — selling would bring stake below `alpha_keep` → returns `None`.

## 3. Color themes

- `src/theme.py`: added `_settings_theme_override()` — theme can now be set from `bagbot_settings.py` via `THEME` + `THEME_SETTINGS`; when present, they override the `THEME = "default"` variable in theme.py. Custom `THEME_SETTINGS` dict merges over the named base theme.
- `bagbot_settings.py`: added commented-out `THEME` / `THEME_SETTINGS` block (default theme settings) so users can uncomment + customize without editing theme.py.
- `settings_loader.py`: wallet credentials now fall back to `WALLET_PW`/`WALLET_NAME` in settings (or overrides file) when missing from `.env`; `.env` always wins.

## 4. Unit test performance

- **18 tests, 18/18 pass, 0.001s** (pure-python paths: grid validation, buy/sell construction, slippage, threshold curves, alpha_keep, min-wallet guard).
- Run: `source .bagbotvirtualenv/bin/activate && WALLET_PW=x WALLET_NAME=y python3 -m unittest test_bagbot.py`
- Post-migration the suite was broken (5 errors from `float(Balance)`) → all fixed.

## 5. New / updated unit tests (this work)

- `testSellBelowAlphaKeep` — alpha_keep floor blocks sell
- `testBuyBelowMinTaoInWallet` — buy blocked below MIN_TAO_IN_WALLET
- Updated existing fixtures for v11: `MockStake` wraps stake in `bt.Balance.from_tao(...)`; assertions use `.tao` / `.amount` / `.sell_threshold` (no `float(Balance)`)
- Power-curve tests (`testBuyPowerCurveLinear`/`Aggressive`/`Conservative`, `testSellPowerCurveLinear`) cover buy/sell zone curve behavior.

## Files changed (uncommitted)

`bagbot_settings.py`, `requirements.txt`, `src/blockchain.py`, `src/settings_loader.py`, `src/theme.py`, `src/trade.py`, `test_bagbot.py` (+ new `HERMES.md`, `MIGRATION_STATUS.md`)

---
Committed: `4be2919` ("unittests"). Pushed from this dev branch.