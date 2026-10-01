import base64
import copy
import csv
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from kobo_sync.sync import (Kobo, SyncError, load_config, merge, reconcile)


CONFIG = {
    "server": "https://kf.kobotoolbox.org", "source_asset_uid": "aSource",
    "target_asset_uid": "aSource", "csv_filename": "choices.csv",
    "select_field": "group/person", "other_value": "other",
    "text_field": "group/other", "extra_columns": {},
    "max_label_length": 200, "page_size": 2, "max_pages": 10,
}
SEED = b"name,label\nalice,Alice\nother,Other (specify)\n"


def submission(text):
    return {"group/person": "other", "group/other": text}


class FakeKobo:
    """Stateful API double: enforces duplicate-file constraints and deployment failure."""
    def __init__(self):
        self.files = {}
        self.counter = 0
        self.put("choices.csv", SEED)
        self.records = [submission("Carol")]
        self.calls = []
        self.deployed = 0
        self.fail_upload = False
        self.fail_deploy = False
        self.asset = {"has_deployment": True, "deployment__active": True,
                      "version_id": "v1", "deployed_version_id": "v1"}

    def put(self, name, content):
        self.counter += 1
        f = {"uid": "f" + str(self.counter), "file_type": "form_media", "metadata": {"filename": name}}
        self.files[name] = (f, content)
        return f

    def pages(self, path, max_pages):
        if "data/?" in path:
            yield from self.records
        else:
            yield from [copy.deepcopy(v[0]) for v in self.files.values()]

    def request(self, method, path, payload=None, raw=False):
        self.calls.append((method, path, payload))
        if path.endswith("deployment/"):
            if self.fail_deploy:
                raise SyncError("Injected redeployment failure")
            assert payload == {"version_id": "v1"}
            self.deployed += 1
            return {}
        if "/files/" not in path:
            return copy.deepcopy(self.asset)
        if method == "POST":
            name = payload["metadata"]["filename"]
            if name in self.files:
                raise SyncError("Duplicate media filename")
            if name == "choices.csv" and self.fail_upload:
                self.fail_upload = False
                raise SyncError("Injected upload failure")
            assert payload["base64Encoded"].startswith("data:text/csv;base64,")
            return self.put(name, base64.b64decode(payload["base64Encoded"].split(",", 1)[1]))
        uid = path.split("/files/")[1].split("/")[0]
        for name, (f, data) in list(self.files.items()):
            if uid == f["uid"]:
                if method == "DELETE":
                    del self.files[name]
                    return None
                return data
        raise SyncError("Missing media")


