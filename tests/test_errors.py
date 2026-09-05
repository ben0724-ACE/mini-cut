import unittest

from minicut.errors import MiniCutError, ProcessingError, UserInputError


class DomainErrorTest(unittest.TestCase):
    def test_expected_errors_share_a_safe_user_facing_base_type(self) -> None:
        errors = (
            UserInputError("The media path does not exist."),
            ProcessingError("Transcription could not be completed."),
        )

        for error in errors:
            with self.subTest(error_type=type(error).__name__):
                with self.assertRaises(MiniCutError) as raised:
                    raise error
                self.assertEqual(str(raised.exception), str(error))


if __name__ == "__main__":
    unittest.main()
