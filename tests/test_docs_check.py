"""Tests for tools/docs_check.py.

The community list checks exist because
https://github.com/teslamotors/light-show/issues/62 is a request to be added
to it, and there will be more. They check the shape of the list only: whether
a site belongs on it is a maintainer's decision, not a script's.
"""

import io
import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import docs_check as dc  # noqa: E402


LIST = """<!-- community-shows: alphabetical -->
- [Alpha](https://alpha.example/)
- [Beta](https://beta.example/)
<!-- /community-shows -->
"""


class FakeRepo:
    """A throwaway repository to check findings against."""

    def __init__(self, tmpdir):
        self.root = tmpdir
        os.makedirs(os.path.join(tmpdir, "images"), exist_ok=True)

    def write(self, relative, text):
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return relative

    def touch(self, relative):
        return self.write(relative, "")

    def check(self, relative):
        return dc.check_file(relative, self.root)

    def check_list(self, relative):
        return dc.check_community_list(relative, self.root)

    def check_commands(self, relative):
        return dc.check_commands(relative, self.root)


class DocsCheckTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = FakeRepo(self._tmp.name)

    def codes(self, findings):
        return [f.code for f in findings]


class SlugTests(unittest.TestCase):
    def test_headings_become_github_anchors(self):
        self.assertEqual(dc.heading_slug("Download a Show"), "download-a-show")
        self.assertEqual(dc.heading_slug("Ramping Channels 4-6"),
                         "ramping-channels-4-6")
        self.assertEqual(dc.heading_slug("Closures channels"),
                         "closures-channels")

    def test_punctuation_is_dropped(self):
        self.assertEqual(dc.heading_slug("What's new, really?"),
                         "whats-new-really")

    def test_inline_html_is_ignored(self):
        self.assertEqual(
            dc.heading_slug('<a name="x"></a>Interior RGB Lights'),
            "interior-rgb-lights")

    def test_anchors_collects_both_kinds(self):
        text = '# One Two\n<a name="explicit"></a>\n## Three\n'
        self.assertEqual(dc.anchors(text), {"one-two", "explicit", "three"})


class ResolveTests(unittest.TestCase):
    def test_a_leading_slash_means_the_repository_root(self):
        self.assertEqual(
            dc.resolve("/images/a.png?raw=true", "examples/sub/README.md"),
            "images/a.png")

    def test_a_relative_path_is_relative_to_the_file(self):
        self.assertEqual(dc.resolve("Car_setup.jpg", "examples/x/README.md"),
                         os.path.join("examples", "x", "Car_setup.jpg"))

    def test_query_and_fragment_are_stripped(self):
        self.assertEqual(dc.resolve("xlights/f.zip?raw=true#frag",
                                    "README.md"), "xlights/f.zip")


class AnchorTests(DocsCheckTestCase):
    def test_a_link_to_a_missing_section_is_an_error(self):
        doc = self.repo.write("README.md", "# Title\n[go](#nowhere)\n")
        findings = self.repo.check(doc)

        self.assertEqual(self.codes(findings), ["anchor-not-found"])
        self.assertEqual(findings[0].severity, dc.ERROR)
        self.assertEqual(findings[0].line, 2)

    def test_a_link_to_a_heading_resolves(self):
        doc = self.repo.write("README.md", "# My Title\n[go](#my-title)\n")
        self.assertEqual(self.repo.check(doc), [])

    def test_a_link_to_an_explicit_anchor_resolves(self):
        doc = self.repo.write(
            "README.md", '<a name="here"></a>\n[go](#here)\n')
        self.assertEqual(self.repo.check(doc), [])

    def test_the_real_readme_has_no_broken_anchors(self):
        findings = dc.check_file("README.md")
        self.assertEqual(
            [f for f in findings if f.code == "anchor-not-found"], [])


