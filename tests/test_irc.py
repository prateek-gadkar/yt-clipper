import unittest

from clipper.irc import parse_irc_line


class TestParseIrcLine(unittest.TestCase):
    def test_tagged_privmsg(self):
        line = (
            "@badge-info=subscriber/12;tmi-sent-ts=1700000000123;color=#FF0000 "
            ":someuser!someuser@someuser.tmi.twitch.tv PRIVMSG #somechannel :PogChamp hello world"
        )
        msg = parse_irc_line(line)
        self.assertEqual(msg["command"], "PRIVMSG")
        self.assertEqual(msg["tags"]["tmi-sent-ts"], "1700000000123")
        self.assertEqual(msg["prefix"], "someuser!someuser@someuser.tmi.twitch.tv")
        self.assertEqual(msg["params"], ["#somechannel", "PogChamp hello world"])

    def test_ping(self):
        msg = parse_irc_line("PING :tmi.twitch.tv")
        self.assertEqual(msg["command"], "PING")
        self.assertEqual(msg["params"], ["tmi.twitch.tv"])

    def test_welcome(self):
        msg = parse_irc_line(":tmi.twitch.tv 001 justinfan1234 :Welcome, GLHF!")
        self.assertEqual(msg["command"], "001")
        self.assertEqual(msg["params"][0], "justinfan1234")

    def test_message_containing_colon_and_hash(self):
        line = ":u!u@u.tmi.twitch.tv PRIVMSG #chan :check this: ratio #123 :)"
        msg = parse_irc_line(line)
        self.assertEqual(msg["params"][1], "check this: ratio #123 :)")


if __name__ == "__main__":
    unittest.main()