class MergeTests(unittest.TestCase):
    def test_normalized_duplicates_and_retry(self):
        result, count = merge(SEED, [submission("  ALICE "), submission("Ｃａｒｏｌ"), submission("carol")], CONFIG)
        self.assertEqual(count, 1)
        self.assertIn(b"alice,Alice", result)
        self.assertIn(b"carol,Carol", result)
        self.assertEqual(merge(result, [submission("Carol")], CONFIG), (result, 0))

    def test_quotes_commas_unicode(self):
        result, count = merge(SEED, [submission('Renée, "R"')], CONFIG)
        self.assertEqual(count, 1)
        self.assertIn('"Renée, ""R"""'.encode(), result)
        self.assertIn(b'renee_r,', result)

    def test_readable_names_and_collisions(self):
        data, count = merge(SEED, [submission("Taylor"), submission("Édouard"),
                                   submission("John Doe"), submission("John-Doe")], CONFIG)
        self.assertEqual(count, 4)
        rows = list(csv.DictReader(io.StringIO(data.decode())))
        names = {row["label"]: row["name"] for row in rows}
        self.assertEqual(names["Taylor"], "james")
        self.assertEqual(names["Édouard"], "edouard")
        self.assertEqual(names["John Doe"], "john_doe")
        self.assertRegex(names["John-Doe"], r"^john_doe_[0-9a-f]{8}$")
        self.assertEqual(merge(data, [submission("TAYLOR"), submission("John-Doe")], CONFIG), (data, 0))

    def test_existing_choice_ids_remain_stable(self):
        old = b"name,label\nother,Other (specify)\nauto_123,Taylor\n"
        data, count = merge(old, [submission("Taylor"), submission("Bob")], CONFIG)
        self.assertEqual(count, 1)
        self.assertIn(b"auto_123,Taylor", data)
        self.assertIn(b"bob,Bob", data)

    def test_reserved_name_uses_suffix(self):
        data, count = merge(SEED, [submission("Other")], CONFIG)
        self.assertEqual(count, 1)
        self.assertRegex(data.decode(), r"other_[0-9a-f]{8},Other")

    def test_skip_regular_answers(self):
        self.assertEqual(merge(SEED, [{"group/person": "alice", "group/other": "stale"}], CONFIG), (SEED, 0))

    def test_invalid_other_aborts(self):
        for value in (None, "", [], "X" * 201, "X\x00Y"):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(SyncError):
                merge(SEED, [submission(value)], CONFIG)

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(SyncError):
            merge(SEED + b"alice,Something else\n", [], CONFIG)

    def test_missing_other_rejected_for_same_form(self):
        with self.assertRaises(SyncError):
            merge(b"name,label\na,A\n", [], CONFIG)

    def test_cross_form_without_other(self):
        c = {**CONFIG, "target_asset_uid": "aTarget"}
        self.assertEqual(merge(b"name,label\n", [submission("Carol")], c)[1], 1)

    def test_bom_and_no_change_preserves_bytes(self):
        data = b"\xef\xbb\xbf" + SEED.replace(b"\n", b"\r\n")
        self.assertEqual(merge(data, [], CONFIG), (data, 0))

    def test_filter_column_scopes_identity(self):
        c = {**CONFIG, "extra_columns": {"district": "group/district"}}
        seed = b"name,label,district\na,Alice,north\nother,Other,north\n"
        rows = [{**submission("Alice"), "group/district": "south"},
                {**submission("ALICE"), "group/district": "north"}]
        result, count = merge(seed, rows, c)
        self.assertEqual(count, 1)
        self.assertIn(b",Alice,south", result)

    def test_unmapped_extra_columns_abort(self):
        with self.assertRaises(SyncError):
            merge(b"name,label,district\nother,Other,north\n", [], CONFIG)

    def test_wrong_field_path_fails_instead_of_silent_noop(self):
        with self.assertRaises(SyncError):
            merge(SEED, [{"wrong_path": "other"}], CONFIG)


class ReconcileTests(unittest.TestCase):
    def run_sync(self, api, dry_run=False):
        with redirect_stdout(io.StringIO()) as out:
            reconcile(api, CONFIG, dry_run)
        return out.getvalue()

    def test_sync_then_noop(self):
        api = FakeKobo()
        output = self.run_sync(api)
        self.assertNotIn("Carol", output)
        self.assertIn(b"Carol", api.files["choices.csv"][1])
        self.assertEqual(list(api.files), ["choices.csv"])
        self.assertEqual(api.deployed, 1)
        self.run_sync(api)
        self.assertEqual(api.deployed, 1)

    def test_dry_run_no_mutations(self):
        api = FakeKobo()
        self.run_sync(api, True)
        self.assertTrue(all(method == "GET" for method, _, _ in api.calls))
        self.assertEqual(api.files["choices.csv"][1], SEED)

    def test_upload_failure_restores_original_then_catches_up(self):
        api = FakeKobo()
        api.fail_upload = True
        with self.assertRaises(SyncError):
            self.run_sync(api)
        self.assertEqual(api.files["choices.csv"][1], SEED)
        self.assertIn("choices_sync_recovery.csv", api.files)
        self.run_sync(api)
        self.assertIn(b"Carol", api.files["choices.csv"][1])
        self.assertEqual(api.deployed, 1)

    def test_deploy_failure_is_retried_even_without_new_choices(self):
        api = FakeKobo()
        api.fail_deploy = True
        with self.assertRaises(SyncError):
            self.run_sync(api)
        self.assertIn("choices_sync_recovery.csv", api.files)
        api.fail_deploy = False
        self.run_sync(api)
        self.assertEqual(api.deployed, 1)
        self.assertNotIn("choices_sync_recovery.csv", api.files)

    def test_interruption_after_delete_recovers(self):
        api = FakeKobo()
        api.put("choices_sync_recovery.csv", SEED)
        del api.files["choices.csv"]
        self.run_sync(api)
        self.assertIn(b"Carol", api.files["choices.csv"][1])
        self.assertEqual(api.deployed, 1)

    def test_draft_and_archived_guard(self):
        for change in ({"version_id": "v2"}, {"deployment__active": False}, {"has_deployment": False}):
            api = FakeKobo()
            api.asset.update(change)
            with self.assertRaises(SyncError):
                self.run_sync(api)
            self.assertTrue(all(method == "GET" for method, _, _ in api.calls))

    def test_bad_submission_prevents_any_write(self):
        api = FakeKobo()
        api.records.append(submission(None))
        with self.assertRaises(SyncError):
            self.run_sync(api)
        self.assertTrue(all(method == "GET" for method, _, _ in api.calls))

    def test_failed_backup_does_not_delete_original(self):
        api = FakeKobo()
        original_request = api.request

        def fail_backup(method, path, payload=None, raw=False):
            if method == "POST":
                raise SyncError("Injected backup failure")
            return original_request(method, path, payload, raw)

        with patch.object(api, "request", side_effect=fail_backup), self.assertRaises(SyncError):
            self.run_sync(api)
        self.assertEqual(api.files["choices.csv"][1], SEED)
        self.assertFalse(any(method == "DELETE" for method, _, _ in api.calls))

    def test_later_data_page_failure_does_not_write(self):
        api = FakeKobo()
        original_pages = api.pages

        def broken_pages(path, maximum):
            if "data/?" in path:
                yield submission("Carol")
                raise SyncError("Injected pagination failure")
            yield from original_pages(path, maximum)

        with patch.object(api, "pages", side_effect=broken_pages), self.assertRaises(SyncError):
            self.run_sync(api)
        self.assertTrue(all(method == "GET" for method, _, _ in api.calls))


