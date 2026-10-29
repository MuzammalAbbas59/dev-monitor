import re
import unittest
from importlib import resources

TEMPLATE = resources.files("dev_monitor").joinpath("dashboard.html").read_text(encoding="utf-8")
IDS = ["provider", "repository-source", "server-host", "server-field", "token-row", "token-input", "token-email",
       "save-token", "forget-token", "token-link", "target-branch", "branch-options", "current-branch", "refresh",
       "local-note", "local-hint", "log-search", "search", "result-count"]


class DashboardTemplateTests(unittest.TestCase):
    def test_placeholder_once(self):
        self.assertEqual(TEMPLATE.count("__MONITOR_DATA__"), 1)

    def test_required_ids_present(self):
        for element_id in IDS:
            self.assertIn(f'id="{element_id}"', TEMPLATE, element_id)

    def test_provider_options(self):
        select = re.search(r'<select id="provider"[^>]*>(.*?)</select>', TEMPLATE, re.S).group(1)
        self.assertEqual(re.findall(r'<option value="(\w+)">([^<]+)</option>', select),
                         [("github", "GitHub"), ("gitlab", "GitLab"), ("bitbucket", "Bitbucket"), ("local", "Local folder")])

    def test_log_search_sits_in_merge_log_header(self):
        heading = re.search(r'<div class="history-heading">(.*?)</div>\s*<div class="table-scroll"', TEMPLATE, re.S).group(1)
        self.assertIn('id="log-search"', heading)
        self.assertIn('id="result-count"', heading)

    def test_no_github_only_copy(self):
        self.assertIsNone(re.search(r"Refresh from GitHub|GitHub repository or local folder|Last checked GitHub|"
                                    r"Dev Monitor\.app|hostname === \"github\.com\"", TEMPLATE))

    def test_links_require_https(self):
        self.assertIn('url.protocol === "https:"', TEMPLATE)


if __name__ == "__main__":
    unittest.main()
