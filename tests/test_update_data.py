import unittest
from unittest.mock import Mock, patch

from scripts import update_data


class GitHubRepoMetadataTests(unittest.TestCase):
    @patch("time.sleep")
    @patch("scripts.update_data._save_cache")
    @patch("scripts.update_data._load_cache", return_value={})
    @patch("scripts.update_data.requests.get")
    def test_retries_transient_network_errors_then_returns_empty_metadata(
        self, mock_get, _load_cache, save_cache, sleep
    ):
        mock_get.side_effect = update_data.requests.ConnectionError("network down")

        result = update_data.gh_repo_meta("owner/repo")

        self.assertEqual(result, {})
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        save_cache.assert_not_called()

    @patch("time.sleep")
    @patch("scripts.update_data._save_cache")
    @patch("scripts.update_data._load_cache", return_value={})
    @patch("scripts.update_data.requests.get")
    def test_recovers_after_a_transient_network_error(
        self, mock_get, _load_cache, save_cache, sleep
    ):
        response = Mock(status_code=200)
        response.json.return_value = {"stargazers_count": 42}
        mock_get.side_effect = [
            update_data.requests.Timeout("slow network"),
            response,
        ]

        result = update_data.gh_repo_meta("owner/repo")

        self.assertEqual(result, {"stargazers_count": 42})
        self.assertEqual(mock_get.call_count, 2)
        sleep.assert_called_once()
        save_cache.assert_called_once()
    @patch("time.sleep")
    @patch("scripts.update_data._save_cache")
    @patch("scripts.update_data._load_cache", return_value={})
    @patch("scripts.update_data.requests.get")
    def test_recovers_from_a_rate_limited_403(
        self, mock_get, _load_cache, save_cache, sleep
    ):
        limited = Mock(
            status_code=403,
            headers={"x-ratelimit-remaining": "0", "retry-after": "1"},
        )
        recovered = Mock(status_code=200, headers={})
        recovered.json.return_value = {"stargazers_count": 7}
        mock_get.side_effect = [limited, recovered]

        result = update_data.gh_repo_meta("owner/repo")

        self.assertEqual(result, {"stargazers_count": 7})
        self.assertEqual(mock_get.call_count, 2)
        sleep.assert_called_once()
        save_cache.assert_called_once()

    @patch("scripts.update_data._save_cache")
    @patch("scripts.update_data._load_cache", return_value={})
    @patch("scripts.update_data.requests.get")
    def test_does_not_cache_non_definitive_403_errors(
        self, mock_get, _load_cache, save_cache
    ):
        mock_get.return_value = Mock(status_code=403, headers={})

        result = update_data.gh_repo_meta("owner/repo")

        self.assertEqual(result, {})
        save_cache.assert_not_called()


if __name__ == "__main__":
    unittest.main()
