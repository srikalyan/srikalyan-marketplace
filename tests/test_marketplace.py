#!/usr/bin/env python3
"""Integration tests validating the srikalyan-marketplace structure.

Verifies:
- marketplace.json is valid and well-formed
- All referenced plugins are accessible (via git ls-remote)
- Plugin repos have correct structure (.claude-plugin/plugin.json, skills/)
- Cross-references between marketplace and plugins are consistent
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent


class MarketplaceTest:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.marketplace = None

    def assert_true(self, condition, message):
        if condition:
            self.passed += 1
            print(f"  PASS: {message}")
        else:
            self.failed += 1
            print(f"  FAIL: {message}")

    def assert_equal(self, actual, expected, message):
        if actual == expected:
            self.passed += 1
            print(f"  PASS: {message}")
        else:
            self.failed += 1
            print(f"  FAIL: {message} (expected {expected!r}, got {actual!r})")

    def test_marketplace_json_exists(self):
        print("\n── Test: marketplace.json exists and is valid ──")
        path = ROOT / ".claude-plugin" / "marketplace.json"
        self.assert_true(path.is_file(), ".claude-plugin/marketplace.json exists")

        with open(path) as f:
            self.marketplace = json.load(f)

        self.assert_true(isinstance(self.marketplace, dict), "marketplace.json is a JSON object")

    def test_marketplace_required_fields(self):
        print("\n── Test: marketplace required fields ──")
        self.assert_true("name" in self.marketplace, "has 'name' field")
        self.assert_true("plugins" in self.marketplace, "has 'plugins' field")
        self.assert_true("owner" in self.marketplace, "has 'owner' field")
        self.assert_true(
            isinstance(self.marketplace["plugins"], list),
            "'plugins' is an array",
        )
        self.assert_true(len(self.marketplace["plugins"]) > 0, "at least one plugin listed")

    def test_marketplace_metadata(self):
        print("\n── Test: marketplace metadata ──")
        self.assert_true(
            len(self.marketplace.get("name", "")) > 0,
            "marketplace name is non-empty",
        )
        self.assert_true(
            len(self.marketplace.get("description", "")) > 0,
            "marketplace description is non-empty",
        )
        owner = self.marketplace.get("owner", {})
        self.assert_true("name" in owner, "owner has 'name' field")

    def test_plugin_entries(self):
        print("\n── Test: plugin entries are well-formed ──")
        required_fields = ["name", "description", "source"]

        for plugin in self.marketplace["plugins"]:
            name = plugin.get("name", "<unnamed>")
            for field in required_fields:
                self.assert_true(
                    field in plugin,
                    f"plugin '{name}' has '{field}' field",
                )

            # Validate source structure
            source = plugin.get("source", {})
            if isinstance(source, dict):
                self.assert_true(
                    "source" in source,
                    f"plugin '{name}' source has 'source' type",
                )
                source_type = source.get("source", "")
                if source_type == "github":
                    self.assert_true(
                        "repo" in source,
                        f"plugin '{name}' github source has 'repo' field",
                    )
                elif source_type == "url":
                    self.assert_true(
                        "url" in source,
                        f"plugin '{name}' url source has 'url' field",
                    )
            elif isinstance(source, str):
                self.assert_true(
                    source.startswith("./") or source.startswith("/"),
                    f"plugin '{name}' relative source starts with './' or '/'",
                )

    def test_no_duplicate_plugins(self):
        print("\n── Test: no duplicate plugin names ──")
        names = [p.get("name") for p in self.marketplace["plugins"]]
        self.assert_equal(len(names), len(set(names)), "all plugin names are unique")

    def test_plugin_repos_accessible(self):
        print("\n── Test: plugin repos are accessible ──")
        for plugin in self.marketplace["plugins"]:
            name = plugin.get("name", "<unnamed>")
            source = plugin.get("source", {})

            if not isinstance(source, dict):
                continue

            source_type = source.get("source", "")

            if source_type == "github":
                repo = source.get("repo", "")
                url = f"https://github.com/{repo}.git"
            elif source_type == "url":
                url = source.get("url", "")
            else:
                continue

            try:
                result = subprocess.run(
                    ["git", "ls-remote", "--exit-code", url],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assert_true(
                    result.returncode == 0,
                    f"plugin '{name}' repo is accessible: {url}",
                )
            except subprocess.TimeoutExpired:
                self.assert_true(False, f"plugin '{name}' repo timed out: {url}")
            except FileNotFoundError:
                self.assert_true(False, f"git not available to check plugin '{name}'")

    def test_plugin_repos_have_plugin_json(self):
        print("\n── Test: plugin repos have .claude-plugin/plugin.json ──")
        for plugin in self.marketplace["plugins"]:
            name = plugin.get("name", "<unnamed>")
            source = plugin.get("source", {})

            if not isinstance(source, dict):
                continue

            source_type = source.get("source", "")
            if source_type == "github":
                repo = source.get("repo", "")
                url = f"https://github.com/{repo}.git"
            elif source_type == "url":
                url = source.get("url", "")
            else:
                continue

            # Clone shallowly to temp dir and verify structure
            with tempfile.TemporaryDirectory(prefix="mkt_test_") as tmp:
                try:
                    result = subprocess.run(
                        ["git", "clone", "--depth", "1", url, tmp + "/repo"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.returncode != 0:
                        self.assert_true(False, f"plugin '{name}' failed to clone")
                        continue

                    repo_root = Path(tmp) / "repo"

                    # Check .claude-plugin/plugin.json
                    plugin_json = repo_root / ".claude-plugin" / "plugin.json"
                    self.assert_true(
                        plugin_json.is_file(),
                        f"plugin '{name}' has .claude-plugin/plugin.json",
                    )

                    if plugin_json.is_file():
                        with open(plugin_json) as f:
                            pdata = json.load(f)
                        self.assert_equal(
                            pdata.get("name"),
                            name,
                            f"plugin.json name matches marketplace entry ('{name}')",
                        )

                    # Check skills directory exists
                    skills_dir = repo_root / "skills"
                    self.assert_true(
                        skills_dir.is_dir(),
                        f"plugin '{name}' has skills/ directory",
                    )

                    # Check at least one SKILL.md
                    skill_files = list(skills_dir.rglob("SKILL.md"))
                    self.assert_true(
                        len(skill_files) > 0,
                        f"plugin '{name}' has at least one SKILL.md",
                    )

                    # Verify SKILL.md has valid frontmatter
                    for sf in skill_files:
                        content = sf.read_text()
                        self.assert_true(
                            content.startswith("---"),
                            f"plugin '{name}' {sf.relative_to(repo_root)} has YAML frontmatter",
                        )

                    # Check scripts directory
                    scripts_dir = repo_root / "scripts"
                    if scripts_dir.is_dir():
                        py_files = list(scripts_dir.glob("*.py"))
                        self.assert_true(
                            len(py_files) > 0,
                            f"plugin '{name}' has Python scripts",
                        )

                except subprocess.TimeoutExpired:
                    self.assert_true(False, f"plugin '{name}' clone timed out")

    def run_all(self):
        print("=" * 60)
        print("Marketplace Integration Tests")
        print("=" * 60)

        self.test_marketplace_json_exists()
        self.test_marketplace_required_fields()
        self.test_marketplace_metadata()
        self.test_plugin_entries()
        self.test_no_duplicate_plugins()
        self.test_plugin_repos_accessible()
        self.test_plugin_repos_have_plugin_json()

        print("\n" + "=" * 60)
        print(f"Results: {self.passed} passed, {self.failed} failed")
        print("=" * 60)

        return self.failed == 0


if __name__ == "__main__":
    test = MarketplaceTest()
    success = test.run_all()
    sys.exit(0 if success else 1)