class PathTests(DocsCheckTestCase):
    def test_a_link_to_a_missing_file_is_an_error(self):
        doc = self.repo.write("README.md", "[tool](tools/gone.py)\n")
        findings = self.repo.check(doc)

        self.assertEqual(self.codes(findings), ["path-not-found"])
        self.assertEqual(findings[0].severity, dc.ERROR)

    def test_a_link_to_a_present_file_resolves(self):
        self.repo.touch("tools/here.py")
        doc = self.repo.write("README.md", "[tool](tools/here.py)\n")
        self.assertEqual(self.repo.check(doc), [])

    def test_html_image_references_are_checked_too(self):
        doc = self.repo.write(
            "README.md", '<img src="/images/missing.png?raw=true" />\n')
        self.assertEqual(self.codes(self.repo.check(doc)), ["path-not-found"])

    def test_a_raw_parameter_does_not_break_the_lookup(self):
        self.repo.touch("images/a.png")
        doc = self.repo.write(
            "README.md", '<img src="/images/a.png?raw=true" />\n')
        self.assertEqual(self.repo.check(doc), [])

    def test_relative_links_resolve_against_their_own_directory(self):
        self.repo.touch("examples/show/Car_setup.jpg")
        doc = self.repo.write("examples/show/README.md",
                              "![setup](Car_setup.jpg)\n")
        self.assertEqual(self.repo.check(doc), [])

    def test_the_real_documents_have_no_missing_files(self):
        for name in dc.markdown_files():
            findings = [f for f in dc.check_file(name)
                        if f.code == "path-not-found"]
            self.assertEqual(findings, [], name)


class ExternalLinkTests(DocsCheckTestCase):
    def test_an_http_link_is_a_warning(self):
        doc = self.repo.write("README.md", "[site](http://example.com/)\n")
        findings = self.repo.check(doc)

        self.assertEqual(self.codes(findings), ["insecure-link"])
        self.assertEqual(findings[0].severity, dc.WARNING)

    def test_an_https_link_is_fine(self):
        doc = self.repo.write("README.md", "[site](https://example.com/)\n")
        self.assertEqual(self.repo.check(doc), [])

    def test_a_tracking_parameter_is_a_warning(self):
        doc = self.repo.write(
            "README.md", "[s](https://example.com/?utm_source=readme)\n")
        findings = self.repo.check(doc)

        self.assertEqual(self.codes(findings), ["tracking-parameter"])

    def test_an_ordinary_query_string_is_not_flagged(self):
        doc = self.repo.write("README.md", "[s](https://example.com/?q=1)\n")
        self.assertEqual(self.repo.check(doc), [])

    def test_the_real_documents_carry_no_tracking_links(self):
        for name in dc.markdown_files():
            bad = [f for f in dc.check_file(name)
                   if f.code in ("tracking-parameter", "insecure-link")]
            self.assertEqual(bad, [], name)


