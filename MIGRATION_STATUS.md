# bagbot — Bittensor v11 Migration Status (agent handoff notes)

> Written 2026-08-28 by the Hermes session that started this migration.
> **Status: MIGRATION COMPLETE through full-run smoke (2026-08-28).
> `src/blockchain.py`, `src/trade.py`, `requirements.txt`, `test_bagbot.py` all
> fixed. Unit tests 18/18, import smoke OK, plan() dry-run OK, and a live
> full-run smoke of `python3 bagbot.py --nocheck` with a real (empty) wallet
> ran 9+ consecutive ticks clean: wallet unlock, finney reads, positions,
> balance, table, trade checks, wait_for_block — no exceptions. Remaining
> before real trading: fund the wallet, then observe a first real buy/sell
> cycle. `bagbot_settings.py` still contains a placeholder validator hotkey
> `5SomeOtherValidatorHotkeyHere` — user should replace via overrides file.**
> Everything below marked **verified** was checked against the *actually
> installed* library and/or **live against finney**, not guessed.

## Goal

Make bagbot run again on bittensor **11.x** (`11.1.0` is installed) so that
`python3 bagbot.py` and `./runBagbot.sh {start|stop|show}` work on Linux & macOS.
Bittensor 11 removed the old `Subtensor` class (~165 methods) and replaced it
with a small `bt.Client` (typed reads) plus a catalog of **intents** executed
through one `plan`/`execute` pipeline. The bot's v10 calls no longer exist.

## Hard constraints (from the user)

- **Do NOT modify functionality.** No new features, no removed features.
- Where v11 has no direct equivalent, write small helper functions that fulfill
  the same purpose (e.g. `create_if_non_existent` is gone from `Wallet`).
- Keep the existing code formatting and naming style (snake_case methods bound
  to `BittensorUtility` at the bottom of `blockchain.py`, single-quote logs,
  same stats-dict shapes).
- **Checkpoint workflow: fix ONE source file, smoke-test, STOP, ask the user
  before touching the next file.** (blockchain.py is that one file; the user
  has seen its smoke test and instructed the remaining work be done elsewhere.)
- Keep a changelog of every modified part: file, row nb, issue, fix, explainer.
- Deliverable bot must run unchanged via `python3 bagbot.py` and `runBagbot.sh`.

## Environment

- Project: `/Users/agent/git/bagbot` (git repo, branch `main`). All changes so
  far are **uncommitted working-tree edits** — `git diff` shows them.
- venv: `.bagbotvirtualenv/` (Python 3.14) — activate with
  `source .bagbotvirtualenv/bin/activate`.
- Installed: **bittensor 11.1.0** (includes btcli + wallet), rich, websockets,
  python-dotenv, async_substrate_interface (still present, still importable).
- No `~/.bittensor/wallets` and no `.env` on this machine → wallet *creation*
  path can't be live-tested here; chain reads **can** (they're public).
- `src/settings_loader.py` hard-requires `WALLET_PW` and `WALLET_NAME` env vars
  (from `.env` in the project dir) at import time. For tests without a real
  `.env`, run with `WALLET_PW=x WALLET_NAME=y python3 ...`.
- Unit tests: `python3 -m unittest test_bagbot.py` (pure-python paths:
  grid validation, buy/sell construction, slippage). **Not yet re-run** after
  the blockchain.py edits.

## Source files and what they touch

| File | Bittensor usage | State |
|---|---|---|
| `bagbot.py` | none (entry point only) | no changes needed |
| `src/blockchain.py` | connection, wallet setup, subnet/stake/balance reads, `wait_for_block` | **FIXED — edits applied, partially live-tested** |
| `src/trade.py` | `add_stake`/`unstake` execution, `bt.Balance` construction | **NOT FIXED — next** |
| `src/printHelpers.py` | only reads stake floats via `botInstance.my_current_stake` | indirect only |
| `src/settings_loader.py`, `src/theme.py` | no bittensor usage | no changes needed |
| `requirements.txt` | still lists `bittensor-cli` + `bittensor-wallet` (superseded) | **NOT FIXED** |
| `runBagbot.sh` | just runs python | no changes needed |
| `MIGRATION_STATUS.md` | this file | handoff notes |

## Deprecated API usage found (pre-fix locations)

All in `src/blockchain.py` unless noted:

| v10 call | was at | v11 replacement |
|---|---|---|
| `from bittensor.core.async_subtensor import get_async_subtensor` | line 10 | **module gone** → `bt.Client(network)` + `await client.connect()` |
| `self.wallet.create_if_non_existent()` | 185 | gone → `if not wallet.coldkey_file.exists_on_device(): wallet.create_new_coldkey(...)` |
| `self.sub.get_stake_info_for_coldkey(coldkey_ss58=)` | 112 | `self.sub.staking.positions(coldkey_ss58=)` → `list[StakePosition]` |
| `self.sub.all_subnets()` | 262 | runtime API `SubnetInfoRuntimeApi.get_all_dynamic_info` (bulk, same fields as old `all_subnets`) |
| `self.sub.get_stake_for_coldkey_and_hotkey(hotkey_ss58=, coldkey_ss58=)` | 311 | `self.sub.staking.positions(coldkey_ss58=)` filtered by `position.hotkey` → `{netuid: StakePosition}` (same shape the callers expect) |
| `self.sub.get_balance(address=)` | 342 | `self.sub.balances.get(address=)` → `Balance` |
| `self.sub.wait_for_block()` | 402 | still exists on `Client` (async, accepts `timeout=`) — **no change needed** |
| `bt.Balance.from_tao(x).set_unit(netuid)` (trade.py:174) | — | `bt.Balance.from_alpha(x, netuid)` |
| `sub.add_stake(wallet=, hotkey_ss58=, netuid=, amount=, rate_tolerance=, safe_staking=, allow_partial_stake=, wait_for_inclusion=, wait_for_finalization=)` (trade.py:209) | — | intent `bt.AddStake(hotkey_ss58=, netuid=, amount_tao=, slippage_protection=True, rate_tolerance=...)` via `await client.execute(intent, wallet)` |
| `sub.unstake(..., safe_unstaking=, allow_partial_stake=)` (trade.py:240) | — | intent `bt.RemoveStake(hotkey_ss58=, netuid=, amount_alpha=, slippage_protection=True, rate_tolerance=...)` |
| `float(stake_obj.stake)` / `float(Balance)` (trade.py:82,93,166; printHelpers via `my_current_stake`) | — | **`float(Balance)` removed in v11** — use `.stake.amount` (unit-agnostic) or `.stake.tao` / `.stake.alpha` explicitly |
| `trade.py` exception handlers call `my_async_subtensor()` which is only defined in blockchain.py (latent NameError under module layout; works because bagbot.py inserts `src/` on sys.path and both modules are imported flat) | trade.py:262,267 | no change strictly needed; if the other agent splits imports, import it from blockchain |
| `import async_substrate_interface` + `async_substrate_interface.errors.SubstrateRequestException` (blockchain.py:11,419,425) | — | still importable in this venv (verified) — **no change needed**; do not remove the handler |

## Verified v11 API surface (bittensor 11.1.0, tested live against finney)

```python
import bittensor as bt

# Connection
c = bt.Client("finney")            # finney is the default; also fallback_endpoints=, retry_forever=
await c.connect()                  # async; c.close() async
c.network, c.endpoint              # attributes exist

# Reads (all async)
c.prices.alpha_prices()                     # -> {netuid: float tao-per-alpha}   (tested live)
c.subnets.subnet_names()                    # -> {netuid: str}                   (tested live)
c.subnets.all()                             # -> list[SubnetInfo(netuid, tempo, burn, neuron_count)]  (no price/pools!)
c.staking.positions(coldkey_ss58)           # -> [StakePosition(hotkey, coldkey, netuid, stake: Balance, is_registered)]
c.staking.get(coldkey_ss58, hotkey_ss58, netuid)   # -> Balance (stake on one pair)
c.balances.get(address)                     # -> Balance (free TAO)              (tested live)
c.read("metagraph", netuid=n)               # -> dict incl. tao_in, alpha_in, name, price
c.block()                                   # -> int
c.wait_for_block(block=None, *, timeout=None)  # -> BlockHeader
c.query(item, params)                       # generic storage query; c.query_map(...) also exists
c.runtime(method, params)                   # raw runtime-API call

# Bulk subnet data — exact replacement for v10 all_subnets():
from bittensor._generated import runtime_apis as api
rows = await c.runtime(api.SubnetInfoRuntimeApi.get_all_dynamic_info, [])
# -> list of dicts, 129 entries live, keys include:
#    netuid, subnet_name (list of ints! decode with bytes(..).decode('utf-8')),
#    token_symbol (same), tao_in, alpha_in (rao ints), alpha_out, owner_coldkey, tempo, ...

# Transactions (intents; both also have *Limit variants with limit_price_rao/allow_partial)
bt.AddStake(hotkey_ss58, netuid, amount_tao, slippage_protection=True, rate_tolerance=0.05)
bt.RemoveStake(hotkey_ss58, netuid, amount_alpha, slippage_protection=True, rate_tolerance=0.05)
result = await c.execute(intent, wallet)    # -> ExtrinsicResult; c.plan(...) is the dry run
result.success                              # bool; ExtrinsicResult has __bool__, .message, .fee, .error

# Wallet
w = bt.Wallet(name=..., path=... default '~/.bittensor/wallets')
w.coldkey_file.exists_on_device()            # existence check (replaces create_if_non_existent)
w.create_new_coldkey(n_words=12, use_password=True, overwrite=False, suppress=False,
                     save_coldkey_to_env=False, coldkey_password=None)
w.coldkey_file.save_password_to_env(pw)      # still exists
w.unlock_coldkey()                           # -> Keypair
w.coldkey.ss58_address                       # still works

# Balance (unit-strict!)
bt.Balance.from_tao(x)                       # TAO-denominated
bt.Balance.from_alpha(x, netuid)             # alpha-denominated (replaces .set_unit)
b.tao     # .tao raises UnitMismatchError on alpha balances — use .alpha / .amount
b.amount  # unit-agnostic float — safe accessor for stake amounts
b.rao, b.decimal, b.unit, b.netuid
```

