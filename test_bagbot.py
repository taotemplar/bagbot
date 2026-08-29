import sys
sys.path.insert(0, 'src')
import unittest, math
import bittensor as bt
from blockchain import BittensorUtility, InvalidSettings
import bagbot_settings

# For tests to work bagbot_settings.py must be as is (to not cause false fails)
class TestBAGBot(unittest.TestCase):

    def setUp(self):
        pass

    def testNoSellPriceException(self):
        args = {}
        bu = BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.01}
        bu.subnet_grids = {90:{'buy_upper':0.01}}
        self.assertRaises(InvalidSettings, bu.validateGrid)

    def testNoBuyPriceException(self):
        args = {}
        bu = BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.01}
        bu.subnet_grids = {90:{'sell_lower':0.01}}
        self.assertRaises(InvalidSettings, bu.validateGrid)

    def testBadSettings1(self):
        args = {}
        bu = BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.01}
        bu.subnet_grids = {90:{'sell_lower':0.005, 'buy_upper':0.01}}
        self.assertRaises(InvalidSettings, bu.validateGrid)

    def testBadSettings2(self):
        args = {}
        bu = BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.01}
        bu.subnet_grids = {'90':{'sell_lower':0.05, 'buy_upper':0.01}}
        self.assertRaises(InvalidSettings, bu.validateGrid)

    def testNoMaxAlpha(self):
        args = {}
        bu = BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.01}
        bu.subnet_grids = {90:{'sell_lower':0.05, 'buy_upper':0.01}}
        self.assertRaises(InvalidSettings, bu.validateGrid)


    def testNoSupportFor0(self):
        args = {}
        bu = BittensorUtility(args)
        bu.stats = {}
        bu.stats[0] = {'price' : 0.01}
        bu.subnet_grids = {0:{'sell_lower':0.05, 'buy_upper':0.01}}
        self.assertRaises(InvalidSettings, bu.validateGrid)



    def testBuyBaseCase(self):
        args = {}
        bu = BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price': 0.01, 'tao_in': 10000}
        bu.balance = 10
        bu.subnet_grids = {90: {
            'buy_upper': 0.02,
            'sell_lower': 0.03,
            'max_alpha': 3000,
            'max_tao_per_buy': 0.02,
        }}
        buyDict = bu.constructBuy(90)
        self.assertEqual(buyDict['netuid'], 90)
        self.assertEqual(buyDict['tao_amount'].tao, 0.02)



    def testBuyLineBaseCase(self):
        args = {}
        bu = BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.01, 'tao_in':10000}
        bu.balance = 10
        bu.current_stake_info = {'somehotkey': {90: MockStake(100)}}
        bu.subnet_grids = {90:{'buy_upper':0.02,
                               'buy_lower':0.01,
                               'sell_lower':0.03,
                               'max_alpha':1000,
                               'max_tao_per_buy': 0.02,
                          }}
        buyDict = bu.constructBuy(90)
        self.assertEqual(buyDict['netuid'], 90)
        self.assertEqual(buyDict['tao_amount'].tao, 0.02)
        #Have 100, want 1000, so we're 10% of the way there, 10% in between the buy_upper and buy_lower is 0.019
        self.assertTrue(math.isclose(buyDict['buy_threshold'], 0.019))



    def testSellBaseCase(self):
        args = {}
        bagbot_settings.MAX_TAO_PER_SELL = 0.02
        bu = BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.04, 'alpha_in':10000}
        bu.balance = 1
        bu.current_stake_info = {'somehotkey': {90: MockStake(100)}}
        bu.subnet_grids = {90:{'buy_upper':0.02,
                               'sell_lower':0.03,
                               'max_alpha':1000,
                               'max_tao_per_sell': 0.02,
                          }}
        sellDict = bu.constructSell(90)
        self.assertEqual(sellDict['netuid'], 90)
        #0.02 TAO per sell, price of 0.04,
        #0.02 / 0.04 = 0.5 alpha to sell
        self.assertEqual(sellDict['alpha_amount'].amount, 0.5)
        self.assertEqual(sellDict['sell_threshold'], 0.03)


    def testSellLineBaseCase(self):
        args = {}
        bagbot_settings.MAX_TAO_PER_SELL = 0.02
        bu = BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.02, 'alpha_in':10000}
        bu.balance = 1
        bu.current_stake_info = {'somehotkey': {90: MockStake(100)}}
        bu.subnet_grids = {90:{'buy_upper':0.001,
                               'sell_lower':0.01,
                               'sell_upper':0.02,
                               'max_alpha':1000,
                               'max_tao_per_sell': 0.02,
                          }}
        sellDict = bu.constructSell(90)
        self.assertEqual(sellDict['netuid'], 90)
        #0.02 TAO per sell, price of 0.02,
        #0.02 / 0.02 = 1 alpha to sell
        self.assertEqual(sellDict['alpha_amount'].amount, 1)
        self.assertTrue(math.isclose(sellDict['sell_threshold'], 0.019))


    def testSellLineOverMaxAlpha(self):
        args = {}
        bagbot_settings.MAX_TAO_PER_SELL = 0.02
        bu = BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.02, 'alpha_in':10000}
        bu.balance = 1
        bu.current_stake_info = {'somehotkey': {90: MockStake(2000)}}
        bu.subnet_grids = {90:{'buy_upper':0.001,
                               'sell_lower':0.01,
                               'sell_upper':0.02,
                               'max_alpha':1000,
                               'max_tao_per_sell': 0.02,
                          }}
        sellDict = bu.constructSell(90)
        self.assertEqual(sellDict['netuid'], 90)
        #0.02 TAO per sell, price of 0.02,
        #0.02 / 0.02 = 1 alpha to sell
        self.assertEqual(sellDict['alpha_amount'].amount, 1)
        self.assertTrue(math.isclose(sellDict['sell_threshold'], 0.01))


    def testDetermineSlippagePythonBS(self):
        args = {}
        bu = BittensorUtility(args)

        ratio = (0.1 + 0.2) * 0.1
        token_amount = 1.0
        token_in_pool = token_amount / ratio - token_amount
        # Without fixes this returns 3.0000000000000004 instead of 3

        # Compute slippage
        slippage = bu.determineSlippage(token_amount, token_in_pool)
        self.assertEqual(slippage, 3)


    def testBuyPowerCurveLinear(self):
        """Test that power curve = 1.0 gives linear behavior"""
        args = {}
        bu = BittensorUtility(args)
        bu.subnet_grids = {90:{'buy_upper':0.02,
                               'buy_lower':0.01,
                               'sell_lower':0.03,
                               'max_alpha':1000,
                               'buy_zone_power': 1.0,
                          }}
        # At 50% progress (500 alpha), should be at midpoint
        buy_threshold = bu.determine_buy_at_for_amount(bu.subnet_grids[90], 500)
        self.assertTrue(math.isclose(buy_threshold, 0.015))


    def testBuyPowerCurveAggressive(self):
        """Test that power curve > 1.0 keeps price higher for longer"""
        args = {}
        bu = BittensorUtility(args)
        bu.subnet_grids = {90:{'buy_upper':0.02,
                               'buy_lower':0.01,
                               'sell_lower':0.03,
                               'max_alpha':1000,
                               'buy_zone_power': 2.0,
                          }}
        # At 50% progress (500 alpha), with power=2.0, curve_value = 0.5^2 = 0.25
        # buy_at = 0.02 - (0.02 - 0.01) * 0.25 = 0.02 - 0.0025 = 0.0175
        buy_threshold = bu.determine_buy_at_for_amount(bu.subnet_grids[90], 500)
        self.assertTrue(math.isclose(buy_threshold, 0.0175))


    def testBuyPowerCurveConservative(self):
        """Test that power curve < 1.0 drops price faster"""
        args = {}
        bu = BittensorUtility(args)
        bu.subnet_grids = {90:{'buy_upper':0.02,
                               'buy_lower':0.01,
                               'sell_lower':0.03,
                               'max_alpha':1000,
                               'buy_zone_power': 0.5,
                          }}
        # At 50% progress (500 alpha), with power=0.5, curve_value = 0.5^0.5 = ~0.707
        # buy_at = 0.02 - (0.02 - 0.01) * 0.707 = 0.02 - 0.00707 = ~0.01293
        buy_threshold = bu.determine_buy_at_for_amount(bu.subnet_grids[90], 500)
        self.assertTrue(math.isclose(buy_threshold, 0.01293, rel_tol=0.001))


    def testSellPowerCurveLinear(self):
        """Test that power curve = 1.0 gives linear behavior for sells"""
        args = {}
        bu = BittensorUtility(args)
        bu.subnet_grids = {90:{'buy_upper':0.01,
                               'sell_lower':0.01,
                               'sell_upper':0.02,
                               'max_alpha':1000,
                               'sell_zone_power': 1.0,
                          }}
        # At 50% progress (500 alpha), should be at midpoint
        sell_threshold = bu.determine_sell_at_for_amount(bu.subnet_grids[90], 500)
        self.assertTrue(math.isclose(sell_threshold, 0.015))
    

    def testSellBelowAlphaKeep(self):
        """Selling would bring alpha below subnet-specific alpha_keep — should return None"""
        args = {}
        bu = BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price': 0.04, 'alpha_in': 10000}
        bu.balance = 1
        bu.current_stake_info = {'somehotkey': {90: MockStake(100)}}
        bu.subnet_grids = {90: {
            'buy_upper': 0.02,
            'sell_lower': 0.03,
            'max_alpha': 1000,
            'max_tao_per_sell': 0.02,
            'alpha_keep': 100,  # stake is exactly 100, nothing left to sell
        }}
        sellDict = bu.constructSell(90)
        self.assertIsNone(sellDict)


    def testBuyBelowMinTaoInWallet(self):
        """Buying would bring wallet TAO below MIN_TAO_IN_WALLET — should return None"""
        args = {}
        bu = BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price': 0.01, 'tao_in': 10000}
        bagbot_settings.MIN_TAO_IN_WALLET = 0.99
        bu.balance = 1.0  # balance of 1.0, buy cost 0.02 => should fail.
        # bagbot_settings.MIN_TAO_IN_WALLET = 0.99
        bu.subnet_grids = {90: {
            'buy_upper': 0.02,
            'sell_lower': 0.03,
            'max_alpha': 3000,
            'max_tao_per_buy': 0.02,
        }}
        buyDict = bu.constructBuy(90)
        self.assertIsNone(buyDict)




class MockStake:
    def __init__(self, stake):
        # v11 stake positions carry a unit-strict Balance (no __float__);
        # my_current_stake() reads .amount off it.
        self.stake = bt.Balance.from_tao(stake)

if __name__ == '__main__':
    unittest.main()