class CommunityListTests(DocsCheckTestCase):
    def test_a_sorted_list_passes(self):
        doc = self.repo.write("README.md", LIST)
        self.assertEqual(self.repo.check_list(doc), [])

    def test_an_unsorted_list_is_an_error(self):
        doc = self.repo.write("README.md", LIST.replace(
            "- [Alpha](https://alpha.example/)\n"
            "- [Beta](https://beta.example/)",
            "- [Beta](https://beta.example/)\n"
            "- [Alpha](https://alpha.example/)"))
        findings = self.repo.check_list(doc)

        self.assertEqual(self.codes(findings), ["community-list-unsorted"])
        self.assertIn("Alpha, Beta", findings[0].detail)

    def test_sorting_ignores_case(self):
        doc = self.repo.write("README.md", LIST.replace("Beta", "beta"))
        self.assertEqual(self.repo.check_list(doc), [])

    def test_the_same_site_twice_is_an_error(self):
        doc = self.repo.write("README.md", LIST.replace(
            "- [Beta](https://beta.example/)",
            "- [Beta](https://www.alpha.example/shows)"))
        findings = self.repo.check_list(doc)

        self.assertIn("community-list-duplicate", self.codes(findings))

    def test_a_malformed_entry_is_an_error(self):
        doc = self.repo.write("README.md", LIST.replace(
            "- [Beta](https://beta.example/)", "- Beta: beta.example"))
        findings = self.repo.check_list(doc)

        self.assertIn("community-list-format", self.codes(findings))

    def test_an_http_entry_is_not_accepted_as_an_entry(self):
        doc = self.repo.write("README.md", LIST.replace(
            "https://beta.example/", "http://beta.example/"))
        self.assertIn("community-list-format",
                      self.codes(self.repo.check_list(doc)))

    def test_a_missing_end_marker_is_an_error(self):
        doc = self.repo.write(
            "README.md", LIST.replace(dc.COMMUNITY_END, ""))
        self.assertEqual(self.codes(self.repo.check_list(doc)),
                         ["community-list-unterminated"])

    def test_an_empty_list_is_a_warning(self):
        doc = self.repo.write("README.md", "{}\n{}\n".format(
            dc.COMMUNITY_START + " -->", dc.COMMUNITY_END))
        self.assertEqual(self.codes(self.repo.check_list(doc)),
                         ["community-list-empty"])

    def test_prose_about_the_markers_is_not_a_list(self):
        """CLAUDE.md documents the markers; that must not count as a list."""
        doc = self.repo.write("CLAUDE.md", (
            "The entries sit between `{}` and `{}` markers.\n".format(
                dc.COMMUNITY_START + " -->", dc.COMMUNITY_END)))
        self.assertEqual(self.repo.check_list(doc), [])

    def test_the_real_claude_md_is_not_treated_as_a_list(self):
        self.assertEqual(dc.check_community_list("CLAUDE.md"), [])

    def test_a_document_without_the_markers_is_not_checked(self):
        doc = self.repo.write("README.md", "# Nothing here\n")
        self.assertEqual(self.repo.check_list(doc), [])


class RealCommunityListTests(unittest.TestCase):
    """The list this repository actually ships."""

    def entries(self):
        with open(os.path.join(REPO_ROOT, "README.md"),
                  encoding="utf-8") as handle:
            return dc.community_entries(handle.read())

    def test_the_list_is_well_formed(self):
        self.assertEqual(dc.check_community_list("README.md"), [])

    def test_every_site_requested_in_an_issue_is_present(self):
        hosts = {url.split("//")[1].split("/")[0].replace("www.", "")
                 for _, _, url in self.entries()}
        self.assertEqual(hosts, {
            "teslalightshare.io",
            "teslalightshows.io",   # issue #62
            "xlightshows.io",
        })

    def test_entries_are_plain_links_with_no_marketing(self):
        for _, name, url in self.entries():
            self.assertTrue(name)
            self.assertTrue(url.startswith("https://"))
            self.assertNotIn("?", url)


class CommandTests(DocsCheckTestCase):
    """A renamed tool leaves the documentation telling people to run it."""

    def test_a_command_naming_a_missing_script_is_an_error(self):
        doc = self.repo.write("README.md",
                              "```\npython3 tools/gone.py drive\n```\n")
        findings = self.repo.check_commands(doc)

        self.assertEqual(self.codes(findings), ["command-not-found"])
        self.assertEqual(findings[0].severity, dc.ERROR)

    def test_a_command_naming_a_present_script_is_fine(self):
        self.repo.touch("tools/here.py")
        doc = self.repo.write("README.md", "```\npython3 tools/here.py\n```\n")
        self.assertEqual(self.repo.check_commands(doc), [])

    def test_a_script_at_the_repository_root_is_found(self):
        self.repo.touch("validator.py")
        doc = self.repo.write("README.md", "```\npython validator.py x.fseq\n```\n")
        self.assertEqual(self.repo.check_commands(doc), [])

    def test_each_missing_script_is_reported_once(self):
        doc = self.repo.write("README.md", (
            "```\npython3 tools/gone.py\n```\n"
            "```\npython3 tools/gone.py --json\n```\n"))
        self.assertEqual(len(self.repo.check_commands(doc)), 1)

    def test_the_real_documents_name_only_scripts_that_exist(self):
        for name in dc.markdown_files():
            self.assertEqual(dc.check_commands(name), [], name)


