import unittest

from mdlp_parser import MarkingCodeError, parse_marking_code


class MarkingCodeTests(unittest.TestCase):
    def test_parse_parenthesized_gs1_code(self):
        code = "(01)04601234567893(21)ABC1234567890"
        parsed = parse_marking_code(code)
        self.assertEqual(parsed.gtin, "04601234567893")
        self.assertEqual(parsed.serial_number, "ABC1234567890")
        self.assertEqual(parsed.sgtin, "04601234567893ABC1234567890")

    def test_parse_with_group_separator_and_crypto_tail(self):
        code = "010460123456789321ABC1234567890\x1d8005TAIL"
        parsed = parse_marking_code(code)
        self.assertEqual(parsed.serial_number, "ABC1234567890")
        self.assertEqual(parsed.gtin, "04601234567893")

    def test_invalid_gtin_check_digit(self):
        with self.assertRaises(MarkingCodeError):
            parse_marking_code("010460123456789421ABC1234567890")

    def test_invalid_serial_length(self):
        with self.assertRaises(MarkingCodeError):
            parse_marking_code("010460123456789321SHORT")


if __name__ == "__main__":
    unittest.main()
