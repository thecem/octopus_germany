"""Regression tests for Kraken email/password authentication."""

# ruff: noqa: INP001, PT009, S105

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from custom_components.octopus_germany.octopus_germany import (
    GRAPH_QL_ENDPOINT,
    OctopusGermany,
    TokenManager,
)

API_MODULE = "custom_components.octopus_germany.octopus_germany"
EMAIL = "test@example.invalid"
PASSWORD = 'test-"password\\with special characters'
TOKEN = "test-token"


class AuthenticationTest(unittest.TestCase):
    """Verify credential transport, rejection diagnostics, and retry behavior."""

    def setUp(self) -> None:
        """Create a client without starting background token refresh."""
        self.api = object.__new__(OctopusGermany)
        self.api._email = EMAIL  # noqa: SLF001
        self.api._password = PASSWORD  # noqa: SLF001
        self.api._token_manager = TokenManager()  # noqa: SLF001
        self.client = Mock(execute_async=AsyncMock())
        self.client.execute_async.return_value = {
            "data": {
                "obtainKrakenToken": {"token": TOKEN, "payload": {"exp": 4102444800}}
            }
        }
        self.client_factory = self.enterContext(
            patch(f"{API_MODULE}.GraphqlClient", return_value=self.client)
        )
        self.sleep = self.enterContext(
            patch(f"{API_MODULE}.asyncio.sleep", new_callable=AsyncMock)
        )

    def test_credentials_are_sent_as_variables_without_authorization(self) -> None:
        """Keep credential values in variables and omit auth headers."""
        self.assertTrue(asyncio.run(self.api.login()))
        self.client_factory.assert_called_once_with(
            endpoint=GRAPH_QL_ENDPOINT, headers={}
        )
        kwargs = self.client.execute_async.await_args.kwargs
        self.assertEqual(kwargs["variables"], {"email": EMAIL, "password": PASSWORD})
        self.assertIn("input: { email: $email, password: $password }", kwargs["query"])
        self.assertNotIn(EMAIL, kwargs["query"])
        self.assertNotIn(PASSWORD, kwargs["query"])
        self.assertEqual(self.api._token_manager.token, TOKEN)  # noqa: SLF001
        self.sleep.assert_not_awaited()

    def test_missing_input_rejection_stops_and_explains_api_error(self) -> None:
        """Stop identical rejected requests without exposing credentials."""
        self.client.execute_async.return_value = {
            "errors": [
                {
                    "message": "Please make sure both email and password are present "
                    "in the input",
                    "extensions": {"errorCode": "KT-CT-1136"},
                }
            ],
            "data": {"obtainKrakenToken": None},
        }
        with self.assertLogs(API_MODULE, level="ERROR") as logs:
            self.assertFalse(asyncio.run(self.api.login()))
        self.client.execute_async.assert_awaited_once()
        self.sleep.assert_not_awaited()
        output = "\n".join(logs.output)
        self.assertIn("KT-CT-1136", output)
        self.assertIn("support", output)
        self.assertIn("All 1 login attempts failed.", output)
        self.assertNotIn(EMAIL, output)
        self.assertNotIn(PASSWORD, output)

    def test_rejection_restores_previous_token(self) -> None:
        """Preserve the previous token when authentication is rejected."""
        self.api._token_manager.set_token(TOKEN, 1)  # noqa: SLF001
        self.client.execute_async.return_value = {
            "errors": [{"extensions": {"errorCode": "KT-CT-1136"}}]
        }
        with self.assertLogs(API_MODULE, level="ERROR"):
            self.assertFalse(asyncio.run(self.api.login()))
        self.assertEqual(self.api._token_manager.token, TOKEN)  # noqa: SLF001

    def test_valid_token_skips_authentication(self) -> None:
        """Avoid unnecessary requests while a cached token is valid."""
        self.api._token_manager.set_token(TOKEN, 4102444800)  # noqa: SLF001
        self.assertTrue(asyncio.run(self.api.login()))
        self.client_factory.assert_not_called()
        self.client.execute_async.assert_not_awaited()

    def test_other_api_errors_keep_retrying_and_log_error_code(self) -> None:
        """Retain existing retries for errors other than missing input."""
        for code in ("KT-CT-1199", "KT-CT-1135"):
            with self.subTest(code=code):
                self.client.execute_async.reset_mock()
                self.sleep.reset_mock()
                self.client.execute_async.side_effect = [
                    {
                        "errors": [
                            {
                                "message": "Request rejected",
                                "extensions": {"errorCode": code},
                            }
                        ]
                    },
                    {
                        "data": {
                            "obtainKrakenToken": {
                                "token": TOKEN,
                                "payload": {"exp": 4102444800},
                            }
                        }
                    },
                ]
                self.api._token_manager.clear()  # noqa: SLF001
                with self.assertLogs(API_MODULE, level="WARNING") as logs:
                    self.assertTrue(asyncio.run(self.api.login()))
                self.assertEqual(self.client.execute_async.await_count, 2)
                self.sleep.assert_awaited_once_with(1)
                if code != "KT-CT-1199":
                    self.assertIn(code, "\n".join(logs.output))

    def test_transport_failure_can_recover(self) -> None:
        """Retry a transient connection failure."""
        self.client.execute_async.side_effect = [
            OSError("Connection unavailable"),
            self.client.execute_async.return_value,
        ]
        with self.assertLogs(API_MODULE, level="ERROR"):
            self.assertTrue(asyncio.run(self.api.login()))
        self.assertEqual(self.client.execute_async.await_count, 2)
        self.sleep.assert_awaited_once_with(1)