class IssueFormTests(unittest.TestCase):
    """Issues 110 and 115 both arrived with a title and nothing else.

    Markdown templates are a suggestion: the body can be deleted. Issue forms
    with required fields cannot be submitted empty, which is why these are
    YAML now.
    """

    TEMPLATE_DIR = os.path.join(REPO_ROOT, ".github", "ISSUE_TEMPLATE")

    def forms(self):
        return sorted(name for name in os.listdir(self.TEMPLATE_DIR)
                      if name.endswith(".yml") and name != "config.yml")

    def text(self, name):
        with open(os.path.join(self.TEMPLATE_DIR, name),
                  encoding="utf-8") as handle:
            return handle.read()

    def fields(self, name):
        """The (id, required) pairs in a form.

        A shape check on files this repository controls, not a YAML parser:
        every field is written as "- type:" with its id two lines of
        indentation in.
        """
        found = []
        current = None
        for line in self.text(name).splitlines():
            stripped = line.strip()
            if stripped.startswith("- type:"):
                current = {"type": stripped.split(":", 1)[1].strip(),
                           "id": None, "required": False}
                found.append(current)
            elif current is not None and stripped.startswith("id:"):
                current["id"] = stripped.split(":", 1)[1].strip()
            elif current is not None and stripped == "required: true":
                current["required"] = True
        return found

    def test_there_is_a_form_for_each_kind_of_report(self):
        self.assertEqual(self.forms(),
                         ["01-repository.yml", "02-vehicle.yml"])

    def test_every_form_declares_a_name_and_description(self):
        for name in self.forms():
            text = self.text(name)
            self.assertRegex(text, r"(?m)^name: \S", name)
            self.assertRegex(text, r"(?m)^description: \S", name)
            self.assertRegex(text, r"(?m)^body:", name)

    def test_every_form_has_at_least_one_required_field(self):
        """The whole point: an empty submission is refused."""
        for name in self.forms():
            required = [f for f in self.fields(name) if f["required"]]
            self.assertTrue(required, name)

    def test_every_input_field_has_an_id(self):
        for name in self.forms():
            for field in self.fields(name):
                if field["type"] == "markdown":
                    continue
                self.assertTrue(field["id"], "{}: {}".format(name, field))

    def test_field_ids_are_unique_within_a_form(self):
        for name in self.forms():
            ids = [f["id"] for f in self.fields(name) if f["id"]]
            self.assertEqual(len(ids), len(set(ids)), name)

    def test_every_form_asks_for_the_checker_output(self):
        for name in self.forms():
            self.assertIn("tools/diagnose.py", self.text(name), name)

    def test_the_vehicle_form_requires_the_vehicle_and_software_version(self):
        required = {f["id"] for f in self.fields("02-vehicle.yml")
                    if f["required"]}
        self.assertIn("vehicle", required)
        self.assertIn("software", required)
        self.assertIn("Tesla service", self.text("02-vehicle.yml"))

    def test_the_chooser_sends_the_three_common_cases_elsewhere(self):
        config = self.text("config.yml")

        self.assertIn("smeighan/xLights/issues", config)
        self.assertIn("CONTRIBUTING.md", config)
        self.assertIn("download_a_show", config)

    def test_blank_issues_are_off_now_that_two_have_arrived_empty(self):
        """Reversed after issue 115.

        #110 kept them on so that anyone who did not fit a template was not
        pushed into the wrong one. #115 arrived empty the same way, and the
        contact links cover the cases the forms do not, so the balance
        changed.
        """
        self.assertIn("blank_issues_enabled: false", self.text("config.yml"))

    def test_the_forms_are_checked_for_the_commands_they_name(self):
        forms = dc.issue_template_files()

        self.assertTrue(forms)
        for form in forms:
            self.assertEqual(dc.check_commands(form), [], form)