class ClientTests(unittest.TestCase):
    def test_real_request_serialization(self):
        api = Kobo(CONFIG["server"], "fake-token")
        response = io.BytesIO(b'{"ok":true}')
        with patch.object(api.opener, "open", return_value=response) as network:
            result = api.request("POST", "/api/test/", {"value": "Renée"})
        req = network.call_args.args[0]
        self.assertEqual(req.get_header("Authorization"), "Token fake-token")
        self.assertEqual(req.method, "POST")
        self.assertEqual(json.loads(req.data), {"value": "Renée"})
        self.assertEqual(result, {"ok": True})

    def test_http_error_never_leaks_body_or_url(self):
        api = Kobo(CONFIG["server"], "fake-token")
        error = HTTPError("https://private.example/secret", 403, "Private Name", {}, io.BytesIO(b"sensitive-data"))
        with patch.object(api.opener, "open", side_effect=error), self.assertRaises(SyncError) as caught:
            api.request("GET", "/api/test/")
        self.assertIn("HTTP 403", str(caught.exception))
        self.assertNotIn("Private", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))

    def test_read_retried_but_uncertain_write_not_retried(self):
        api = Kobo(CONFIG["server"], "fake-token")
        with patch.object(api.opener, "open", side_effect=[URLError("network"), io.BytesIO(b"{}")] ) as network, patch("kobo_sync.sync.time.sleep"):
            self.assertEqual(api.request("GET", "/api/test/"), {})
            self.assertEqual(network.call_count, 2)
        with patch.object(api.opener, "open", side_effect=URLError("network")) as network, self.assertRaises(SyncError):
            api.request("POST", "/api/test/", {})
        self.assertEqual(network.call_count, 1)

    def test_redirects_are_not_followed(self):
        from kobo_sync.sync import NoRedirect
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))

    def test_cross_origin_is_blocked_before_network(self):
        api = Kobo(CONFIG["server"], "fake-token")
        with patch.object(api.opener, "open") as network:
            with self.assertRaises(SyncError):
                api.request("GET", "https://example.org/steal")
            network.assert_not_called()

    def test_all_pages_consumed(self):
        api = Kobo(CONFIG["server"], "fake-token")
        with patch.object(api, "request", side_effect=[{"results": [1], "next": "/page2"}, {"results": [2], "next": None}]):
            self.assertEqual(list(api.pages("/page1", 10)), [1, 2])

    def test_loop_and_page_limit_fail(self):
        api = Kobo(CONFIG["server"], "fake-token")
        with patch.object(api, "request", return_value={"results": [1], "next": "/page1"}):
            with self.assertRaises(SyncError):
                list(api.pages("/page1", 10))
        with patch.object(api, "request", return_value={"results": [1], "next": "/page2"}):
            with self.assertRaises(SyncError):
                list(api.pages("/page1", 1))

    def test_valid_and_placeholder_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(CONFIG), encoding="utf-8")
            self.assertEqual(load_config(str(path)), CONFIG)
            path.write_text(json.dumps({**CONFIG, "source_asset_uid": "REPLACE_UID"}), encoding="utf-8")
            with self.assertRaises(SyncError):
                load_config(str(path))


if __name__ == "__main__":
    unittest.main()