Live-test results (2026-08-28, finney): `alpha_prices` returned 129 entries
(sn1 ≈ 0.00761 τ/α), `get_all_dynamic_info` returned 129 rows with
`subnet_name` as int-lists, dummy-coldkey `positions` → `[]`, balance read →
τ8.101145378, `quote_stake(netuid=1, amount_tao=1.0)` → 131.32 α out.

## Semantic traps (behavior-changing, verified)

1. **`float(Balance)` no longer works.** Anywhere the old code did
   `float(stake_obj.stake)`, use `.stake.amount`. Alpha `.tao` raises
   `UnitMismatchError` (it's not TAO!). This affects trade.py
   `my_current_stake` (line 82) and `determineHotKey` (line 93) first.
2. **`get_all_dynamic_info` returns raw dicts**, not objects: `subnet_name` and
   `token_symbol` are int-lists (`bytes(x).decode('utf-8')`), amounts are rao
   ints. Compute `price = tao_in/alpha_in` yourself (rao ratio == tao ratio).
   **Already implemented in the fixed blockchain.py — see changelog.**
3. **`subnets.all()` is NOT the old `all_subnets()`** — it lacks price and pool
   reserves. Use the runtime API listed above.
4. `Swap.BalancerTaoReservoir` is *not* per-netuid (empty map query live). Pool
   reserves live in `SubtensorModule.SubnetAlphaIn` / per-subnet metagraph
   `tao_in`/`alpha_in` — or just use `get_all_dynamic_info` (chosen approach).
5. `execute`/`plan` are **coroutines**. The old flags
   `wait_for_inclusion=False, wait_for_finalization=False` (buys) and `True,
   False` (sells) have no 1:1 kwargs on `execute` — check `execute`'s accepted
   kwargs (`policy`/`proxy_for`/`proxy_type` per the docstring) and map
   carefully; do not silently drop the semantics.
6. Old `add_stake(..., safe_staking=True)` maps to
   `AddStake(slippage_protection=True, rate_tolerance=...)`; `allow_partial_stake=False`
   is default behavior of `AddStake` (the `*Limit` variants expose `allow_partial`).
7. Intent amount fields accept `int | float | str | Decimal | Balance`
   (unit carried by the field name: `amount_tao` vs `amount_alpha`). The trade
   dicts in trade.py already carry `bt.Balance` objects — they can likely pass
   through unchanged; `float(buyTrade['tao_amount'])` at trade.py:207,225 needs
   the `.tao`/`.amount` treatment.
8. Trade.py result checks `stake_result is True or stake_result.__dict__.get('success') is True`
   — v11 `ExtrinsicResult` is a dataclass (has `.success`, `.__bool__`) so the
   second clause works via attribute; simplify only if it stays behavior-identical.
9. Migration doc pin pitfalls: remove `bittensor-cli` and `bittensor-wallet`
   from requirements; anything pinning `bittensor<11` silently keeps v10.

## Changelog — edits ACTUALLY APPLIED to src/blockchain.py (uncommitted)

Line numbers are post-edit file positions. Git diff against HEAD `4be2919` shows all of them.

| line(s) | issue | fix | explainer |
|---|---|---|---|
| 10 | `from bittensor.core.async_subtensor import get_async_subtensor` — module gone in v11 | `from bittensor._generated import runtime_apis as bt_runtime_apis` | v11 ships runtime-API descriptors under `bittensor._generated`; needed for the bulk subnet read |
| 64-78 | `get_async_subtensor()` gone | `my_async_subtensor()` now does `client = bt.Client(*args, **kwargs); await client.connect(); return client` | same signature, same retry loop (20 attempts, linear backoff), same caught exception tuple; returns connected client every call site treats as `self.sub` |
| 111-113 | `self.sub.get_stake_info_for_coldkey(coldkey_ss58=...)` gone | `self.sub.staking.positions(coldkey_ss58=...)` | returns `list[StakePosition]`; the existing `hasattr(stake_info, 'hotkey_ss58')/hasattr(stake_info, 'hotkey')` extraction still matches because `StakePosition.hotkey` exists |
| 180-192 | `self.wallet.create_if_non_existent()` gone (v11 Wallet has no such method) | guard: `if not self.wallet.coldkey_file.exists_on_device(): self.wallet.create_new_coldkey(use_password=bool(wallet_pw), overwrite=False, suppress=True, coldkey_password=wallet_pw)` | recreates old behavior (create only if missing, keep password protection); `save_password_to_env` + `unlock_coldkey` still exist and were kept |
| 261-265 | `self.sub.all_subnets()` gone | `self.sub.runtime(bt_runtime_apis.SubnetInfoRuntimeApi.get_all_dynamic_info, [])` | verified live: one call returns all 129 subnets incl. `tao_in`, `alpha_in`, `subnet_name` — the exact fields the old v10 `SubnetInfo` carried |
| 293-315 | v10 `SubnetInfo` attribute access (`subnet.netuid`, `subnet.price`, `subnet.tao_in.tao`, `subnet.subnet_name`) gone | parse raw dicts: `netuid=int(subnet['netuid'])`, `price = tao_in_rao/alpha_in_rao` (rao ratio == tao ratio), `name = bytes(subnet['subnet_name']).decode('utf-8')`, amounts via existing `rao_to_tao()` | keeps the exact stats-dict shape `{"name","price","tao_in","alpha_in"}` that trade.py + printHelpers.py expect; also added `alpha_in_rao <= 0` skip so the price division can't ZeroDivision (old `price <= 0: continue` semantics preserved) |
| 317-334 | `self.sub.get_stake_for_coldkey_and_hotkey(...)` gone | one `self.sub.staking.positions(coldkey_ss58=...)` call, filtered: `{p.netuid: p for p in positions if p.hotkey == hotkey}` | preserves the return shape `{netuid: obj with .stake}` consumed by `refresh_stats` and printHelpers; comment added in code |
| 349-359 | `self.sub.get_balance(address=...)` gone | `self.sub.balances.get(address=...)` then `self.balance = float(balance_obj.tao)` | v11 `Balance` has no `__float__`; `.tao` on a TAO balance is the float amount |

### Smoke tests run after the fix (real finney connection)

| test | result |
|---|---|
| module import + settings load (`WALLET_PW=x WALLET_NAME=y`) | PASS |
| `my_async_subtensor("finney")` → connect | PASS (`c.network == 'finney'`) |
| `get_subnet_stats()` | PASS — 129 subnets, sn1 `{'name': 'Apex', 'price': 0.00746, 'tao_in': 24533.8, 'alpha_in': 3286766.4}` |
| `refresh_subnet_grid()` → `validateGrid()` | PASS |
| `get_stake_for_hotkey()` with stub wallet | **NOT RUN** — test harness was denied before executing; code path is the verified `positions()` read + dict comprehension, but the assembled method has not executed |
| `refresh_stats()` balance block with stub wallet | **NOT RUN** — same as above |
| `setupWallet()` real wallet creation | **NOT RUN** — no wallet/.env on this machine; only the individual v11 wallet calls (`create_new_coldkey`, `save_password_to_env`, `unlock_coldkey`) were verified in isolation against a throwaway wallet (worked, then deleted) |

## Changelog — edits ACTUALLY APPLIED to src/trade.py, requirements.txt, test_bagbot.py (uncommitted)

Line numbers are post-edit file positions.

| file | line(s) | issue | fix | explainer |
|---|---|---|---|---|
| src/trade.py | 82-84 | `float(stake_obj.stake)` in `my_current_stake` — `float(Balance)` removed in v11 | `stake_obj.stake.amount` | `.amount` is the unit-agnostic float accessor; stake here can be TAO- or alpha-denominated, same as before |
| src/trade.py | 93-95 | same `float(stake_obj.stake)` in `determineHotKey` | `stake_obj.stake.amount` | same reason |
| src/trade.py | 174-175 | `bt.Balance.from_tao(x).set_unit(subnet_netuid)` — `set_unit` removed | `bt.Balance.from_alpha(x, subnet_netuid)` | direct v11 replacement, produces the alpha-denominated Balance the trade dict always carried |
| src/trade.py | 207-226 | `self.sub.add_stake(wallet=, hotkey_ss58=, netuid=, amount=, rate_tolerance=, wait_for_inclusion=False, wait_for_finalization=False, safe_staking=True, allow_partial_stake=False)` gone | `self.sub.execute(bt.AddStake(hotkey_ss58=, netuid=, amount_tao=, slippage_protection=True, rate_tolerance=), self.wallet, wait_for_inclusion=False, wait_for_finalization=False)` | v11 intent pipeline. `safe_staking=True` → `slippage_protection=True`; `allow_partial_stake=False` is AddStake's default behavior (partial only exists on the `*Limit` variants). Old fire-and-forget buy semantics (wait inclusion=F, finalization=F) preserved — **verified** `Executor.execute` accepts both kwargs (executor.py:551-566), resolving trap #5 with no semantic drop |
| src/trade.py | 240-258 | `self.sub.unstake(..., wait_for_inclusion=True, wait_for_finalization=False, safe_unstaking=True, allow_partial_stake=False)` gone | `self.sub.execute(bt.RemoveStake(hotkey_ss58=, netuid=, amount_alpha=, slippage_protection=True, rate_tolerance=), self.wallet, wait_for_inclusion=True, wait_for_finalization=False)` | same mapping; old sell semantics (wait inclusion=T, finalization=F) preserved via execute kwargs |
| src/trade.py | 255 | sell result check was `if unstake_result is True:` only — v11 returns `ExtrinsicResult` (not `True`) so successes would have been logged as failures | `if unstake_result is True or getattr(unstake_result, 'success', False) is True:` | mirrors the buy path's existing check; `ExtrinsicResult.success` verified on the installed dataclass |
| src/trade.py | 207, 228-229, 261 | `float(buyTrade['tao_amount'])` / `float(sellTrade['alpha_amount'])` in log lines — `Balance` has no `__float__` (TypeError at exactly trade-success time) | log the Balance object itself (renders as `τ0.020000000` / `0.500000000α₁`) | display-only change, no behavior change |
| requirements.txt | 4-5 | `bittensor-cli` + `bittensor-wallet` superseded | removed | v11 ships everything in the single `bittensor` package (per migration doc pin pitfalls #9) |
| test_bagbot.py | 4, 79, 98, 121, 141, 143, 165, 285-299 | test fixtures mocked stake as plain int and asserted via `float(Balance)` | `MockStake` now wraps stake in `bt.Balance.from_tao(stake)`; assertions use `.tao` / `.amount` | test-only changes so fixtures match the v11 `StakePosition.stake: Balance` shape; no production code touched |

### Tests / smoke run after the trade.py fix (2026-08-28)

| test | result |
|---|---|
| `WALLET_PW=x WALLET_NAME=y python3 -m unittest test_bagbot.py` | **PASS 18/18** (was 5 errors + 1 latent pre-fix) |
| `WALLET_PW=x WALLET_NAME=y python3 -c "import bagbot"` | PASS |
| live `c.plan(bt.AddStake(...), keypair)` dry-run against finney (`//Alice` dev keypair, nothing signed/submitted) | PASS — `plan ok: True`, no violations; RemoveStake intent also constructs (`op == 'remove_stake'`) |
| `Executor.execute` accepts `wait_for_inclusion` / `wait_for_finalization` kwargs | verified by source inspection (executor.py:551-566) — old buy/sell wait semantics map 1:1 |
| `float(Balance)` raises `TypeError`, alpha `.tao` raises `UnitMismatchError`, `Balance.from_alpha(x, n).amount` works | verified in venv |

## Next steps for the picking-up agent (ordered)

1. **Finish blockchain.py verification** (optional but recommended): stub
   `bot.wallet` with `SimpleNamespace(coldkey=SimpleNamespace(ss58_address=...))`
   and run `get_stake_for_hotkey()` + the balance block of `refresh_stats()`
   against finney. No wallet files needed.
2. **Fix `src/trade.py`**:
   - line 82 `my_current_stake`: `float(stake_obj.stake)` → `stake_obj.stake.amount`
   - line 93 `determineHotKey`: same `.stake.amount` change
   - line 136 `constructBuy`: `bt.Balance.from_tao(tao_amount)` still valid — keep
   - line 174 `constructSell`: `bt.Balance.from_tao(alpha_to_sell).set_unit(subnet_netuid)`
     → `bt.Balance.from_alpha(alpha_to_sell, subnet_netuid)`
   - line 166: `float(self.my_current_stake(...))` — works once `my_current_stake`
     returns plain floats (fix at the source, line 82)
   - lines 208-221 `do_available_trades` buy: replace `self.sub.add_stake(...)`
     with `self.sub.execute(bt.AddStake(hotkey_ss58=buyTrade['hotkey'], netuid=buyTrade['netuid'],
     amount_tao=buyTrade['tao_amount'], slippage_protection=True,
     rate_tolerance=buyTrade['max_slippage']), self.wallet)` — then reconcile the
     old `wait_for_inclusion=False` semantics per trap #5
   - lines 239-252 sell: same with `bt.RemoveStake(..., amount_alpha=..., ...)`
   - result checks (lines 224, 254): `ExtrinsicResult.success` verified — the
     existing checks work; `stake_result.__dict__.get('success')` works on dataclasses
   - line 262/267: `my_async_subtensor` is defined in blockchain.py — fine as-is
     under the flat `src/` import layout, do not duplicate it
3. **Fix `requirements.txt`**: delete `bittensor-cli` and `bittensor-wallet`
   lines (superseded by single `bittensor` package).
4. **Run `python3 -m unittest test_bagbot.py`** (with `WALLET_PW=x WALLET_NAME=y`)
   and fix any fallout. NOTE: tests import bot modules; if they construct
   `Balance`-like mocks with `float()` they may need the same `.amount` treatment —
   check `test_bagbot.py` around its stake-object fixtures.
5. **Full-run smoke**: `python3 bagbot.py --nocheck` for one tick (table print +
   `wait_for_block`), confirm no exceptions; do NOT let it trade without the
   user's explicit OK.
6. **Cosmetics (ask user first)**: CLAUDE.md says Python 3.9-3.12 (venv is 3.14)
   and shows old `btcli w create` spelling (`btcli wallet create` also still
   works as alias); README version mentions.
7. Update this changelog with trade.py/requirements.txt rows as you go; commit
   style in repo is short lowercase one-liners (e.g. "unittests", "env fixes &
   keep_alpha setting etc").

## Verification protocol

- Smoke imports: `WALLET_PW=x WALLET_NAME=y python3 -c "import bagbot"` from repo root.
- Live reads (no wallet needed): instantiate `BittensorUtility` via
  `BittensorUtility.__new__(BittensorUtility)`, set `current_stake_info={}`,
  `tick=0`, `gridLoaded=False`, `sub = await my_async_subtensor("finney")`, then
  call `get_subnet_stats()`; for stake paths add a
  `SimpleNamespace(coldkey=SimpleNamespace(ss58_address='<any ss58>'))` wallet.
- Never submit a real trade in testing; `client.plan(intent, wallet)` is the
  v11 dry-run if execution needs testing.

## Resources

- Migration page (authoritative mapping): https://www.bittensor.com/docs/migration
- Live catalogs to verify against instead of guessing:
  `bt.intents.list_tools()` / `bt.reads.list_reads()` in Python;
  `btcli tools`, `btcli query --help` on CLI.
- Installed lib source (best reference):
  `.bagbotvirtualenv/lib/python3.14/site-packages/bittensor/`
  (`client.py`, `namespaces.py`, `reads/staking.py`, `reads/subnets.py`,
  `reads/prices.py`, `reads/accounts.py`, `intents/`, `result.py`, `balance.py`,
  `_generated/runtime_apis.py`, `_generated/storage.py`, `metagraph.py`).
- Project internals doc: `CLAUDE.md` in repo root (architecture, settings system).
- `git diff` in the repo shows every applied edit; `MIGRATION_STATUS.md` (this
  file) is untracked — add it to the commit or remove it per user preference.

