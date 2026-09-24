import unittest

from mdlp_parser import MarkingCodeError, parse_marking_code


class MarkingCodeTests(unittest.TestCase):
    def test_parse_parenthesized_gs1_code(self):
        code = "(01)04601234567893(21)ABC1234567890"
        parsed = parse_marking_code(code)
        self.assertEqual(parsed.gtin, "04601234567893")
        self.assertEqual(parsed.serial_number, "ABC1234567890")
        self.assertEqual(parsed.sgtin, "04601234567893ABC1234567890")
        self.assertIsNone(parsed.expiry_date)
        self.assertIsNone(parsed.batch_number)

    def test_parse_with_group_separator_and_crypto_tail(self):
        code = "010460123456789321ABC1234567890\x1d8005TAIL"
        parsed = parse_marking_code(code)
        self.assertEqual(parsed.serial_number, "ABC1234567890")
        self.assertEqual(parsed.gtin, "04601234567893")

    def test_invalid_gtin_check_digit(self):
        with self.assertRaises(MarkingCodeError):
            parse_marking_code("010460123456789421ABC1234567890")

    def test_parse_expiry_and_batch(self):
        code = "(01)04601234567893(17)271231(10)BATCH42(21)ABC1234567890"
        parsed = parse_marking_code(code)
        self.assertEqual(parsed.expiry_date, "2027-12-31")
        self.assertEqual(parsed.batch_number, "BATCH42")
        self.assertEqual(parsed.serial_number, "ABC1234567890")

    def test_parse_expiry_after_serial(self):
        code = "010460123456789321ABC1234567890\x1d17271231"
        parsed = parse_marking_code(code)
        self.assertEqual(parsed.expiry_date, "2027-12-31")

    def test_invalid_date(self):
        with self.assertRaises(MarkingCodeError):
            parse_marking_code("01046012345678931727133221ABC1234567890")

    def test_invalid_serial_length(self):
        with self.assertRaises(MarkingCodeError):
            parse_marking_code("010460123456789321SHORT")


if __name__ == "__main__":
    unittest.main()