class DownloadRouteTests(unittest.TestCase):
    """The project folder must not be reachable by only one host.

    Issues 101 and 106 are both "I cannot download the show folder", and a
    ?raw=true link leaves github.com for raw.githubusercontent.com, which
    some networks block on its own. The README has to offer routes that do
    not share that dependency.
    """

    def readme(self):
        with open(os.path.join(REPO_ROOT, "README.md"),
                  encoding="utf-8") as handle:
            return handle.read()

    def test_every_documented_host_is_named(self):
        text = self.readme()
        for host in ("raw.githubusercontent.com", "github.com",
                     "codeload.github.com"):
            self.assertIn(host, text, host)

    def test_the_alternatives_are_still_documented(self):
        text = self.readme()
        self.assertIn("git clone https://github.com/teslamotors/light-show.git",
                      text)
        self.assertIn("Download ZIP", text)

    def test_the_symptom_is_named_so_it_can_be_searched_for(self):
        self.assertIn("file not found", self.readme())

    def test_it_says_no_lfs_is_involved(self):
        # The repository-side cause, ruled out in the same place.
        self.assertIn("Git LFS", self.readme())


class UnreferencedImageTests(DocsCheckTestCase):
    def test_an_unused_image_is_a_note(self):
        self.repo.touch("images/used.png")
        self.repo.touch("images/spare.png")
        self.repo.write("README.md", '<img src="/images/used.png" />\n')
        findings = dc.check_unreferenced_images(self.repo.root)

        self.assertEqual(self.codes(findings), ["unreferenced-image"])
        self.assertEqual(findings[0].severity, dc.INFO)
        self.assertIn("spare.png", findings[0].detail)

    def test_images_used_by_any_document_count_as_used(self):
        self.repo.touch("images/shared.png")
        self.repo.write("README.md", "# No images\n")
        self.repo.write("examples/x/README.md",
                        '<img src="/images/shared.png" />\n')
        self.assertEqual(dc.check_unreferenced_images(self.repo.root), [])


class WholeRepositoryTests(unittest.TestCase):
    def test_the_repository_documentation_is_consistent(self):
        serious = [f for f in dc.check_all()
                   if f.severity in (dc.ERROR, dc.WARNING)]
        self.assertEqual(
            [], serious,
            "\n".join("{}:{} {}".format(f.file, f.line, f.summary)
                      for f in serious))

    def test_every_markdown_file_is_checked(self):
        names = dc.markdown_files()
        self.assertIn("README.md", names)
        self.assertIn("CLAUDE.md", names)
        self.assertTrue(
            any(n.startswith("examples/") for n in names), names)


class CommandLineTests(unittest.TestCase):
    def run_main(self, *argv):
        stdout = io.StringIO()
        original = sys.stdout
        sys.stdout = stdout
        try:
            code = dc.main(list(argv))
        finally:
            sys.stdout = original
        return code, stdout.getvalue()

    def test_a_clean_repository_exits_zero(self):
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("Documentation links are consistent.", out)

    def test_json_output_parses(self):
        code, out = self.run_main("--json")
        payload = json.loads(out)

        self.assertEqual(code, 0)
        self.assertIn("README.md", payload["documents"])
        self.assertIsInstance(payload["findings"], list)

    def test_notes_are_hidden_unless_verbose(self):
        quiet = self.run_main()[1]
        loud = self.run_main("-v")[1]
        self.assertLessEqual(len(quiet), len(loud))


if __name__ == "__main__":
    unittest.main()
