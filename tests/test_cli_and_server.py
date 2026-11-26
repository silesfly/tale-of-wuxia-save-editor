"""협객풍운전 세이브 에디터 CLI 및 로컬 루프백 브리지 서버 표준 라이브러리 단위 테스트."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.request
from pathlib import Path

from twx_editor import (
    _capture_root_identity,
    _posix_supports_rename_exchange,
    _slot_backup_prefix,
    _slot_lock_guard,
    _store_lock_guard,
    atomic_save_with_backup,
    create_bridge_server,
    create_demo_data,
    discover_roots,
    is_backup_for_slot,
    list_slots,
    main,
    parse_json_lossless,
    read_safe_bytes,
    resolve_safe_save_path,
    restore_backup,
    serialize_json_lossless,
    validate_data,
)


class TestTwxEditorCliAndServer(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = os.path.realpath(tempfile.mkdtemp(prefix="twx_py_test_"))
        self.root = Path(self.tmp_dir)
        self.demo_save = create_demo_data("save")
        self.save0 = self.root / "Save0.Save"
        self.save0.write_text(serialize_json_lossless(self.demo_save), encoding="utf-8")

        title_init = [
            {
                "m_bHaveData": False,
                "m_strPlayerName": "",
                "m_strPlaceName": "",
                "m_strYear": "1",
                "m_strMonth": "",
                "m_strTime": "",
                "m_strPlayerIconName": "900005",
                "m_strTrueYear": "2026/11/18",
                "m_strTrueTime": "12\uff1a00",
            }
        ]
        (self.root / "SaveTitle.SaveTitle").write_text(
            serialize_json_lossless(title_init), encoding="utf-8"
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_lossless_codec_and_types(self) -> None:
        raw = '\ufeff{"flag":true,"count":1,"sci":30e-4,"flt":2.67857671,"tag":"\\u003Cbr>","kor":"\\uB3D9\\uBC29\\r"}\r\n'
        data, meta = parse_json_lossless(raw)
        self.assertIs(data["flag"], True)
        self.assertIsInstance(data["count"], int)
        self.assertNotIsInstance(data["count"], bool)
        self.assertEqual(serialize_json_lossless(data, meta), raw)

        data["count"] = 42
        updated = serialize_json_lossless(data, meta)
        self.assertIn('"count":42', updated)
        self.assertIn('"sci":30e-4', updated)
        self.assertIn('"flt":2.67857671', updated)

        arr_data, arr_meta = parse_json_lossless('{"vals":[99,1.0e-5,"\\u003Cx>"]}')
        del arr_data["vals"][0]
        arr_data["vals"].append(7)
        self.assertEqual(
            serialize_json_lossless(arr_data, arr_meta),
            '{"vals":[1.0e-5,"\\u003Cx>",7]}',
        )

        edge = create_demo_data("save")
        edge["m_iNowTime"] = 0
        edge["m_iBattleDifficulty"] = 8
        edge["m_BackpackList"][0]["m_iAmount"] = 0
        edge["m_PlayerRoutineNodeList"][0]["m_iLV"] = 0
        edge["m_NpcFriendlyNodeList"][0]["m_iFriendly"] = -50
        edge["m_teamMemberList"] = list(range(1, 11))
        self.assertEqual(validate_data(edge), "save")

        bad = create_demo_data("save")
        bad["m_teamMemberList"] = [-1]
        with self.assertRaises(ValueError):
            validate_data(bad)

    def test_safe_path_and_symlink_guards(self) -> None:
        for bad in ("../outside.Save", "Save0.Save:ads", "CON.Save", "NUL", "COM1.Save", "/etc/passwd"):
            with self.assertRaises(ValueError):
                resolve_safe_save_path(self.root, bad)

        outside_dir = Path(tempfile.mkdtemp(prefix="twx_outside_"))
        try:
            secret = outside_dir / "secret.Save"
            secret.write_text("{}", encoding="utf-8")
            sym_file = self.root / "SymSlot.Save"
            sym_dir = self.root / "symdir"
            os.symlink(secret, sym_file)
            os.symlink(outside_dir, sym_dir)
            with self.assertRaises(ValueError):
                resolve_safe_save_path(self.root, "SymSlot.Save")
            with self.assertRaises(ValueError):
                resolve_safe_save_path(self.root, "symdir/secret.Save")
        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)

    def test_atomic_save_companion_title_and_restore(self) -> None:
        orig_bytes = self.save0.read_bytes()
        edited = create_demo_data("save")
        edited["m_iMoney"] = 7777777
        edited["m_iYear"] = 4
        res = atomic_save_with_backup(self.root, "Save0.Save", serialize_json_lossless(edited))
        self.assertTrue(res["ok"])
        self.assertTrue(res["backup"].endswith(".bak"))

        title_parsed, _ = parse_json_lossless((self.root / "SaveTitle.SaveTitle").read_text(encoding="utf-8"))
        self.assertEqual(validate_data(title_parsed), "title")
        self.assertTrue(title_parsed[0]["m_bHaveData"])
        self.assertEqual(title_parsed[0]["m_strYear"], "4")

        restore_res = restore_backup(self.root, res["backup"], "Save0.Save")
        self.assertTrue(restore_res["ok"])
        self.assertEqual(self.save0.read_bytes(), orig_bytes)
        title_restored, _ = parse_json_lossless((self.root / "SaveTitle.SaveTitle").read_bytes().decode("utf-8"))
        self.assertEqual(title_restored[0]["m_strYear"], "2")

        # Cross-slot schema mismatch must be rejected
        with self.assertRaises(ValueError):
            atomic_save_with_backup(self.root, "Round.dat", serialize_json_lossless(edited))

        # UTF-8 BOM preservation when browser strips leading BOM from text
        self.save0.write_bytes(b"\xef\xbb\xbf" + orig_bytes)
        atomic_save_with_backup(self.root, "Save0.Save", serialize_json_lossless(edited))
        self.assertTrue(self.save0.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.save0.write_bytes(orig_bytes)

        # Malformed companion SaveTitle.SaveTitle must abort BEFORE modifying Save0.Save
        (self.root / "SaveTitle.SaveTitle").write_bytes(b"{corrupted_json")
        with self.assertRaises(ValueError):
            atomic_save_with_backup(self.root, "Save0.Save", serialize_json_lossless(edited))
        self.assertEqual(self.save0.read_bytes(), orig_bytes)

    def test_game_running_guard(self) -> None:
        os.environ["TWX_SIMULATE_GAME_RUNNING"] = "1"
        try:
            with self.assertRaises(RuntimeError) as ctx:
                atomic_save_with_backup(self.root, "Save0.Save", self.save0.read_text(encoding="utf-8"))
            self.assertEqual(str(ctx.exception), "GAME_RUNNING")
        finally:
            os.environ.pop("TWX_SIMULATE_GAME_RUNNING", None)

    def test_cli_subcommands(self) -> None:
        round_out = self.root / "Round.dat"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main(["demo", "--kind", "round", "--out", str(round_out)]), 0)
            self.assertEqual(main(["validate", str(round_out)]), 0)
            self.assertEqual(main(["inspect", "--json", str(self.save0)]), 0)
            self.assertEqual(main(["presets", "--json"]), 0)
            self.assertEqual(main(["apply", str(self.save0), "--preset", "max_money", "--root", str(self.root)]), 0)

        after_apply, _ = parse_json_lossless(self.save0.read_text(encoding="utf-8"))
        self.assertEqual(after_apply["m_iMoney"], 9999999)

    def test_bridge_server_security_and_api_roundtrip(self) -> None:
        srv = create_bridge_server(self.root, "127.0.0.1", 0)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        base = f"http://127.0.0.1:{port}"

        def expect_http_error(req: urllib.request.Request, expected_code: int) -> None:
            try:
                with urllib.request.urlopen(req, timeout=5):
                    self.fail(f"Expected HTTP {expected_code}")
            except urllib.error.HTTPError as err:
                try:
                    self.assertEqual(err.code, expected_code)
                finally:
                    err.close()

        try:
            with urllib.request.urlopen(f"{base}/", timeout=5) as resp:
                html = resp.read().decode("utf-8")
            self.assertIn("connect-src 'self'", html)
            m = re.search(r'<meta name="twx-bridge-token" content="([^"]+)">', html)
            self.assertIsNotNone(m)
            token = m.group(1) if m else ""

            with urllib.request.urlopen(f"{base}/api/health", timeout=5) as resp:
                health = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(health.get("ok"), True)
            self.assertNotIn("token", health)

            # Security checks: missing token, Origin: null, spoofed Origin, bad Host, cross-site
            expect_http_error(urllib.request.Request(f"{base}/api/slots"), 403)
            expect_http_error(
                urllib.request.Request(f"{base}/api/slots", headers={"X-TWX-Token": token, "Origin": "null"}),
                403,
            )
            expect_http_error(
                urllib.request.Request(
                    f"{base}/api/slots",
                    headers={"X-TWX-Token": token, "Origin": "http://127.0.0.1.evil.com"},
                ),
                403,
            )
            expect_http_error(
                urllib.request.Request(f"{base}/api/slots", headers={"X-TWX-Token": token, "Host": "evil.com"}),
                403,
            )
            expect_http_error(
                urllib.request.Request(
                    f"{base}/api/slots",
                    headers={"X-TWX-Token": token, "Sec-Fetch-Site": "cross-site"},
                ),
                403,
            )

            # Authorized workflow: slots -> load -> save -> backups -> restore
            hdrs = {"X-TWX-Token": token, "Origin": base}
            with urllib.request.urlopen(urllib.request.Request(f"{base}/api/slots", headers=hdrs), timeout=5) as resp:
                slots_payload = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(any(s["slot"] == "Save0.Save" for s in slots_payload["slots"]))

            with urllib.request.urlopen(
                urllib.request.Request(f"{base}/api/load?slot=Save0.Save", headers=hdrs), timeout=5
            ) as resp:
                loaded_raw = resp.read().decode("utf-8")
                base_sha = resp.headers.get("X-TWX-Sha256") or ""
            self.assertEqual(len(base_sha), 64)
            loaded_data, loaded_meta = parse_json_lossless(loaded_raw)
            loaded_data["m_iMoney"] = 8888888
            new_raw = serialize_json_lossless(loaded_data, loaded_meta)

            post_hdrs = {"X-TWX-Token": token, "Origin": base, "Content-Type": "application/json"}
            save_req = urllib.request.Request(
                f"{base}/api/save",
                data=json.dumps({"slot": "Save0.Save", "text": new_raw, "baseSha256": base_sha}).encode("utf-8"),
                headers=post_hdrs,
                method="POST",
            )
            with urllib.request.urlopen(save_req, timeout=5) as resp:
                save_res = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(save_res["ok"])

            stale_req = urllib.request.Request(
                f"{base}/api/save",
                data=json.dumps({"slot": "Save0.Save", "text": new_raw, "baseSha256": base_sha}).encode("utf-8"),
                headers=post_hdrs,
                method="POST",
            )
            expect_http_error(stale_req, 409)

            missing_base_req = urllib.request.Request(
                f"{base}/api/save",
                data=json.dumps({"slot": "Save0.Save", "text": new_raw}).encode("utf-8"),
                headers=post_hdrs,
                method="POST",
            )
            expect_http_error(missing_base_req, 400)

            with urllib.request.urlopen(
                urllib.request.Request(f"{base}/api/backups?slot=Save0.Save", headers=hdrs), timeout=5
            ) as resp:
                baks = json.loads(resp.read().decode("utf-8"))["backups"]
            self.assertGreaterEqual(len(baks), 1)

            os.environ["TWX_SIMULATE_GAME_RUNNING"] = "1"
            try:
                blocked_req = urllib.request.Request(
                    f"{base}/api/save",
                    data=json.dumps(
                        {"slot": "Save0.Save", "text": new_raw, "baseSha256": save_res["sha256"]}
                    ).encode("utf-8"),
                    headers=post_hdrs,
                    method="POST",
                )
                expect_http_error(blocked_req, 409)
            finally:
                os.environ.pop("TWX_SIMULATE_GAME_RUNNING", None)

            restore_req = urllib.request.Request(
                f"{base}/api/restore",
                data=json.dumps({"slot": "Save0.Save", "backup": baks[0]["name"]}).encode("utf-8"),
                headers=post_hdrs,
                method="POST",
            )
            with urllib.request.urlopen(restore_req, timeout=5) as resp:
                restored = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(restored["ok"])
            check_data, _ = parse_json_lossless(self.save0.read_text(encoding="utf-8"))
            self.assertEqual(check_data["m_iMoney"], self.demo_save["m_iMoney"])
        finally:
            srv.shutdown()
            srv.server_close()
            th.join(timeout=3)

    def test_cross_slot_backup_restore_rejection(self) -> None:
        slot = {
            "m_bHaveData": False,
            "m_strPlayerName": "",
            "m_strPlaceName": "",
            "m_strYear": "1",
            "m_strMonth": "",
            "m_strTime": "",
            "m_strPlayerIconName": "900005",
            "m_strTrueYear": "2026/11/18",
            "m_strTrueTime": "12\uff1a00",
        }
        (self.root / "SaveTitle.SaveTitle").write_text(
            serialize_json_lossless([dict(slot) for _ in range(11)]), encoding="utf-8"
        )
        raw_demo = serialize_json_lossless(self.demo_save)
        (self.root / "Save1.Save").write_text(raw_demo, encoding="utf-8")
        (self.root / "Save10.Save").write_text(raw_demo, encoding="utf-8")
        save0_bak = atomic_save_with_backup(self.root, "Save0.Save", raw_demo)["backup"]
        save1_bak = atomic_save_with_backup(self.root, "Save1.Save", raw_demo)["backup"]
        save10_bak = atomic_save_with_backup(self.root, "Save10.Save", raw_demo)["backup"]

        sub = self.root / "sub"
        sub.mkdir(exist_ok=True)
        (sub / "Save1.Save").write_text(raw_demo, encoding="utf-8")
        sub_save1_bak = atomic_save_with_backup(self.root, "sub/Save1.Save", raw_demo)["backup"]

        guid_id = "362d07a4-5ce8-4d7b-878e-7955e689f209"
        raw_guid = serialize_json_lossless(create_demo_data("guid"))
        (self.root / guid_id).write_text(raw_guid, encoding="utf-8")
        (self.root / f"{guid_id}.Save").write_text(raw_guid, encoding="utf-8")
        guid_bak = atomic_save_with_backup(self.root, guid_id, raw_guid)["backup"]
        guid_save_bak = atomic_save_with_backup(self.root, f"{guid_id}.Save", raw_guid)["backup"]

        self.assertTrue(is_backup_for_slot(save1_bak, "Save1.Save"))
        self.assertFalse(is_backup_for_slot(save1_bak, "Save1"))
        self.assertFalse(is_backup_for_slot(save1_bak, "sub/Save1.Save"))
        self.assertTrue(is_backup_for_slot(sub_save1_bak, "sub/Save1.Save"))
        self.assertFalse(is_backup_for_slot(sub_save1_bak, "Save1.Save"))
        self.assertTrue(is_backup_for_slot(guid_bak, guid_id))
        self.assertFalse(is_backup_for_slot(guid_bak, f"{guid_id}.Save"))
        self.assertTrue(is_backup_for_slot(guid_save_bak, f"{guid_id}.Save"))
        self.assertFalse(is_backup_for_slot(guid_save_bak, guid_id))

        with self.assertRaises(ValueError):
            restore_backup(self.root, save0_bak, "Save1.Save")
        with self.assertRaises(ValueError):
            restore_backup(self.root, save1_bak, "sub/Save1.Save")
        with self.assertRaises(ValueError):
            restore_backup(self.root, sub_save1_bak, "Save1.Save")
        with self.assertRaises(ValueError):
            restore_backup(self.root, guid_bak, f"{guid_id}.Save")
        with self.assertRaises(ValueError):
            restore_backup(self.root, guid_save_bak, guid_id)

        srv = create_bridge_server(self.root, "127.0.0.1", 0)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            port = srv.server_address[1]
            base = f"http://127.0.0.1:{port}"
            token = srv.bridge_token
            hdrs = {"X-TWX-Token": token, "Origin": base}

            def fetch_backups(slot_q: str) -> dict:
                req = urllib.request.Request(f"{base}/api/backups?slot={slot_q}", headers=hdrs)
                with urllib.request.urlopen(req, timeout=5) as r:
                    return json.loads(r.read().decode("utf-8"))

            body = fetch_backups("Save1.Save")
            names = [x["name"] for x in body["backups"]]
            self.assertIn(save1_bak, names)
            self.assertNotIn(save0_bak, names)
            self.assertNotIn(save10_bak, names)
            self.assertNotIn(sub_save1_bak, names)

            body = fetch_backups("Save1")
            names = [x["name"] for x in body["backups"]]
            self.assertNotIn(save1_bak, names)

            body = fetch_backups("sub/Save1.Save")
            names = [x["name"] for x in body["backups"]]
            self.assertIn(sub_save1_bak, names)
            self.assertNotIn(save1_bak, names)

            data = json.dumps({"slot": "Save1.Save", "backup": save0_bak}).encode("utf-8")
            req = urllib.request.Request(
                f"{base}/api/restore",
                data=data,
                headers={**hdrs, "Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=5)
            try:
                self.assertEqual(cm.exception.code, 400)
            finally:
                cm.exception.close()
        finally:
            srv.shutdown()
            srv.server_close()
            th.join(timeout=3)

    def test_cli_apply_out_guards_and_backup(self) -> None:
        draft = self.root / "Draft.json"
        draft.write_text(serialize_json_lossless(self.demo_save), encoding="utf-8")
        orig_bytes = self.save0.read_bytes()
        os.environ["TWX_SIMULATE_GAME_RUNNING"] = "1"
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main(["apply", str(draft), "--preset", "max_money", "--out", str(self.save0)])
            self.assertEqual(code, 1)
            self.assertEqual(self.save0.read_bytes(), orig_bytes)
        finally:
            os.environ.pop("TWX_SIMULATE_GAME_RUNNING", None)

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(
                main(["apply", str(draft), "--preset", "max_money", "--out", str(self.save0)]), 0
            )
        backup_dir = self.root / "backups"
        self.assertTrue(any(is_backup_for_slot(p.name, "Save0.Save") for p in backup_dir.iterdir()))
        title_data = parse_json_lossless((self.root / "SaveTitle.SaveTitle").read_text(encoding="utf-8"))[0]
        self.assertIs(title_data[0]["m_bHaveData"], True)

        sym = self.root / "SymIn.Save"
        os.symlink(draft, sym)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(
                main(["apply", str(sym), "--preset", "max_money", "--out", str(self.save0)]), 1
            )

    def test_title_write_failure_rollback(self) -> None:
        orig_bytes = self.save0.read_bytes()
        edited = create_demo_data("save")
        edited["m_iMoney"] = 1234567
        os.environ["TWX_SIMULATE_TITLE_WRITE_FAIL"] = "1"
        try:
            with self.assertRaises(OSError):
                atomic_save_with_backup(self.root, "Save0.Save", serialize_json_lossless(edited))
            self.assertEqual(self.save0.read_bytes(), orig_bytes)
        finally:
            os.environ.pop("TWX_SIMULATE_TITLE_WRITE_FAIL", None)

    def test_bridge_server_strict_port_and_host_guards(self) -> None:
        srv = create_bridge_server(self.root, "127.0.0.1", 0)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            port = srv.server_address[1]
            base = f"http://127.0.0.1:{port}"
            token = srv.bridge_token
            bad_port = 9999 if port != 9999 else 9998
            cases = (
                {"X-TWX-Token": token, "Origin": f"http://127.0.0.1:{bad_port}"},
                {"X-TWX-Token": token, "Origin": f"http://127.0.0.1:{port}?"},
                {"X-TWX-Token": token, "Origin": f"http://127.0.0.1:{port}#"},
                {"X-TWX-Token": token, "Host": "127.0.0.1"},
                {"X-TWX-Token": token, "Host": "localhost"},
            )
            for headers in cases:
                req = urllib.request.Request(f"{base}/api/slots", headers=headers)
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(req, timeout=5)
                try:
                    self.assertEqual(cm.exception.code, 403)
                finally:
                    cm.exception.close()
        finally:
            srv.shutdown()
            srv.server_close()
            th.join(timeout=3)

    def test_cross_process_concurrent_cli_apply(self) -> None:
        save1 = self.root / "Save1.Save"
        save1.write_text(serialize_json_lossless(self.demo_save), encoding="utf-8")
        empty = {
            "m_bHaveData": False,
            "m_strPlayerName": "",
            "m_strPlaceName": "",
            "m_strYear": "1",
            "m_strMonth": "",
            "m_strTime": "",
            "m_strPlayerIconName": "900005",
            "m_strTrueYear": "2026/11/18",
            "m_strTrueTime": "12\uff1a00",
        }
        (self.root / "SaveTitle.SaveTitle").write_text(
            serialize_json_lossless([dict(empty), dict(empty)]), encoding="utf-8"
        )
        script = Path(__file__).resolve().parents[1] / "twx_editor.py"
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        common = {"creationflags": flags, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}
        with subprocess.Popen(
            [sys.executable, "-B", str(script), "apply", str(self.save0), "--set-money", "111111", "--root", str(self.root)],
            **common,
        ) as p0, subprocess.Popen(
            [sys.executable, "-B", str(script), "apply", str(save1), "--set-money", "222222", "--root", str(self.root)],
            **common,
        ) as p1:
            out0, err0 = p0.communicate(timeout=15)
            out1, err1 = p1.communicate(timeout=15)
            self.assertEqual(p0.returncode, 0, err0)
            self.assertEqual(p1.returncode, 0, err1)
        rows = parse_json_lossless((self.root / "SaveTitle.SaveTitle").read_text(encoding="utf-8"))[0]
        self.assertIs(rows[0]["m_bHaveData"], True)
        self.assertIs(rows[1]["m_bHaveData"], True)

    def test_demo_refuses_existing_file_overwrite(self) -> None:
        before = self.save0.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = main(["demo", "--kind", "save", "--out", str(self.save0)])
        self.assertEqual(rc, 1)
        self.assertEqual(self.save0.read_bytes(), before)

    def test_same_slot_concurrent_cli_apply_preserves_both_edits(self) -> None:
        script = Path(__file__).resolve().parents[1] / "twx_editor.py"
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        common = {"creationflags": flags, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}
        with subprocess.Popen(
            [sys.executable, "-B", str(script), "apply", str(self.save0), "--set-money", "777777", "--root", str(self.root)],
            **common,
        ) as p0, subprocess.Popen(
            [sys.executable, "-B", str(script), "apply", str(self.save0), "--preset", "max_friendship", "--root", str(self.root)],
            **common,
        ) as p1:
            out0, err0 = p0.communicate(timeout=15)
            out1, err1 = p1.communicate(timeout=15)
            self.assertEqual(p0.returncode, 0, err0)
            self.assertEqual(p1.returncode, 0, err1)
        raw = (self.root / "Save0.Save").read_text(encoding="utf-8")
        saved = parse_json_lossless(raw)[0]
        self.assertEqual(saved["m_iMoney"], 777777)
        self.assertGreaterEqual(len(saved["m_NpcFriendlyNodeList"]), 1)
        self.assertTrue(all(n["m_iFriendly"] == 100 for n in saved["m_NpcFriendlyNodeList"]))

    def test_savetitle_preserves_other_slots_crlf_and_raw_tokens(self) -> None:
        self.assertTrue(_slot_backup_prefix("Save0.Save").startswith("save0__s"))
        self.assertTrue(
            is_backup_for_slot(
                "Save0" + _slot_backup_prefix("Save0.Save")[5:] + "_20261118T000000Z_12345678.bak",
                "Save0.Save",
            )
        )
        slot0_init = '[\r\n  {"m_bHaveData": false, "m_strYear": "1"}'
        slot1_verbatim = ',\r\n  {"m_bHaveData": false, "m_strYear": "1", "m_fRawToken": 1.0e-5}\r\n]\r\n'
        (self.root / "SaveTitle.SaveTitle").write_bytes((slot0_init + slot1_verbatim).encode("utf-8"))
        atomic_save_with_backup(self.root, "Save0.Save", serialize_json_lossless(self.demo_save))
        updated = (self.root / "SaveTitle.SaveTitle").read_bytes().decode("utf-8")
        self.assertTrue(updated.startswith("[\r\n  {"))
        self.assertTrue(updated.endswith(slot1_verbatim))
        self.assertIn("true", updated[:len(updated) - len(slot1_verbatim)])

    def test_apply_out_new_file_enforces_lock_and_game_running(self) -> None:
        draft = self.root / "Draft.json"
        draft.write_text(serialize_json_lossless(self.demo_save), encoding="utf-8")
        new_slot = self.root / "fresh_out" / "Save5.Save"
        self.assertFalse(new_slot.exists())
        try:
            os.environ["TWX_SIMULATE_GAME_RUNNING"] = "1"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = main(["apply", str(draft), "--preset", "max_money", "--out", str(new_slot)])
            self.assertEqual(rc, 1)
            self.assertFalse(new_slot.exists())
        finally:
            os.environ.pop("TWX_SIMULATE_GAME_RUNNING", None)
        os.environ.pop("TWX_SIMULATE_GAME_RUNNING", None)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = main(["apply", str(draft), "--preset", "max_money", "--out", str(new_slot)])
        self.assertEqual(rc, 0)
        self.assertTrue(new_slot.exists())
        self.assertEqual(parse_json_lossless(new_slot.read_text(encoding="utf-8"))[0]["m_iMoney"], 9999999)

    def test_lockfile_dotfile_origin_and_case_collision_guards(self) -> None:
        raw_demo = serialize_json_lossless(self.demo_save)
        lock_path = self.root / ".twx_store.lock"
        with self.assertRaises(ValueError):
            atomic_save_with_backup(self.root, ".twx_store.lock", raw_demo)
        with self.assertRaises(ValueError):
            atomic_save_with_backup(self.root, "backups/Save0.Save", raw_demo)
        self.assertEqual(lock_path.read_bytes(), b"")

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(
                main(["demo", "--kind", "save", "--out", str(lock_path)]),
                1,
            )
        self.assertEqual(lock_path.read_bytes(), b"")

        with self.assertRaises(ValueError):
            atomic_save_with_backup(self.root, "save0.save", raw_demo)

        if os.name != "nt":
            lower_slot = self.root / "save0.save"
            lower_slot.write_text(raw_demo, encoding="utf-8")
            slots = [s["slot"] for s in list_slots(self.root)]
            self.assertNotIn("Save0.Save", slots)
            self.assertNotIn("save0.save", slots)

            with self.assertRaises(ValueError):
                atomic_save_with_backup(self.root, "Save0.Save", raw_demo)

            lower_slot.unlink()
            self.assertIn("Save0.Save", [s["slot"] for s in list_slots(self.root)])

    def test_v6_subdir_lock_root_swap_fifo_and_post_replace_rollback(self) -> None:
        import time

        # 1) Subdirectory lock alignment between root-relative save and CLI apply without --root
        sub = self.root / "sub"
        sub.mkdir(parents=True, exist_ok=True)
        sub_save = sub / "Save0.Save"
        sub_save.write_text(serialize_json_lossless(self.demo_save), encoding="utf-8")
        sub_title = sub / "SaveTitle.SaveTitle"
        sub_title.write_bytes((self.root / "SaveTitle.SaveTitle").read_bytes())

        edited_money = create_demo_data("save")
        edited_money["m_iMoney"] = 333333
        raw_money = serialize_json_lossless(edited_money)

        thread_errs: list[BaseException] = []

        def _worker() -> None:
            try:
                atomic_save_with_backup(self.root, "sub/Save0.Save", raw_money)
            except BaseException as exc:
                thread_errs.append(exc)

        script = Path(__file__).resolve().parents[1] / "twx_editor.py"
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        th = threading.Thread(target=_worker)
        th.start()
        with subprocess.Popen(
            [sys.executable, "-B", str(script), "apply", str(sub_save), "--preset", "max_friendship"],
            creationflags=flags,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as proc:
            out_s, err_s = proc.communicate(timeout=20)
            rc = proc.returncode
        th.join(timeout=10)
        self.assertFalse(th.is_alive())
        self.assertEqual(thread_errs, [])
        self.assertEqual(rc, 0, err_s)
        self.assertTrue((sub / ".twx_store.lock").exists())
        sub_title_parsed, _ = parse_json_lossless(sub_title.read_text(encoding="utf-8"))
        self.assertEqual(validate_data(sub_title_parsed), "title")
        self.assertIs(sub_title_parsed[0]["m_bHaveData"], True)
        sub_saved_parsed, _ = parse_json_lossless(sub_save.read_text(encoding="utf-8"))
        self.assertEqual(validate_data(sub_saved_parsed), "save")
        self.assertEqual(sub_saved_parsed["m_iMoney"], 333333)

        # 2) Ancestor symlink swap after create_bridge_server starts
        if hasattr(os, "symlink"):
            outer = self.root / "outer"
            active_parent = outer / "active_parent"
            moved_parent = outer / "moved_parent"
            decoy_parent = outer / "decoy_parent"
            saves = active_parent / "saves"
            decoy_saves = decoy_parent / "saves"
            saves.mkdir(parents=True, exist_ok=True)
            decoy_saves.mkdir(parents=True, exist_ok=True)
            raw_demo = serialize_json_lossless(self.demo_save)
            (saves / "Save0.Save").write_text(raw_demo, encoding="utf-8")
            decoy_orig = b'{"decoy":true}\n'
            (decoy_saves / "Save0.Save").write_bytes(decoy_orig)

            srv = create_bridge_server(saves, "127.0.0.1", 0)
            srv_th = threading.Thread(target=srv.serve_forever, daemon=True)
            srv_th.start()
            try:
                port = srv.server_address[1]
                base = f"http://127.0.0.1:{port}"
                hdrs = {"X-TWX-Token": srv.bridge_token, "Origin": base}
                post_hdrs = {**hdrs, "Content-Type": "application/json"}

                with urllib.request.urlopen(
                    urllib.request.Request(f"{base}/api/load?slot=Save0.Save", headers=hdrs), timeout=5
                ) as resp:
                    _ = resp.read()
                    init_sha = resp.headers.get("X-TWX-Sha256") or ""

                os.rename(active_parent, moved_parent)
                os.symlink(decoy_parent, active_parent)

                for req in (
                    urllib.request.Request(f"{base}/api/slots", headers=hdrs),
                    urllib.request.Request(f"{base}/api/load?slot=Save0.Save", headers=hdrs),
                    urllib.request.Request(f"{base}/api/backups", headers=hdrs),
                    urllib.request.Request(
                        f"{base}/api/save",
                        data=json.dumps(
                            {"slot": "Save0.Save", "text": raw_demo, "baseSha256": init_sha}
                        ).encode("utf-8"),
                        headers=post_hdrs,
                        method="POST",
                    ),
                ):
                    with self.assertRaises(urllib.error.HTTPError) as cm:
                        urllib.request.urlopen(req, timeout=5)
                    try:
                        self.assertEqual(cm.exception.code, 400)
                    finally:
                        cm.exception.close()

                self.assertEqual((decoy_saves / "Save0.Save").read_bytes(), decoy_orig)
            finally:
                srv.shutdown()
                srv.server_close()
                srv_th.join(timeout=3)

        # 3) POSIX FIFO non-blocking rejection within 2.0s
        if hasattr(os, "mkfifo"):
            fifo_path = self.root / "PipeSlot.Save"
            os.mkfifo(fifo_path)
            srv = create_bridge_server(self.root, "127.0.0.1", 0)
            srv_th = threading.Thread(target=srv.serve_forever, daemon=True)
            srv_th.start()
            try:
                port = srv.server_address[1]
                base = f"http://127.0.0.1:{port}"
                hdrs = {"X-TWX-Token": srv.bridge_token, "Origin": base}
                t0 = time.monotonic()
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(
                        urllib.request.Request(f"{base}/api/load?slot=PipeSlot.Save", headers=hdrs),
                        timeout=2.0,
                    )
                try:
                    self.assertEqual(cm.exception.code, 400)
                finally:
                    cm.exception.close()
                self.assertLess(time.monotonic() - t0, 2.0)
            finally:
                srv.shutdown()
                srv.server_close()
                srv_th.join(timeout=3)
                fifo_path.unlink(missing_ok=True)

        # 4) Post-replace fsync symmetry rollback for atomic_save_with_backup and restore_backup
        base_state = create_demo_data("save")
        base_state["m_iMoney"] = 123456
        base_state["m_iYear"] = 2
        save_res = atomic_save_with_backup(self.root, "Save0.Save", serialize_json_lossless(base_state))
        bak_name = save_res["backup"]
        self.assertTrue(bak_name.endswith(".bak"))

        mutated_state = create_demo_data("save")
        mutated_state["m_iMoney"] = 987654
        mutated_state["m_iYear"] = 5
        raw_mutated = serialize_json_lossless(mutated_state)

        for env_key in ("TWX_SIMULATE_POST_SLOT_SYNC_FAIL", "TWX_SIMULATE_POST_TITLE_SYNC_FAIL"):
            orig_slot = self.save0.read_bytes()
            orig_title = (self.root / "SaveTitle.SaveTitle").read_bytes()
            os.environ[env_key] = "1"
            try:
                with self.assertRaises(OSError):
                    atomic_save_with_backup(self.root, "Save0.Save", raw_mutated)
                self.assertEqual(self.save0.read_bytes(), orig_slot)
                self.assertEqual((self.root / "SaveTitle.SaveTitle").read_bytes(), orig_title)

                with self.assertRaises(OSError):
                    restore_backup(self.root, bak_name, "Save0.Save")
                self.assertEqual(self.save0.read_bytes(), orig_slot)
                self.assertEqual((self.root / "SaveTitle.SaveTitle").read_bytes(), orig_title)
            finally:
                os.environ.pop(env_key, None)

        brand_new_slot = self.root / "Round.dat"
        self.assertFalse(brand_new_slot.exists())
        raw_round = serialize_json_lossless(create_demo_data("round"))
        orig_title = (self.root / "SaveTitle.SaveTitle").read_bytes()
        os.environ["TWX_SIMULATE_POST_SLOT_SYNC_FAIL"] = "1"
        try:
            with self.assertRaises(OSError):
                atomic_save_with_backup(self.root, "Round.dat", raw_round)
            self.assertFalse(brand_new_slot.exists())
            self.assertEqual((self.root / "SaveTitle.SaveTitle").read_bytes(), orig_title)
        finally:
            os.environ.pop("TWX_SIMULATE_POST_SLOT_SYNC_FAIL", None)

    def test_v7_cli_lock_order_external_writer_cas_and_win_case_sensitive(self) -> None:
        script = Path(__file__).resolve().parents[1] / "twx_editor.py"
        z_dir = self.root / "z"
        a_dir = self.root / "a"
        z_dir.mkdir(parents=True, exist_ok=True)
        a_dir.mkdir(parents=True, exist_ok=True)
        z_save0 = z_dir / "Save0.Save"
        out_save = a_dir / "Save1.Save"
        z_save0.write_text(serialize_json_lossless(create_demo_data("save")), encoding="utf-8")

        for _round in range(3):
            p1 = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    str(script),
                    "apply",
                    str(z_save0),
                    "--out",
                    str(out_save),
                    "--root",
                    str(self.root),
                    "--set-money",
                    "111111",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            p2 = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    str(script),
                    "apply",
                    str(z_save0),
                    "--out",
                    str(out_save),
                    "--set-money",
                    "222222",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            out1, err1 = p1.communicate(timeout=15)
            out2, err2 = p2.communicate(timeout=15)
            self.assertEqual(p1.returncode, 0, msg=(out1 + err1).decode("utf-8", "replace"))
            self.assertEqual(p2.returncode, 0, msg=(out2 + err2).decode("utf-8", "replace"))

        if os.name != "nt":
            orig_bytes = self.save0.read_bytes()
            orig_sha = hashlib.sha256(orig_bytes).hexdigest()
            new_state = create_demo_data("save")
            new_state["m_iMoney"] = 888888
            raw_new = serialize_json_lossless(new_state)
            baks_before = (
                sorted((self.root / "backups").glob("*.bak"))
                if (self.root / "backups").is_dir()
                else []
            )
            os.environ["TWX_SIMULATE_EXTERNAL_WRITE_DURING_SAVE"] = "1"
            try:
                with self.assertRaises(RuntimeError) as cm:
                    atomic_save_with_backup(
                        self.root,
                        "Save0.Save",
                        raw_new,
                        expected_orig_sha256=orig_sha,
                    )
                self.assertEqual(str(cm.exception), "CONFLICT_MODIFIED")
                after_bytes = self.save0.read_bytes()
                self.assertNotEqual(after_bytes, orig_bytes)
                self.assertNotEqual(after_bytes, raw_new.encode("utf-8"))
                parsed_ext, _ = parse_json_lossless(after_bytes.decode("utf-8"))
                self.assertEqual(parsed_ext["m_iMoney"], 777777)
                baks_after = (
                    sorted((self.root / "backups").glob("*.bak"))
                    if (self.root / "backups").is_dir()
                    else []
                )
                self.assertEqual(baks_after, baks_before)
            finally:
                os.environ.pop("TWX_SIMULATE_EXTERNAL_WRITE_DURING_SAVE", None)

            prep_res = atomic_save_with_backup(
                self.root,
                "Save0.Save",
                serialize_json_lossless(create_demo_data("save")),
            )
            slot_before_t = self.save0.read_bytes()
            slot_sha_t = hashlib.sha256(slot_before_t).hexdigest()
            baks_before_t = sorted((self.root / "backups").glob("*.bak"))
            os.environ["TWX_SIMULATE_EXTERNAL_TITLE_WRITE_DURING_SAVE"] = "1"
            try:
                with self.assertRaises(RuntimeError) as cm_t:
                    atomic_save_with_backup(
                        self.root,
                        "Save0.Save",
                        raw_new,
                        expected_orig_sha256=slot_sha_t,
                    )
                self.assertEqual(str(cm_t.exception), "CONFLICT_MODIFIED")
                self.assertEqual(self.save0.read_bytes(), slot_before_t)
                t_parsed, _ = parse_json_lossless(
                    (self.root / "SaveTitle.SaveTitle").read_bytes().decode("utf-8")
                )
                self.assertEqual(t_parsed[0]["m_strPlayerName"], "EXT_TITLE_WRITER")
                self.assertEqual(
                    sorted((self.root / "backups").glob("*.bak")), baks_before_t
                )
                self.assertEqual(list(self.root.glob(".*.tmp")), [])

                srv = create_bridge_server(self.root, "127.0.0.1", 0)
                srv_th = threading.Thread(target=srv.serve_forever, daemon=True)
                srv_th.start()
                try:
                    port = srv.server_address[1]
                    base = f"http://127.0.0.1:{port}"
                    req = urllib.request.Request(
                        f"{base}/api/restore",
                        data=json.dumps(
                            {"slot": "Save0.Save", "backup": prep_res["backup"]}
                        ).encode("utf-8"),
                        headers={
                            "X-TWX-Token": srv.bridge_token,
                            "Origin": base,
                            "Content-Type": "application/json",
                        },
                        method="POST",
                    )
                    with self.assertRaises(urllib.error.HTTPError) as cm_http:
                        urllib.request.urlopen(req, timeout=5)
                    try:
                        self.assertEqual(cm_http.exception.code, 409)
                        err_body = json.loads(cm_http.exception.read().decode("utf-8"))
                        self.assertEqual(err_body["error"], "CONFLICT_MODIFIED")
                    finally:
                        cm_http.exception.close()
                finally:
                    srv.shutdown()
                    srv.server_close()
                    srv_th.join(timeout=3)
                self.assertEqual(self.save0.read_bytes(), slot_before_t)
                t_http, _ = parse_json_lossless(
                    (self.root / "SaveTitle.SaveTitle").read_bytes().decode("utf-8")
                )
                self.assertEqual(
                    t_http[0]["m_strPlayerName"], "EXT_TITLE_WRITER_2"
                )
                self.assertEqual(
                    sorted((self.root / "backups").glob("*.bak")), baks_before_t
                )
                self.assertEqual(list(self.root.glob(".*.tmp")), [])
            finally:
                os.environ.pop("TWX_SIMULATE_EXTERNAL_TITLE_WRITE_DURING_SAVE", None)

        import twx_editor
        import unittest.mock

        real_fsync_dir_fd = twx_editor._fsync_dir_fd

        ed1 = create_demo_data("save")
        ed1["m_iMoney"] = 333333
        raw_ed1 = serialize_json_lossless(ed1)
        expected_ed1_bytes = raw_ed1.encode("utf-8")
        ext1 = create_demo_data("save")
        ext1["m_iMoney"] = 555555
        ext1_bytes = serialize_json_lossless(ext1).encode("utf-8")
        trig1 = [False]

        def fsync_ext_slot(dfd_arg):
            if not trig1[0] and self.save0.exists() and self.save0.read_bytes() == expected_ed1_bytes:
                trig1[0] = True
                self.save0.write_bytes(ext1_bytes)
                raise OSError("SIMULATED_FSYNC_AFTER_EXT_SLOT")
            return real_fsync_dir_fd(dfd_arg)

        with unittest.mock.patch.object(
            twx_editor, "_fsync_dir_fd", side_effect=fsync_ext_slot
        ):
            with self.assertRaises(OSError):
                atomic_save_with_backup(self.root, "Save0.Save", raw_ed1)
        self.assertEqual(self.save0.read_bytes(), ext1_bytes)

        self.save0.unlink()
        save2 = self.save0
        self.assertFalse(save2.exists())
        ed2 = create_demo_data("save")
        ed2["m_iMoney"] = 444444
        raw_ed2 = serialize_json_lossless(ed2)
        expected_ed2_bytes = raw_ed2.encode("utf-8")
        ext2 = create_demo_data("save")
        ext2["m_iMoney"] = 666666
        ext2_bytes = serialize_json_lossless(ext2).encode("utf-8")
        trig2 = [False]

        def fsync_ext_new_slot(dfd_arg):
            if not trig2[0] and save2.exists() and save2.read_bytes() == expected_ed2_bytes:
                trig2[0] = True
                save2.write_bytes(ext2_bytes)
                raise OSError("SIMULATED_FSYNC_AFTER_EXT_NEW_SLOT")
            return real_fsync_dir_fd(dfd_arg)

        with unittest.mock.patch.object(
            twx_editor, "_fsync_dir_fd", side_effect=fsync_ext_new_slot
        ):
            with self.assertRaises(OSError):
                atomic_save_with_backup(self.root, "Save0.Save", raw_ed2)
        self.assertTrue(save2.exists())
        self.assertEqual(save2.read_bytes(), ext2_bytes)

        title_path = self.root / "SaveTitle.SaveTitle"
        ext_title_obj, _ = parse_json_lossless(
            title_path.read_bytes().decode("utf-8")
        )
        ext_title_obj[0]["m_strPlayerName"] = "EXT_NEWER_TITLE"
        ext_title_bytes = serialize_json_lossless(ext_title_obj).encode("utf-8")
        ed3 = create_demo_data("save")
        ed3["m_iMoney"] = 222222
        raw_ed3 = serialize_json_lossless(ed3)
        expected_ed3_bytes = raw_ed3.encode("utf-8")
        slot_before_ed3 = self.save0.read_bytes()
        title_before_ed3 = title_path.read_bytes()
        trig3 = [False]

        def fsync_ext_title(dfd_arg):
            if (
                not trig3[0]
                and self.save0.read_bytes() == expected_ed3_bytes
                and title_path.read_bytes() != title_before_ed3
            ):
                trig3[0] = True
                title_path.write_bytes(ext_title_bytes)
                raise OSError("SIMULATED_FSYNC_AFTER_EXT_TITLE")
            return real_fsync_dir_fd(dfd_arg)

        with unittest.mock.patch.object(
            twx_editor, "_fsync_dir_fd", side_effect=fsync_ext_title
        ):
            with self.assertRaises(OSError):
                atomic_save_with_backup(self.root, "Save0.Save", raw_ed3)
        self.assertEqual(title_path.read_bytes(), ext_title_bytes)
        self.assertEqual(self.save0.read_bytes(), slot_before_ed3)

        raw_demo = serialize_json_lossless(create_demo_data("save"))
        with self.assertRaises(RuntimeError) as cm_exists:
            atomic_save_with_backup(self.root, "Save0.Save", raw_demo, expected_orig_sha256="")
        self.assertEqual(str(cm_exists.exception), "CONFLICT_MODIFIED")

        if os.name == "nt":
            cs_dir = self.root / "win_cs"
            cs_dir.mkdir()
            cp = subprocess.run(
                ["fsutil", "file", "setCaseSensitiveInfo", str(cs_dir), "enable"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if cp.returncode == 0:
                (cs_dir / "Save0.Save").write_text(raw_demo, encoding="utf-8")
                (cs_dir / "save0.save").write_text(raw_demo, encoding="utf-8")
                self.assertEqual(list_slots(cs_dir), [])
                with self.assertRaises(ValueError):
                    atomic_save_with_backup(cs_dir, "Save0.Save", raw_demo)

    def test_v9_open_fd_inode_swap_rollback_prestage_and_read_locks(self) -> None:
        import unittest.mock

        init_state = create_demo_data("save")
        init_state["m_iMoney"] = 101010
        atomic_save_with_backup(self.root, "Save0.Save", serialize_json_lossless(init_state))

        ed_state = create_demo_data("save")
        ed_state["m_iMoney"] = 654321
        raw_ed = serialize_json_lossless(ed_state)

        # 1) POSIX open-fd vs dir_fd lstat swap detection right after read & before replace
        if os.name != "nt":
            # 1a: "slot"
            slot_before = self.save0.read_bytes()
            slot_sha = hashlib.sha256(slot_before).hexdigest()
            title_before = (self.root / "SaveTitle.SaveTitle").read_bytes()
            baks_before = sorted((self.root / "backups").glob("*.bak"))
            os.environ["TWX_SIMULATE_EXTERNAL_SWAP_DURING_VERIFY"] = "slot"
            try:
                with self.assertRaises(RuntimeError) as cm_slot:
                    atomic_save_with_backup(
                        self.root,
                        "Save0.Save",
                        raw_ed,
                        expected_orig_sha256=slot_sha,
                    )
                self.assertEqual(str(cm_slot.exception), "CONFLICT_MODIFIED")
            finally:
                os.environ.pop("TWX_SIMULATE_EXTERNAL_SWAP_DURING_VERIFY", None)
            after_slot = self.save0.read_bytes()
            self.assertNotEqual(after_slot, slot_before)
            self.assertNotEqual(after_slot, raw_ed.encode("utf-8"))
            self.assertIn(
                parse_json_lossless(after_slot.decode("utf-8"))[0]["m_iMoney"],
                (777777, 777778),
            )
            self.assertEqual((self.root / "SaveTitle.SaveTitle").read_bytes(), title_before)
            self.assertEqual(list(self.root.glob(".*.tmp")), [])
            self.assertEqual(sorted((self.root / "backups").glob("*.bak")), baks_before)

            # 1b: "title_pre"
            slot_before = self.save0.read_bytes()
            slot_sha = hashlib.sha256(slot_before).hexdigest()
            baks_before = sorted((self.root / "backups").glob("*.bak"))
            os.environ["TWX_SIMULATE_EXTERNAL_SWAP_DURING_VERIFY"] = "title_pre"
            try:
                with self.assertRaises(RuntimeError) as cm_tpre:
                    atomic_save_with_backup(
                        self.root,
                        "Save0.Save",
                        raw_ed,
                        expected_orig_sha256=slot_sha,
                    )
                self.assertEqual(str(cm_tpre.exception), "CONFLICT_MODIFIED")
            finally:
                os.environ.pop("TWX_SIMULATE_EXTERNAL_SWAP_DURING_VERIFY", None)
            self.assertEqual(self.save0.read_bytes(), slot_before)
            t_pre_obj, _ = parse_json_lossless(
                (self.root / "SaveTitle.SaveTitle").read_bytes().decode("utf-8")
            )
            self.assertIn(t_pre_obj[0]["m_strPlayerName"], ("EXT_TITLE_WRITER", "EXT_TITLE_WRITER_2"))
            self.assertEqual(list(self.root.glob(".*.tmp")), [])
            self.assertEqual(sorted((self.root / "backups").glob("*.bak")), baks_before)

            # 1c: "title_post" (slot rolls back to original & backups cleaned up)
            slot_before = self.save0.read_bytes()
            slot_sha = hashlib.sha256(slot_before).hexdigest()
            title_before_post = (self.root / "SaveTitle.SaveTitle").read_bytes()
            baks_before = sorted((self.root / "backups").glob("*.bak"))
            os.environ["TWX_SIMULATE_EXTERNAL_SWAP_DURING_VERIFY"] = "title_post"
            try:
                with self.assertRaises(RuntimeError) as cm_tpost:
                    atomic_save_with_backup(
                        self.root,
                        "Save0.Save",
                        raw_ed,
                        expected_orig_sha256=slot_sha,
                    )
                self.assertEqual(str(cm_tpost.exception), "CONFLICT_MODIFIED")
            finally:
                os.environ.pop("TWX_SIMULATE_EXTERNAL_SWAP_DURING_VERIFY", None)
            self.assertEqual(self.save0.read_bytes(), slot_before)
            title_after_post = (self.root / "SaveTitle.SaveTitle").read_bytes()
            self.assertNotEqual(title_after_post, title_before_post)
            t_post_obj, _ = parse_json_lossless(title_after_post.decode("utf-8"))
            self.assertIn(t_post_obj[0]["m_strPlayerName"], ("EXT_TITLE_WRITER", "EXT_TITLE_WRITER_2"))
            self.assertEqual(list(self.root.glob(".*.tmp")), [])
            self.assertEqual(sorted((self.root / "backups").glob("*.bak")), baks_before)

        # 2) External slot write during rollback temp pre-staging: external bytes preserved & .bak retained
        orig_slot_bytes = self.save0.read_bytes()
        orig_slot_sha = hashlib.sha256(orig_slot_bytes).hexdigest()
        baks_before_set = (
            set((self.root / "backups").glob("*.bak"))
            if (self.root / "backups").is_dir()
            else set()
        )
        os.environ["TWX_SIMULATE_TITLE_WRITE_FAIL"] = "1"
        os.environ["TWX_SIMULATE_EXT_WRITE_DURING_RB_STAGE"] = "slot"
        try:
            with self.assertRaises(OSError):
                atomic_save_with_backup(
                    self.root,
                    "Save0.Save",
                    raw_ed,
                    expected_orig_sha256=orig_slot_sha,
                )
        finally:
            os.environ.pop("TWX_SIMULATE_TITLE_WRITE_FAIL", None)
            os.environ.pop("TWX_SIMULATE_EXT_WRITE_DURING_RB_STAGE", None)
        ext_rb_bytes = self.save0.read_bytes()
        self.assertIn(
            parse_json_lossless(ext_rb_bytes.decode("utf-8"))[0]["m_iMoney"],
            (919191, 919192),
        )
        self.assertEqual(list(self.root.glob(".*.tmp")), [])
        new_baks_rb = set((self.root / "backups").glob("*.bak")) - baks_before_set
        preserved_slot_baks = [
            p for p in new_baks_rb if is_backup_for_slot(p.name, "Save0.Save")
        ]
        self.assertEqual(len(preserved_slot_baks), 1)
        self.assertEqual(preserved_slot_baks[0].read_bytes(), orig_slot_bytes)

        # 3) Rollback os.replace OSError after "title_post" conflict: verified .bak retained
        if os.name != "nt":
            import twx_editor
            orig_slot_bytes_3 = self.save0.read_bytes()
            orig_slot_sha_3 = hashlib.sha256(orig_slot_bytes_3).hexdigest()
            baks_before_set_3 = set((self.root / "backups").glob("*.bak"))
            real_os_replace = os.replace
            real_try_exchange = twx_editor._posix_try_rename_exchange
            slot_replace_calls = [0]

            def fail_on_slot_rb_replace(src, dst, *args, **kwargs):
                if Path(str(dst)).name == "Save0.Save":
                    slot_replace_calls[0] += 1
                    if slot_replace_calls[0] >= 2:
                        raise OSError("SIMULATED_RB_REPLACE_FAIL")
                return real_os_replace(src, dst, *args, **kwargs)

            def fail_on_slot_rb_exchange(dfd_arg, src_name, dst_name):
                if Path(str(dst_name)).name == "Save0.Save":
                    if slot_replace_calls[0] >= 1:
                        slot_replace_calls[0] += 1
                        raise OSError("SIMULATED_RB_REPLACE_FAIL")
                    mode = real_try_exchange(dfd_arg, src_name, dst_name)
                    if mode != "UNSUPPORTED":
                        slot_replace_calls[0] += 1
                    return mode
                return real_try_exchange(dfd_arg, src_name, dst_name)

            os.environ["TWX_SIMULATE_EXTERNAL_SWAP_DURING_VERIFY"] = "title_post"
            try:
                with unittest.mock.patch.object(
                    twx_editor,
                    "_posix_try_rename_exchange",
                    side_effect=fail_on_slot_rb_exchange,
                ), unittest.mock.patch("os.replace", side_effect=fail_on_slot_rb_replace):
                    with self.assertRaises(RuntimeError) as cm_rb_err:
                        atomic_save_with_backup(
                            self.root,
                            "Save0.Save",
                            raw_ed,
                            expected_orig_sha256=orig_slot_sha_3,
                        )
                    self.assertEqual(str(cm_rb_err.exception), "CONFLICT_MODIFIED")
            finally:
                os.environ.pop("TWX_SIMULATE_EXTERNAL_SWAP_DURING_VERIFY", None)
            self.assertEqual(slot_replace_calls[0], 2)
            self.assertEqual(list(self.root.glob(".*.tmp")), [])
            new_baks_3 = set((self.root / "backups").glob("*.bak")) - baks_before_set_3
            preserved_slot_baks_3 = [
                p for p in new_baks_3 if is_backup_for_slot(p.name, "Save0.Save")
            ]
            self.assertEqual(len(preserved_slot_baks_3), 1)
            self.assertEqual(preserved_slot_baks_3[0].read_bytes(), orig_slot_bytes_3)

        # 4) Hardlink-poisoned .twx_store.lock rejected by inspect, validate, and /api/slots
        poison_dir = self.root / "poison_store"
        poison_dir.mkdir(parents=True, exist_ok=True)
        poison_save = poison_dir / "Save0.Save"
        poison_save.write_text(serialize_json_lossless(create_demo_data("save")), encoding="utf-8")
        srv = create_bridge_server(poison_dir, "127.0.0.1", 0)
        srv_th = threading.Thread(target=srv.serve_forever, daemon=True)
        srv_th.start()
        try:
            lock_file = poison_dir / ".twx_store.lock"
            lock_file.write_bytes(b"")
            hardlink_path = poison_dir / "lock_hardlink.dat"
            os.link(lock_file, hardlink_path)

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["inspect", str(poison_save)]), 1)
                self.assertEqual(main(["validate", str(poison_save)]), 1)

            port = srv.server_address[1]
            base = f"http://127.0.0.1:{port}"
            req = urllib.request.Request(
                f"{base}/api/slots",
                headers={"X-TWX-Token": srv.bridge_token, "Origin": base},
            )
            with self.assertRaises(urllib.error.HTTPError) as cm_slots:
                urllib.request.urlopen(req, timeout=5)
            try:
                self.assertEqual(cm_slots.exception.code, 400)
            finally:
                cm_slots.exception.close()
        finally:
            srv.shutdown()
            srv.server_close()
            srv_th.join(timeout=3)

    def test_v10_dfd_bound_slots_cli_case_collision_and_win_fileid_rollback(self) -> None:
        raw_demo = serialize_json_lossless(create_demo_data("save"))

        # 1) POSIX /api/slots enumeration bound to locked root_dir_fd across post-lock root swap
        if os.name != "nt":
            swap_base = self.root / "v10_swap"
            store = swap_base / "store"
            decoy = swap_base / "store_decoy"
            moved = swap_base / "store_moved"
            store.mkdir(parents=True, exist_ok=True)
            decoy.mkdir(parents=True, exist_ok=True)
            (store / "Save0.Save").write_text(raw_demo, encoding="utf-8")
            (decoy / "Save19.Save").write_text(raw_demo, encoding="utf-8")

            srv = create_bridge_server(store, "127.0.0.1", 0)
            srv_th = threading.Thread(target=srv.serve_forever, daemon=True)
            srv_th.start()
            os.environ["TWX_SIMULATE_ROOT_SWAP_AFTER_LOCK"] = "1"
            try:
                port = srv.server_address[1]
                base = f"http://127.0.0.1:{port}"
                req = urllib.request.Request(
                    f"{base}/api/slots",
                    headers={"X-TWX-Token": srv.bridge_token, "Origin": base},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    payload = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(moved.is_dir())
                self.assertTrue((store / "Save19.Save").is_file())
                slot_names = [s["slot"] for s in payload["slots"]]
                self.assertEqual(slot_names, ["Save0.Save"])
                self.assertNotIn("Save19.Save", slot_names)
            finally:
                os.environ.pop("TWX_SIMULATE_ROOT_SWAP_AFTER_LOCK", None)
                srv.shutdown()
                srv.server_close()
                srv_th.join(timeout=3)
                if moved.exists():
                    if store.exists() and not decoy.exists():
                        os.rename(store, decoy)
                    if not store.exists():
                        os.rename(moved, store)

        # 2) CLI inspect & validate reject case-colliding sibling files
        cs_dir = self.root / "v10_cs_cli"
        cs_dir.mkdir(parents=True, exist_ok=True)
        cs_ready = os.name != "nt"
        if os.name == "nt":
            cp = subprocess.run(
                ["fsutil", "file", "setCaseSensitiveInfo", str(cs_dir), "enable"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            cs_ready = cp.returncode == 0
        if cs_ready:
            (cs_dir / "Save0.Save").write_text(raw_demo, encoding="utf-8")
            (cs_dir / "save0.save").write_text(raw_demo, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["inspect", str(cs_dir / "Save0.Save")]), 1)
                self.assertEqual(main(["validate", str(cs_dir / "Save0.Save")]), 1)
                self.assertEqual(main(["inspect", str(cs_dir / "save0.save")]), 1)
                self.assertEqual(main(["validate", str(cs_dir / "save0.save")]), 1)

        # 3) Supplementary plane codepoint replaced with a single underscore per character
        sup_no_sep = "Save0\U00020bb7.Save"
        tag_no_sep = hashlib.sha256("save0\U00020bb7.save".encode("utf-8")).hexdigest()[:16]
        pref_no_sep = _slot_backup_prefix(sup_no_sep)
        self.assertFalse(pref_no_sep.startswith("save0____s"))
        self.assertEqual(pref_no_sep, f"save0___s{tag_no_sep}")

        sup_with_sep = "Save0_\U00020bb7.Save"
        tag_with_sep = hashlib.sha256("save0_\U00020bb7.save".encode("utf-8")).hexdigest()[:16]
        pref_with_sep = _slot_backup_prefix(sup_with_sep)
        self.assertFalse(pref_with_sep.startswith("save0_____s"))
        self.assertEqual(pref_with_sep, f"save0____s{tag_with_sep}")

        # 4) Windows FileId + SHA-256 dual verification on rollback preserves same-byte external file & backups
        if os.name == "nt":
            nt_dir = self.root / "v10_nt_rb"
            nt_dir.mkdir(parents=True, exist_ok=True)
            nt_save0 = nt_dir / "Save0.Save"
            init_nt = create_demo_data("save")
            init_nt["m_iMoney"] = 123123
            nt_save0.write_text(serialize_json_lossless(init_nt), encoding="utf-8")
            t0 = json.loads((self.root / "SaveTitle.SaveTitle").read_text(encoding="utf-8"))
            title_two = [dict(t0[0]), dict(t0[0])]
            nt_title0 = nt_dir / "SaveTitle.SaveTitle"
            nt_title0.write_text(serialize_json_lossless(title_two), encoding="utf-8")

            ed_nt = create_demo_data("save")
            ed_nt["m_iMoney"] = 888888
            raw_ed_nt = serialize_json_lossless(ed_nt)
            expected_ed_bytes = raw_ed_nt.encode("utf-8")

            orig_nt_bytes = nt_save0.read_bytes()
            orig_nt_sha = hashlib.sha256(orig_nt_bytes).hexdigest()
            baks_before_slot = (
                set((nt_dir / "backups").glob("*.bak"))
                if (nt_dir / "backups").is_dir()
                else set()
            )
            os.environ["TWX_SIMULATE_TITLE_WRITE_FAIL"] = "1"
            os.environ["TWX_SIMULATE_EXT_SAME_BYTES_DURING_RB_STAGE"] = "slot"
            try:
                with self.assertRaises(OSError):
                    atomic_save_with_backup(
                        nt_dir,
                        "Save0.Save",
                        raw_ed_nt,
                        expected_orig_sha256=orig_nt_sha,
                    )
            finally:
                os.environ.pop("TWX_SIMULATE_TITLE_WRITE_FAIL", None)
                os.environ.pop("TWX_SIMULATE_EXT_SAME_BYTES_DURING_RB_STAGE", None)
            self.assertEqual(nt_save0.read_bytes(), expected_ed_bytes)
            self.assertEqual(list(nt_dir.glob(".*.tmp")), [])
            new_baks_slot = set((nt_dir / "backups").glob("*.bak")) - baks_before_slot
            slot_baks = [p for p in new_baks_slot if is_backup_for_slot(p.name, "Save0.Save")]
            self.assertEqual(len(slot_baks), 1)
            self.assertEqual(slot_baks[0].read_bytes(), orig_nt_bytes)

            baks_before_new = set((nt_dir / "backups").glob("*.bak"))
            nt_save1 = nt_dir / "Save1.Save"
            os.environ["TWX_SIMULATE_TITLE_WRITE_FAIL"] = "1"
            os.environ["TWX_SIMULATE_EXT_SAME_BYTES_DURING_RB_STAGE"] = "slot_new"
            try:
                with self.assertRaises(OSError):
                    atomic_save_with_backup(nt_dir, "Save1.Save", raw_ed_nt)
            finally:
                os.environ.pop("TWX_SIMULATE_TITLE_WRITE_FAIL", None)
                os.environ.pop("TWX_SIMULATE_EXT_SAME_BYTES_DURING_RB_STAGE", None)
            self.assertTrue(nt_save1.is_file())
            self.assertEqual(nt_save1.read_bytes(), expected_ed_bytes)
            self.assertEqual(list(nt_dir.glob(".*.tmp")), [])
            new_baks_slot1 = set((nt_dir / "backups").glob("*.bak")) - baks_before_new
            self.assertGreaterEqual(len(new_baks_slot1), 1)

    def test_v11_slots_fd_no_leak_win_alias_and_ascii_key_parity(self) -> None:
        from twx_editor import _assert_no_case_collision, read_safe_bytes

        if os.name != "nt":
            srv = create_bridge_server(self.root, "127.0.0.1", 0)
            srv_th = threading.Thread(target=srv.serve_forever, daemon=True); srv_th.start()
            base_threads = threading.active_count()
            try:
                port = srv.server_address[1]
                base = f"http://127.0.0.1:{port}"
                url = f"{base}/api/slots"
                req = urllib.request.Request(url, headers={"X-TWX-Token": srv.bridge_token, "Origin": base, "Connection": "close"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    resp.read()
                for _ in range(400):
                    if threading.active_count() <= base_threads:
                        break
                    threading.Event().wait(0.005)

                def _fd_count() -> int:
                    for path in ("/proc/self/fd", "/dev/fd"):
                        try:
                            return len(os.listdir(path))
                        except OSError:
                            pass
                    fd = os.dup(0)
                    try:
                        return fd
                    finally:
                        os.close(fd)

                before_fds = _fd_count()
                for _ in range(25):
                    req = urllib.request.Request(url, headers={"X-TWX-Token": srv.bridge_token, "Origin": base, "Connection": "close"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        self.assertEqual(resp.status, 200)
                        resp.read()
                for _ in range(400):
                    if threading.active_count() <= base_threads:
                        break
                    threading.Event().wait(0.005)
                after_fds = _fd_count()
                self.assertEqual(after_fds, before_fds)
            finally:
                srv.shutdown()
                srv.server_close()
                srv_th.join(timeout=3)

        for bad in ("Save0.Save.", "Save0.Save "):
            with self.assertRaises(ValueError):
                resolve_safe_save_path(self.root, bad)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["validate", str(self.root / bad)]), 1)
                self.assertEqual(main(["apply", str(self.root / bad), "--preset", "max_money"]), 1)

        if os.name == "nt":
            auto_path = self.root / "AutomaticSave0.Save"
            title_path = self.root / "SaveAutomaticTitle.SaveTitle"
            raw_demo = serialize_json_lossless(create_demo_data("save"))
            auto_path.write_text(raw_demo, encoding="utf-8")
            title_path.write_bytes((self.root / "SaveTitle.SaveTitle").read_bytes())
            with self.assertRaises(ValueError):
                _assert_no_case_collision(self.root, "AutomaticSave0.Save.")
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            n = ctypes.windll.kernel32.GetShortPathNameW(str(auto_path), buf, len(buf))
            if n and buf.value:
                short_leaf = Path(buf.value).name
                if short_leaf.lower() != auto_path.name.lower():
                    with self.assertRaises(ValueError):
                        read_safe_bytes(self.root, short_leaf)
                    with self.assertRaises(ValueError):
                        atomic_save_with_backup(self.root, short_leaf, raw_demo)

        tag1 = hashlib.sha256("\u0391\u0392\u03a3.save".encode("utf-8")).hexdigest()[:16]
        tag2 = hashlib.sha256("save\u0130.save".encode("utf-8")).hexdigest()[:16]
        self.assertEqual(_slot_backup_prefix("\u0391\u0392\u03a3.Save"), f"_____s{tag1}")
        self.assertEqual(_slot_backup_prefix("Save\u0130.Save"), f"save___s{tag2}")

    def test_v12_cli_parent_dir_8dot3_alias_rejected(self) -> None:
        if os.name == "nt":
            import ctypes

            long_parent = self.root / "LongParentDirectoryName"
            long_parent.mkdir(parents=True, exist_ok=True)
            (long_parent / "Save0.Save").write_text(
                serialize_json_lossless(self.demo_save), encoding="utf-8"
            )
            (long_parent / "SaveTitle.SaveTitle").write_bytes(
                (self.root / "SaveTitle.SaveTitle").read_bytes()
            )
            buf = ctypes.create_unicode_buffer(260)
            n = ctypes.windll.kernel32.GetShortPathNameW(str(long_parent), buf, len(buf))
            if (
                n
                and buf.value
                and os.path.normcase(buf.value.rstrip("\\"))
                != os.path.normcase(str(long_parent).rstrip("\\"))
            ):
                short_parent = Path(buf.value)
                short_save = short_parent / "Save0.Save"
                orig_bytes = (long_parent / "Save0.Save").read_bytes()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["inspect", str(short_save)]), 1)
                    self.assertEqual(main(["validate", str(short_save)]), 1)
                    self.assertEqual(main(["apply", str(short_save), "--preset", "max_money"]), 1)
                    self.assertEqual(main(["discover", "--root", str(short_parent)]), 1)
                    with self.assertRaises(ValueError):
                        list_slots(short_parent)
                    with self.assertRaises(ValueError):
                        create_bridge_server(short_parent, "127.0.0.1", 0)
                self.assertEqual((long_parent / "Save0.Save").read_bytes(), orig_bytes)
        else:
            for name in ("bad_dir.", "bad_dir "):
                d = self.root / name
                d.mkdir(parents=True, exist_ok=True)
                save = d / "Save0.Save"
                save.write_text(serialize_json_lossless(self.demo_save), encoding="utf-8")
                orig = save.read_bytes()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["inspect", str(save)]), 1)
                    self.assertEqual(main(["validate", str(save)]), 1)
                    self.assertEqual(main(["apply", str(save), "--preset", "max_money"]), 1)
                self.assertEqual(save.read_bytes(), orig)

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["inspect", str(self.root / "bad_dir." / "Save0.Save")]), 1)
            self.assertEqual(main(["validate", str(self.root / "bad_dir." / "Save0.Save")]), 1)

    def test_v13_backups_pin_root_nofollow_and_staged_temp_verify(self) -> None:
        edited = create_demo_data("save")
        edited["m_iMoney"] = 765432
        raw_ed = serialize_json_lossless(edited)

        orig_slot_bytes = (self.root / "Save0.Save").read_bytes()
        orig_title_bytes = (self.root / "SaveTitle.SaveTitle").read_bytes()
        orig_sha = hashlib.sha256(orig_slot_bytes).hexdigest()

        # (a) POSIX backups -> backups_moved + same-name decoy .bak in new backups/
        if os.name != "nt":
            bdir_root = self.root / "v13_bak_swap"
            bdir_root.mkdir(parents=True, exist_ok=True)
            (bdir_root / "Save0.Save").write_bytes(orig_slot_bytes)
            (bdir_root / "SaveTitle.SaveTitle").write_bytes(orig_title_bytes)
            init_baks = bdir_root / "backups"
            init_baks.mkdir(parents=True, exist_ok=True)
            (init_baks / "preexisting.bak").write_bytes(b"PREEXISTING")

            os.environ["TWX_SIMULATE_BACKUPS_RENAME_BEFORE_COMMIT"] = "1"
            try:
                with self.assertRaises(RuntimeError) as cm_bak:
                    atomic_save_with_backup(
                        bdir_root,
                        "Save0.Save",
                        raw_ed,
                        expected_orig_sha256=orig_sha,
                    )
                self.assertEqual(str(cm_bak.exception), "CONFLICT_MODIFIED")
            finally:
                os.environ.pop("TWX_SIMULATE_BACKUPS_RENAME_BEFORE_COMMIT", None)

            self.assertEqual((bdir_root / "Save0.Save").read_bytes(), orig_slot_bytes)
            self.assertEqual((bdir_root / "SaveTitle.SaveTitle").read_bytes(), orig_title_bytes)
            new_decoy_baks = sorted((bdir_root / "backups").glob("*.bak"))
            self.assertEqual(len(new_decoy_baks), 2)
            self.assertTrue(any(is_backup_for_slot(p.name, "Save0.Save") for p in new_decoy_baks))
            self.assertTrue(
                any(is_backup_for_slot(p.name, "SaveTitle.SaveTitle") for p in new_decoy_baks)
            )
            for p in new_decoy_baks:
                self.assertEqual(p.read_bytes(), b"DECOY_BACKUP")
            moved_remaining = [p.name for p in (bdir_root / "backups_moved").glob("*.bak")]
            self.assertEqual(moved_remaining, ["preexisting.bak"])
            self.assertEqual((bdir_root / "backups_moved" / "preexisting.bak").read_bytes(), b"PREEXISTING")

        # (b) POSIX ancestor symlink swap during create_bridge_server root pinning (zero pre-realpath)
        if os.name != "nt" and hasattr(os, "symlink"):
            pin_outer = self.root / "v13_pin_outer"
            anc_dir = pin_outer / "anc_swap_seg"
            saves_dir = anc_dir / "saves"
            ext_dir = self.root / "v13_ext_target"
            saves_dir.mkdir(parents=True, exist_ok=True)
            ext_dir.mkdir(parents=True, exist_ok=True)
            (ext_dir / "Save0.Save").write_bytes(b'{"ext":1}')

            os.environ["TWX_SIMULATE_ANCESTOR_SWAP_DURING_ROOT_PIN"] = "anc_swap_seg"
            os.environ["TWX_SIMULATE_ANCESTOR_SWAP_TARGET"] = str(ext_dir)
            try:
                with self.assertRaises(ValueError):
                    create_bridge_server(saves_dir, "127.0.0.1", 0)
            finally:
                os.environ.pop("TWX_SIMULATE_ANCESTOR_SWAP_DURING_ROOT_PIN", None)
                os.environ.pop("TWX_SIMULATE_ANCESTOR_SWAP_TARGET", None)

            self.assertTrue(anc_dir.is_symlink())
            self.assertFalse((ext_dir / ".twx_store.lock").exists())
            self.assertFalse((ext_dir / "saves").exists())

        # (c) POSIX & Windows staged temp tamper ("slot" and "title") rejected before commit / rolled back
        tamper_dir = self.root / "v13_tamper"
        tamper_dir.mkdir(parents=True, exist_ok=True)
        (tamper_dir / "Save0.Save").write_bytes(orig_slot_bytes)
        (tamper_dir / "SaveTitle.SaveTitle").write_bytes(orig_title_bytes)
        orig_s = (tamper_dir / "Save0.Save").read_bytes()
        orig_t = (tamper_dir / "SaveTitle.SaveTitle").read_bytes()
        orig_s_sha = hashlib.sha256(orig_s).hexdigest()

        for mode in ("slot", "title"):
            os.environ["TWX_SIMULATE_STAGED_TEMP_TAMPER"] = mode
            try:
                with self.assertRaises(RuntimeError) as cm_tmp:
                    atomic_save_with_backup(
                        tamper_dir,
                        "Save0.Save",
                        raw_ed,
                        expected_orig_sha256=orig_s_sha,
                    )
                self.assertEqual(str(cm_tmp.exception), "CONFLICT_MODIFIED")
            finally:
                os.environ.pop("TWX_SIMULATE_STAGED_TEMP_TAMPER", None)

            self.assertEqual((tamper_dir / "Save0.Save").read_bytes(), orig_s)
            self.assertEqual((tamper_dir / "SaveTitle.SaveTitle").read_bytes(), orig_t)
            self.assertEqual(list(tamper_dir.glob(".*.tmp")), [])
            if (tamper_dir / "backups").exists():
                self.assertEqual(list((tamper_dir / "backups").glob("*.bak")), [])

    def test_v14_pre_replace_order_and_rollback_temp_verify(self) -> None:
        edited = create_demo_data("save")
        edited["m_iMoney"] = 876543
        raw_ed = serialize_json_lossless(edited)

        orig_slot_bytes = (self.root / "Save0.Save").read_bytes()
        orig_title_bytes = (self.root / "SaveTitle.SaveTitle").read_bytes()
        orig_sha = hashlib.sha256(orig_slot_bytes).hexdigest()

        if os.name != "nt":
            ps_dir = self.root / "v14_posix_slot"
            ps_dir.mkdir(parents=True, exist_ok=True)
            (ps_dir / "Save0.Save").write_bytes(orig_slot_bytes)
            (ps_dir / "SaveTitle.SaveTitle").write_bytes(orig_title_bytes)

            os.environ["TWX_SIMULATE_EXT_SWAP_DURING_TMP_VERIFY"] = "slot"
            try:
                with self.assertRaises(RuntimeError) as cm:
                    atomic_save_with_backup(
                        ps_dir,
                        "Save0.Save",
                        raw_ed,
                        expected_orig_sha256=orig_sha,
                    )
                self.assertEqual(str(cm.exception), "CONFLICT_MODIFIED")
            finally:
                os.environ.pop("TWX_SIMULATE_EXT_SWAP_DURING_TMP_VERIFY", None)

            ext_s = (ps_dir / "Save0.Save").read_bytes()
            self.assertNotEqual(ext_s, orig_slot_bytes)
            self.assertNotEqual(ext_s, raw_ed.encode("utf-8"))
            self.assertIn(
                json.loads(ext_s.decode("utf-8-sig"))["m_iMoney"],
                (777777, 777778),
            )
            self.assertEqual(
                (ps_dir / "SaveTitle.SaveTitle").read_bytes(),
                orig_title_bytes,
            )
            self.assertEqual(list(ps_dir.glob(".*.tmp")), [])
            self.assertEqual(list(ps_dir.glob("*.tmp")), [])

            pt_dir = self.root / "v14_posix_title"
            pt_dir.mkdir(parents=True, exist_ok=True)
            (pt_dir / "Save0.Save").write_bytes(orig_slot_bytes)
            (pt_dir / "SaveTitle.SaveTitle").write_bytes(orig_title_bytes)

            os.environ["TWX_SIMULATE_EXT_SWAP_DURING_TMP_VERIFY"] = "title"
            try:
                with self.assertRaises(RuntimeError) as cm:
                    atomic_save_with_backup(
                        pt_dir,
                        "Save0.Save",
                        raw_ed,
                        expected_orig_sha256=orig_sha,
                    )
                self.assertEqual(str(cm.exception), "CONFLICT_MODIFIED")
            finally:
                os.environ.pop("TWX_SIMULATE_EXT_SWAP_DURING_TMP_VERIFY", None)

            self.assertEqual((pt_dir / "Save0.Save").read_bytes(), orig_slot_bytes)
            ext_t = (pt_dir / "SaveTitle.SaveTitle").read_bytes()
            self.assertNotEqual(ext_t, orig_title_bytes)
            self.assertIn("EXT_TITLE_WRITER", ext_t.decode("utf-8-sig"))
            self.assertEqual(list(pt_dir.glob(".*.tmp")), [])
            self.assertEqual(list(pt_dir.glob("*.tmp")), [])

        if os.name == "nt":
            for mode in ("slot", "title"):
                w_dir = self.root / f"v14_win_pin_{mode}"
                w_dir.mkdir(parents=True, exist_ok=True)
                (w_dir / "Save0.Save").write_bytes(orig_slot_bytes)
                (w_dir / "SaveTitle.SaveTitle").write_bytes(orig_title_bytes)

                os.environ["TWX_SIMULATE_EXT_WRITE_DURING_STAGED_VERIFY"] = mode
                try:
                    res = atomic_save_with_backup(
                        w_dir,
                        "Save0.Save",
                        raw_ed,
                        expected_orig_sha256=orig_sha,
                    )
                finally:
                    os.environ.pop(
                        "TWX_SIMULATE_EXT_WRITE_DURING_STAGED_VERIFY",
                        None,
                    )

                self.assertEqual(
                    json.loads(
                        (w_dir / "Save0.Save").read_text(encoding="utf-8-sig")
                    )["m_iMoney"],
                    876543,
                )
                self.assertEqual(
                    hashlib.sha256((w_dir / "Save0.Save").read_bytes()).hexdigest(),
                    res["sha256"],
                )
                self.assertEqual(list(w_dir.glob(".*.tmp")), [])

        for tag, env_key in (
            ("rb_temp", "TWX_SIMULATE_RB_TEMP_TAMPER"),
            ("post_rb", "TWX_SIMULATE_POST_RB_TAMPER"),
        ):
            rb_dir = self.root / f"v14_{tag}"
            rb_dir.mkdir(parents=True, exist_ok=True)
            (rb_dir / "Save0.Save").write_bytes(orig_slot_bytes)
            (rb_dir / "SaveTitle.SaveTitle").write_bytes(orig_title_bytes)

            os.environ["TWX_SIMULATE_POST_SLOT_SYNC_FAIL"] = "1"
            os.environ[env_key] = "slot"
            try:
                with self.assertRaises(OSError):
                    atomic_save_with_backup(
                        rb_dir,
                        "Save0.Save",
                        raw_ed,
                        expected_orig_sha256=orig_sha,
                    )
            finally:
                os.environ.pop("TWX_SIMULATE_POST_SLOT_SYNC_FAIL", None)
                os.environ.pop(env_key, None)

            self.assertEqual(list(rb_dir.glob(".*.tmp")), [])
            self.assertEqual(list(rb_dir.glob("*.tmp")), [])
            self.assertTrue((rb_dir / "backups").is_dir())
            slot_baks = [
                p
                for p in (rb_dir / "backups").glob("*.bak")
                if is_backup_for_slot(p.name, "Save0.Save")
            ]
            self.assertEqual(len(slot_baks), 1)
            self.assertEqual(slot_baks[0].read_bytes(), orig_slot_bytes)

    def test_v15_post_verify_tmp_tamper_and_linux_steam_discover(self) -> None:
        edited = create_demo_data("save")
        edited["m_iMoney"] = 654321
        raw_ed = serialize_json_lossless(edited)
        orig_slot_bytes = (self.root / "Save0.Save").read_bytes()
        orig_title_bytes = (self.root / "SaveTitle.SaveTitle").read_bytes()
        orig_sha = hashlib.sha256(orig_slot_bytes).hexdigest()

        if os.name != "nt":
            for mode in ("slot_inplace", "slot_swap", "title_inplace", "title_swap"):
                pv_dir = self.root / f"v15_pv_{mode}"
                pv_dir.mkdir(parents=True, exist_ok=True)
                (pv_dir / "Save0.Save").write_bytes(orig_slot_bytes)
                (pv_dir / "SaveTitle.SaveTitle").write_bytes(orig_title_bytes)
                old_mode = os.environ.get("TWX_SIMULATE_POST_VERIFY_TMP_TAMPER")
                os.environ["TWX_SIMULATE_POST_VERIFY_TMP_TAMPER"] = mode
                try:
                    with self.assertRaises(RuntimeError) as cm:
                        atomic_save_with_backup(
                            pv_dir,
                            "Save0.Save",
                            raw_ed,
                            expected_orig_sha256=orig_sha,
                        )
                    self.assertEqual(str(cm.exception), "CONFLICT_MODIFIED")
                finally:
                    if old_mode is None:
                        os.environ.pop("TWX_SIMULATE_POST_VERIFY_TMP_TAMPER", None)
                    else:
                        os.environ["TWX_SIMULATE_POST_VERIFY_TMP_TAMPER"] = old_mode
                self.assertEqual((pv_dir / "Save0.Save").read_bytes(), orig_slot_bytes)
                self.assertEqual((pv_dir / "SaveTitle.SaveTitle").read_bytes(), orig_title_bytes)
                if mode in ("slot_inplace", "title_inplace"):
                    self.assertEqual(list(pv_dir.glob(".*.tmp")), [])
                elif mode == "slot_swap":
                    self.assertEqual(list(pv_dir.glob(".SaveTitle.SaveTitle.*.tmp")), [])
                    slot_swap_tmps = list(pv_dir.glob(".Save0.Save.*.tmp"))
                    self.assertEqual(len(slot_swap_tmps), 1)
                    self.assertEqual(slot_swap_tmps[0].read_bytes(), b'{"pv_swapped":1}')
                elif mode == "title_swap":
                    self.assertEqual(list(pv_dir.glob(".Save0.Save.*.tmp")), [])
                    title_swap_tmps = list(pv_dir.glob(".SaveTitle.SaveTitle.*.tmp"))
                    self.assertEqual(len(title_swap_tmps), 1)
                    self.assertEqual(title_swap_tmps[0].read_bytes(), b'{"pv_title_swapped":1}')
                self.assertEqual([p for p in pv_dir.glob("*.tmp") if not p.name.startswith(".")], [])
                if (pv_dir / "backups").exists():
                    self.assertEqual(list((pv_dir / "backups").glob("*.bak")), [])

        @contextlib.contextmanager
        def _fake_home_env(home_p: Path):
            keys = ("HOME", "USERPROFILE", "ProgramFiles(x86)", "ProgramFiles", "TWX_SAVE_ROOT")
            missing = object()
            old = {k: os.environ.get(k, missing) for k in keys}
            os.environ["HOME"] = str(home_p)
            os.environ["USERPROFILE"] = str(home_p)
            os.environ["ProgramFiles(x86)"] = ""
            os.environ["ProgramFiles"] = ""
            os.environ.pop("TWX_SAVE_ROOT", None)
            try:
                yield
            finally:
                for k, v in old.items():
                    if v is missing:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = str(v)

        fake_home = self.root / "fake_home"
        real_remote = (
            fake_home
            / ".local"
            / "share"
            / "Steam"
            / "userdata"
            / "123456"
            / "377530"
            / "remote"
        )
        real_remote.mkdir(parents=True, exist_ok=True)
        (real_remote / "Save0.Save").write_bytes(orig_slot_bytes)
        some_other_dir = self.root / "some_other_dir"
        some_other_dir.mkdir(parents=True, exist_ok=True)
        (some_other_dir / "Save9.Save").write_bytes(orig_slot_bytes)

        if os.name != "nt":
            steam_link = fake_home / ".steam" / "steam"
            steam_link.parent.mkdir(parents=True, exist_ok=True)
            steam_link.symlink_to(
                fake_home / ".local" / "share" / "Steam", target_is_directory=True
            )
            trap_parent = (
                fake_home
                / ".local"
                / "share"
                / "Steam"
                / "userdata"
                / "000001"
                / "377530"
            )
            trap_parent.mkdir(parents=True, exist_ok=True)
            (trap_parent / "remote").symlink_to(some_other_dir, target_is_directory=True)

        with _fake_home_env(fake_home):
            roots = discover_roots()
            self.assertEqual(len(roots), 1)
            self.assertEqual(
                os.path.normcase(str(roots[0])),
                os.path.normcase(str(real_remote)),
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = main(["discover", "--json"])
            self.assertEqual(rc, 0)
            disc_payload = json.loads(out.getvalue())
            self.assertEqual(len(disc_payload), 1)
            self.assertTrue(
                any(s["slot"] == "Save0.Save" for s in disc_payload[0]["slots"])
            )
            self.assertFalse(
                any(s["slot"] == "Save9.Save" for s in disc_payload[0]["slots"])
            )

            env = os.environ.copy()
            env["HOME"] = str(fake_home)
            env["USERPROFILE"] = str(fake_home)
            env["ProgramFiles(x86)"] = ""
            env["ProgramFiles"] = ""
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env.pop("TWX_SAVE_ROOT", None)
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            )
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).resolve().parent.parent / "twx_editor.py"),
                    "serve",
                    "--port",
                    "0",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                creationflags=creationflags,
            )
            try:
                assert proc.stdout is not None
                line_b = proc.stdout.readline()
                self.assertTrue(line_b)
                line = line_b.decode("utf-8", "replace")
                m = re.search(r"http://127\.0\.0\.1:(\d+)/", line)
                self.assertIsNotNone(m, f"Unexpected serve output: {line!r}")
                port = int(m.group(1)) if m else 0
                base = f"http://127.0.0.1:{port}"
                with urllib.request.urlopen(f"{base}/", timeout=10) as resp:
                    page = resp.read().decode("utf-8", "replace")
                m2 = re.search(r'<meta name="twx-bridge-token" content="([^"]+)">', page)
                self.assertIsNotNone(m2)
                token = m2.group(1) if m2 else ""
                req = urllib.request.Request(
                    f"{base}/api/slots",
                    headers={"X-TWX-Token": token, "Origin": base},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    self.assertEqual(resp.status, 200)
                    slots_payload = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(
                    any(s["slot"] == "Save0.Save" for s in slots_payload["slots"])
                )
                self.assertFalse(
                    any(s["slot"] == "Save9.Save" for s in slots_payload["slots"])
                )
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=10)
                else:
                    proc.wait(timeout=10)
                if proc.stdout is not None:
                    proc.stdout.close()
                if proc.stderr is not None:
                    proc.stderr.close()

        if os.name != "nt":
            fake_home2 = self.root / "fake_home2"
            custom_remote = (
                fake_home2
                / "custom_steam"
                / "userdata"
                / "777"
                / "377530"
                / "remote"
            )
            custom_remote.mkdir(parents=True, exist_ok=True)
            (custom_remote / "Save0.Save").write_bytes(orig_slot_bytes)
            trap_parent2 = (
                fake_home2
                / "custom_steam"
                / "userdata"
                / "000002"
                / "377530"
            )
            trap_parent2.mkdir(parents=True, exist_ok=True)
            (trap_parent2 / "remote").symlink_to(some_other_dir, target_is_directory=True)
            steam_link2 = fake_home2 / ".steam" / "steam"
            steam_link2.parent.mkdir(parents=True, exist_ok=True)
            steam_link2.symlink_to(
                fake_home2 / "custom_steam", target_is_directory=True
            )
            with _fake_home_env(fake_home2):
                roots2 = discover_roots()
                self.assertEqual(len(roots2), 1)
                self.assertEqual(
                    os.path.normcase(str(roots2[0])),
                    os.path.normcase(str(custom_remote)),
                )
                out2 = io.StringIO()
                with contextlib.redirect_stdout(out2):
                    rc2 = main(["discover", "--json"])
                self.assertEqual(rc2, 0)
                disc_payload2 = json.loads(out2.getvalue())
                self.assertEqual(len(disc_payload2), 1)
                self.assertTrue(
                    any(s["slot"] == "Save0.Save" for s in disc_payload2[0]["slots"])
                )
                self.assertFalse(
                    any(s["slot"] == "Save9.Save" for s in disc_payload2[0]["slots"])
                )

    def test_v16_win_exclusive_handle_rename_save_and_rollback(self) -> None:
        title_path = self.root / "SaveTitle.SaveTitle"
        init_title, _ = parse_json_lossless(title_path.read_text(encoding="utf-8"))
        t0 = dict(init_title[0])
        title_path.write_text(
            serialize_json_lossless([dict(t0), dict(t0), dict(t0)]),
            encoding="utf-8",
        )
        orig_save0 = self.save0.read_bytes()
        save2_path = self.root / "Save2.Save"
        self.assertFalse(save2_path.exists())

        os.environ["TWX_VERIFY_EXCLUSIVE_TEMP_RENAME"] = "1"
        try:
            edited0 = create_demo_data("save")
            edited0["m_iMoney"] = 654321
            edited0["m_iYear"] = 6
            res0 = atomic_save_with_backup(
                self.root, "Save0.Save", serialize_json_lossless(edited0)
            )
            self.assertTrue(res0["ok"])
            t_after0, _ = parse_json_lossless(title_path.read_text(encoding="utf-8"))
            self.assertEqual(t_after0[0]["m_strYear"], "6")

            edited2 = create_demo_data("save")
            edited2["m_iMoney"] = 222222
            edited2["m_iYear"] = 3
            res2 = atomic_save_with_backup(
                self.root, "Save2.Save", serialize_json_lossless(edited2)
            )
            self.assertTrue(res2["ok"])
            self.assertTrue(save2_path.exists())
            t_after2, _ = parse_json_lossless(title_path.read_text(encoding="utf-8"))
            self.assertEqual(t_after2[2]["m_strYear"], "3")

            rest_res = restore_backup(self.root, res0["backup"], "Save0.Save")
            self.assertTrue(rest_res["ok"])
            self.assertEqual(self.save0.read_bytes(), orig_save0)
            t_after_rest, _ = parse_json_lossless(
                title_path.read_text(encoding="utf-8")
            )
            self.assertEqual(t_after_rest[0]["m_strYear"], "2")
            self.assertEqual(t_after_rest[2]["m_strYear"], "3")

            pre_rb_save0 = self.save0.read_bytes()
            pre_rb_title = title_path.read_bytes()
            fail_edit = create_demo_data("save")
            fail_edit["m_iMoney"] = 777777
            fail_edit["m_iYear"] = 7
            os.environ["TWX_SIMULATE_POST_TITLE_SYNC_FAIL"] = "1"
            try:
                with self.assertRaises(OSError) as cm:
                    atomic_save_with_backup(
                        self.root, "Save0.Save", serialize_json_lossless(fail_edit)
                    )
                self.assertNotIn(
                    "EXCLUSIVE_TEMP_PIN_NOT_ENFORCED", str(cm.exception)
                )
            finally:
                os.environ.pop("TWX_SIMULATE_POST_TITLE_SYNC_FAIL", None)

            self.assertEqual(self.save0.read_bytes(), pre_rb_save0)
            self.assertEqual(title_path.read_bytes(), pre_rb_title)

            leftovers = [
                p.name
                for p in self.root.rglob("*")
                if p.name.endswith(".tmp") or p.name.endswith(".hijack")
            ]
            self.assertEqual(leftovers, [])
        finally:
            os.environ.pop("TWX_VERIFY_EXCLUSIVE_TEMP_RENAME", None)
            os.environ.pop("TWX_SIMULATE_POST_TITLE_SYNC_FAIL", None)

    def test_v17_chained_out_mkdir_and_invalid_utf8_load(self) -> None:
        if os.name != "nt" and hasattr(os, "symlink"):
            ext_target_dir = self.root / "v17_ext_target"
            ext_target_dir.mkdir(parents=True, exist_ok=True)

            outer1 = self.root / "v17_outer1"
            outer1.mkdir()
            swap_out_dir1 = outer1 / "v17_swap_out1"

            old_swap_name = os.environ.get("TWX_SIMULATE_ANCESTOR_SWAP_DURING_ROOT_PIN")
            old_swap_target = os.environ.get("TWX_SIMULATE_ANCESTOR_SWAP_TARGET")
            try:
                os.environ["TWX_SIMULATE_ANCESTOR_SWAP_DURING_ROOT_PIN"] = "v17_swap_out1"
                os.environ["TWX_SIMULATE_ANCESTOR_SWAP_TARGET"] = str(ext_target_dir)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    rc1 = main([
                        "apply",
                        str(self.save0),
                        "--preset",
                        "max_money",
                        "--out",
                        str(swap_out_dir1 / "nested" / "Save1.Save"),
                    ])
            finally:
                if old_swap_name is None:
                    os.environ.pop("TWX_SIMULATE_ANCESTOR_SWAP_DURING_ROOT_PIN", None)
                else:
                    os.environ["TWX_SIMULATE_ANCESTOR_SWAP_DURING_ROOT_PIN"] = old_swap_name
                if old_swap_target is None:
                    os.environ.pop("TWX_SIMULATE_ANCESTOR_SWAP_TARGET", None)
                else:
                    os.environ["TWX_SIMULATE_ANCESTOR_SWAP_TARGET"] = old_swap_target

            self.assertEqual(rc1, 1)
            self.assertTrue(swap_out_dir1.is_symlink())
            self.assertFalse((ext_target_dir / "nested").exists())
            self.assertEqual(list(ext_target_dir.iterdir()), [])

            outer2 = self.root / "v17_outer2"
            outer2.mkdir()
            swap_out_dir2 = outer2 / "v17_swap_out2"

            old_swap_name = os.environ.get("TWX_SIMULATE_ANCESTOR_SWAP_DURING_ROOT_PIN")
            old_swap_target = os.environ.get("TWX_SIMULATE_ANCESTOR_SWAP_TARGET")
            try:
                os.environ["TWX_SIMULATE_ANCESTOR_SWAP_DURING_ROOT_PIN"] = "v17_swap_out2"
                os.environ["TWX_SIMULATE_ANCESTOR_SWAP_TARGET"] = str(ext_target_dir)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    rc2 = main([
                        "apply",
                        str(self.save0),
                        "--preset",
                        "max_money",
                        "--root",
                        str(swap_out_dir2),
                        "--out",
                        str(swap_out_dir2 / "nested" / "Save1.Save"),
                    ])
            finally:
                if old_swap_name is None:
                    os.environ.pop("TWX_SIMULATE_ANCESTOR_SWAP_DURING_ROOT_PIN", None)
                else:
                    os.environ["TWX_SIMULATE_ANCESTOR_SWAP_DURING_ROOT_PIN"] = old_swap_name
                if old_swap_target is None:
                    os.environ.pop("TWX_SIMULATE_ANCESTOR_SWAP_TARGET", None)
                else:
                    os.environ["TWX_SIMULATE_ANCESTOR_SWAP_TARGET"] = old_swap_target

            self.assertEqual(rc2, 1)
            self.assertTrue(swap_out_dir2.is_symlink())
            self.assertFalse((ext_target_dir / "nested").exists())
            self.assertEqual(list(ext_target_dir.iterdir()), [])

        real_sub = self.root / "v17_real_sub"
        out_ok = real_sub / "a" / "b" / "Save1.Save"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc_ok = main([
                "apply",
                str(self.save0),
                "--preset",
                "max_money",
                "--out",
                str(out_ok),
            ])
        self.assertEqual(rc_ok, 0)
        self.assertTrue(out_ok.is_file())
        self.assertEqual(parse_json_lossless(out_ok.read_text(encoding="utf-8"))[0]["m_iMoney"], 9_999_999)

        real_sub_r = self.root / "v17_real_sub_root"
        out_ok_r = real_sub_r / "c" / "d" / "Save1.Save"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc_ok_r = main([
                "apply",
                str(self.save0),
                "--preset",
                "max_money",
                "--root",
                str(real_sub_r),
                "--out",
                str(out_ok_r),
            ])
        self.assertEqual(rc_ok_r, 0)
        self.assertTrue(out_ok_r.is_file())
        self.assertEqual(parse_json_lossless(out_ok_r.read_text(encoding="utf-8"))[0]["m_iMoney"], 9_999_999)

        bad_slot = self.root / "Save4.Save"
        bad_slot.write_bytes(b'{"m_strPlayerName":"' + b"\xff\xfe" + b'"}')

        srv = create_bridge_server(self.root, "127.0.0.1", 0)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            root_url = f"http://127.0.0.1:{port}/"
            with urllib.request.urlopen(root_url, timeout=5) as resp:
                html = resp.read().decode("utf-8")
            match = re.search(r'<meta name="twx-bridge-token" content="([^"]+)">', html)
            self.assertIsNotNone(match)
            token = match.group(1) if match else ""
            headers = {"X-TWX-Token": token, "Origin": f"http://127.0.0.1:{port}"}
            load_url = f"http://127.0.0.1:{port}/api/load?slot=Save4.Save"
            req = urllib.request.Request(load_url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=5):
                    self.fail("Expected HTTP 400 for invalid UTF-8 slot")
            except urllib.error.HTTPError as err:
                try:
                    self.assertEqual(err.code, 400)
                finally:
                    err.close()
        finally:
            srv.shutdown()
            srv.server_close()
            th.join(timeout=5)

    def test_v18_posix_backslash_cli_guard_and_post_surrogate(self) -> None:
        def write_save(path: Path, money: int) -> bytes:
            data = create_demo_data("save")
            data["m_iMoney"] = money
            raw = serialize_json_lossless(data).encode("utf-8")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            return raw

        if os.name != "nt":
            lit_bs = self.root / "sub\\Save0.Save"
            orig_lit_bytes = write_save(lit_bs, 111)

            sub_dir = self.root / "sub"
            sub_dir.mkdir(parents=True, exist_ok=True)
            real_sub_save = sub_dir / "Save0.Save"
            orig_sub_bytes = write_save(real_sub_save, 222)

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["apply", str(lit_bs), "--preset", "max_money"]), 1)
                prev_cwd = os.getcwd()
                try:
                    os.chdir(self.root)
                    self.assertEqual(main(["apply", "sub\\Save0.Save", "--preset", "max_money"]), 1)
                    self.assertEqual(main(["inspect", "sub\\Save0.Save"]), 1)
                    self.assertEqual(main(["validate", "sub\\Save0.Save"]), 1)
                    self.assertEqual(
                        main(
                            [
                                "restore",
                                "--root",
                                str(self.root),
                                "--slot",
                                "sub\\Save0.Save",
                                "--backup",
                                "Save0__s0000000000000000_20260101_000000_00000000.bak",
                            ]
                        ),
                        1,
                    )
                finally:
                    os.chdir(prev_cwd)

            with self.assertRaises(ValueError):
                resolve_safe_save_path(self.root, "sub\\Save0.Save")
            slots = list_slots(self.root)
            self.assertNotIn("sub\\Save0.Save", [s["slot"] for s in slots])
            self.assertEqual(lit_bs.read_bytes(), orig_lit_bytes)
            self.assertEqual(real_sub_save.read_bytes(), orig_sub_bytes)

        orig_save0_bytes = (self.root / "Save0.Save").read_bytes()
        orig_title_bytes = (self.root / "SaveTitle.SaveTitle").read_bytes()
        orig_sha = hashlib.sha256(orig_save0_bytes).hexdigest()

        srv = create_bridge_server(self.root, "127.0.0.1", 0)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            port = srv.server_address[1]
            base_url = f"http://127.0.0.1:{port}"

            tmpl = create_demo_data("save")
            tmpl["m_strPlayerName"] = "__V18_MARK__"
            base_json_str = json.dumps(
                {
                    "slot": "Save0.Save",
                    "baseSha256": orig_sha,
                    "text": serialize_json_lossless(tmpl),
                },
                ensure_ascii=True,
            )

            def post_save_body(body: bytes) -> urllib.error.HTTPError:
                req = urllib.request.Request(
                    base_url + "/api/save",
                    data=body,
                    method="POST",
                    headers={
                        "X-TWX-Token": srv.bridge_token,
                        "Origin": base_url,
                        "Content-Type": "application/json",
                    },
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(req, timeout=5)
                return caught.exception

            bad_utf8_body = base_json_str.encode("utf-8").replace(b"__V18_MARK__", b"\xff\xfe")
            err = post_save_body(bad_utf8_body)
            try:
                self.assertEqual(err.code, 400)
            finally:
                err.close()

            surrogate_body = base_json_str.replace("__V18_MARK__", "\\uD800").encode("utf-8")
            err = post_save_body(surrogate_body)
            try:
                self.assertEqual(err.code, 400)
                err_payload = json.loads(err.read().decode("utf-8"))
                self.assertIn("서로게이트", err_payload.get("error", ""))
            finally:
                err.close()

            self.assertEqual((self.root / "Save0.Save").read_bytes(), orig_save0_bytes)
            self.assertEqual((self.root / "SaveTitle.SaveTitle").read_bytes(), orig_title_bytes)
        finally:
            srv.shutdown()
            srv.server_close()
            th.join(timeout=5)

    def test_v19_rename_exchange_post_preverify_swap_link_unlink_fail_and_double_bom(self) -> None:
        if os.name != "nt":
            title_entry = {
                "m_bHaveData": False,
                "m_strPlayerName": "",
                "m_strPlaceName": "",
                "m_strYear": "1",
                "m_strMonth": "",
                "m_strTime": "",
                "m_strPlayerIconName": "900005",
                "m_strTrueYear": "2026/11/18",
                "m_strTrueTime": "12\uff1a00",
            }
            entries = [dict(title_entry) for _ in range(6)]
            (self.root / "SaveTitle.SaveTitle").write_bytes(
                serialize_json_lossless(entries).encode("utf-8")
            )
            seed = create_demo_data("save")
            seed["m_iMoney"] = 111111
            bak_name = atomic_save_with_backup(
                self.root, "Save0.Save", serialize_json_lossless(seed)
            )["backup"]

            def reset_state(money: int, label: str) -> tuple[bytes, bytes]:
                s_data = create_demo_data("save")
                s_data["m_iMoney"] = money
                s_data["m_strPlayerName"] = label + "\r"
                s_text = serialize_json_lossless(s_data)
                (self.root / "Save0.Save").write_bytes(s_text.encode("utf-8"))
                t_entries = [dict(title_entry) for _ in range(6)]
                t_entries[0]["m_strPlayerName"] = label
                t_text = serialize_json_lossless(t_entries)
                (self.root / "SaveTitle.SaveTitle").write_bytes(t_text.encode("utf-8"))
                return (
                    (self.root / "Save0.Save").read_bytes(),
                    (self.root / "SaveTitle.SaveTitle").read_bytes(),
                )

            cand_save = create_demo_data("save")
            cand_save["m_iMoney"] = 999999
            cand_text = serialize_json_lossless(cand_save)

            if platform.system() == "Linux":
                self.assertTrue(_posix_supports_rename_exchange(self.root))
            if _posix_supports_rename_exchange(self.root):
                bs, bt = reset_state(123456, "ORIG")
                try:
                    os.environ["TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP"] = "slot"
                    with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                        atomic_save_with_backup(
                            self.root,
                            "Save0.Save",
                            cand_text,
                            expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                        )
                    self.assertEqual(
                        parse_json_lossless(
                            read_safe_bytes(self.root, "Save0.Save").decode("utf-8")
                        )[0]["m_iMoney"],
                        777777,
                    )
                    self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
                    self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".tmp")], [])
                finally:
                    os.environ.pop("TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP", None)

                bs, bt = reset_state(234567, "ORIG")
                try:
                    os.environ["TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP"] = "slot"
                    with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                        restore_backup(self.root, bak_name, "Save0.Save")
                    self.assertEqual(
                        parse_json_lossless(
                            read_safe_bytes(self.root, "Save0.Save").decode("utf-8")
                        )[0]["m_iMoney"],
                        777777,
                    )
                    self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
                    self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".tmp")], [])
                finally:
                    os.environ.pop("TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP", None)

                bs, bt = reset_state(345678, "ORIG")
                try:
                    os.environ["TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP"] = "title"
                    with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                        atomic_save_with_backup(
                            self.root,
                            "Save0.Save",
                            cand_text,
                            expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                        )
                    self.assertEqual(read_safe_bytes(self.root, "Save0.Save"), bs)
                    self.assertEqual(
                        parse_json_lossless(
                            read_safe_bytes(self.root, "SaveTitle.SaveTitle").decode("utf-8")
                        )[0][0]["m_strPlayerName"],
                        "EXT_TITLE_WRITER",
                    )
                    self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".tmp")], [])
                finally:
                    os.environ.pop("TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP", None)

                bs, bt = reset_state(456789, "ORIG")
                try:
                    os.environ["TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP"] = "title"
                    with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                        restore_backup(self.root, bak_name, "Save0.Save")
                    self.assertEqual(read_safe_bytes(self.root, "Save0.Save"), bs)
                    self.assertEqual(
                        parse_json_lossless(
                            read_safe_bytes(self.root, "SaveTitle.SaveTitle").decode("utf-8")
                        )[0][0]["m_strPlayerName"],
                        "EXT_TITLE_WRITER",
                    )
                    self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".tmp")], [])
                finally:
                    os.environ.pop("TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP", None)

            reset_state(555555, "초기무")
            try:
                os.environ["TWX_SIMULATE_POSIX_LINK_TMP_UNLINK_FAIL"] = "1"
                with self.assertRaises(OSError):
                    atomic_save_with_backup(self.root, "Save5.Save", cand_text)
                self.assertFalse((self.root / "Save5.Save").exists())
                self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".tmp")], [])
            finally:
                os.environ.pop("TWX_SIMULATE_POSIX_LINK_TMP_UNLINK_FAIL", None)
            self.assertTrue(
                atomic_save_with_backup(self.root, "Save5.Save", cand_text)["ok"]
            )
            self.assertEqual(
                parse_json_lossless(
                    read_safe_bytes(self.root, "Save5.Save").decode("utf-8")
                )[0]["m_iMoney"],
                999999,
            )

        import urllib.parse

        valid_save = create_demo_data("save")
        valid_save["m_strPlayerName"] = "__SURR_MARK__"
        valid_text = serialize_json_lossless(valid_save)
        valid_bytes = valid_text.encode("utf-8")
        double_bom_bytes = b"\xef\xbb\xbf\xef\xbb\xbf" + valid_bytes
        surr_bytes = valid_text.replace("__SURR_MARK__", "\\uD800").encode("utf-8")

        for bad_text in (double_bom_bytes.decode("utf-8"), surr_bytes.decode("utf-8"), '{"m_strPlayerName":"\ud800"}'):
            with self.assertRaises(ValueError):
                parse_json_lossless(bad_text)

        with self.assertRaises(ValueError):
            validate_data({"m_strPlayerName": "\ud800", "m_strPlayerLastName": "동방"})

        (self.root / "backups").mkdir(exist_ok=True)
        prefix = _slot_backup_prefix("Save0.Save")
        dbom_bak = f"{prefix}_20261119T000001000000Z_{hashlib.sha256(double_bom_bytes).hexdigest()[:8]}.bak"
        surr_bak = f"{prefix}_20261119T000002000000Z_{hashlib.sha256(surr_bytes).hexdigest()[:8]}.bak"
        (self.root / "backups" / dbom_bak).write_bytes(double_bom_bytes)
        (self.root / "backups" / surr_bak).write_bytes(surr_bytes)

        for bak in (dbom_bak, surr_bak):
            with self.assertRaises(ValueError):
                restore_backup(self.root, bak, "Save0.Save")

        (self.root / "Save2.Save").write_bytes(double_bom_bytes)
        (self.root / "Save3.Save").write_bytes(surr_bytes)
        (self.root / "Save6.Save").write_bytes(serialize_json_lossless(create_demo_data("round")).encode("utf-8"))

        srv = create_bridge_server(self.root, "127.0.0.1", 0)
        base_url = f"http://127.0.0.1:{srv.server_address[1]}"
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            for slot in ("Save2.Save", "Save3.Save", "Save6.Save"):
                req = urllib.request.Request(
                    f"{base_url}/api/load?slot={urllib.parse.quote(slot)}",
                    headers={
                        "Origin": base_url,
                        "X-TWX-Token": srv.bridge_token,
                    },
                )
                err = None
                try:
                    with self.assertRaises(urllib.error.HTTPError) as cm:
                        urllib.request.urlopen(req, timeout=5)
                    err = cm.exception
                    self.assertEqual(err.code, 400)
                finally:
                    if err is not None:
                        err.close()

            for backup in (dbom_bak, surr_bak):
                payload = f'{{"slot":"Save0.Save","backup":"{backup}"}}'.encode("utf-8")
                req = urllib.request.Request(
                    f"{base_url}/api/restore",
                    data=payload,
                    headers={
                        "Origin": base_url,
                        "X-TWX-Token": srv.bridge_token,
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                err = None
                try:
                    with self.assertRaises(urllib.error.HTTPError) as cm:
                        urllib.request.urlopen(req, timeout=5)
                    err = cm.exception
                    self.assertEqual(err.code, 400)
                finally:
                    if err is not None:
                        err.close()
        finally:
            srv.shutdown()
            srv.server_close()
            th.join(timeout=5)

    def test_v20_exchange_failure_paths_and_flock_inode_recheck(self) -> None:
        def reset_state(money: int, label: str) -> tuple[bytes, bytes]:
            for entry in self.root.iterdir():
                if entry.name.endswith(".tmp"):
                    try:
                        entry.unlink()
                    except FileNotFoundError:
                        pass
            backup_dir = self.root / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            for entry in backup_dir.iterdir():
                if entry.name.endswith(".bak"):
                    try:
                        entry.unlink()
                    except FileNotFoundError:
                        pass

            save_obj = create_demo_data("save")
            save_obj["m_iMoney"] = money
            save_obj["m_strPlayerName"] = label + "\r"
            save_bytes = serialize_json_lossless(save_obj).encode("utf-8")

            title_entry = {
                "m_bHaveData": False,
                "m_strPlayerName": "",
                "m_strPlaceName": "",
                "m_strYear": "1",
                "m_strMonth": "",
                "m_strTime": "",
                "m_strPlayerIconName": "900005",
                "m_strTrueYear": "2026/11/18",
                "m_strTrueTime": "12\uff1a00",
            }
            t_entries = [dict(title_entry) for _ in range(6)]
            t_entries[0]["m_strPlayerName"] = label
            title_bytes = serialize_json_lossless(t_entries).encode("utf-8")

            (self.root / "Save0.Save").write_bytes(save_bytes)
            (self.root / "SaveTitle.SaveTitle").write_bytes(title_bytes)
            return save_bytes, title_bytes

        if os.name != "nt":
            if _posix_supports_rename_exchange(self.root):
                cand_text = serialize_json_lossless(
                    {
                        **create_demo_data("save"),
                        "m_iMoney": 999999,
                        "m_strPlayerName": "CAND\r",
                    }
                )

                bs, bt = reset_state(123456, "ORIG")
                try:
                    os.environ["TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP"] = "slot"
                    os.environ["TWX_SIMULATE_SWAPBACK_FAIL"] = "slot"
                    with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                        atomic_save_with_backup(
                            self.root,
                            "Save0.Save",
                            cand_text,
                            expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                        )
                    self.assertEqual(
                        parse_json_lossless(
                            read_safe_bytes(self.root, "Save0.Save").decode("utf-8")
                        )[0]["m_iMoney"],
                        777777,
                    )
                    self.assertEqual(
                        read_safe_bytes(self.root, "SaveTitle.SaveTitle"),
                        bt,
                    )
                    displaced = [
                        p
                        for p in self.root.iterdir()
                        if p.name.startswith(".Save0.Save.") and p.name.endswith(".tmp")
                    ]
                    self.assertEqual(len(displaced), 1)
                    self.assertEqual(
                        parse_json_lossless(displaced[0].read_bytes().decode("utf-8"))[0]["m_iMoney"],
                        777777,
                    )
                    self.assertTrue(
                        [p for p in (self.root / "backups").iterdir() if p.name.endswith(".bak")]
                    )
                finally:
                    os.environ.pop("TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP", None)
                    os.environ.pop("TWX_SIMULATE_SWAPBACK_FAIL", None)

                bs, bt = reset_state(234567, "ORIG")
                try:
                    os.environ["TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP"] = "title"
                    os.environ["TWX_SIMULATE_SWAPBACK_FAIL"] = "title"
                    with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                        atomic_save_with_backup(
                            self.root,
                            "Save0.Save",
                            cand_text,
                            expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                        )
                    self.assertEqual(read_safe_bytes(self.root, "Save0.Save"), bs)
                    self.assertEqual(
                        parse_json_lossless(
                            read_safe_bytes(self.root, "SaveTitle.SaveTitle").decode("utf-8")
                        )[0][0]["m_strPlayerName"],
                        "EXT_TITLE_WRITER",
                    )
                    displaced_titles = [
                        p
                        for p in self.root.iterdir()
                        if p.name.startswith(".SaveTitle.SaveTitle.") and p.name.endswith(".tmp")
                    ]
                    self.assertEqual(len(displaced_titles), 1)
                    self.assertEqual(
                        parse_json_lossless(displaced_titles[0].read_bytes().decode("utf-8"))[0][0][
                            "m_strPlayerName"
                        ],
                        "EXT_TITLE_WRITER",
                    )
                    self.assertTrue(
                        [p for p in (self.root / "backups").iterdir() if p.name.endswith(".bak")]
                    )
                finally:
                    os.environ.pop("TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP", None)
                    os.environ.pop("TWX_SIMULATE_SWAPBACK_FAIL", None)

                bs, bt = reset_state(300001, "ORIG")
                try:
                    os.environ["TWX_SIMULATE_POST_EXCHANGE_UNLINK_FAIL"] = "slot"
                    with self.assertRaises(OSError):
                        atomic_save_with_backup(
                            self.root,
                            "Save0.Save",
                            cand_text,
                            expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                        )
                    self.assertEqual(read_safe_bytes(self.root, "Save0.Save"), bs)
                    self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
                    self.assertEqual(
                        [p.name for p in self.root.iterdir() if p.name.endswith(".tmp")],
                        [],
                    )
                finally:
                    os.environ.pop("TWX_SIMULATE_POST_EXCHANGE_UNLINK_FAIL", None)

                bs, bt = reset_state(300002, "ORIG")
                try:
                    os.environ["TWX_SIMULATE_POST_EXCHANGE_UNLINK_FAIL"] = "title"
                    with self.assertRaises(OSError):
                        atomic_save_with_backup(
                            self.root,
                            "Save0.Save",
                            cand_text,
                            expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                        )
                    self.assertEqual(read_safe_bytes(self.root, "Save0.Save"), bs)
                    self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
                    self.assertEqual(
                        [p.name for p in self.root.iterdir() if p.name.endswith(".tmp")],
                        [],
                    )
                finally:
                    os.environ.pop("TWX_SIMULATE_POST_EXCHANGE_UNLINK_FAIL", None)

                bs, bt = reset_state(300003, "ORIG")
                try:
                    os.environ["TWX_SIMULATE_POST_EXCHANGE_UNLINK_FAIL"] = "title"
                    os.environ["TWX_SIMULATE_SWAPBACK_FAIL"] = "title"
                    with self.assertRaises(OSError):
                        atomic_save_with_backup(
                            self.root,
                            "Save0.Save",
                            cand_text,
                            expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                        )
                    self.assertEqual(read_safe_bytes(self.root, "Save0.Save"), bs)
                    self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
                    self.assertTrue(
                        [p for p in (self.root / "backups").iterdir() if p.name.endswith(".bak")]
                    )
                finally:
                    os.environ.pop("TWX_SIMULATE_POST_EXCHANGE_UNLINK_FAIL", None)
                    os.environ.pop("TWX_SIMULATE_SWAPBACK_FAIL", None)

                for env_name, env_value in (
                    ("TWX_SIMULATE_POST_PREVERIFY_TMP_TAMPER", "slot"),
                    ("TWX_SIMULATE_POST_PREVERIFY_TMP_TAMPER", "title"),
                    ("TWX_SIMULATE_POST_PREVERIFY_TMP_SWAP", "slot"),
                ):
                    bs, bt = reset_state(300004, "ORIG")
                    try:
                        os.environ[env_name] = env_value
                        with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                            atomic_save_with_backup(
                                self.root,
                                "Save0.Save",
                                cand_text,
                                expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                            )
                        self.assertEqual(read_safe_bytes(self.root, "Save0.Save"), bs)
                        self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
                        if env_name == "TWX_SIMULATE_POST_PREVERIFY_TMP_SWAP":
                            self.assertEqual(
                                list(self.root.glob(".SaveTitle.SaveTitle.*.tmp")),
                                [],
                            )
                            post_pv_tmp_swap_tmps = list(self.root.glob(".Save0.Save.*.tmp"))
                            self.assertEqual(len(post_pv_tmp_swap_tmps), 1)
                            self.assertEqual(
                                post_pv_tmp_swap_tmps[0].read_bytes(),
                                b'{"post_pv_tmp_swapped":1}',
                            )
                        else:
                            self.assertEqual(
                                [p.name for p in self.root.iterdir() if p.name.endswith(".tmp")],
                                [],
                            )
                        self.assertEqual(
                            [p for p in (self.root / "backups").iterdir() if p.name.endswith(".bak")],
                            [],
                        )
                    finally:
                        os.environ.pop(env_name, None)

            import fcntl

            for entry in self.root.iterdir():
                if entry.name.endswith(".tmp"):
                    try:
                        entry.unlink()
                    except FileNotFoundError:
                        pass
            lock_path = self.root / ".twx_store.lock"
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

            ext_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                old_ino = os.fstat(ext_fd).st_ino
                orig_flock = fcntl.flock
                orig_flock(ext_fd, fcntl.LOCK_EX)
                locked_inos: list[int] = []
                reached_first_flock = threading.Event()
                entered_guard = threading.Event()
                release_guard = threading.Event()
                live_ino_box: list[int] = []
                worker_errors: list[BaseException] = []

                def patched_flock(fd: int, operation: int) -> None:
                    if threading.current_thread() is thread and (operation & fcntl.LOCK_EX):
                        locked_inos.append(os.fstat(fd).st_ino)
                        if len(locked_inos) == 1:
                            reached_first_flock.set()
                    return orig_flock(fd, operation)

                def worker() -> None:
                    try:
                        with _store_lock_guard(self.root):
                            live_ino_box.append(os.lstat(lock_path).st_ino)
                            entered_guard.set()
                            release_guard.wait(timeout=10)
                    except BaseException as exc:
                        worker_errors.append(exc)

                thread = threading.Thread(target=worker)
                with unittest.mock.patch("fcntl.flock", side_effect=patched_flock):
                    thread.start()
                    self.assertTrue(reached_first_flock.wait(timeout=10))
                    self.assertEqual(locked_inos[0], old_ino)
                    os.unlink(lock_path)
                    orig_flock(ext_fd, fcntl.LOCK_UN)
                    os.close(ext_fd)
                    ext_fd = -1

                    self.assertTrue(entered_guard.wait(timeout=10))
                    self.assertTrue(lock_path.exists())
                    self.assertGreaterEqual(len(locked_inos), 2)
                    self.assertEqual(locked_inos[-1], live_ino_box[0])
                    self.assertEqual(live_ino_box[0], os.lstat(lock_path).st_ino)

                    probe_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
                    try:
                        with self.assertRaises(BlockingIOError):
                            orig_flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    finally:
                        os.close(probe_fd)

                    release_guard.set()
                    thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
                self.assertEqual(worker_errors, [])
            finally:
                if ext_fd != -1:
                    try:
                        orig_flock(ext_fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
                    os.close(ext_fd)
                release_guard.set()

        old_max_save_bytes = getattr(__import__("twx_editor"), "MAX_SAVE_BYTES")
        try:
            with unittest.mock.patch("twx_editor.MAX_SAVE_BYTES", 300 * 1024):
                big_save = create_demo_data("save")
                big_save["_pad"] = "A" * (250 * 1024)
                big_text = serialize_json_lossless(big_save)
                initial_bytes = big_text.encode("utf-8")
                (self.root / "Save0.Save").write_bytes(initial_bytes)
                base_sha = hashlib.sha256(initial_bytes).hexdigest()
                text_literal = json.dumps(big_text)
                encoded_text = text_literal.replace("A", "\\u0041")
                payload = (
                    '{"slot":"Save0.Save","text":'
                    + encoded_text
                    + ',"baseSha256":"'
                    + base_sha
                    + '"}'
                ).encode("utf-8")
                self.assertGreater(len(payload), 300 * 1024 + 1024 * 1024)
                self.assertLess(len(payload), 300 * 1024 * 6 + 1024 * 1024)

                srv = create_bridge_server(self.root, "127.0.0.1", 0)
                th = threading.Thread(target=srv.serve_forever, daemon=True)
                th.start()
                try:
                    port = srv.server_address[1]
                    base_url = f"http://127.0.0.1:{port}"
                    req = urllib.request.Request(
                        f"{base_url}/api/save",
                        data=payload,
                        method="POST",
                        headers={
                            "Origin": base_url,
                            "X-TWX-Token": srv.bridge_token,
                            "Content-Type": "application/json",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        self.assertEqual(resp.status, 200)
                        res_json = json.loads(resp.read().decode("utf-8"))
                    self.assertIs(res_json["ok"], True)
                finally:
                    srv.shutdown()
                    srv.server_close()
                    th.join(timeout=5)
        finally:
            __import__("twx_editor").MAX_SAVE_BYTES = old_max_save_bytes

    def test_v21_post_exchange_ext_replace_corrupt_swapback_fail_and_slash_dedup(self) -> None:
        def reset_state(money: int, label: str) -> tuple[bytes, bytes]:
            for entry in self.root.iterdir():
                if entry.name.endswith(".tmp"):
                    try:
                        entry.unlink()
                    except FileNotFoundError:
                        pass
            backup_dir = self.root / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            for entry in backup_dir.iterdir():
                if entry.name.endswith(".bak"):
                    try:
                        entry.unlink()
                    except FileNotFoundError:
                        pass

            save_obj = create_demo_data("save")
            save_obj["m_iMoney"] = money
            save_obj["m_strPlayerName"] = label + "\r"
            save_bytes = serialize_json_lossless(save_obj).encode("utf-8")

            title_entry = {
                "m_bHaveData": False,
                "m_strPlayerName": "",
                "m_strPlaceName": "",
                "m_strYear": "1",
                "m_strMonth": "",
                "m_strTime": "",
                "m_strPlayerIconName": "900005",
                "m_strTrueYear": "2026/11/18",
                "m_strTrueTime": "12\uff1a00",
            }
            t_entries = [dict(title_entry) for _ in range(6)]
            t_entries[0]["m_strPlayerName"] = label
            title_bytes = serialize_json_lossless(t_entries).encode("utf-8")

            (self.root / "Save0.Save").write_bytes(save_bytes)
            (self.root / "SaveTitle.SaveTitle").write_bytes(title_bytes)
            return save_bytes, title_bytes

        cand_text = serialize_json_lossless(
            {
                **create_demo_data("save"),
                "m_iMoney": 555555,
                "m_strPlayerName": "CAND_V21\r",
            }
        )

        if os.name != "nt" and _posix_supports_rename_exchange(self.root):
            bs, bt = reset_state(400001, "ORIG")
            try:
                os.environ["TWX_SIMULATE_POST_EXCHANGE_EXT_REPLACE"] = "slot"
                with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                    atomic_save_with_backup(
                        self.root,
                        "Save0.Save",
                        cand_text,
                        expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                    )
                self.assertEqual(
                    parse_json_lossless(
                        read_safe_bytes(self.root, "Save0.Save").decode("utf-8")
                    )[0]["m_iMoney"],
                    888888,
                )
                self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
                self.assertEqual(list(self.root.glob(".SaveTitle.SaveTitle.*.tmp")), [])
                self.assertTrue(list((self.root / "backups").glob("*.bak")))
            finally:
                os.environ.pop("TWX_SIMULATE_POST_EXCHANGE_EXT_REPLACE", None)

            bs, bt = reset_state(400002, "ORIG")
            try:
                os.environ["TWX_SIMULATE_POST_EXCHANGE_EXT_REPLACE"] = "title"
                with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                    atomic_save_with_backup(
                        self.root,
                        "Save0.Save",
                        cand_text,
                        expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                    )
                self.assertEqual(
                    parse_json_lossless(
                        read_safe_bytes(self.root, "SaveTitle.SaveTitle").decode("utf-8")
                    )[0][0]["m_strPlayerName"],
                    "EXT_POST_EXCHANGE_TITLE",
                )
                self.assertEqual(read_safe_bytes(self.root, "Save0.Save"), bs)
                self.assertTrue(list((self.root / "backups").glob("*.bak")))
            finally:
                os.environ.pop("TWX_SIMULATE_POST_EXCHANGE_EXT_REPLACE", None)

            import twx_editor

            for role in ("slot", "title"):
                bs, bt = reset_state(400003, "ORIG")
                exchanged_targets: list[str] = []
                orig_rename_exchange = twx_editor._posix_try_rename_exchange

                def _spy_rename_exchange(dfd_s: int, src_s: str, dst_s: str) -> str:
                    exchanged_targets.append(dst_s)
                    return orig_rename_exchange(dfd_s, src_s, dst_s)

                try:
                    os.environ["TWX_SIMULATE_POST_PREVERIFY_TMP_TAMPER"] = role
                    os.environ["TWX_SIMULATE_SWAPBACK_FAIL"] = role
                    with unittest.mock.patch.object(
                        twx_editor, "_posix_try_rename_exchange", side_effect=_spy_rename_exchange
                    ):
                        with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                            atomic_save_with_backup(
                                self.root,
                                "Save0.Save",
                                cand_text,
                                expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                            )
                    if role == "slot":
                        self.assertNotIn("Save0.Save", exchanged_targets)
                    else:
                        self.assertNotIn("SaveTitle.SaveTitle", exchanged_targets)
                    self.assertEqual(read_safe_bytes(self.root, "Save0.Save"), bs)
                    self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
                    self.assertEqual([n for n in os.listdir(self.root) if n.endswith(".tmp")], [])
                finally:
                    os.environ.pop("TWX_SIMULATE_POST_PREVERIFY_TMP_TAMPER", None)
                    os.environ.pop("TWX_SIMULATE_SWAPBACK_FAIL", None)

        if os.name != "nt":
            reset_state(1000, "ORIG")
            slash2_root = "//" + str(self.root).lstrip("/")
            slash3_root = "///" + str(self.root).lstrip("/")

            nested_errors: list[BaseException] = []

            def _nested_lock_worker() -> None:
                try:
                    with _store_lock_guard(self.root):
                        with _store_lock_guard(Path(slash2_root)):
                            with _store_lock_guard(Path(slash3_root)):
                                pass
                except BaseException as exc:
                    nested_errors.append(exc)

            th = threading.Thread(target=_nested_lock_worker)
            th.start()
            th.join(timeout=5.0)
            self.assertFalse(th.is_alive())
            self.assertEqual(nested_errors, [])

            apply_result: dict[str, object] = {"code": None, "errors": []}

            def _slash_apply_worker() -> None:
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        apply_result["code"] = main(
                            [
                                "apply",
                                str(self.root / "Save0.Save"),
                                "--root",
                                slash2_root,
                                "--preset",
                                "max_money",
                            ]
                        )
                except BaseException as exc:
                    errs = apply_result["errors"]
                    if isinstance(errs, list):
                        errs.append(exc)

            th_apply = threading.Thread(target=_slash_apply_worker)
            th_apply.start()
            th_apply.join(timeout=5.0)
            self.assertFalse(th_apply.is_alive())
            self.assertEqual(apply_result["errors"], [])
            self.assertEqual(apply_result["code"], 0)
            self.assertEqual(
                parse_json_lossless(
                    read_safe_bytes(self.root, "Save0.Save").decode("utf-8")
                )[0]["m_iMoney"],
                9999999,
            )
        else:
            nested_errors_nt: list[BaseException] = []

            def _same_root_nested_lock_worker() -> None:
                try:
                    with _store_lock_guard(self.root):
                        with _store_lock_guard(self.root):
                            pass
                except BaseException as exc:
                    nested_errors_nt.append(exc)

            th_same = threading.Thread(target=_same_root_nested_lock_worker)
            th_same.start()
            th_same.join(timeout=5.0)
            self.assertFalse(th_same.is_alive())
            self.assertEqual(nested_errors_nt, [])

    def test_v22_post_exchange_inplace_ext_write_and_global_ident_lock_order(self) -> None:
        import twx_editor

        def reset_state(money: int, label: str) -> tuple[bytes, bytes]:
            for entry in self.root.iterdir():
                if entry.name.endswith(".tmp"):
                    try:
                        entry.unlink()
                    except FileNotFoundError:
                        pass
            backup_dir = self.root / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            for entry in backup_dir.iterdir():
                if entry.name.endswith(".bak"):
                    try:
                        entry.unlink()
                    except FileNotFoundError:
                        pass

            save_obj = create_demo_data("save")
            save_obj["m_iMoney"] = money
            save_obj["m_strPlayerName"] = label + "\r"
            save_bytes = serialize_json_lossless(save_obj).encode("utf-8")

            title_entry = {
                "m_bHaveData": False,
                "m_strPlayerName": "",
                "m_strPlaceName": "",
                "m_strYear": "1",
                "m_strMonth": "",
                "m_strTime": "",
                "m_strPlayerIconName": "900005",
                "m_strTrueYear": "2026/11/18",
                "m_strTrueTime": "12\uff1a00",
            }
            t_entries = [dict(title_entry) for _ in range(6)]
            t_entries[0]["m_strPlayerName"] = label
            title_bytes = serialize_json_lossless(t_entries).encode("utf-8")

            (self.root / "Save0.Save").write_bytes(save_bytes)
            (self.root / "SaveTitle.SaveTitle").write_bytes(title_bytes)
            return save_bytes, title_bytes

        cand_text = serialize_json_lossless(
            {
                **create_demo_data("save"),
                "m_iMoney": 654321,
                "m_strPlayerName": "CAND_V22\r",
            }
        )

        if os.name != "nt" and _posix_supports_rename_exchange(self.root):
            for swapback_fail in (False, True):
                bs, bt = reset_state(500001, "ORIG_V22")
                try:
                    os.environ["TWX_SIMULATE_POST_EXCHANGE_EXT_INPLACE"] = "slot"
                    if swapback_fail:
                        os.environ["TWX_SIMULATE_SWAPBACK_FAIL"] = "slot"
                    with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                        atomic_save_with_backup(
                            self.root,
                            "Save0.Save",
                            cand_text,
                            expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                        )
                    self.assertEqual(
                        parse_json_lossless(
                            read_safe_bytes(self.root, "Save0.Save").decode("utf-8")
                        )[0]["m_iMoney"],
                        765432,
                    )
                    self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
                    displaced_slots = list(self.root.glob(".Save0.Save.*.tmp"))
                    self.assertEqual(len(displaced_slots), 1)
                    self.assertEqual(
                        parse_json_lossless(displaced_slots[0].read_bytes().decode("utf-8"))[0][
                            "m_iMoney"
                        ],
                        500001,
                    )
                    self.assertEqual(list(self.root.glob(".SaveTitle.SaveTitle.*.tmp")), [])
                    self.assertTrue(list((self.root / "backups").glob("*.bak")))
                finally:
                    os.environ.pop("TWX_SIMULATE_POST_EXCHANGE_EXT_INPLACE", None)
                    os.environ.pop("TWX_SIMULATE_SWAPBACK_FAIL", None)

            for swapback_fail in (False, True):
                bs, bt = reset_state(500002, "ORIG_V22")
                try:
                    os.environ["TWX_SIMULATE_POST_EXCHANGE_EXT_INPLACE"] = "title"
                    if swapback_fail:
                        os.environ["TWX_SIMULATE_SWAPBACK_FAIL"] = "title"
                    with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                        atomic_save_with_backup(
                            self.root,
                            "Save0.Save",
                            cand_text,
                            expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                        )
                    self.assertEqual(
                        parse_json_lossless(
                            read_safe_bytes(self.root, "SaveTitle.SaveTitle").decode("utf-8")
                        )[0][0]["m_strPlayerName"],
                        "EXT_POST_EXCHANGE_INPLACE_TITLE",
                    )
                    self.assertEqual(read_safe_bytes(self.root, "Save0.Save"), bs)
                    displaced_titles = list(self.root.glob(".SaveTitle.SaveTitle.*.tmp"))
                    self.assertEqual(len(displaced_titles), 1)
                    self.assertEqual(displaced_titles[0].read_bytes(), bt)
                    self.assertEqual(list(self.root.glob(".Save0.Save.*.tmp")), [])
                    self.assertTrue(list((self.root / "backups").glob("*.bak")))
                finally:
                    os.environ.pop("TWX_SIMULATE_POST_EXCHANGE_EXT_INPLACE", None)
                    os.environ.pop("TWX_SIMULATE_SWAPBACK_FAIL", None)

        sacrificial = self.root / "00_sacrificial_ino"
        sacrificial.mkdir(parents=True, exist_ok=True)
        z_dir = self.root / "z_ident_test"
        a_dir = self.root / "a_ident_test"
        z_dir.mkdir(parents=True, exist_ok=True)
        a_dir.mkdir(parents=True, exist_ok=True)
        sacrificial.rmdir()
        sub_dir = z_dir / "sub_slot"
        sub_dir.mkdir(parents=True, exist_ok=True)

        z_save = z_dir / "Save0.Save"
        a_save = a_dir / "Save0.Save"
        z_save.write_text(serialize_json_lossless(create_demo_data("save")), encoding="utf-8")
        a_save.write_text(serialize_json_lossless(create_demo_data("save")), encoding="utf-8")

        id_z = _capture_root_identity(z_dir)
        id_a = _capture_root_identity(a_dir)
        id_sub = _capture_root_identity(sub_dir)
        expected_za = sorted([id_z, id_a])
        expected_zsub = sorted([id_z, id_sub])

        real_store_lock_guard = twx_editor._store_lock_guard
        recorded_runs: list[list[tuple[object, ...]]] = []
        current_run: list[tuple[object, ...]] = []
        held_idents: set[tuple[object, ...]] = set()

        @contextlib.contextmanager
        def spy_store_lock_guard(root_p: Path, *args: object, **kwargs: object):
            ident = _capture_root_identity(root_p)
            is_outer = ident not in held_idents
            if is_outer:
                current_run.append(ident)
                held_idents.add(ident)
            try:
                with real_store_lock_guard(root_p, *args, **kwargs) as val:
                    yield val
            finally:
                if is_outer:
                    held_idents.discard(ident)

        with unittest.mock.patch.object(twx_editor, "_store_lock_guard", spy_store_lock_guard):
            current_run = []
            with contextlib.redirect_stdout(io.StringIO()):
                rc1 = main(["apply", str(z_save), "--out", str(a_save), "--set-money", "123456"])
            self.assertEqual(rc1, 0)
            recorded_runs.append(list(current_run))

            current_run = []
            with contextlib.redirect_stdout(io.StringIO()):
                rc2 = main(["apply", str(a_save), "--out", str(z_save), "--set-money", "654321"])
            self.assertEqual(rc2, 0)
            recorded_runs.append(list(current_run))

            current_run = []
            with _slot_lock_guard(z_dir, "sub_slot/Save0.Save", create_dirs=True):
                pass
            recorded_runs.append(list(current_run))

        self.assertEqual(recorded_runs[0], expected_za)
        self.assertEqual(recorded_runs[1], expected_za)
        self.assertEqual(recorded_runs[2], expected_zsub)

    def test_v23_unsupported_exchange_and_displaced_orig_write(self) -> None:
        import twx_editor

        def reset_state(money: int, label: str) -> tuple[bytes, bytes]:
            for entry in self.root.iterdir():
                if entry.name.endswith(".tmp"):
                    try:
                        entry.unlink()
                    except FileNotFoundError:
                        pass
            backup_dir = self.root / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            for entry in backup_dir.iterdir():
                if entry.name.endswith(".bak"):
                    try:
                        entry.unlink()
                    except FileNotFoundError:
                        pass

            save_obj = create_demo_data("save")
            save_obj["m_iMoney"] = money
            save_obj["m_strPlayerName"] = label + "\r"
            save_bytes = serialize_json_lossless(save_obj).encode("utf-8")

            title_entry = {
                "m_bHaveData": False,
                "m_strPlayerName": "",
                "m_strPlaceName": "",
                "m_strYear": "1",
                "m_strMonth": "",
                "m_strTime": "",
                "m_strPlayerIconName": "900005",
                "m_strTrueYear": "2026/11/18",
                "m_strTrueTime": "12\uff1a00",
            }
            t_entries = [dict(title_entry) for _ in range(6)]
            t_entries[0]["m_strPlayerName"] = label
            title_bytes = serialize_json_lossless(t_entries).encode("utf-8")

            (self.root / "Save0.Save").write_bytes(save_bytes)
            (self.root / "SaveTitle.SaveTitle").write_bytes(title_bytes)
            return save_bytes, title_bytes

        cand_text = serialize_json_lossless(
            {
                **create_demo_data("save"),
                "m_iMoney": 753159,
                "m_strPlayerName": "CAND_V23\r",
            }
        )

        if os.name != "nt":
            bs, bt = reset_state(600001, "ORIG_V23")
            real_replace = os.replace

            def forbid_slot_or_title_replace(src: object, dst: object, *a: object, **kw: object) -> None:
                if Path(str(dst)).name in ("Save0.Save", "Save1.Save", "SaveTitle.SaveTitle"):
                    raise AssertionError("os.replace must not overwrite slot or title under UNSUPPORTED")
                return real_replace(src, dst, *a, **kw)  # type: ignore[arg-type]

            with (
                unittest.mock.patch.object(
                    twx_editor, "_posix_try_rename_exchange", return_value="UNSUPPORTED"
                ),
                unittest.mock.patch("os.replace", side_effect=forbid_slot_or_title_replace),
            ):
                with self.assertRaisesRegex(RuntimeError, "ATOMIC_EXCHANGE_UNSUPPORTED"):
                    atomic_save_with_backup(
                        self.root,
                        "Save0.Save",
                        cand_text,
                        expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                    )
                self.assertEqual(read_safe_bytes(self.root, "Save0.Save"), bs)
                self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
                self.assertEqual(
                    [p.name for p in self.root.iterdir() if p.name.endswith(".tmp")],
                    [],
                )
                with self.assertRaisesRegex(RuntimeError, "ATOMIC_EXCHANGE_UNSUPPORTED"):
                    atomic_save_with_backup(self.root, "Save1.Save", cand_text)
                self.assertFalse(os.path.lexists(self.root / "Save1.Save"))
                self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
                self.assertEqual(
                    [p.name for p in self.root.iterdir() if p.name.endswith(".tmp")],
                    [],
                )

        if os.name != "nt" and _posix_supports_rename_exchange(self.root):
            for env_name in (
                "TWX_SIMULATE_POST_INSTALL_DISPLACED_WRITE",
                "TWX_SIMULATE_PRE_UNLINK_DISPLACED_WRITE",
            ):
                for swapback_fail in (False, True):
                    bs, bt = reset_state(600002, "ORIG_V23")
                    try:
                        os.environ[env_name] = "slot"
                        if swapback_fail:
                            os.environ["TWX_SIMULATE_SWAPBACK_FAIL"] = "slot"
                        with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                            atomic_save_with_backup(
                                self.root,
                                "Save0.Save",
                                cand_text,
                                expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                            )
                        self.assertEqual(
                            parse_json_lossless(
                                read_safe_bytes(self.root, "Save0.Save").decode("utf-8")
                            )[0]["m_iMoney"],
                            642000,
                        )
                        self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
                        displaced_slots = list(self.root.glob(".Save0.Save.*.tmp"))
                        if swapback_fail:
                            self.assertEqual(len(displaced_slots), 1)
                            self.assertEqual(
                                parse_json_lossless(
                                    displaced_slots[0].read_bytes().decode("utf-8")
                                )[0]["m_iMoney"],
                                642000,
                            )
                        else:
                            self.assertEqual(displaced_slots, [])
                        self.assertEqual(list(self.root.glob(".SaveTitle.SaveTitle.*.tmp")), [])
                        baks = list((self.root / "backups").glob("*.bak"))
                        self.assertTrue(baks)
                        self.assertTrue(any(p.read_bytes() == bs for p in baks))
                    finally:
                        os.environ.pop(env_name, None)
                        os.environ.pop("TWX_SIMULATE_SWAPBACK_FAIL", None)

                for swapback_fail in (False, True):
                    bs, bt = reset_state(600003, "ORIG_V23")
                    try:
                        os.environ[env_name] = "title"
                        if swapback_fail:
                            os.environ["TWX_SIMULATE_SWAPBACK_FAIL"] = "title"
                        with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                            atomic_save_with_backup(
                                self.root,
                                "Save0.Save",
                                cand_text,
                                expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                            )
                        self.assertEqual(
                            parse_json_lossless(
                                read_safe_bytes(self.root, "SaveTitle.SaveTitle").decode("utf-8")
                            )[0][0]["m_strPlayerName"],
                            "EXT_DISPLACED_ORIG_TITLE",
                        )
                        self.assertEqual(read_safe_bytes(self.root, "Save0.Save"), bs)
                        displaced_titles = list(self.root.glob(".SaveTitle.SaveTitle.*.tmp"))
                        if swapback_fail:
                            self.assertEqual(len(displaced_titles), 1)
                        else:
                            self.assertEqual(displaced_titles, [])
                        self.assertEqual(list(self.root.glob(".Save0.Save.*.tmp")), [])
                        baks = list((self.root / "backups").glob("*.bak"))
                        self.assertTrue(baks)
                        self.assertTrue(any(p.read_bytes() == bt for p in baks))
                    finally:
                        os.environ.pop(env_name, None)
                        os.environ.pop("TWX_SIMULATE_SWAPBACK_FAIL", None)

    def test_v24_unsupported_dual_fd_tamper_and_new_slot_fd_bound_link(self) -> None:
        if os.name == "nt":
            return
        import twx_editor

        def purge_tmps_and_baks() -> None:
            for name in os.listdir(self.root):
                if name.endswith(".tmp"):
                    try:
                        os.unlink(self.root / name)
                    except FileNotFoundError:
                        pass
            bdir = self.root / "backups"
            if bdir.exists():
                for bp in bdir.iterdir():
                    if bp.name.endswith(".bak"):
                        bp.unlink(missing_ok=True)

        base_save = create_demo_data("save")
        base_save["m_iMoney"] = 700001
        base_save["m_strPlayerName"] = "ORIG_V24\r"
        bs = serialize_json_lossless(base_save).encode("utf-8")

        t_arr = [
            {
                "m_bHaveData": False,
                "m_strPlayerName": "ORIG_V24" if idx == 0 else "",
                "m_strPlaceName": "",
                "m_strYear": "1",
                "m_strMonth": "",
                "m_strTime": "",
                "m_strPlayerIconName": "900005",
                "m_strTrueYear": "2026/11/19",
                "m_strTrueTime": "14\uff1a00",
            }
            for idx in range(4)
        ]
        bt = serialize_json_lossless(t_arr).encode("utf-8")

        cand_save = create_demo_data("save")
        cand_save["m_iMoney"] = 864200
        cand_save["m_strPlayerName"] = "CAND_V24\r"
        cand_text = serialize_json_lossless(cand_save)

        purge_tmps_and_baks()
        (self.root / "Save0.Save").write_bytes(bs)
        (self.root / "SaveTitle.SaveTitle").write_bytes(bt)
        real_os_replace = os.replace

        def spy_no_target_replace(src: object, dst: object, *a: object, **kw: object) -> None:
            if Path(str(dst)).name in ("Save0.Save", "Save1.Save", "SaveTitle.SaveTitle"):
                raise AssertionError("os.replace must not overwrite slot or title under UNSUPPORTED")
            return real_os_replace(src, dst, *a, **kw)  # type: ignore[arg-type]

        with (
            unittest.mock.patch.object(
                twx_editor, "_posix_try_rename_exchange", return_value="UNSUPPORTED"
            ),
            unittest.mock.patch("os.replace", side_effect=spy_no_target_replace),
        ):
            with self.assertRaisesRegex(RuntimeError, "ATOMIC_EXCHANGE_UNSUPPORTED"):
                atomic_save_with_backup(
                    self.root,
                    "Save0.Save",
                    cand_text,
                    expected_orig_sha256=hashlib.sha256(bs).hexdigest(),
                )
        self.assertEqual(read_safe_bytes(self.root, "Save0.Save"), bs)
        self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
        self.assertEqual([n for n in os.listdir(self.root) if n.endswith(".tmp")], [])

        with tempfile.TemporaryDirectory(dir=self.root.parent) as ext_dir:
            ext_secret = Path(ext_dir) / "outside_secret.txt"
            ext_secret.write_bytes(b"OUTSIDE_SECRET_DO_NOT_LINK")

            (self.root / "Save0.Save").write_bytes(bs)
            (self.root / "SaveTitle.SaveTitle").write_bytes(bt)

            swap_cases = [
                {
                    "TWX_SIMULATE_POSIX_NEW_SLOT_TMP_SWAP": "ext_symlink",
                    "TWX_SIMULATE_POSIX_NEW_SLOT_EXT_TARGET": str(ext_secret),
                },
                {
                    "TWX_SIMULATE_POSIX_NEW_SLOT_TMP_SWAP": "other_reg",
                },
                {
                    "TWX_SIMULATE_POSIX_NEW_SLOT_POST_LINK_TMP_SWAP": "ext_symlink",
                    "TWX_SIMULATE_POSIX_NEW_SLOT_EXT_TARGET": str(ext_secret),
                },
            ]
            for env_case in swap_cases:
                purge_tmps_and_baks()
                if os.path.lexists(self.root / "Save1.Save"):
                    os.unlink(self.root / "Save1.Save")
                with unittest.mock.patch.dict(os.environ, env_case, clear=False):
                    with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                        atomic_save_with_backup(self.root, "Save1.Save", cand_text)
                self.assertFalse(os.path.lexists(self.root / "Save1.Save"))
                self.assertEqual(ext_secret.stat().st_nlink, 1)
                self.assertEqual(ext_secret.read_bytes(), b"OUTSIDE_SECRET_DO_NOT_LINK")
                self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)

            purge_tmps_and_baks()
            ext_peer = Path(ext_dir) / "peer_hardlink.dat"
            ext_peer.write_bytes(b"EXT_REPLACED_SAVE1_NLINK2")
            ext_src = Path(ext_dir) / "replace_src.dat"
            os.link(ext_peer, ext_src)
            self.assertEqual(ext_src.stat().st_nlink, 2)
            with unittest.mock.patch.dict(
                os.environ,
                {
                    "TWX_SIMULATE_POSIX_NEW_SLOT_POST_LINK_TARGET_REPLACE": "1",
                    "TWX_SIMULATE_POSIX_NEW_SLOT_REPLACE_SRC": str(ext_src),
                },
                clear=False,
            ):
                with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                    atomic_save_with_backup(self.root, "Save1.Save", cand_text)
            self.assertTrue((self.root / "Save1.Save").is_file())
            self.assertEqual((self.root / "Save1.Save").read_bytes(), b"EXT_REPLACED_SAVE1_NLINK2")
            self.assertEqual(os.lstat(self.root / "Save1.Save").st_nlink, 2)
            self.assertEqual([n for n in os.listdir(self.root) if n.endswith(".tmp")], [])
            self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
            os.unlink(self.root / "Save1.Save")

            purge_tmps_and_baks()
            with unittest.mock.patch.dict(
                os.environ, {"TWX_FORCE_POSIX_NO_PROC_FD": "1"}, clear=False
            ):
                with self.assertRaisesRegex(RuntimeError, "ATOMIC_FD_LINK_UNSUPPORTED"):
                    atomic_save_with_backup(self.root, "Save1.Save", cand_text)
            self.assertFalse(os.path.lexists(self.root / "Save1.Save"))
            self.assertEqual([n for n in os.listdir(self.root) if n.endswith(".tmp")], [])
            self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)

            purge_tmps_and_baks()
            with unittest.mock.patch.dict(
                os.environ,
                {"TWX_SIMULATE_POSIX_NEW_SLOT_POST_LINK_SAME_INODE_WRITE": "1"},
                clear=False,
            ):
                with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                    atomic_save_with_backup(self.root, "Save1.Save", cand_text)
            self.assertTrue((self.root / "Save1.Save").is_file())
            ext_inplace_parsed, _ = parse_json_lossless(
                (self.root / "Save1.Save").read_text(encoding="utf-8")
            )
            self.assertEqual(ext_inplace_parsed["m_iMoney"], 919191)
            self.assertEqual(ext_inplace_parsed["m_strPlayerName"], "EXT_NEW_SLOT_INPLACE\r")
            self.assertEqual(os.lstat(self.root / "Save1.Save").st_nlink, 1)
            self.assertEqual([n for n in os.listdir(self.root) if n.endswith(".tmp")], [])
            self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
            os.unlink(self.root / "Save1.Save")

            purge_tmps_and_baks()
            import errno

            real_unlink = os.unlink
            unlink_attempts = [0]

            def _transient_fail_save1_unlink(p_arg: Any, *u_args: Any, **u_kw: Any) -> None:
                if Path(os.fsdecode(p_arg)).name == "Save1.Save":
                    unlink_attempts[0] += 1
                    if unlink_attempts[0] == 1:
                        raise OSError(errno.EIO, "TRANSIENT_SAVE1_UNLINK_FAIL")
                return real_unlink(p_arg, *u_args, **u_kw)

            with (
                unittest.mock.patch.dict(
                    os.environ, {"TWX_SIMULATE_POSIX_LINK_TMP_UNLINK_FAIL": "1"}, clear=False
                ),
                unittest.mock.patch("os.unlink", side_effect=_transient_fail_save1_unlink),
            ):
                with self.assertRaises(OSError):
                    atomic_save_with_backup(self.root, "Save1.Save", cand_text)
            self.assertGreaterEqual(unlink_attempts[0], 2)
            self.assertFalse(os.path.lexists(self.root / "Save1.Save"))
            self.assertEqual([n for n in os.listdir(self.root) if n.endswith(".tmp")], [])
            self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
            self.assertEqual(list((self.root / "backups").glob("*.bak")), [])

            purge_tmps_and_baks()

            def _persistent_fail_save1_unlink(p_arg: Any, *u_args: Any, **u_kw: Any) -> None:
                if Path(os.fsdecode(p_arg)).name == "Save1.Save":
                    raise OSError(errno.EACCES, "PERSISTENT_SAVE1_UNLINK_FAIL")
                return real_unlink(p_arg, *u_args, **u_kw)

            with (
                unittest.mock.patch.dict(
                    os.environ, {"TWX_SIMULATE_POSIX_LINK_TMP_UNLINK_FAIL": "1"}, clear=False
                ),
                unittest.mock.patch("os.unlink", side_effect=_persistent_fail_save1_unlink),
            ):
                with self.assertRaises(OSError):
                    atomic_save_with_backup(self.root, "Save1.Save", cand_text)
            self.assertTrue((self.root / "Save1.Save").is_file())
            self.assertEqual(os.lstat(self.root / "Save1.Save").st_nlink, 1)
            self.assertEqual([n for n in os.listdir(self.root) if n.endswith(".tmp")], [])
            self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
            self.assertGreaterEqual(len(list((self.root / "backups").glob("*.bak"))), 1)
            os.unlink(self.root / "Save1.Save")

            purge_tmps_and_baks()
            with unittest.mock.patch.dict(
                os.environ, {"TWX_FORCE_POSIX_NO_PROC_FD": "1"}, clear=False
            ):
                with self.assertRaisesRegex(RuntimeError, "ATOMIC_FD_LINK_UNSUPPORTED"):
                    twx_editor._write_backup_verified(self.root, "Save0.Save", bs)
            self.assertEqual(
                [n for n in os.listdir(self.root / "backups") if n.endswith(".tmp")], []
            )

            purge_tmps_and_baks()
            real_lstat = os.lstat
            save1_lstat_calls = [0]

            def _eio_init_lstat_save1(p_arg: Any, *l_args: Any, **l_kw: Any) -> Any:
                res_st = real_lstat(p_arg, *l_args, **l_kw)
                if Path(os.fsdecode(p_arg)).name == "Save1.Save":
                    save1_lstat_calls[0] += 1
                    if save1_lstat_calls[0] >= 2:
                        raise OSError(errno.EIO, "SIMULATED_SAVE1_LSTAT_EIO")
                return res_st

            with (
                unittest.mock.patch.dict(
                    os.environ, {"TWX_SIMULATE_POSIX_LINK_TMP_UNLINK_FAIL": "1"}, clear=False
                ),
                unittest.mock.patch("os.lstat", side_effect=_eio_init_lstat_save1),
            ):
                with self.assertRaises(OSError):
                    atomic_save_with_backup(self.root, "Save1.Save", cand_text)
            self.assertEqual([n for n in os.listdir(self.root) if n.endswith(".tmp")], [])
            self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
            self.assertGreaterEqual(len(list((self.root / "backups").glob("*.bak"))), 1)
            if os.path.lexists(self.root / "Save1.Save"):
                os.unlink(self.root / "Save1.Save")

            purge_tmps_and_baks()
            real_fsync_dir = twx_editor._fsync_dir_fd
            unlinked_save1_flag = [False]

            def _track_unlink_save1(p_arg: Any, *u_args: Any, **u_kw: Any) -> None:
                if Path(os.fsdecode(p_arg)).name == "Save1.Save":
                    unlinked_save1_flag[0] = True
                return real_unlink(p_arg, *u_args, **u_kw)

            def _fail_fsync_after_save1_unlink(d_fd: int | None) -> None:
                if unlinked_save1_flag[0]:
                    unlinked_save1_flag[0] = False
                    raise OSError(errno.EIO, "SIMULATED_POST_UNLINK_DIR_FSYNC_FAIL")
                return real_fsync_dir(d_fd)

            with (
                unittest.mock.patch.dict(
                    os.environ, {"TWX_SIMULATE_POSIX_LINK_TMP_UNLINK_FAIL": "1"}, clear=False
                ),
                unittest.mock.patch("os.unlink", side_effect=_track_unlink_save1),
                unittest.mock.patch.object(
                    twx_editor, "_fsync_dir_fd", side_effect=_fail_fsync_after_save1_unlink
                ),
            ):
                with self.assertRaises(OSError):
                    atomic_save_with_backup(self.root, "Save1.Save", cand_text)
            self.assertFalse(os.path.lexists(self.root / "Save1.Save"))
            self.assertEqual([n for n in os.listdir(self.root) if n.endswith(".tmp")], [])
            self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
            self.assertGreaterEqual(len(list((self.root / "backups").glob("*.bak"))), 1)

            purge_tmps_and_baks()
            post_unlink_lstat = [False]

            def _mark_unlink_for_post_lstat(p_arg: Any, *u_args: Any, **u_kw: Any) -> None:
                if Path(os.fsdecode(p_arg)).name == "Save1.Save":
                    post_unlink_lstat[0] = True
                return real_unlink(p_arg, *u_args, **u_kw)

            def _eio_post_unlink_lstat(p_arg: Any, *l_args: Any, **l_kw: Any) -> Any:
                if post_unlink_lstat[0] and Path(os.fsdecode(p_arg)).name == "Save1.Save":
                    raise OSError(errno.EIO, "SIMULATED_POST_UNLINK_LSTAT_EIO")
                return real_lstat(p_arg, *l_args, **l_kw)

            with (
                unittest.mock.patch.dict(
                    os.environ, {"TWX_SIMULATE_POSIX_LINK_TMP_UNLINK_FAIL": "1"}, clear=False
                ),
                unittest.mock.patch("os.unlink", side_effect=_mark_unlink_for_post_lstat),
                unittest.mock.patch("os.lstat", side_effect=_eio_post_unlink_lstat),
            ):
                with self.assertRaises(OSError):
                    atomic_save_with_backup(self.root, "Save1.Save", cand_text)
            self.assertEqual([n for n in os.listdir(self.root) if n.endswith(".tmp")], [])
            self.assertEqual(read_safe_bytes(self.root, "SaveTitle.SaveTitle"), bt)
            self.assertGreaterEqual(len(list((self.root / "backups").glob("*.bak"))), 1)

            purge_tmps_and_baks()
            res1 = atomic_save_with_backup(self.root, "Save1.Save", cand_text)
            self.assertEqual(res1["sha256"], hashlib.sha256(cand_text.encode("utf-8")).hexdigest())
            self.assertEqual(os.lstat(self.root / "Save1.Save").st_nlink, 1)
            self.assertEqual([n for n in os.listdir(self.root) if n.endswith(".tmp")], [])

    def test_v26_sci_int_and_cli_ancestor_case_collision(self) -> None:
        sub_dir = self.root / "subcase"
        sub_dir.mkdir()
        sub_slot = sub_dir / "Save0.Save"
        sub_slot.write_text(serialize_json_lossless(create_demo_data("save")), encoding="utf-8")
        out_ok = io.StringIO()
        err_ok = io.StringIO()
        with contextlib.redirect_stdout(out_ok), contextlib.redirect_stderr(err_ok):
            self.assertEqual(main(["validate", str(sub_slot)]), 0)

        colliding_arg = str(self.root / "SubCase" / "Save0.Save")
        for subcmd in ("validate", "inspect"):
            out_err = io.StringIO()
            err_buf = io.StringIO()
            with contextlib.redirect_stdout(out_err), contextlib.redirect_stderr(err_buf):
                self.assertEqual(main([subcmd, colliding_arg]), 1)
            self.assertIn("대소문자", err_buf.getvalue())

        sci_raw = re.sub(
            r'"m_iMoney":\d+',
            '"m_iMoney":5E+5',
            re.sub(
                r'"m_iYear":\d+',
                '"m_iYear":3E+0',
                serialize_json_lossless(create_demo_data("save"))
                .replace('"m_iType":0,', '"m_iType":0E+0,', 1)
                .replace(
                    '"m_iValue":80,"m_iIndex":0,"m_iExp":0',
                    '"m_iValue":1.2E+5,"m_iIndex":0,"m_iExp":0',
                )
                .replace(
                    '"m_iValue":150,"m_iIndex":1,"m_iExp":0',
                    '"m_iValue":150,"m_iIndex":1E+0,"m_iExp":0',
                )
                .replace(
                    '"m_iValue":80,"m_iIndex":4,"m_iExp":0',
                    '"m_iValue":80,"m_iIndex":4E+0,"m_iExp":0',
                ),
                count=1,
            ),
            count=1,
        )
        self.assertIn('"m_iValue":1.2E+5', sci_raw)
        self.assertIn('"m_iIndex":1E+0', sci_raw)
        self.assertIn('"m_iIndex":4E+0', sci_raw)
        self.assertIn('"m_iYear":3E+0', sci_raw)
        self.assertIn('"m_iMoney":5E+5', sci_raw)
        t_base, _ = parse_json_lossless((self.root / "SaveTitle.SaveTitle").read_text(encoding="utf-8"))
        (self.root / "SaveTitle.SaveTitle").write_text(
            serialize_json_lossless([dict(t_base[0]) for _ in range(3)]), encoding="utf-8"
        )
        sci_slot = self.root / "Save2.Save"
        sci_slot.write_text(sci_raw, encoding="utf-8")

        for bad_tok in ("-0.0", "1.5E+0"):
            bad_parsed, _ = parse_json_lossless(sci_raw.replace('"m_iYear":3E+0', f'"m_iYear":{bad_tok}'))
            with self.assertRaises(ValueError):
                validate_data(bad_parsed)

        insp_out = io.StringIO()
        with contextlib.redirect_stdout(insp_out):
            self.assertEqual(main(["validate", str(sci_slot)]), 0)
        insp_json_buf = io.StringIO()
        with contextlib.redirect_stdout(insp_json_buf):
            self.assertEqual(main(["inspect", "--json", str(sci_slot)]), 0)
        insp_info = json.loads(insp_json_buf.getvalue())
        self.assertEqual(insp_info["money"], 500000)
        self.assertEqual(insp_info["year"], 3)

        srv = create_bridge_server(self.root, "127.0.0.1", 0)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        base = f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(f"{base}/", timeout=5) as resp:
                html = resp.read().decode("utf-8")
            m = re.search(r'<meta name="twx-bridge-token" content="([^"]+)">', html)
            self.assertIsNotNone(m)
            token = m.group(1) if m else ""
            hdrs = {"X-TWX-Token": token, "Origin": base}
            with urllib.request.urlopen(
                urllib.request.Request(f"{base}/api/load?slot=Save2.Save", headers=hdrs), timeout=5
            ) as resp:
                loaded_sci_raw = resp.read().decode("utf-8")
                sci_sha = resp.headers.get("X-TWX-Sha256") or ""
            loaded_sci_data, loaded_sci_meta = parse_json_lossless(loaded_sci_raw)
            loaded_sci_data["m_PropertyGroupsNodeList"][0]["m_GroupsNodwList"][0]["m_iExp"] = 65432
            edited_sci_raw = serialize_json_lossless(loaded_sci_data, loaded_sci_meta)
            save_req = urllib.request.Request(
                f"{base}/api/save",
                data=json.dumps({"slot": "Save2.Save", "text": edited_sci_raw, "baseSha256": sci_sha}).encode("utf-8"),
                headers={"X-TWX-Token": token, "Origin": base, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(save_req, timeout=5) as resp:
                self.assertTrue(json.loads(resp.read().decode("utf-8"))["ok"])
            disk_sci = sci_slot.read_text(encoding="utf-8")
            self.assertIn('"m_iValue":1.2E+5,"m_iIndex":0,"m_iExp":65432', disk_sci)
            self.assertIn('"m_iIndex":1E+0', disk_sci)
            self.assertIn('"m_iYear":3E+0', disk_sci)
            self.assertIn('"m_iMoney":5E+5', disk_sci)
            title_after, _ = parse_json_lossless((self.root / "SaveTitle.SaveTitle").read_text(encoding="utf-8"))
            self.assertEqual(title_after[2]["m_strYear"], "3")
        finally:
            srv.shutdown()
            srv.server_close()
            th.join(timeout=5)

        apply_out = io.StringIO()
        with contextlib.redirect_stdout(apply_out):
            self.assertEqual(
                main(["apply", str(sci_slot), "--preset", "max_core_stats", "--root", str(self.root)]), 0
            )
        after_preset_sci = sci_slot.read_text(encoding="utf-8")
        self.assertIn('"m_iType":0E+0,', after_preset_sci)
        self.assertIn('"m_iValue":500,"m_iIndex":1E+0,"m_iExp":0', after_preset_sci)
        self.assertIn('"m_iValue":100,"m_iIndex":4E+0,"m_iExp":85700', after_preset_sci)

        sci_round_raw = (
            serialize_json_lossless(create_demo_data("round"))
            .replace("10001", "10001E+0")
        )
        r_data, r_meta = parse_json_lossless(sci_round_raw)
        from twx_editor import apply_preset, is_backup_for_slot

        apply_preset(r_data, "unlock_all_achievements")
        r_out = serialize_json_lossless(r_data, r_meta)
        self.assertIn("10001E+0", r_out)
        self.assertEqual(sum(1 for x in r_data["achiFinishList"] if int(x) == 10001), 1)

        sci_guid_raw = serialize_json_lossless(create_demo_data("guid")).replace("102", "102E+0", 1)
        g_data, g_meta = parse_json_lossless(sci_guid_raw)
        apply_preset(g_data, "unlock_guid_talents_chests")
        g_out = serialize_json_lossless(g_data, g_meta)
        self.assertIn("102E+0", g_out)
        self.assertEqual(sum(1 for x in g_data["openTalentList"] if int(x) == 102), 1)

        orig_s0_bytes = self.save0.read_bytes()
        s0_ed = create_demo_data("save")
        s0_ed["m_iMoney"] = 616161
        with unittest.mock.patch.dict(os.environ, {"TWX_SIMULATE_BACKUP_NAME_RACE": "1"}, clear=False):
            race_res = atomic_save_with_backup(
                self.root,
                "Save0.Save",
                serialize_json_lossless(s0_ed),
                expected_orig_sha256=hashlib.sha256(orig_s0_bytes).hexdigest(),
            )
        self.assertTrue(race_res["ok"])
        bdir = self.root / "backups"
        all_baks = list(bdir.glob("*.bak"))
        self.assertTrue(any(p.read_bytes() == b'{"preexisting_backup":1}' for p in all_baks))
        self.assertTrue(
            any(
                is_backup_for_slot(p.name, "Save0.Save") and p.read_bytes() == orig_s0_bytes
                for p in all_baks
            )
        )

        if os.name == "nt":
            cur_s0_win = self.save0.read_bytes()
            s0_win_ed = create_demo_data("save")
            s0_win_ed["m_iMoney"] = 727272
            with unittest.mock.patch.dict(os.environ, {"TWX_SIMULATE_STAGED_TEMP_SWAP": "slot"}, clear=False):
                with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                    atomic_save_with_backup(
                        self.root,
                        "Save0.Save",
                        serialize_json_lossless(s0_win_ed),
                        expected_orig_sha256=hashlib.sha256(cur_s0_win).hexdigest(),
                    )
            self.assertEqual(self.save0.read_bytes(), cur_s0_win)
            foreign_tmps = [p for p in self.root.glob("*.tmp") if p.read_bytes() == b'{"foreign_at_tmp":1}']
            self.assertEqual(len(foreign_tmps), 1)
            for ft in foreign_tmps:
                ft.unlink(missing_ok=True)

        # V29-1: POSIX swap-back followed by directory fsync EIO preserves both .bak backups
        if os.name != "nt":
            import twx_editor

            for sb_role in ("slot", "title"):
                sb_root = Path(tempfile.mkdtemp())
                self.addCleanup(lambda p=sb_root: shutil.rmtree(p, ignore_errors=True))
                sb_obj = create_demo_data("save")
                sb_obj["m_iMoney"] = 500001
                sb_obj["m_strPlayerName"] = "SB_ORIG\r"
                sb_bytes = serialize_json_lossless(sb_obj).encode("utf-8")
                sb_t_entry = {
                    "m_bHaveData": True,
                    "m_strPlayerName": "SB_ORIG",
                    "m_strPlaceName": "",
                    "m_strYear": "1",
                    "m_strMonth": "",
                    "m_strTime": "",
                    "m_strPlayerIconName": "900005",
                    "m_strTrueYear": "2026/11/19",
                    "m_strTrueTime": "12\uff1a00",
                }
                sb_t_bytes = serialize_json_lossless([dict(sb_t_entry) for _ in range(6)]).encode("utf-8")
                (sb_root / "Save0.Save").write_bytes(sb_bytes)
                (sb_root / "SaveTitle.SaveTitle").write_bytes(sb_t_bytes)
                sb_cand = create_demo_data("save")
                sb_cand["m_iMoney"] = 900009
                sb_cand["m_strPlayerName"] = "SB_CAND\r"
                with unittest.mock.patch.dict(
                    os.environ,
                    {
                        "TWX_SIMULATE_POST_EXCHANGE_UNLINK_FAIL": sb_role,
                        "TWX_SIMULATE_POST_SWAPBACK_SYNC_FAIL": sb_role,
                    },
                    clear=False,
                ):
                    with self.assertRaisesRegex(OSError, "SIMULATED_POST_SWAPBACK_SYNC_FAIL"):
                        atomic_save_with_backup(
                            sb_root,
                            "Save0.Save",
                            serialize_json_lossless(sb_cand),
                            expected_orig_sha256=hashlib.sha256(sb_bytes).hexdigest(),
                        )
                self.assertEqual((sb_root / "Save0.Save").read_bytes(), sb_bytes)
                self.assertEqual((sb_root / "SaveTitle.SaveTitle").read_bytes(), sb_t_bytes)
                sb_baks = list((sb_root / "backups").glob("*.bak"))
                self.assertTrue(any(is_backup_for_slot(p.name, "Save0.Save") for p in sb_baks))
                self.assertTrue(any(is_backup_for_slot(p.name, "SaveTitle.SaveTitle") for p in sb_baks))

        # V29-2: CLI apply --out bind-mount / dual-path same-file CAS & source_file_guard
        import twx_editor

        bm_root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(bm_root, ignore_errors=True))
        bm_save = bm_root / "Save0.Save"
        bm_init = create_demo_data("save")
        bm_init["m_iMoney"] = 111111
        bm_save.write_bytes(serialize_json_lossless(bm_init).encode("utf-8"))
        real_realpath = os.path.realpath
        real_apply_preset = twx_editor.apply_preset

        fake_realpath_hits: list[str] = []

        def fake_bind_realpath(p_arg: object) -> str:
            fr = sys._getframe(1)
            while fr is not None and fr.f_code.co_filename != twx_editor.__file__:
                fr = fr.f_back
            if fr is not None and fr.f_code is twx_editor.main.__code__:
                mapped = f"/virtual_bind_mount_{len(fake_realpath_hits) + 1}/Save0.Save"
                fake_realpath_hits.append(mapped)
                return mapped
            return real_realpath(p_arg)  # type: ignore[arg-type]

        def ext_replace_during_apply(d_obj: dict, preset_id: str) -> None:
            real_apply_preset(d_obj, preset_id)
            ext_d = create_demo_data("save")
            ext_d["m_iMoney"] = 999888
            ext_tmp = bm_root / "ext_writer.tmp"
            ext_tmp.write_bytes(serialize_json_lossless(ext_d).encode("utf-8"))
            os.replace(ext_tmp, bm_save)

        prev_cwd = os.getcwd()
        err_buf = io.StringIO()
        try:
            os.chdir(bm_root.parent)
            src_cli_arg = str(bm_save)
            out_cli_arg = f"{bm_root.name}{os.sep}Save0.Save"
            self.assertNotEqual(str(Path(src_cli_arg)), str(Path(out_cli_arg)))
            with (
                unittest.mock.patch("os.path.realpath", side_effect=fake_bind_realpath),
                unittest.mock.patch.object(twx_editor, "apply_preset", side_effect=ext_replace_during_apply),
                contextlib.redirect_stderr(err_buf),
            ):
                rc_bm = main(["apply", src_cli_arg, "--preset", "max_money", "--out", out_cli_arg])
        finally:
            os.chdir(prev_cwd)
        self.assertEqual(fake_realpath_hits, ["/virtual_bind_mount_1/Save0.Save", "/virtual_bind_mount_2/Save0.Save"])
        self.assertEqual(rc_bm, 1)
        self.assertIn("CONFLICT_MODIFIED", err_buf.getvalue())
        after_bm, _ = parse_json_lossless(bm_save.read_text(encoding="utf-8"))
        self.assertEqual(after_bm["m_iMoney"], 999888)

        # Cross-directory file-bind-mount simulation (bm_dir_a/Save0.Save -> bm_dir_b/Save1.Save)
        bm_dir_a = Path(tempfile.mkdtemp())
        bm_dir_b = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(bm_dir_a, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(bm_dir_b, ignore_errors=True))
        bm_src_a = bm_dir_a / "Save0.Save"
        bm_out_b = bm_dir_b / "Save1.Save"
        bm_src_a.write_bytes(serialize_json_lossless(bm_init).encode("utf-8"))
        bm_out_b.write_bytes(serialize_json_lossless(bm_init).encode("utf-8"))
        _, src_a_fid = twx_editor.read_safe_bytes_with_id(bm_dir_a, "Save0.Save")
        real_probe = twx_editor._probe_verified_file_id_in_dir

        def fake_cross_dir_probe(d_p: Path, leaf_n: str) -> object:
            if d_p == bm_dir_b and leaf_n == "Save1.Save":
                return src_a_fid
            return real_probe(d_p, leaf_n)

        def ext_write_out_b(d_obj: dict, preset_id: str) -> None:
            real_apply_preset(d_obj, preset_id)
            ext_d2 = create_demo_data("save")
            ext_d2["m_iMoney"] = 777666
            bm_out_b.write_bytes(serialize_json_lossless(ext_d2).encode("utf-8"))

        err_buf2 = io.StringIO()
        with (
            unittest.mock.patch.object(twx_editor, "_probe_verified_file_id_in_dir", side_effect=fake_cross_dir_probe),
            unittest.mock.patch.object(twx_editor, "apply_preset", side_effect=ext_write_out_b),
            contextlib.redirect_stderr(err_buf2),
        ):
            rc_bm2 = main(["apply", str(bm_src_a), "--preset", "max_money", "--out", str(bm_out_b)])
        self.assertEqual(rc_bm2, 1)
        self.assertIn("CONFLICT_MODIFIED", err_buf2.getvalue())
        after_bm2, _ = parse_json_lossless(bm_out_b.read_text(encoding="utf-8"))
        self.assertEqual(after_bm2["m_iMoney"], 777666)

        _, cur_bm_fid = twx_editor.read_safe_bytes_with_id(bm_root, "Save0.Save")
        self.assertIsNotNone(cur_bm_fid)
        with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
            atomic_save_with_backup(
                bm_root,
                "Save0.Save",
                serialize_json_lossless(create_demo_data("save")),
                expected_orig_sha256=None,
                source_file_guard=(cur_bm_fid, "0" * 64),  # type: ignore[arg-type]
            )

        # V29-3: restore_backup rejects .bak case collision
        rc_root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(rc_root, ignore_errors=True))
        (rc_root / "Save0.Save").write_bytes(serialize_json_lossless(create_demo_data("save")).encode("utf-8"))
        ed_rc = create_demo_data("save")
        ed_rc["m_iMoney"] = 222333
        rc_res = atomic_save_with_backup(rc_root, "Save0.Save", serialize_json_lossless(ed_rc))
        bak_real_name = rc_res["backup"]
        self.assertTrue(bak_real_name.endswith(".bak"))
        bak_upper_ext = bak_real_name[:-4] + ".BAK"
        with self.assertRaisesRegex(ValueError, "대소문자만 다른 동일 이름"):
            restore_backup(rc_root, bak_upper_ext, "Save0.Save")
        if os.name != "nt":
            ((rc_root / "backups") / bak_upper_ext).write_bytes(((rc_root / "backups") / bak_real_name).read_bytes())
            with self.assertRaisesRegex(ValueError, "대소문자만 다른 동일 이름"):
                restore_backup(rc_root, bak_real_name, "Save0.Save")

        # V30-1: demo failure cleanup preserves foreign files on POSIX and Windows
        demo_root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(demo_root, ignore_errors=True))
        demo_target = demo_root / "DemoOut.Save"
        if os.name != "nt":
            with (
                unittest.mock.patch.dict(
                    os.environ,
                    {"TWX_SIMULATE_DEMO_FOREIGN_REPLACE": "1", "TWX_SIMULATE_DEMO_WRITE_FAIL": "1"},
                    clear=False,
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                rc_demo_fail = main(["demo", "--kind", "save", "--out", str(demo_target)])
            self.assertEqual(rc_demo_fail, 1)
            self.assertEqual(demo_target.read_bytes(), b'{"foreign_at_demo":1}')
        else:
            with (
                unittest.mock.patch.dict(
                    os.environ,
                    {"TWX_SIMULATE_DEMO_TMP_SWAP": "1"},
                    clear=False,
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                rc_demo_win = main(["demo", "--kind", "save", "--out", str(demo_target)])
            self.assertEqual(rc_demo_win, 1)
            self.assertFalse(demo_target.exists())
            foreign_demo_tmps = [p for p in demo_root.glob("*.tmp") if p.read_bytes() == b'{"foreign_demo_tmp":1}']
            self.assertEqual(len(foreign_demo_tmps), 1)
            for fdt in foreign_demo_tmps:
                fdt.unlink(missing_ok=True)

        # V30-2: POSIX _rollback_on_conflict rejects torn displaced read and restores untorn original
        if os.name != "nt":
            tr_root = Path(tempfile.mkdtemp())
            self.addCleanup(lambda: shutil.rmtree(tr_root, ignore_errors=True))
            tr_orig_obj = create_demo_data("save")
            tr_orig_obj["m_iMoney"] = 313131
            tr_orig_obj["m_strPlayerName"] = "TR_ORIG\r"
            tr_orig_bytes = serialize_json_lossless(tr_orig_obj).encode("utf-8")
            (tr_root / "Save0.Save").write_bytes(tr_orig_bytes)
            tr_cand_obj = create_demo_data("save")
            tr_cand_obj["m_iMoney"] = 414141
            with unittest.mock.patch.dict(
                os.environ,
                {
                    "TWX_SIMULATE_POST_INSTALL_DISPLACED_WRITE": "slot",
                    "TWX_SIMULATE_SWAPBACK_FAIL": "slot",
                    "TWX_SIMULATE_TORN_DISPLACED_READ": "slot",
                },
                clear=False,
            ):
                with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                    atomic_save_with_backup(
                        tr_root,
                        "Save0.Save",
                        serialize_json_lossless(tr_cand_obj),
                        expected_orig_sha256=hashlib.sha256(tr_orig_bytes).hexdigest(),
                    )
            self.assertEqual((tr_root / "Save0.Save").read_bytes(), tr_orig_bytes)
            tr_baks = list((tr_root / "backups").glob("*.bak"))
            self.assertTrue(any(is_backup_for_slot(p.name, "Save0.Save") for p in tr_baks))
            tr_displaced = [p for p in tr_root.glob("*.tmp") if b"EXT_TORN_SLOT" in p.read_bytes()]
            self.assertEqual(len(tr_displaced), 1)

            # V31-1: POSIX _rollback_on_conflict preserves concurrent active-target modification via RENAME_EXCHANGE
            ts_root = Path(tempfile.mkdtemp())
            self.addCleanup(lambda: shutil.rmtree(ts_root, ignore_errors=True))
            ts_orig = create_demo_data("save")
            ts_orig["m_iMoney"] = 303030
            ts_orig_bytes = serialize_json_lossless(ts_orig).encode("utf-8")
            (ts_root / "Save0.Save").write_bytes(ts_orig_bytes)
            ts_cand = create_demo_data("save")
            ts_cand["m_iMoney"] = 404040
            with unittest.mock.patch.dict(
                os.environ,
                {
                    "TWX_SIMULATE_POST_INSTALL_DISPLACED_WRITE": "slot",
                    "TWX_SIMULATE_SWAPBACK_FAIL": "slot",
                    "TWX_SIMULATE_TARGET_SWAP_DURING_DISP_RECHECK": "slot",
                },
                clear=False,
            ):
                with self.assertRaisesRegex(RuntimeError, "CONFLICT_MODIFIED"):
                    atomic_save_with_backup(
                        ts_root,
                        "Save0.Save",
                        serialize_json_lossless(ts_cand),
                        expected_orig_sha256=hashlib.sha256(ts_orig_bytes).hexdigest(),
                    )
            ts_after, _ = parse_json_lossless((ts_root / "Save0.Save").read_text(encoding="utf-8"))
            self.assertEqual(ts_after["m_iMoney"], 951753)
            self.assertEqual(ts_after["m_strPlayerName"], "LATEST_EXT_TARGET\r")
            self.assertTrue(list((ts_root / "backups").glob("*.bak")))

            # V31-2: POSIX demo rejects .tmp unlink failure instead of leaving st_nlink == 2
            du_root = Path(tempfile.mkdtemp())
            self.addCleanup(lambda: shutil.rmtree(du_root, ignore_errors=True))
            du_target = du_root / "DemoUnlinkFail.Save"
            with (
                unittest.mock.patch.dict(
                    os.environ, {"TWX_SIMULATE_DEMO_TMP_UNLINK_FAIL": "1"}, clear=False
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                rc_du = main(["demo", "--kind", "save", "--out", str(du_target)])
            self.assertEqual(rc_du, 1)
            self.assertFalse(os.path.lexists(du_target))

        # V31-3: Pre-existing uppercase Backups directory rejected before slot modification
        ub_root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(ub_root, ignore_errors=True))
        (ub_root / "Backups").mkdir()
        ub_orig_bytes = serialize_json_lossless(create_demo_data("save")).encode("utf-8")
        (ub_root / "Save0.Save").write_bytes(ub_orig_bytes)
        ub_ed = create_demo_data("save")
        ub_ed["m_iMoney"] = 818181
        with self.assertRaisesRegex(ValueError, "대소문자만 다른 동일 이름"):
            atomic_save_with_backup(ub_root, "Save0.Save", serialize_json_lossless(ub_ed))
        self.assertEqual((ub_root / "Save0.Save").read_bytes(), ub_orig_bytes)
        self.assertEqual([e for e in os.listdir(ub_root) if e.lower() == "backups"], ["Backups"])


if __name__ == "__main__":
    unittest.main()
