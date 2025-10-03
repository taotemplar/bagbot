import unittest
import utils
import settings
import bagbot
import math

utils.log = lambda *args : None
utils.logAndPrint = lambda *args : None


"""
class MockExchange(Exchange):
    def fetchTickerMap(self, *args):
        pass
    def fetchCurrentSnapshotData(self, *args):
        pass
"""

class TestBAGBot(unittest.TestCase):

    def setUp(self):
        pass

    def testNoSellPriceException(self):
        args = {}
        bu = bagbot.BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.01}
        bu.subnet_grids = {90:{'buy_upper':0.01}}
        self.assertRaises(bagbot.InvalidSettings, bu.validateGrid)

    def testNoBuyPriceException(self):
        args = {}
        bu = bagbot.BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.01}
        bu.subnet_grids = {90:{'sell_lower':0.01}}
        self.assertRaises(bagbot.InvalidSettings, bu.validateGrid)

    def testBadSettings1(self):
        args = {}
        bu = bagbot.BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.01}
        bu.subnet_grids = {90:{'sell_lower':0.005, 'buy_upper':0.01}}
        self.assertRaises(bagbot.InvalidSettings, bu.validateGrid)

    def testBadSettings2(self):
        args = {}
        bu = bagbot.BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.01}
        bu.subnet_grids = {'90':{'sell_lower':0.05, 'buy_upper':0.01}}
        self.assertRaises(bagbot.InvalidSettings, bu.validateGrid)

    def testNoMaxAlpha(self):
        args = {}
        bu = bagbot.BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.01}
        bu.subnet_grids = {90:{'sell_lower':0.05, 'buy_upper':0.01}}
        self.assertRaises(bagbot.InvalidSettings, bu.validateGrid)


    def testNoSupportFor0(self):
        args = {}
        bu = bagbot.BittensorUtility(args)
        bu.stats = {}
        bu.stats[0] = {'price' : 0.01}
        bu.subnet_grids = {0:{'sell_lower':0.05, 'buy_upper':0.01}}
        self.assertRaises(bagbot.InvalidSettings, bu.validateGrid)





    def testBuyBaseCase(self):
        args = {}
        bu = bagbot.BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.01, 'tao_in':10000}
        bu.balance = 1
        bu.subnet_grids = {90:{'buy_upper':0.02,
                               'sell_lower':0.03,
                               'max_alpha':3000,
                          }}
        buyDict = bu.constructBuy(90)
        self.assertEqual(buyDict['netuid'], 90)
        self.assertEqual(float(buyDict['tao_amount']), 0.02)


    def testBuyLineBaseCase(self):
        args = {}
        bu = bagbot.BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.01, 'tao_in':10000}
        bu.balance = 1
        bu.current_stake_info = {'somehotkey': {90: MockStake(100)}}
        bu.subnet_grids = {90:{'buy_upper':0.02,
                               'buy_lower':0.01,
                               'sell_lower':0.03,
                               'max_alpha':1000,
                          }}
        buyDict = bu.constructBuy(90)
        self.assertEqual(buyDict['netuid'], 90)
        self.assertEqual(float(buyDict['tao_amount']), 0.02)
        #Have 100, want 1000, so we're 10% of the way there, 10% in between the buy_upper and buy_lower is 0.019
        self.assertTrue(math.isclose(buyDict['buy_threshold'], 0.019))



    def testSellBaseCase(self):
        args = {}
        bagbot.bagbot_settings.MAX_TAO_PER_SELL = 0.02
        bu = bagbot.BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.04, 'alpha_in':10000}
        bu.balance = 1
        bu.current_stake_info = {'somehotkey': {90: MockStake(100)}}
        bu.subnet_grids = {90:{'buy_upper':0.02,
                               'sell_lower':0.03,
                               'max_alpha':1000,
                          }}
        sellDict = bu.constructSell(90)
        self.assertEqual(sellDict['netuid'], 90)
        #0.02 TAO per sell, price of 0.04,
        #0.02 / 0.04 = 0.5 alpha to sell
        self.assertEqual(float(sellDict['alpha_amount']), 0.5)
        self.assertEqual(float(sellDict['sell_threshold']), 0.03)


    def testSellLineBaseCase(self):
        args = {}
        bagbot.bagbot_settings.MAX_TAO_PER_SELL = 0.02
        bu = bagbot.BittensorUtility(args)
        bu.stats = {}
        bu.stats[90] = {'price' : 0.02, 'alpha_in':10000}
        bu.balance = 1
        bu.current_stake_info = {'somehotkey': {90: MockStake(100)}}
        bu.subnet_grids = {90:{'buy_upper':0.001,
                               'sell_lower':0.01,
                               'sell_upper':0.02,
                               'max_alpha':1000,
                          }}
        sellDict = bu.constructSell(90)
        self.assertEqual(sellDict['netuid'], 90)
        #0.02 TAO per sell, price of 0.02,
        #0.02 / 0.02 = 1 alpha to sell
        self.assertEqual(float(sellDict['alpha_amount']), 1)
        self.assertTrue(math.isclose(float(sellDict['sell_threshold']), 0.019))





class MockStake:
    def __init__(self, stake):
        self.stake = stake

if __name__ == '__main__':
    unittest.main()
