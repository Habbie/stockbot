import threading
import unittest
import vcr

from unittest.mock import patch

from stockbot.command import root_command
from stockbot.db import Session, create_tables, drop_tables
from stockbot.persistence import DatabaseCollection, ScheduledCommand
from stockbot.provider import QuoteServiceFactory, NasdaqCompany
from stockbot.provider.google import GoogleFinanceSearchResult, GoogleFinanceQueryService, StockDomain


class FakeQuoteService(object):

    def get_quote(self, ticker):
        return "Here's your fake quote for {}".format(ticker)

    def search(self, query):
        return GoogleFinanceSearchResult(result={
            "matches": [
                {"t": "FOO", "e": "Foo Market", "n": "Foo Company"}
            ]
        })


class FakeIrcBot(object):

    commands = DatabaseCollection(type=ScheduledCommand, attribute="command")
    scheduler_interval = 3600
    scheduler = False
    callback_args = None

    def callback(self, *args):
        self.callback_args = args


class TestCommand(unittest.TestCase):

    def setUp(self):

        self.ircbot = FakeIrcBot()
        self.service = FakeQuoteService()
        self.session = Session()
        create_tables()

    def tearDown(self):
        drop_tables()
        self.session.close()

    def __cmd_wrap(self, *args):
        """ test helper """
        factory = QuoteServiceFactory()
        factory.providers = {"fakeprovider": FakeQuoteService}
        return root_command.execute(*args, command_args={"service_factory": factory, "instance": self.ircbot})

    def test_quote_get_command(self):

        command = ["quote", "get", "fakeprovider", "aapl"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("Here's your fake quote for aapl", res)

    def test_lucky_quote_and_quick_get_command(self):

        class FakeQuote(object):

            def __init__(self, data={}):
                self.data = data

            def is_empty(self):
                return len(self.data.items()) == 0

            def __str__(self):
                return "Ticker: {}".format(self.data.get("ticker"))

        class FakeQuoteServiceLocal(object):

            def get_quote(self, ticker):
                if ticker == "fancyticker":
                    return FakeQuote()
                else:
                    return FakeQuote(data={"ticker": "AWESOMO"})

            def search(self, query):
                return GoogleFinanceSearchResult(result={
                    "matches": [
                        {"t": "AWESOMO", "e": "Foo Market", "n": "Foo Company"}
                    ]
                })

        factory = QuoteServiceFactory()
        factory.providers = {"fakeprovider": FakeQuoteServiceLocal}
        command = ["q", "gl", "fakeprovider", "fancyticker"]
        res = root_command.execute(*command, command_args={"service_factory": factory, "instance": self.ircbot})
        self.assertEquals("Ticker: AWESOMO", str(res))

        factory.providers = {"bloomberg": FakeQuoteServiceLocal}
        command = ["qq", "fancyticker"]
        res = root_command.execute(*command, command_args={"service_factory": factory, "instance": self.ircbot})
        self.assertEquals("Ticker: AWESOMO", str(res))

    def test_quote_get_command_invalid_input(self):

        command = ["quote", "get", "aapl"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("No such provider 'aapl'", res)

        command = ["quote", "get", "invalid-provider", "aapl"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("No such provider 'invalid-provider'", res)

    def test_quote_search_command(self):

        command = ["quote", "search", "fakeprovider", "foobar"]
        res = self.__cmd_wrap(*command)
        self.assertIn("Ticker: FOO, Market: Foo Market, Name: Foo Company", res)

    def test_quote_search_command_invalid_input(self):

        command = ["quote", "search", "foobar"]
        res = self.__cmd_wrap(*command)
        self.assertIn("No such provider 'foobar", res)

        command = ["quote", "search", "invalid-provider", "foobar"]
        res = self.__cmd_wrap(*command)
        self.assertIn("No such provider 'invalid-provider", res)

    def test_execute_help_command(self):

        command = ["help"]
        res = self.__cmd_wrap(*command)
        self.assertIn("quote(q) get <provider> <ticker>", res)
        self.assertIn("quote(q) search <provider> <ticker>", res)

    def test_execute_scheduler_ticker_commands(self):

        # blank state
        command = ["quote", "scheduler", "command", "get"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("No commands added", res)

        # add command
        command = ["quote", "scheduler", "command", "add", "quote", "get", "google", "foobar"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("Added command: quote get google foobar", res)

        # add command again and fail gracefully
        command = ["quote", "scheduler", "command", "add", "quote", "get", "google", "foobar"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("Command already in list", res)

        # verify command is there
        command = ["quote", "scheduler", "command", "get"]
        res = self.__cmd_wrap(*command)
        self.assertIn("Command: quote get google foobar", res)

        # remove command
        command = ["quote", "scheduler", "command", "remove", "quote", "get", "google", "foobar"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("Removed command: quote get google foobar", res)

        # verify command is not there
        command = ["quote", "scheduler", "command", "get"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("No commands added", res)

        # remove it again and fail gracefully
        command = ["quote", "scheduler", "command", "remove", "quote", "get", "google", "foobar"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("Command not in list", res)

    def test_execute_scheduler_interval_command(self):

        # default state
        command = ["quote", "scheduler", "interval", "get"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("Interval: 3600 seconds", res)

        # update interval
        command = ["quote", "scheduler", "interval", "set", "60"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("New interval: 60 seconds", res)

        # get updated state
        command = ["quote", "scheduler", "interval", "get"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("Interval: 60 seconds", res)

        # set garbage input
        command = ["quote", "scheduler", "interval", "set", "horseshit"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("Can't set interval from garbage input, must be of an int", res)

    def test_execute_scheduler_toggle_command(self):

        command = ["quote", "scheduler", "enable"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("Scheduler: enabled", res)
        self.assertTrue(self.ircbot.scheduler)

        command = ["quote", "scheduler", "disable"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("Scheduler: disabled", res)
        self.assertFalse(self.ircbot.scheduler)

    def test_execute_unknown_command(self):

        command = ["hi", "stockbot"]
        res = self.__cmd_wrap(*command)
        self.assertEquals(None, res)

    @vcr.use_cassette('mock/vcr_cassettes/nasdaq/scraper.yaml')
    def test_execute_scrape_nasdaq(self):

        command = ["scrape", "nasdaq"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("Scraped 657 companies from Nasdaq", res)

        command = ["scrape", "stats"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("Scraped: nordic large cap=201, nordic mid cap=219, nordic small cap=237", res)

    @patch('time.sleep')
    @vcr.use_cassette('mock/vcr_cassettes/google/quote/scrape_large_cap.yaml')
    def test_execute_nonblocking_scrape_stocks(self, sleep_mock):

        # Mock sleep in the scrape task
        sleep_mock.return_value = False

        companies = [
            NasdaqCompany(name="AAK", ticker="AAK", currency="SEK", category="bla", segment="nordic large cap"),
            NasdaqCompany(name="ABB Ltd", ticker="ABB", currency="SEK", category="bla", segment="nordic large cap")
        ]
        self.session.add_all(companies)
        self.session.commit()

        command = ["scrape", "stocks", "sek", "nordic", "large", "cap"]
        root_command.execute(*command, command_args={'service': GoogleFinanceQueryService()},
                             callback=self.ircbot.callback)

        self.assertEquals("Task started", self.ircbot.callback_args[0])

        for t in threading.enumerate():
            if t.name == "thread-sek_nordic_large_cap":
                t.join()

        self.assertEquals("Done scraping segment 'nordic large cap' currency 'SEK' - scraped 2 companies",
                          self.ircbot.callback_args[0])

        for c in companies:
            row = self.session.query(StockDomain).filter(StockDomain.ticker == c.ticker).first()
            self.assertNotEquals(None, row)

    def test_execute_analytics_fields(self):

        command = ["fundamental", "fields"]
        res = self.__cmd_wrap(*command)
        self.assertEquals("Fields: id, name, ticker, net_profit_margin_last_q, net_profit_margin_last_y, operating_margin_last_q, operating_margin_last_y, ebitd_margin_last_q, ebitd_margin_last_y, roaa_last_q, roaa_last_y, roae_last_q, roae_last_y, market_cap, price_to_earnings, beta, earnings_per_share, dividend_yield, latest_dividend", res)

    def test_execute_analytics_top(self):
        # TODO: fix test data

        command = ["fundamental", "top", "5", "net_profit_margin_last_q"]
        res = self.__cmd_wrap(*command)
        self.assertEquals(["Nothing found"], res)

        command = ["fundamental", "top", "foobar", "net_profit_margin_last_q"]
        res = self.__cmd_wrap(*command)
        self.assertEquals(["Error: foobar is not a number sherlock"], res)

        command = ["fundamental", "top", "5", "this_field_doesnt_exist"]
        res = self.__cmd_wrap(*command)
        self.assertEquals(["Error: 'this_field_doesnt_exist' is not a valid field"], res)
