from types import SimpleNamespace
import unittest

import requests

from multi_city_scheduler import classify_failure


class MultiCityRetryPolicyTests(unittest.TestCase):
    def test_retryable_transport_errors(self):
        self.assertEqual(classify_failure(requests.Timeout("timed out")), (True, "timeout"))
        self.assertEqual(classify_failure(requests.ConnectionError("connection reset")),
                         (True, "connection_error"))

    def test_retryable_server_error(self):
        error = requests.HTTPError("server error", response=SimpleNamespace(status_code=503))
        self.assertEqual(classify_failure(error), (True, "http_503"))

    def test_client_and_parse_errors_are_permanent(self):
        not_found = requests.HTTPError("not found", response=SimpleNamespace(status_code=404))
        self.assertEqual(classify_failure(not_found), (False, "http_404"))
        self.assertEqual(classify_failure(
            ValueError("No movie metadata found; do not interpret as zero shows")),
            (False, "unrecognized_page"))
        self.assertEqual(classify_failure(ValueError("City redirect: requested foo, got bar")),
                         (False, "city_mismatch"))
