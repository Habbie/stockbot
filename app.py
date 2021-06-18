import logging
import os
import sys
import signal
import types
import time
import ssl
from datetime import datetime

import irc.strings
from irc.bot import SingleServerIRCBot
from irc.client import ip_numstr_to_quad

from stockbot.configuration import configuration
from stockbot.db import create_tables
from stockbot.persistence import DatabaseCollection, ScheduledCommand
from stockbot.command import root_command
from stockbot.provider import QuoteServiceFactory
from stockbot.util import colorify


# Set up logging
LOGLEVEL = os.getenv("LOGLEVEL", "info").upper()
logging.basicConfig(level=getattr(logging, LOGLEVEL),
                    format="%(asctime)s %(levelname)s %(module)s.%(funcName)s.%(filename)s:%(lineno)d : %(message)s")
LOGGER = logging.getLogger(__name__)


class ScheduleHandler(object):

    days = [1, 2, 3, 4, 5]
    hours = [9, 10, 11, 12, 13, 14, 15, 16, 17]

    def timer_should_execute(self, dt):
        """

        :param dt:
        :type dt: datetime
        :return:
        """
        return (dt.isoweekday() in self.days) and (dt.hour in self.hours)


class ScheduleHandlerAlways(object):

    @staticmethod
    def timer_should_execute(*args):
        return True


class IRCBot(SingleServerIRCBot, ScheduleHandlerAlways):

    def __init__(self, **kwargs):
        super(IRCBot, self).__init__([(configuration.server_name, int(configuration.server_port), configuration.server_password)], configuration.nick,
                                     configuration.nick, **kwargs)
        self.channel = configuration.channel_name
        self.failed_health_checks = 0
        self.max_failed_health_checks = 10
        self.scheduler = configuration.scheduler
        self.reactor.scheduler.execute_every(60, self.stock_check_scheduler)
        self.reactor.scheduler.execute_every(60, self.health_check)
        self.quote_service_factory = QuoteServiceFactory()
        self.commands = DatabaseCollection(type=ScheduledCommand, attribute="command")
        self.scheduler_interval = 3600
        self.last_check = None

    def health_check(self):
        if self.connection.is_connected():
            self.failed_health_checks = 0
        else:
            self.failed_health_checks += 1
            if self.failed_health_checks >= self.max_failed_health_checks:
                LOGGER.error("Still not connected after {} seconds, killing the bot "
                             .format(60 * self.failed_health_checks))
                self.die("BAI")

    def stock_check_scheduler(self):

        if not self.scheduler:
            LOGGER.debug("Scheduler is disabled")
            return

        if not self.connection.is_connected():
            LOGGER.debug("Not connected yet, hold off")
            return

        now = datetime.now()

        if self.last_check is not None:
            if int(now.timestamp()) - self.last_check < self.scheduler_interval:
                return

        # TODO: not so configurable, fix
        if not self.timer_should_execute(now):
            return

        for command in self.commands:
            try:
                root_command.execute(*command.split(" "), command_args={"service_factory": self.quote_service_factory,
                                     "instance": self}, callback=self.command_callback, callback_args={})
            except Exception as e:
                LOGGER.exception("failed to execute scheduled command '{}'".format(command))

        self.last_check = int(now.timestamp())

    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")

    def on_welcome(self, c, e):
        c.join(self.channel)
        if os.path.exists("version.txt"):
            with open("version.txt", "r") as f:
                self.connection.privmsg(self.channel,
                                        "\x0306,13 I'M \x03\x0313,06 BACK! \x03\x0306 Running version\x03: \x0314{}\x03".
                                        format(f.read().strip()))

    def on_privmsg(self, c, e):
        sender = e.source.nick
        message = e.arguments[0]
        commands = [irc.strings.lower(x) for x in message.split(" ")]
        root_command.execute(*commands, command_args={"service_factory": self.quote_service_factory,
                                                      "instance": self, "sender": sender},
                             callback=self.command_callback_priv, callback_args={"sender": sender})

    def on_pubmsg(self, c, e):
        sender = e.source.nick
        message = e.arguments[0]
        if message[0] != '!':
            return

        split = message[1:].split(" ")

        commands = [irc.strings.lower(x) for x in split]
        try:
            root_command.execute(*commands, command_args={"service_factory": self.quote_service_factory,
                                                          "instance": self, "sender": sender},
                                 callback=self.command_callback, callback_args={"sender": sender})
        except Exception as e:
            LOGGER.exception("something failed", e)
            self.command_callback("something failed", sender=sender)

    def command_callback_priv(self, result, **kwargs):
        target = kwargs.get('sender', None)
        if isinstance(result, list) or isinstance(result, types.GeneratorType):
            for row in result:
                self.colorify_send(target, str(row))
                time.sleep(1)  # avoid getting kicked out from server
        elif result is not None:
            self.colorify_send(target, str(result))

    def command_callback(self, result, **kwargs):
        if isinstance(result, list) or isinstance(result, types.GeneratorType):
            for row in result:
                self.colorify_send(self.channel, str(row))
                time.sleep(1)  # avoid getting kicked out from server
        elif result is not None:
            self.colorify_send(self.channel, str(result))

    def colorify_send(self, target, msg):
        # irc.client.MessageTooLong: Messages limited to 512 bytes including CR/LF
        colored_message = colorify(msg)
        if len(colored_message) > 512:
            self.connection.privmsg(target, msg[:512])
        else:
            self.connection.privmsg(target, colored_message)

    def colorify_notice(self, target, msg):
        # irc.client.MessageTooLong: Messages limited to 512 bytes including CR/LF
        colored_message = colorify(msg)
        if len(colored_message) > 512:
            self.connection.notice(target, msg[:512])
        else:
            self.connection.notice(target, colored_message)

    def on_dccmsg(self, c, e):
        # non-chat DCC messages are raw bytes; decode as text
        text = e.arguments[0].decode('utf-8')
        c.privmsg("You said: " + text)

    def on_dccchat(self, c, e):
        if len(e.arguments) != 2:
            return
        args = e.arguments[1].split()
        if len(args) == 4:
            try:
                address = ip_numstr_to_quad(args[2])
                port = int(args[3])
            except ValueError:
                return
            self.dcc_connect(address, port)


if __name__ == '__main__':

    create_tables()

    kwargs = {}
    if configuration.server_use_ssl:
        ssl_factory = irc.connection.Factory(wrapper=ssl.wrap_socket)
        kwargs["connect_factory"] = ssl_factory
    bot = IRCBot(**kwargs)

    def sigterm_handler(*args):
        bot.die("kthxbai")
        sys.exit(0)

    signal.signal(signal.SIGTERM, sigterm_handler)

    bot.start()
