using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using TaleOfWuxiaSaveEditor;

namespace TaleOfWuxiaSaveEditorTests
{
    internal static class SaveStoreTests
    {
        private static int _passed;
        private static int _failed;

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern uint GetShortPathNameW(string lpszLongPath, StringBuilder lpszShortPath, uint cchBuffer);

        internal static int Main()
        {
            RunTest("ValidateSaveJsonAllSchemas", TestValidateSaveJson);
            RunTest("ResolveSafePathAndJunctionGuard", TestResolveSafePath);
            RunTest("SaveLoadCompanionTitleBackupRestore", TestSaveLoadBackupRestore);
            RunTest("GameRunningGuard", TestGameRunningGuard);
            RunTest("CrossSlotBackupRestoreRejected", Test_CrossSlotBackupRestoreRejected);
            RunTest("SaveTitlePreservesCrlfAndRawToken", Test_SaveTitlePreservesCrlfAndRawToken);
            RunTest("SimulatedTitleWriteFailRollsBack", Test_SimulatedTitleWriteFailRollsBack);
            RunTest("TeamMemberListLimit", Test_TeamMemberListLimit);
            RunTest("SaveSlotBomAndOptimisticConcurrency", Test_SaveSlotBomAndOptimisticConcurrency);
            RunTest("RootIdentityAncestorJunctionAndCaseCollision", Test_RootIdentityAncestorJunctionAndCaseCollision);
            RunTest("CaseSensitiveDirAndPinnedShareCas", Test_CaseSensitiveDirAndPinnedShareCas);
            RunTest("RollbackPreStageExternalWriteAndListLocks", Test_RollbackPreStageExternalWriteAndListLocks);
            RunTest("DefaultOverloadRaceSameBytesRollbackIdAndSubdirBackupLock", Test_DefaultOverloadRaceSameBytesRollbackIdAndSubdirBackupLock);
            RunTest("PruneKeepsCurrentBackupAliasGuardAndAsciiKeyParity", Test_PruneKeepsCurrentBackupAliasGuardAndAsciiKeyParity);
            RunTest("PinnedBackupsPruneHandleDeleteAndIsBackupPredicate", Test_PinnedBackupsPruneHandleDeleteAndIsBackupPredicate);
            RunTest("StagedAndPostCommitVerifyAndChainedRootPin", Test_StagedAndPostCommitVerifyAndChainedRootPin);
            RunTest("TargetPinDuringStagedVerifyRollbackVerifyAndBackupRollback", Test_TargetPinDuringStagedVerifyRollbackVerifyAndBackupRollback);
            RunTest("ZeroGapMoveEntryPinAndSafeDiscoverRoots", Test_ZeroGapMoveEntryPinAndSafeDiscoverRoots);
            RunTest("ExclusiveTempHandleRenameAndSafeRootCreate", Test_ExclusiveTempHandleRenameAndSafeRootCreate);
            RunTest("FinalTitleVerificationHeldPinsAndBridgeServerSafeRoot", Test_FinalTitleVerificationHeldPinsAndBridgeServerSafeRoot);
            RunTest("StrictUtf8HttpSaveBodyAndSurrogateRejection", Test_StrictUtf8HttpSaveBodyAndSurrogateRejection);
            RunTest("DoubleBomRejectionAndRestoreCodecRoundtrip", Test_DoubleBomRejectionAndRestoreCodecRoundtrip);
            RunTest("StrictJsonSyntaxRejectsSingleQuotesAndNonStandardForms", Test_StrictJsonSyntaxRejectsSingleQuotesAndNonStandardForms);
            RunTest("SubdirFileIdLockOrderAndCrossProcessPythonContention", Test_SubdirFileIdLockOrderAndCrossProcessPythonContention);

            Console.WriteLine(string.Format(CultureInfo.InvariantCulture, "Summary: {0} passed, {1} failed.", _passed, _failed));
            return _failed == 0 ? 0 : 1;
        }

        private static void RunTest(string name, Action act)
        {
            try
            {
                act();
                _passed++;
                Console.WriteLine("[PASS] " + name);
            }
            catch (Exception ex)
            {
                _failed++;
                Console.WriteLine("[FAIL] " + name + ": " + ex.Message);
            }
        }

        private static string MakeSaveJson(long money, int year, int routineLv)
        {
            return string.Format(
                CultureInfo.InvariantCulture,
                "{{\"m_strVersion\":\"1.0.3.1\",\"m_strPlayerName\":\"\\uBBF8\\uBA85\\r\",\"m_strPlayerLastName\":\"\\uB3D9\\uBC29\\r\",\"m_PlayerIconID\":\"900005\",\"m_iMoney\":{0},\"m_iYear\":{1},\"m_iMonth\":2,\"m_iMonthInterval\":1,\"m_iNowTime\":3,\"m_iPhysical\":10,\"m_iMood\":4,\"m_iBattleDifficulty\":1,\"m_strSceneName\":\"Develop\",\"m_PropertyGroupsNodeList\":[{{\"m_iType\":0,\"m_GroupsNodwList\":[{{\"m_iValue\":80,\"m_iIndex\":0,\"m_iExp\":0,\"m_iMax\":500}}]}}],\"m_PlayerRoutineNodeList\":[{{\"m_iRoutineID\":70001,\"m_strRoutineName\":\"\\uC18C\\uC694\\uAD8C\\uBC95\",\"m_iWearAmsType\":1,\"m_iAccumulationExp\":1000,\"m_iLV\":{2}}}],\"m_PlayerNeigongNodeList\":[{{\"m_iNeigongID\":60001,\"m_iLV\":8,\"m_iAccumulationExp\":2000}}],\"m_BackpackList\":[{{\"m_iAmount\":3,\"_ItemDataNode\":{{\"m_iItemID\":100051,\"m_ItmeEffectNodeList\":[]}}}}],\"m_NpcFriendlyNodeList\":[{{\"m_iNpcID\":100001,\"m_iFriendly\":60}}]}}",
                money, year, routineLv);
        }

        private static string MakeRoundJson()
        {
            return "{\"finishGuidList\":[],\"iMasterLevelCount\":1,\"iProLevelCount\":1,\"iNormalLevelCount\":1,\"iStartBegger\":0,\"achiFinishList\":[10001],\"achiCountList\":[{\"m_iID\":10001,\"m_iNow\":1}]}";
        }

        private static string MakeGuidJson(int diff)
        {
            return string.Format(
                CultureInfo.InvariantCulture,
                "{{\"guid\":\"362d07a4-5ce8-4d7b-878e-7955e689f209\",\"iDifficulty\":{0},\"openTalentList\":[102],\"openChestList\":[\"M000501\"]}}",
                diff);
        }

        private static string MakeTitleJson()
        {
            return MakeTitleJsonSlots(2);
        }

        private static string MakeTitleJsonSlots(int count)
        {
            const string slot = "{\"m_bHaveData\":false,\"m_strPlayerName\":\"\",\"m_strPlaceName\":\"\",\"m_strYear\":\"1\",\"m_strMonth\":\"\",\"m_strTime\":\"\",\"m_strPlayerIconName\":\"900005\",\"m_strTrueYear\":\"2026/11/18\",\"m_strTrueTime\":\"12\\uFF1A00\"}";
            var sb = new StringBuilder("[");
            for (int i = 0; i < count; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append(slot);
            }
            sb.Append(']');
            return sb.ToString();
        }

        private static void TestValidateSaveJson()
        {
            Assert(SaveStore.ValidateSaveJson(MakeSaveJson(5000, 2, 6)) == "save", "Expected save kind");
            Assert(SaveStore.ValidateSaveJson(MakeRoundJson()) == "round", "Expected round kind");
            Assert(SaveStore.ValidateSaveJson(MakeGuidJson(2)) == "guid", "Expected guid kind");
            Assert(SaveStore.ValidateSaveJson(MakeTitleJson()) == "title", "Expected title kind");

            AssertThrows(delegate { SaveStore.ValidateSaveJson("{bad"); }, "Malformed JSON");
            AssertThrows(delegate { SaveStore.ValidateSaveJson(MakeSaveJson(-1, 2, 6)); }, "Negative money");
            Assert(SaveStore.ValidateSaveJson(MakeSaveJson(100, 25, 0)) == "save", "Expected extended year & lv=0 save");
            Assert(SaveStore.ValidateSaveJson(MakeGuidJson(8)) == "guid", "Expected extended guid difficulty=8");
            AssertThrows(delegate { SaveStore.ValidateSaveJson(MakeSaveJson(100, -1, 6)); }, "Year < 0");
            AssertThrows(delegate { SaveStore.ValidateSaveJson(MakeSaveJson(100, 2, -1)); }, "Routine LV < 0");
            AssertThrows(delegate { SaveStore.ValidateSaveJson(MakeGuidJson(100)); }, "Guid difficulty > 99");
        }

        private static void TestResolveSafePath()
        {
            string root = CreateTempDir();
            string outside = CreateTempDir();
            try
            {
                string valid = SaveStore.ResolveSafePath(root, "Save0.Save");
                Assert(valid.StartsWith(Path.GetFullPath(root), StringComparison.OrdinalIgnoreCase), "Valid relative path");

                AssertThrows(delegate { SaveStore.ResolveSafePath(root, "../outside.Save"); }, "Traversal ..");
                AssertThrows(delegate { SaveStore.ResolveSafePath(root, "Save0.Save:stream"); }, "ADS colon");
                AssertThrows(delegate { SaveStore.ResolveSafePath(root, "CON.Save"); }, "Reserved CON");
                AssertThrows(delegate { SaveStore.ResolveSafePath(root, "NUL"); }, "Reserved NUL");
                AssertThrows(delegate { SaveStore.ResolveSafePath(root, "COM1.Save"); }, "Reserved COM1");

                File.WriteAllText(Path.Combine(outside, "Save1.Save"), MakeSaveJson(10, 1, 1), new UTF8Encoding(false));
                string junction = Path.Combine(root, "sublink");
                if (TryCreateJunction(junction, outside))
                {
                    SaveLoadResult jLoad = SaveStore.LoadSlot(root, "sublink/Save1.Save");
                    Assert(!jLoad.Success, "Must reject LoadSlot across directory junction");

                    SaveWriteResult jWrite = SaveStore.SaveSlot(root, "sublink/NewSlot.Save", MakeSaveJson(99, 1, 1));
                    Assert(!jWrite.Success && !File.Exists(Path.Combine(outside, "NewSlot.Save")), "Must reject new file SaveSlot across directory junction");
                }
            }
            finally
            {
                DeleteDir(root);
                DeleteDir(outside);
            }
        }

        private static void TestSaveLoadBackupRestore()
        {
            string root = CreateTempDir();
            try
            {
                string v1 = MakeSaveJson(1200, 1, 5);
                string v2 = MakeSaveJson(9999999, 3, 10);
                string s0 = Path.Combine(root, "Save0.Save");
                string s1 = Path.Combine(root, "Save1.Save");
                string roundPath = Path.Combine(root, "Round.dat");
                string guidPath = Path.Combine(root, "362d07a4-5ce8-4d7b-878e-7955e689f209");
                string titlePath = Path.Combine(root, "SaveTitle.SaveTitle");

                File.WriteAllText(s0, v1, new UTF8Encoding(true));
                File.WriteAllText(s1, v1, new UTF8Encoding(false));
                File.WriteAllText(roundPath, MakeRoundJson(), new UTF8Encoding(false));
                File.WriteAllText(guidPath, MakeGuidJson(1), new UTF8Encoding(false));
                File.WriteAllText(titlePath, MakeTitleJson(), new UTF8Encoding(false));

                byte[] origS0 = File.ReadAllBytes(s0);
                string origSha = ComputeSha256(origS0);

                List<SaveSlotInfo> slots = SaveStore.ListSlots(root);
                Assert(slots.Count == 4, "Expected 4 slots (Save0, Save1, Round.dat, UUID)");

                SaveLoadResult loaded = SaveStore.LoadSlot(root, "Save0.Save");
                Assert(loaded.Success && string.Equals(loaded.Sha256, origSha, StringComparison.OrdinalIgnoreCase), "LoadSlot SHA-256 check");

                SaveWriteResult w0 = SaveStore.SaveSlot(root, "Save0.Save", v2);
                Assert(w0.Success, "SaveSlot BOM failed: " + w0.Message);
                Assert(HasBom(File.ReadAllBytes(s0)), "UTF-8 BOM must be preserved");
                Assert(!string.IsNullOrEmpty(w0.BackupPath) && File.Exists(w0.BackupPath), "Backup file must exist");

                string syncedTitle = File.ReadAllText(titlePath, Encoding.UTF8);
                Assert(syncedTitle.IndexOf("\"m_bHaveData\":true", StringComparison.Ordinal) >= 0, "Companion SaveTitle.SaveTitle must set m_bHaveData=true");
                Assert(syncedTitle.IndexOf("\"m_strYear\":\"3\"", StringComparison.Ordinal) >= 0, "Companion SaveTitle.SaveTitle must update year");

                SaveWriteResult w1 = SaveStore.SaveSlot(root, "Save1.Save", v2);
                Assert(w1.Success && !HasBom(File.ReadAllBytes(s1)), "No-BOM must be preserved");

                SaveWriteResult restored = SaveStore.RestoreBackup(root, w0.BackupPath, "Save0.Save");
                Assert(restored.Success, "RestoreBackup failed: " + restored.Message);
                Assert(BytesEqual(origS0, File.ReadAllBytes(s0)), "RestoreBackup must restore exact original bytes");
                string restoredTitle = File.ReadAllText(titlePath, Encoding.UTF8);
                Assert(restoredTitle.IndexOf("\"m_strYear\":\"1\"", StringComparison.Ordinal) >= 0, "RestoreBackup must sync SaveTitle.SaveTitle back to restored year 1");

                SaveWriteResult badKind = SaveStore.SaveSlot(root, "Round.dat", v1);
                Assert(!badKind.Success && badKind.Message.IndexOf("SLOT_SCHEMA_MISMATCH", StringComparison.Ordinal) >= 0, "Must reject writing save schema into Round.dat");

                File.WriteAllText(Path.Combine(root, "Save6.Save"), MakeRoundJson(), new UTF8Encoding(false));
                SaveLoadResult badLoadSave = SaveStore.LoadSlot(root, "Save6.Save");
                Assert(!badLoadSave.Success && badLoadSave.Message == "SLOT_SCHEMA_MISMATCH", "LoadSlot must reject round schema in Save6.Save, got: " + (badLoadSave.Message ?? "null"));
                File.Delete(Path.Combine(root, "Save6.Save"));

                File.WriteAllText(roundPath, v1, new UTF8Encoding(false));
                SaveLoadResult badLoadRound = SaveStore.LoadSlot(root, "Round.dat");
                Assert(!badLoadRound.Success && badLoadRound.Message == "SLOT_SCHEMA_MISMATCH", "LoadSlot must reject save schema in Round.dat, got: " + (badLoadRound.Message ?? "null"));
                File.WriteAllText(roundPath, MakeRoundJson(), new UTF8Encoding(false));

                File.WriteAllText(titlePath, MakeTitleJsonSlots(3), new UTF8Encoding(false));
                string sciJson = MakeSaveJson(1200, 2, 5)
                    .Replace("\"m_iValue\":80,\"m_iIndex\":0,\"m_iExp\":0", "\"m_iValue\":1.2E+5,\"m_iIndex\":0,\"m_iExp\":0")
                    .Replace("\"m_iYear\":2", "\"m_iYear\":2E+0");
                string s2 = Path.Combine(root, "Save2.Save");
                File.WriteAllText(s2, sciJson, new UTF8Encoding(false));
                SaveLoadResult sciLoad = SaveStore.LoadSlot(root, "Save2.Save");
                Assert(sciLoad.Success && sciLoad.Slot != null && sciLoad.Slot.Kind == "save", "LoadSlot must accept integral scientific notation: " + (sciLoad.Message ?? ""));
                string sciEdited = sciJson.Replace("\"m_iExp\":0", "\"m_iExp\":65432");
                SaveWriteResult sciSave = SaveStore.SaveSlot(root, "Save2.Save", sciEdited, sciLoad.Sha256);
                Assert(sciSave.Success, "SaveSlot must accept integral scientific notation: " + (sciSave.Message ?? ""));
                string sciOnDisk = File.ReadAllText(s2, Encoding.UTF8);
                Assert(sciOnDisk.IndexOf("\"m_iValue\":1.2E+5,\"m_iIndex\":0,\"m_iExp\":65432", StringComparison.Ordinal) >= 0, "SaveSlot must preserve raw 1.2E+5 token");
                string sciTitle = File.ReadAllText(titlePath, Encoding.UTF8);
                Assert(sciTitle.IndexOf("\"m_strYear\":\"2\"", StringComparison.Ordinal) >= 0 && sciTitle.IndexOf("2.0", StringComparison.Ordinal) < 0, "Companion SaveTitle must format 2E+0 as integer year 2");

                File.WriteAllText(titlePath, "{corrupted", new UTF8Encoding(false));
                SaveWriteResult aborted = SaveStore.SaveSlot(root, "Save0.Save", v2);
                Assert(!aborted.Success, "Malformed SaveTitle.SaveTitle must abort SaveSlot");
                Assert(BytesEqual(origS0, File.ReadAllBytes(s0)), "Aborted SaveSlot must leave Save0.Save untouched");
            }
            finally
            {
                DeleteDir(root);
            }
        }

        private static void TestGameRunningGuard()
        {
            string root = CreateTempDir();
            try
            {
                string v1 = MakeSaveJson(100, 1, 1);
                string v2 = MakeSaveJson(500, 2, 2);
                File.WriteAllText(Path.Combine(root, "Save0.Save"), v1, new UTF8Encoding(false));
                SaveWriteResult seed = SaveStore.SaveSlot(root, "Save0.Save", v2);
                Assert(seed.Success && !string.IsNullOrEmpty(seed.BackupPath), "Seed write should succeed");

                Environment.SetEnvironmentVariable("TWX_SIMULATE_GAME_RUNNING", "1");
                Assert(SaveStore.IsGameRunning(), "IsGameRunning must be true");

                SaveWriteResult blockedSave = SaveStore.SaveSlot(root, "Save0.Save", v1);
                Assert(!blockedSave.Success && blockedSave.Message == "GAME_RUNNING", "SaveSlot must return GAME_RUNNING");

                SaveWriteResult blockedRestore = SaveStore.RestoreBackup(root, seed.BackupPath, "Save0.Save");
                Assert(!blockedRestore.Success && blockedRestore.Message == "GAME_RUNNING", "RestoreBackup must return GAME_RUNNING");
            }
            finally
            {
                Environment.SetEnvironmentVariable("TWX_SIMULATE_GAME_RUNNING", null);
                DeleteDir(root);
            }
        }

        private static void Test_CrossSlotBackupRestoreRejected()
        {
            string root = CreateTempDir();
            try
            {
                SaveWriteResult w0 = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(100, 1, 1));
                Assert(w0.Success, "Save0 first save failed: " + w0.Message);
                w0 = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(200, 2, 2));
                Assert(w0.Success, "Save0 second save failed: " + w0.Message);
                Assert(!string.IsNullOrEmpty(w0.BackupPath), "expected a Save0 backup path");

                SaveWriteResult w1 = SaveStore.SaveSlot(root, "Save1.Save", MakeSaveJson(300, 3, 3));
                Assert(w1.Success, "Save1 save failed: " + w1.Message);

                SaveWriteResult res = SaveStore.RestoreBackup(root, w0.BackupPath, "Save1.Save");
                Assert(!res.Success, "cross-slot restore should have failed");
                Assert(res.Message != null &&
                       res.Message.IndexOf("BACKUP_SLOT_MISMATCH", StringComparison.Ordinal) >= 0,
                       "expected BACKUP_SLOT_MISMATCH, got: " + (res.Message == null ? "null" : res.Message));

                string save1Prefix = SaveStore.SlotBackupPrefix("Save1.Save");
                string save1Bak = save1Prefix + "_20261118T0000000Z_12345678.bak";
                string save1BakTie = save1Prefix + "_20261118T0000000Z_a1b2_12345678.bak";
                Assert(SaveStore.IsBackupForSlot(save1Bak, "Save1.Save"),
                       "Save1 backup must match Save1.Save");
                Assert(SaveStore.IsBackupForSlot(save1BakTie, "Save1.Save"),
                       "Save1 backup with hex tag must match Save1.Save");
                Assert(!SaveStore.IsBackupForSlot(save1Bak, "Save1"),
                       "Save1.Save backup must not match extensionless Save1");
                Assert(!SaveStore.IsBackupForSlot(save1Bak, "sub/Save1.Save"),
                       "Save1.Save backup must not match sub/Save1.Save");
                Assert(!SaveStore.IsBackupForSlot(save1Bak, "Save10.Save"),
                       "Save1.Save backup must not match Save10.Save");

                string guid = "362d07a4-5ce8-4d7b-878e-7955e689f209";
                SaveWriteResult gFirst = SaveStore.SaveSlot(root, guid, MakeGuidJson(1));
                Assert(gFirst.Success, "Guid first save failed: " + gFirst.Message);
                SaveWriteResult gw = SaveStore.SaveSlot(root, guid, MakeGuidJson(2));
                Assert(gw.Success && !string.IsNullOrEmpty(gw.BackupPath), "Guid second save failed: " + gw.Message);
                File.WriteAllText(Path.Combine(root, guid + ".Save"), MakeGuidJson(1), new UTF8Encoding(false));

                List<SaveSlotInfo> slots = SaveStore.ListSlots(root);
                bool hasGuid = false;
                bool hasGuidSave = false;
                for (int i = 0; i < slots.Count; i++)
                {
                    if (string.Equals(slots[i].FileName, guid, StringComparison.OrdinalIgnoreCase))
                        hasGuid = true;
                    if (string.Equals(slots[i].FileName, guid + ".Save", StringComparison.OrdinalIgnoreCase))
                        hasGuidSave = true;
                }
                Assert(hasGuid, "ListSlots must include strict UUID slot");
                Assert(!hasGuidSave, "ListSlots must exclude UUID.Save slot");

                SaveWriteResult guidCross = SaveStore.RestoreBackup(root, gw.BackupPath, guid + ".Save");
                Assert(!guidCross.Success && guidCross.Message != null &&
                       guidCross.Message.IndexOf("BACKUP_SLOT_MISMATCH", StringComparison.Ordinal) >= 0,
                       "Backup of UUID must be rejected when restoring onto UUID.Save, got: " +
                       (guidCross.Message == null ? "null" : guidCross.Message));

                File.WriteAllText(Path.Combine(root, "Save2.Save"), MakeSaveJson(400, 4, 4), new UTF8Encoding(true));
                SaveLoadResult loaded = SaveStore.LoadSlot(root, "Save2.Save");
                Assert(loaded.Success && loaded.RawBytes != null && HasBom(loaded.RawBytes),
                       "LoadSlot must preserve UTF-8 BOM in RawBytes");
            }
            finally
            {
                DeleteDir(root);
            }
        }

        private static void Test_SaveTitlePreservesCrlfAndRawToken()
        {
            string root = CreateTempDir();
            try
            {
                UTF8Encoding noBom = new UTF8Encoding(false);
                string save0Path = Path.Combine(root, "Save0.Save");
                string titlePath = Path.Combine(root, "SaveTitle.SaveTitle");

                File.WriteAllText(save0Path, MakeSaveJson(100, 1, 1), noBom);

                string slot1Verbatim = ",\r\n  {\"m_bHaveData\": false, \"m_strYear\": \"1\", \"m_fRawToken\": 1.0e-5}\r\n]\r\n";
                string titleContent =
                    "[\r\n" +
                    "  {\"m_bHaveData\": false, \"m_strPlayerName\": \"\", \"m_strPlaceName\": \"\", \"m_strYear\": \"0\", \"m_strMonth\": \"\", \"m_strTime\": \"\", \"m_strPlayerIconName\": \"900005\", \"m_strTrueYear\": \"2026/11/18\", \"m_strTrueTime\": \"12\\uFF1A00\"}" +
                    slot1Verbatim;
                File.WriteAllText(titlePath, titleContent, noBom);

                SaveWriteResult upd = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(7777, 4, 8));
                Assert(upd.Success, "SaveSlot failed: " + upd.Message);

                string updated = File.ReadAllText(titlePath, noBom);
                Assert(updated.StartsWith("[\r\n  {", StringComparison.Ordinal),
                       "leading CRLF array prefix not preserved");
                Assert(updated.EndsWith(slot1Verbatim, StringComparison.Ordinal),
                       "slot 1 body / CRLF / raw token `1.0e-5` was not preserved verbatim");
                Assert(updated.IndexOf("\"m_bHaveData\": true", StringComparison.Ordinal) >= 0,
                       "slot 0 m_bHaveData was not flipped to true");
                Assert(updated.IndexOf("\"m_strYear\": \"4\"", StringComparison.Ordinal) >= 0,
                       "slot 0 m_strYear was not updated to \"4\"");

                byte[] expectedSuffixBytes = noBom.GetBytes(slot1Verbatim);
                byte[] updatedBytes = File.ReadAllBytes(titlePath);
                Assert(ContainsBytes(updatedBytes, expectedSuffixBytes),
                       "slot 1 suffix and raw token 1.0e-5 bytes not preserved byte-for-byte");
            }
            finally
            {
                DeleteDir(root);
            }
        }

        private static void Test_SimulatedTitleWriteFailRollsBack()
        {
            string root = CreateTempDir();
            try
            {
                UTF8Encoding noBom = new UTF8Encoding(false);
                string s0 = Path.Combine(root, "Save0.Save");
                string titlePath = Path.Combine(root, "SaveTitle.SaveTitle");

                byte[] jsonBytes = noBom.GetBytes(MakeSaveJson(500, 3, 3));
                byte[] saveWithBom = new byte[jsonBytes.Length + 3];
                saveWithBom[0] = 0xEF;
                saveWithBom[1] = 0xBB;
                saveWithBom[2] = 0xBF;
                Array.Copy(jsonBytes, 0, saveWithBom, 3, jsonBytes.Length);
                File.WriteAllBytes(s0, saveWithBom);

                string slot1Verbatim = ",\r\n  {\"m_bHaveData\": false, \"m_strYear\": \"1\", \"m_fRawToken\": 1.0e-5}\r\n]\r\n";
                string titleContent =
                    "[\r\n" +
                    "  {\"m_bHaveData\": true, \"m_strPlayerName\": \"\", \"m_strPlaceName\": \"\", \"m_strYear\": \"3\", \"m_strMonth\": \"\", \"m_strTime\": \"\", \"m_strPlayerIconName\": \"900005\", \"m_strTrueYear\": \"2026/11/18\", \"m_strTrueTime\": \"12\\uFF1A00\"}" +
                    slot1Verbatim;
                File.WriteAllText(titlePath, titleContent, noBom);

                byte[] origSaveBytes = File.ReadAllBytes(s0);
                byte[] origTitleBytes = File.ReadAllBytes(titlePath);

                try
                {
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL", "1");

                    SaveWriteResult failRes = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(88888, 5, 9));
                    Assert(!failRes.Success, "simulated failure should not have succeeded");
                    Assert(failRes.Message != null &&
                           failRes.Message.IndexOf("SIMULATED_TITLE_WRITE_FAIL", StringComparison.Ordinal) >= 0,
                           "expected SIMULATED_TITLE_WRITE_FAIL marker, got: " +
                           (failRes.Message == null ? "null" : failRes.Message));

                    Assert(BytesEqual(origSaveBytes, File.ReadAllBytes(s0)),
                           "Save0.Save bytes were modified despite title-write failure");
                    Assert(BytesEqual(origTitleBytes, File.ReadAllBytes(titlePath)),
                           "SaveTitle.SaveTitle bytes were modified despite simulated failure");
                }
                finally
                {
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL", null);
                }
            }
            finally
            {
                DeleteDir(root);
            }
        }

        private static void Test_TeamMemberListLimit()
        {
            string baseJson = MakeSaveJson(1000, 1, 5);

            string good = InsertTeamMemberList(baseJson, "[1,2,3,4,5,6,7,8,9]");
            string goodKind = SaveStore.ValidateSaveJson(good);
            Assert(string.Equals(goodKind, "save", StringComparison.Ordinal),
                   "9-entry team list should validate as save, got: " +
                   (goodKind == null ? "null" : goodKind));

            string ten = InsertTeamMemberList(baseJson, "[1,2,3,4,5,6,7,8,9,10]");
            string tenKind = SaveStore.ValidateSaveJson(ten);
            Assert(string.Equals(tenKind, "save", StringComparison.Ordinal),
                   "10-entry team list should validate as save for mod/scene tolerance, got: " +
                   (tenKind == null ? "null" : tenKind));

            string neg = InsertTeamMemberList(baseJson, "[-1]");
            AssertThrows(delegate { SaveStore.ValidateSaveJson(neg); }, "Invalid negative team member -1");

            string bad = InsertTeamMemberList(baseJson, "[\"bad\"]");
            AssertThrows(delegate { SaveStore.ValidateSaveJson(bad); }, "Invalid team member string");
        }

        private static void Test_SaveSlotBomAndOptimisticConcurrency()
        {
            string root = CreateTempDir();
            try
            {
                string s0 = Path.Combine(root, "Save0.Save");
                File.WriteAllText(s0, MakeSaveJson(1000, 1, 1), new UTF8Encoding(true));
                File.WriteAllText(Path.Combine(root, "SaveTitle.SaveTitle"), MakeTitleJson(), new UTF8Encoding(false));

                SaveLoadResult loaded = SaveStore.LoadSlot(root, "Save0.Save");
                Assert(loaded.Success && loaded.RawBytes != null && HasBom(loaded.RawBytes),
                       "LoadSlot must return RawBytes with UTF-8 BOM");
                Assert(!string.IsNullOrEmpty(loaded.Sha256),
                       "LoadSlot must return non-empty Sha256");

                SaveWriteResult w1 = SaveStore.SaveSlot(
                    root,
                    "Save0.Save",
                    "\uFEFF" + MakeSaveJson(9999999, 3, 6),
                    loaded.Sha256);
                Assert(w1.Success, "SaveSlot with matching baseSha256 failed: " + w1.Message);

                byte[] savedBytes = File.ReadAllBytes(s0);
                Assert(HasBom(savedBytes), "Saved Save0.Save must preserve UTF-8 BOM");
                Assert(!(savedBytes.Length >= 6 && savedBytes[3] == 0xEF && savedBytes[4] == 0xBB && savedBytes[5] == 0xBF),
                       "Saved Save0.Save must not contain double UTF-8 BOM");
                Assert(SaveStore.ValidateSaveJson(File.ReadAllText(s0, Encoding.UTF8)) == "save",
                       "Saved Save0.Save must validate as save");

                SaveWriteResult wStale = SaveStore.SaveSlot(
                    root,
                    "Save0.Save",
                    MakeSaveJson(111, 1, 1),
                    loaded.Sha256);
                Assert(!wStale.Success && wStale.Message == "CONFLICT_MODIFIED",
                       "Expected CONFLICT_MODIFIED on stale baseSha256, got: " + (wStale.Message ?? "null"));
                Assert(BytesEqual(savedBytes, File.ReadAllBytes(s0)),
                       "Stale SaveSlot must not modify Save0.Save bytes");

                Assert(SaveStore.IsBackupForSlot(
                           "Save0" + SaveStore.SlotBackupPrefix("Save0.Save").Substring(5) + "_20261118T0000000Z_12345678.bak",
                           "Save0.Save"),
                       "IsBackupForSlot must accept case-insensitive stem parity");

                SaveWriteResult lockAttempt = SaveStore.SaveSlot(root, ".twx_store.lock", MakeSaveJson(100, 1, 1));
                Assert(!lockAttempt.Success, ".twx_store.lock must be rejected as a slot");

                SaveWriteResult bakAttempt = SaveStore.SaveSlot(root, "backups/Save0.Save", MakeSaveJson(100, 1, 1));
                Assert(!bakAttempt.Success, "backups/ must be rejected as a slot");
            }
            finally
            {
                DeleteDir(root);
            }
        }

        private static void Test_RootIdentityAncestorJunctionAndCaseCollision()
        {
            string juncHost = CreateTempDir();
            string realBase = CreateTempDir();
            string root1 = CreateTempDir();
            string root2 = CreateTempDir();
            string parentJunc = Path.Combine(juncHost, "parentJunc");
            try
            {
                string realSaves = Path.Combine(realBase, "saves");
                Directory.CreateDirectory(realSaves);
                File.WriteAllText(Path.Combine(realSaves, "Save0.Save"), MakeSaveJson(100, 1, 1), new UTF8Encoding(false));

                if (TryCreateJunction(parentJunc, realBase))
                {
                    string juncRoot = Path.Combine(parentJunc, "saves");
                    SaveLoadResult ancLoad = SaveStore.LoadSlot(juncRoot, "Save0.Save");
                    Assert(!ancLoad.Success, "Must reject LoadSlot when an ancestor above root is a junction");

                    SaveWriteResult ancSave = SaveStore.SaveSlot(juncRoot, "Save0.Save", MakeSaveJson(200, 1, 1));
                    Assert(!ancSave.Success, "Must reject SaveSlot when an ancestor above root is a junction");
                }

                File.WriteAllText(Path.Combine(root2, "Save0.Save"), MakeSaveJson(50, 1, 1), new UTF8Encoding(false));
                SaveStore.FileId id1 = SaveStore.CaptureRootIdentity(root1);
                Assert(id1.IsValid, "CaptureRootIdentity must return IsValid=true");

                SaveLoadResult mismatchLoad = SaveStore.LoadSlot(root2, "Save0.Save", id1);
                Assert(!mismatchLoad.Success && mismatchLoad.Message == "ROOT_IDENTITY_CHANGED",
                       "Expected ROOT_IDENTITY_CHANGED on LoadSlot, got: " + (mismatchLoad.Message ?? "null"));

                SaveWriteResult mismatchSave = SaveStore.SaveSlot(root2, "Save0.Save", MakeSaveJson(1, 1, 1), null, id1);
                Assert(!mismatchSave.Success && mismatchSave.Message == "ROOT_IDENTITY_CHANGED",
                       "Expected ROOT_IDENTITY_CHANGED on SaveSlot, got: " + (mismatchSave.Message ?? "null"));

                SaveWriteResult seed1 = SaveStore.SaveSlot(root1, "Save0.Save", MakeSaveJson(100, 1, 1));
                Assert(seed1.Success, "Seed Save0.Save failed: " + seed1.Message);
                SaveWriteResult seed2 = SaveStore.SaveSlot(root1, "Save0.Save", MakeSaveJson(200, 1, 1));
                Assert(seed2.Success && !string.IsNullOrEmpty(seed2.BackupPath), "Backup Save0.Save failed: " + seed2.Message);
                string bak = seed2.BackupPath;

                SaveLoadResult caseLoad = SaveStore.LoadSlot(root1, "save0.save");
                Assert(!caseLoad.Success && caseLoad.Message == "CASE_COLLISION_REJECTED",
                       "Expected CASE_COLLISION_REJECTED on LoadSlot, got: " + (caseLoad.Message ?? "null"));

                SaveWriteResult caseSave = SaveStore.SaveSlot(root1, "save0.save", MakeSaveJson(2, 1, 1));
                Assert(!caseSave.Success && caseSave.Message == "CASE_COLLISION_REJECTED",
                       "Expected CASE_COLLISION_REJECTED on SaveSlot, got: " + (caseSave.Message ?? "null"));

                SaveWriteResult caseRestore = SaveStore.RestoreBackup(root1, bak, "save0.save");
                Assert(!caseRestore.Success && caseRestore.Message == "CASE_COLLISION_REJECTED",
                       "Expected CASE_COLLISION_REJECTED on RestoreBackup, got: " + (caseRestore.Message ?? "null"));

                SaveWriteResult subSave = SaveStore.SaveSlot(root1, "sub/Save1.Save", MakeSaveJson(300, 1, 1));
                Assert(subSave.Success, "Subdirectory SaveSlot failed: " + subSave.Message);
                Assert(File.Exists(Path.Combine(root1, ".twx_store.lock")), "Expected root1\\.twx_store.lock");
                Assert(File.Exists(Path.Combine(root1, "sub", ".twx_store.lock")), "Expected sub\\.twx_store.lock");
            }
            finally
            {
                try { if (Directory.Exists(parentJunc)) Directory.Delete(parentJunc, false); } catch { }
                DeleteDir(juncHost);
                DeleteDir(realBase);
                DeleteDir(root1);
                DeleteDir(root2);
            }
        }

        private static int TryEnableCaseSensitiveDir(string dirPath)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo(
                    "cmd.exe",
                    string.Format(CultureInfo.InvariantCulture, "/c fsutil file setCaseSensitiveInfo \"{0}\" enable", dirPath));
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                using (Process p = Process.Start(psi))
                {
                    if (p == null) return -1;
                    p.StandardOutput.ReadToEnd();
                    p.StandardError.ReadToEnd();
                    p.WaitForExit(5000);
                    return p.ExitCode;
                }
            }
            catch
            {
                return -1;
            }
        }

        private static void Test_CaseSensitiveDirAndPinnedShareCas()
        {
            string csDir = CreateTempDir();
            string root = CreateTempDir();
            string hlDir = CreateTempDir();
            try
            {
                UTF8Encoding noBom = new UTF8Encoding(false);
                int fsExit = TryEnableCaseSensitiveDir(csDir);
                if (Environment.GetEnvironmentVariable("TWX_REQUIRE_CASE_SENSITIVE_DIR") == "1")
                {
                    Assert(fsExit == 0, "fsutil setCaseSensitiveInfo failed with exit code " + fsExit.ToString(CultureInfo.InvariantCulture));
                }
                if (fsExit == 0)
                {
                    string upperPath = Path.Combine(csDir, "Save0.Save");
                    string lowerPath = Path.Combine(csDir, "save0.save");
                    File.WriteAllText(upperPath, MakeSaveJson(10, 1, 1), noBom);
                    File.WriteAllText(lowerPath, MakeSaveJson(20, 1, 1), noBom);

                    Assert(File.Exists(upperPath) && File.Exists(lowerPath),
                           "Expected both Save0.Save and save0.save to exist in csDir");
                    Assert(Directory.GetFiles(csDir).Length == 2,
                           "Expected 2 distinct files in case-sensitive directory");
                    Assert(SaveStore.ListSlots(csDir).Count == 0,
                           "Expected ListSlots(csDir).Count == 0 when Save0.Save and save0.save coexist");

                    SaveLoadResult csLoadUpper = SaveStore.LoadSlot(csDir, "Save0.Save");
                    Assert(!csLoadUpper.Success && csLoadUpper.Message == "CASE_COLLISION_REJECTED",
                           "Expected CASE_COLLISION_REJECTED on LoadSlot(Save0.Save), got: " + (csLoadUpper.Message ?? "null"));

                    SaveLoadResult csLoadLower = SaveStore.LoadSlot(csDir, "save0.save");
                    Assert(!csLoadLower.Success && csLoadLower.Message == "CASE_COLLISION_REJECTED",
                           "Expected CASE_COLLISION_REJECTED on LoadSlot(save0.save), got: " + (csLoadLower.Message ?? "null"));

                    SaveWriteResult csSave = SaveStore.SaveSlot(csDir, "Save0.Save", MakeSaveJson(9, 1, 1));
                    Assert(!csSave.Success && csSave.Message == "CASE_COLLISION_REJECTED",
                           "Expected CASE_COLLISION_REJECTED on SaveSlot(Save0.Save), got: " + (csSave.Message ?? "null"));
                }

                SaveWriteResult seed = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(100, 1, 1));
                Assert(seed.Success, "Seed Save0.Save failed: " + seed.Message);

                SaveLoadResult loaded = SaveStore.LoadSlot(root, "Save0.Save");
                Assert(loaded.Success && !string.IsNullOrEmpty(loaded.Sha256),
                       "LoadSlot Save0.Save failed: " + loaded.Message);

                string prevVerify = Environment.GetEnvironmentVariable("TWX_VERIFY_PINNED_SHARE_MODE");
                try
                {
                    Environment.SetEnvironmentVariable("TWX_VERIFY_PINNED_SHARE_MODE", "1");
                    SaveWriteResult pinnedSave = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(555, 2, 2), loaded.Sha256);
                    Assert(pinnedSave.Success, "SaveSlot with TWX_VERIFY_PINNED_SHARE_MODE=1 failed: " + pinnedSave.Message);
                }
                finally
                {
                    Environment.SetEnvironmentVariable("TWX_VERIFY_PINNED_SHARE_MODE", prevVerify);
                }

                string s0 = Path.Combine(root, "Save0.Save");
                byte[] beforeCasBytes = File.ReadAllBytes(s0);
                SaveWriteResult casNewAgainstExisting = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(777, 2, 2), "");
                Assert(!casNewAgainstExisting.Success && casNewAgainstExisting.Message == "CONFLICT_MODIFIED",
                       "Expected CONFLICT_MODIFIED when expectedOrigSha256 is empty on existing file, got: " + (casNewAgainstExisting.Message ?? "null"));
                Assert(BytesEqual(beforeCasBytes, File.ReadAllBytes(s0)),
                       "Save0.Save bytes must not be modified on CONFLICT_MODIFIED");

                SaveWriteResult casCleanNew = SaveStore.SaveSlot(root, "Save2.Save", MakeSaveJson(666, 2, 2), "");
                Assert(casCleanNew.Success, "Expected new Save2.Save with empty expectedOrigSha256 to succeed: " + casCleanNew.Message);

                string prevRace = Environment.GetEnvironmentVariable("TWX_SIMULATE_NEW_FILE_RACE");
                try
                {
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_NEW_FILE_RACE", "1");
                    SaveWriteResult casRaceNew = SaveStore.SaveSlot(root, "Save1.Save", MakeSaveJson(888, 2, 2), "");
                    Assert(!casRaceNew.Success && casRaceNew.Message == "CONFLICT_MODIFIED",
                           "Expected CONFLICT_MODIFIED on non-replace CommitStagedTemp race, got: " + (casRaceNew.Message ?? "null"));
                    string s1 = Path.Combine(root, "Save1.Save");
                    Assert(File.Exists(s1) && File.ReadAllText(s1, Encoding.UTF8) == "{\"race\":1}",
                           "Non-replace CommitStagedTemp must not overwrite externally created Save1.Save");
                    Assert(Directory.GetFiles(root, "*.tmp").Length == 0,
                           "No staged .tmp files should remain after CONFLICT_MODIFIED");
                }
                finally
                {
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_NEW_FILE_RACE", prevRace);
                }

                File.WriteAllText(Path.Combine(hlDir, "Save0.Save"), MakeSaveJson(100, 1, 1), noBom);
                string decoy = Path.Combine(hlDir, "decoy.txt");
                File.WriteAllText(decoy, "decoy-content", noBom);
                string hardLock = Path.Combine(hlDir, ".twx_store.lock");
                bool hardLinkCreated = TryCreateHardLink(hardLock, decoy);
                Assert(hardLinkCreated, "Failed to create hardlink for .twx_store.lock test");

                SaveWriteResult hlSave = SaveStore.SaveSlot(hlDir, "Save0.Save", MakeSaveJson(777, 3, 3));
                Assert(!hlSave.Success && hlSave.Message == "HARD_LINK_REJECTED",
                       "Hardlinked lock SaveSlot expected HARD_LINK_REJECTED, got: " + (hlSave.Message ?? "null"));

                SaveLoadResult hlLoad = SaveStore.LoadSlot(hlDir, "Save0.Save");
                Assert(!hlLoad.Success && hlLoad.Message == "HARD_LINK_REJECTED",
                       "Hardlinked lock LoadSlot expected HARD_LINK_REJECTED, got: " + (hlLoad.Message ?? "null"));

                bool decoyLockable = false;
                try
                {
                    using (FileStream decoyStream = new FileStream(decoy, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
                    {
                        decoyLockable = decoyStream.Length > 0;
                    }
                }
                catch (IOException)
                {
                    decoyLockable = false;
                }
                Assert(decoyLockable, "decoy.txt was left locked by SaveStore lock handling");
                Assert(File.ReadAllText(decoy, Encoding.UTF8) == "decoy-content", "decoy.txt content changed");

                string titlePath = Path.Combine(root, "SaveTitle.SaveTitle");
                File.WriteAllText(titlePath, MakeTitleJson(), noBom);
                SaveLoadResult loadedBeforeTitlePin = SaveStore.LoadSlot(root, "Save0.Save");
                Assert(loadedBeforeTitlePin.Success, "LoadSlot before companion title pin check failed: " + loadedBeforeTitlePin.Message);

                string prevTitleVerify = Environment.GetEnvironmentVariable("TWX_VERIFY_PINNED_SHARE_MODE");
                try
                {
                    Environment.SetEnvironmentVariable("TWX_VERIFY_PINNED_SHARE_MODE", "1");
                    SaveWriteResult titleSave = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(888, 4, 4), loadedBeforeTitlePin.Sha256);
                    Assert(titleSave.Success, "SaveSlot with companion title pinning failed: " + titleSave.Message);
                }
                finally
                {
                    Environment.SetEnvironmentVariable("TWX_VERIFY_PINNED_SHARE_MODE", prevTitleVerify);
                }

                Assert(File.Exists(titlePath), "SaveTitle.SaveTitle missing after SaveSlot");
                string syncedTitleText = File.ReadAllText(titlePath, Encoding.UTF8);
                Assert(syncedTitleText.IndexOf("\"m_strYear\":\"4\"", StringComparison.Ordinal) >= 0,
                       "Companion SaveTitle.SaveTitle year was not updated under pinned share mode");
                bool titleUnlocked = false;
                try
                {
                    using (FileStream titleStream = new FileStream(titlePath, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
                    {
                        titleUnlocked = titleStream.Length > 0;
                    }
                }
                catch (IOException)
                {
                    titleUnlocked = false;
                }
                Assert(titleUnlocked, "SaveTitle.SaveTitle was left locked after SaveSlot");
            }
            finally
            {
                DeleteDir(csDir);
                DeleteDir(root);
                DeleteDir(hlDir);
            }
        }

        private static void Test_RollbackPreStageExternalWriteAndListLocks()
        {
            string root = CreateTempDir();
            string hlDir = CreateTempDir();
            string prevTitleFail = Environment.GetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL");
            string prevExtRb = Environment.GetEnvironmentVariable("TWX_SIMULATE_EXT_WRITE_DURING_RB_STAGE");
            try
            {
                UTF8Encoding noBom = new UTF8Encoding(false);
                string s0 = Path.Combine(root, "Save0.Save");
                string titlePath = Path.Combine(root, "SaveTitle.SaveTitle");
                byte[] origV1Bytes = noBom.GetBytes(MakeSaveJson(1000, 1, 1));
                File.WriteAllBytes(s0, origV1Bytes);
                File.WriteAllText(titlePath, MakeTitleJsonSlots(6), noBom);

                Environment.SetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL", "1");
                Environment.SetEnvironmentVariable("TWX_SIMULATE_EXT_WRITE_DURING_RB_STAGE", "1");

                SaveWriteResult failSave0 = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(2222, 2, 2));
                Assert(!failSave0.Success && failSave0.Message != null &&
                       failSave0.Message.IndexOf("SIMULATED_TITLE_WRITE_FAIL", StringComparison.Ordinal) >= 0,
                       "Expected SIMULATED_TITLE_WRITE_FAIL on Save0 SaveSlot, got: " + (failSave0.Message ?? "null"));
                Assert(File.ReadAllText(s0, Encoding.UTF8) == "{\"ext_rb_stage\":1}",
                       "SaveSlot rollback must preserve external write made during pre-staging");
                Assert(Directory.GetFiles(root, "*.tmp").Length == 0,
                       "Expected zero .tmp files after SaveSlot rollback abort");

                List<BackupInfo> baks1 = SaveStore.ListBackups(root);
                BackupInfo save0Bak = null;
                for (int i = 0; i < baks1.Count; i++)
                {
                    if (SaveStore.IsBackupForSlot(baks1[i].FileName, "Save0.Save"))
                    {
                        save0Bak = baks1[i];
                        break;
                    }
                }
                Assert(save0Bak != null && File.Exists(save0Bak.FullPath),
                       "Expected Save0.Save .bak backup to remain in backups/");
                Assert(BytesEqual(origV1Bytes, File.ReadAllBytes(save0Bak.FullPath)),
                       "Preserved Save0.Save .bak must match original Save0.Save bytes");

                File.WriteAllText(s0, MakeSaveJson(3333, 3, 3), noBom);
                SaveWriteResult failRestore0 = SaveStore.RestoreBackup(root, save0Bak.FileName, "Save0.Save");
                Assert(!failRestore0.Success && failRestore0.Message != null &&
                       failRestore0.Message.IndexOf("SIMULATED_TITLE_WRITE_FAIL", StringComparison.Ordinal) >= 0,
                       "Expected SIMULATED_TITLE_WRITE_FAIL on Save0 RestoreBackup, got: " + (failRestore0.Message ?? "null"));
                Assert(File.ReadAllText(s0, Encoding.UTF8) == "{\"ext_rb_stage\":1}",
                       "RestoreBackup rollback must preserve external write made during pre-staging");
                Assert(Directory.GetFiles(root, "*.tmp").Length == 0,
                       "Expected zero .tmp files after RestoreBackup rollback abort");
                Assert(File.Exists(save0Bak.FullPath) && BytesEqual(origV1Bytes, File.ReadAllBytes(save0Bak.FullPath)),
                       "Original Save0.Save .bak must still exist after RestoreBackup rollback abort");

                List<BackupInfo> baks2 = SaveStore.ListBackups(root);
                int save0BakCount = 0;
                for (int i = 0; i < baks2.Count; i++)
                {
                    if (SaveStore.IsBackupForSlot(baks2[i].FileName, "Save0.Save"))
                        save0BakCount++;
                }
                Assert(save0BakCount >= 2, "Expected both original and pre-restore .bak files preserved in backups/");

                string s3 = Path.Combine(root, "Save3.Save");
                Assert(!File.Exists(s3), "Save3.Save must not exist prior to test");
                SaveWriteResult failSave3 = SaveStore.SaveSlot(root, "Save3.Save", MakeSaveJson(4444, 4, 4));
                Assert(!failSave3.Success && failSave3.Message != null &&
                       failSave3.Message.IndexOf("SIMULATED_TITLE_WRITE_FAIL", StringComparison.Ordinal) >= 0,
                       "Expected SIMULATED_TITLE_WRITE_FAIL on new Save3 SaveSlot, got: " + (failSave3.Message ?? "null"));
                Assert(File.Exists(s3) && File.ReadAllText(s3, Encoding.UTF8) == "{\"ext_rb_stage_new\":1}",
                       "External write on newly created Save3.Save must be preserved");
                Assert(Directory.GetFiles(root, "*.tmp").Length == 0,
                       "Expected zero .tmp files after Save3 rollback abort");

                Environment.SetEnvironmentVariable("TWX_SIMULATE_EXT_WRITE_DURING_RB_STAGE", null);
                string s4 = Path.Combine(root, "Save4.Save");
                Assert(!File.Exists(s4), "Save4.Save must not exist prior to test");
                SaveWriteResult failSave4 = SaveStore.SaveSlot(root, "Save4.Save", MakeSaveJson(5555, 5, 5));
                Assert(!failSave4.Success && failSave4.Message != null &&
                       failSave4.Message.IndexOf("SIMULATED_TITLE_WRITE_FAIL", StringComparison.Ordinal) >= 0,
                       "Expected SIMULATED_TITLE_WRITE_FAIL on new Save4 SaveSlot, got: " + (failSave4.Message ?? "null"));
                Assert(!File.Exists(s4),
                       "Newly created Save4.Save must be deleted via SetFileInformationByHandle on rollback");
                Assert(Directory.GetFiles(root, "*.tmp").Length == 0,
                       "Expected zero .tmp files after Save4 rollback");

                Environment.SetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL", null);

                File.WriteAllText(Path.Combine(hlDir, "Save0.Save"), MakeSaveJson(100, 1, 1), noBom);
                Directory.CreateDirectory(Path.Combine(hlDir, "backups"));
                string decoy = Path.Combine(hlDir, "decoy.txt");
                File.WriteAllText(decoy, "decoy-lock-content", noBom);
                Assert(TryCreateHardLink(Path.Combine(hlDir, ".twx_store.lock"), decoy),
                       "Failed to create hardlink for .twx_store.lock in hlDir");

                string listSlotsErr = null;
                try { SaveStore.ListSlots(hlDir); }
                catch (Exception ex) { listSlotsErr = ex.Message; }
                Assert(listSlotsErr == "HARD_LINK_REJECTED",
                       "ListSlots on hardlinked lock expected HARD_LINK_REJECTED, got: " + (listSlotsErr ?? "no-exception"));

                string listBackupsErr = null;
                try { SaveStore.ListBackups(hlDir); }
                catch (Exception ex) { listBackupsErr = ex.Message; }
                Assert(listBackupsErr == "HARD_LINK_REJECTED",
                       "ListBackups on hardlinked lock expected HARD_LINK_REJECTED, got: " + (listBackupsErr ?? "no-exception"));
            }
            finally
            {
                Environment.SetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL", prevTitleFail);
                Environment.SetEnvironmentVariable("TWX_SIMULATE_EXT_WRITE_DURING_RB_STAGE", prevExtRb);
                DeleteDir(root);
                DeleteDir(hlDir);
            }
        }

        private static void Test_DefaultOverloadRaceSameBytesRollbackIdAndSubdirBackupLock()
        {
            string root = CreateTempDir();
            string hlRoot = CreateTempDir();
            try
            {
                UTF8Encoding enc = new UTF8Encoding(false);
                File.WriteAllText(Path.Combine(root, "SaveTitle.SaveTitle"), MakeTitleJsonSlots(10), enc);

                string s5 = Path.Combine(root, "Save5.Save");
                try
                {
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_NEW_FILE_RACE", "1");
                    var r5 = SaveStore.SaveSlot(root, "Save5.Save", MakeSaveJson(777, 1, 1));
                    Assert(!r5.Success && r5.Message == "CONFLICT_MODIFIED", "Save5 conflict");
                    Assert(File.Exists(s5) && File.ReadAllText(s5, Encoding.UTF8) == "{\"race\":1}", "Save5 race bytes");
                    Assert(Directory.GetFiles(root, "*.tmp").Length == 0, "Save5 tmp");
                }
                finally
                {
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_NEW_FILE_RACE", null);
                }

                string s0 = Path.Combine(root, "Save0.Save");
                byte[] v0Bytes = enc.GetBytes(MakeSaveJson(1000, 1, 1));
                File.WriteAllBytes(s0, v0Bytes);
                SaveStore.FileId idOrig0 = SaveStore.CaptureFileIdentity(s0);

                string vTryJson = MakeSaveJson(2222, 2, 2);
                byte[] vTryBytes = enc.GetBytes(vTryJson);
                try
                {
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL", "1");
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_EXT_SAME_BYTES_DURING_RB_STAGE", "1");

                    var rTitle = SaveStore.SaveSlot(root, "Save0.Save", vTryJson);
                    Assert(!rTitle.Success && rTitle.Message == "SIMULATED_TITLE_WRITE_FAIL", "title fail");
                    Assert(BytesEqual(vTryBytes, File.ReadAllBytes(s0)), "title bytes");
                    Assert(!SaveStore.CaptureFileIdentity(s0).EqualsId(idOrig0), "title id");
                    Assert(Directory.GetFiles(root, "*.tmp").Length == 0, "title tmp");

                    var baks0 = SaveStore.ListBackupsForSlot(root, "Save0.Save");
                    Assert(baks0.Count == 1, "bak count");
                    Assert(BytesEqual(v0Bytes, File.ReadAllBytes(baks0[0].FullPath)), "bak bytes");

                    File.WriteAllBytes(s0, enc.GetBytes(MakeSaveJson(3333, 3, 3)));
                    SaveStore.FileId idPreRestore = SaveStore.CaptureFileIdentity(s0);
                    var rRb = SaveStore.RestoreBackup(root, baks0[0].FileName, "Save0.Save");
                    Assert(!rRb.Success && rRb.Message == "SIMULATED_TITLE_WRITE_FAIL", "rb fail");
                    Assert(BytesEqual(v0Bytes, File.ReadAllBytes(s0)), "rb bytes");
                    Assert(!SaveStore.CaptureFileIdentity(s0).EqualsId(idPreRestore), "rb id");
                    Assert(Directory.GetFiles(root, "*.tmp").Length == 0, "rb tmp");
                    Assert(File.Exists(baks0[0].FullPath) && BytesEqual(v0Bytes, File.ReadAllBytes(baks0[0].FullPath)), "rb bak preserved");

                    string s6 = Path.Combine(root, "Save6.Save");
                    string v6Json = MakeSaveJson(6666, 6, 6);
                    byte[] v6Bytes = enc.GetBytes(v6Json);
                    Assert(!File.Exists(s6), "Save6 pre");
                    var r6 = SaveStore.SaveSlot(root, "Save6.Save", v6Json);
                    Assert(!r6.Success && r6.Message == "SIMULATED_TITLE_WRITE_FAIL", "Save6 fail");
                    Assert(File.Exists(s6) && BytesEqual(v6Bytes, File.ReadAllBytes(s6)) && SaveStore.CaptureFileIdentity(s6).IsValid, "Save6 bytes id");
                    Assert(Directory.GetFiles(root, "*.tmp").Length == 0, "Save6 tmp");
                }
                finally
                {
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL", null);
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_EXT_SAME_BYTES_DURING_RB_STAGE", null);
                }

                string pNoSep = SaveStore.SlotBackupPrefix("Save0\uD842\uDFB7.Save");
                Assert(pNoSep.StartsWith("save0___s", StringComparison.Ordinal) && !pNoSep.StartsWith("save0____s", StringComparison.Ordinal), "prefix nosep");
                string pSep = SaveStore.SlotBackupPrefix("Save0_\uD842\uDFB7.Save");
                Assert(pSep.StartsWith("save0____s", StringComparison.Ordinal) && !pSep.StartsWith("save0_____s", StringComparison.Ordinal), "prefix sep");
                string pDot = SaveStore.SlotBackupPrefix(".Save");
                Assert(pDot.StartsWith("save__s", StringComparison.Ordinal), "prefix dot");

                string hlSubDir = Path.Combine(hlRoot, "hl");
                string sub = Path.Combine(hlSubDir, "sub");
                Directory.CreateDirectory(sub);
                File.WriteAllBytes(Path.Combine(sub, "Save0.Save"), v0Bytes);
                string decoy = Path.Combine(sub, "decoy.txt");
                File.WriteAllText(decoy, "decoy");
                string lockPath = Path.Combine(sub, ".twx_store.lock");
                Assert(TryCreateHardLink(lockPath, decoy), "hardlink");
                try
                {
                    SaveStore.ListBackupsForSlot(hlSubDir, "sub/Save0.Save");
                    Assert(false, "hardlink rejected expected");
                }
                catch (Exception ex)
                {
                    Assert(ex.Message.IndexOf("HARD_LINK_REJECTED", StringComparison.Ordinal) >= 0, "hardlink msg");
                }
            }
            finally
            {
                DeleteDir(root);
                DeleteDir(hlRoot);
            }
        }

        private static void Test_PruneKeepsCurrentBackupAliasGuardAndAsciiKeyParity()
        {
            string root = CreateTempDir();
            string oldTitleFail = Environment.GetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL");
            string oldPostTitleFail = Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL");
            try
            {
                UTF8Encoding noBom = new UTF8Encoding(false);
                string s0 = Path.Combine(root, "Save0.Save");
                string titlePath = Path.Combine(root, "SaveTitle.SaveTitle");
                File.WriteAllBytes(s0, noBom.GetBytes(MakeSaveJson(100, 1, 1)));
                byte[] origSave0Bytes = File.ReadAllBytes(s0);
                File.WriteAllText(titlePath, MakeTitleJsonSlots(4), noBom);

                string backups = Path.Combine(root, "backups");
                Directory.CreateDirectory(backups);
                string seedJson = MakeSaveJson(100, 1, 1);
                string seedSha8 = ComputeSha256(noBom.GetBytes(seedJson)).Substring(0, 8);
                string prefix = SaveStore.SlotBackupPrefix("Save0.Save");
                string[] futurePaths = new string[20];
                for (int k = 0; k < 20; k++)
                {
                    string name = prefix + "_" + string.Format(CultureInfo.InvariantCulture, "99991231T235959{0:D7}Z", k) + "_" + seedSha8 + ".bak";
                    futurePaths[k] = Path.Combine(backups, name);
                    File.WriteAllBytes(futurePaths[k], origSave0Bytes);
                }

                Environment.SetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL", "1");
                SaveWriteResult failSaveResult = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(888, 2, 2));
                Assert(!failSaveResult.Success, "simulated title write failure should fail SaveSlot");
                Assert(failSaveResult.Message == "SIMULATED_TITLE_WRITE_FAIL", "simulated title write failure message should match");
                for (int k = 0; k < futurePaths.Length; k++)
                {
                    Assert(File.Exists(futurePaths[k]), "prune must not remove backups on failed commit");
                }

                Environment.SetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL", null);
                var res = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(999, 2, 2));
                Assert(res.Success, "save should succeed");
                Assert(!string.IsNullOrEmpty(res.BackupPath), "backup path should be present");
                Assert(File.Exists(res.BackupPath), "backup file should exist");
                Assert(BytesEqual(origSave0Bytes, File.ReadAllBytes(res.BackupPath)), "backup bytes should match original slot");
                Assert(SaveStore.ListBackupsForSlot(root, "Save0.Save").Count == 20, "prune must keep exactly 20 backups");
                Assert(File.Exists(res.BackupPath), "kept current backup alias must remain on disk");

                byte[] preSaveBytes = File.ReadAllBytes(s0);
                byte[] preTitleBytes = File.ReadAllBytes(titlePath);
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", "1");
                SaveWriteResult postSaveResult = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(5555, 5, 5));
                Assert(!postSaveResult.Success, "post-title failure should fail SaveSlot");
                Assert(postSaveResult.Message == "SIMULATED_POST_TITLE_FAIL", "post-title failure message should match");
                Assert(BytesEqual(preSaveBytes, File.ReadAllBytes(s0)), "slot must roll back after post-title failure");
                Assert(BytesEqual(preTitleBytes, File.ReadAllBytes(titlePath)), "title must roll back after post-title failure");

                SaveWriteResult postRestoreResult = SaveStore.RestoreBackup(root, res.BackupPath, "Save0.Save");
                Assert(!postRestoreResult.Success, "post-title failure should fail RestoreBackup");
                Assert(postRestoreResult.Message == "SIMULATED_POST_TITLE_FAIL", "post-title failure message should match");
                Assert(BytesEqual(preSaveBytes, File.ReadAllBytes(s0)), "slot must remain rolled back after failed restore");
                Assert(BytesEqual(preTitleBytes, File.ReadAllBytes(titlePath)), "title must remain rolled back after failed restore");
                Assert(Directory.GetFiles(root, "*.tmp", SearchOption.AllDirectories).Length == 0, "no .tmp files should remain");
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", null);

                string badDot = "AutomaticSave0.Save.";
                string badSpace = "AutomaticSave0.Save ";
                AssertThrows(delegate { SaveStore.ResolveSafePath(root, badDot); }, "trailing dot should be rejected by ResolveSafePath");
                AssertThrows(delegate { SaveStore.ResolveSafePath(root, badSpace); }, "trailing space should be rejected by ResolveSafePath");
                SaveWriteResult badDotSaveResult = SaveStore.SaveSlot(root, badDot, MakeRoundJson());
                Assert(!badDotSaveResult.Success, "trailing dot should be rejected by SaveSlot");
                Assert(badDotSaveResult.Message == "TRAILING_DOT_OR_SPACE_REJECTED", "trailing dot rejection message should match");
                SaveWriteResult badSpaceSaveResult = SaveStore.SaveSlot(root, badSpace, MakeRoundJson());
                Assert(!badSpaceSaveResult.Success, "trailing space should be rejected by SaveSlot");
                Assert(badSpaceSaveResult.Message == "TRAILING_DOT_OR_SPACE_REJECTED", "trailing space rejection message should match");

                string autoPath = Path.Combine(root, "AutomaticSave0.Save");
                byte[] origAutoBytes = noBom.GetBytes(MakeSaveJson(321, 1, 1));
                File.WriteAllBytes(autoPath, origAutoBytes);
                StringBuilder shortBuffer = new StringBuilder(260);
                uint shortLen = GetShortPathNameW(autoPath, shortBuffer, (uint)shortBuffer.Capacity);
                if (shortLen > 0 && shortLen < shortBuffer.Capacity)
                {
                    string shortName = Path.GetFileName(shortBuffer.ToString(0, (int)shortLen));
                    if (!string.IsNullOrEmpty(shortName) && !string.Equals(shortName, "AutomaticSave0.Save", StringComparison.OrdinalIgnoreCase))
                    {
                        SaveLoadResult loadAliasResult = SaveStore.LoadSlot(root, shortName);
                        Assert(!loadAliasResult.Success, "loading a short-name alias must be rejected");
                        Assert(loadAliasResult.Message == "ALIAS_NAME_REJECTED", "alias rejection message should match");
                        SaveWriteResult saveAliasResult = SaveStore.SaveSlot(root, shortName, MakeRoundJson());
                        Assert(!saveAliasResult.Success, "saving a short-name alias must be rejected");
                        Assert(saveAliasResult.Message == "ALIAS_NAME_REJECTED", "alias rejection message should match");
                        bool listAliasThrew = false;
                        try
                        {
                            SaveStore.ListBackupsForSlot(root, shortName);
                        }
                        catch (Exception ex)
                        {
                            listAliasThrew = ex.Message == "ALIAS_NAME_REJECTED";
                        }
                        Assert(listAliasThrew, "listing backups for a short-name alias must be rejected");
                        Assert(BytesEqual(origAutoBytes, File.ReadAllBytes(autoPath)), "alias rejection must not alter original file");
                    }
                }

                Assert(SaveStore.NormalizeRelSlotKey("\u0391\u0392\u03A3.Save") == "\u0391\u0392\u03A3.save", "Greek final sigma key must use ASCII parity format");
                Assert(SaveStore.NormalizeRelSlotKey("Save\u0130.Save") == "save\u0130.save", "Turkish dotted I key must use ASCII parity format");
                Assert(SaveStore.NormalizeRelSlotKey("Save0.Save.") == null, "trailing dot key must normalize to null");
                Assert(SaveStore.NormalizeRelSlotKey("Save0.Save ") == null, "trailing space key must normalize to null");
                string greekSuffix = "__s" + ComputeSha256(noBom.GetBytes("\u0391\u0392\u03A3.save")).Substring(0, 16);
                string turkishSuffix = "__s" + ComputeSha256(noBom.GetBytes("save\u0130.save")).Substring(0, 16);
                Assert(SaveStore.SlotBackupPrefix("\u0391\u0392\u03A3.Save").EndsWith(greekSuffix, StringComparison.Ordinal), "Greek key backup prefix parity mismatch");
                Assert(SaveStore.SlotBackupPrefix("Save\u0130.Save").EndsWith(turkishSuffix, StringComparison.Ordinal), "Turkish key backup prefix parity mismatch");
            }
            finally
            {
                Environment.SetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL", oldTitleFail);
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", oldPostTitleFail);
                DeleteDir(root);
            }
        }

        private static void Test_PinnedBackupsPruneHandleDeleteAndIsBackupPredicate()
        {
            string root = CreateTempDir();
            string juncRoot = CreateTempDir();
            string outsideBackups = CreateTempDir();
            string oldShareMode = Environment.GetEnvironmentVariable("TWX_VERIFY_PINNED_BACKUPS_SHARE_MODE");
            string juncBackups = Path.Combine(juncRoot, "backups");
            var utf8 = new UTF8Encoding(false);
            try
            {
                File.WriteAllText(Path.Combine(root, "Save0.Save"), MakeSaveJson(100, 1, 1), utf8);
                File.WriteAllText(Path.Combine(root, "SaveTitle.SaveTitle"), MakeTitleJsonSlots(4), utf8);

                string backups = Path.Combine(root, "backups");
                Directory.CreateDirectory(backups);
                string prefix = SaveStore.SlotBackupPrefix("Save0.Save");
                for (int i = 0; i < 20; i++)
                {
                    string name = string.Format(CultureInfo.InvariantCulture, "{0}_99991231T235959{1:D7}Z_{2:x8}.bak", prefix, i, i);
                    File.WriteAllText(Path.Combine(backups, name), MakeSaveJson(200 + i, 1, 1), utf8);
                }

                string manualContent = "manual-notes";
                string zeroManualContent = "manual-notes-zero";
                string manualNotesPath = Path.Combine(backups, prefix + "_manual_notes.bak");
                string zeroManualNotesPath = Path.Combine(backups, prefix + "_0000_manual_notes.bak");
                File.WriteAllText(manualNotesPath, manualContent, utf8);
                File.WriteAllText(zeroManualNotesPath, zeroManualContent, utf8);

                Environment.SetEnvironmentVariable("TWX_VERIFY_PINNED_BACKUPS_SHARE_MODE", "1");
                var res = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(777, 2, 2));
                Assert(res.Success, "Expected SaveSlot to succeed with pinned backups verification enabled.");
                Assert(File.Exists(res.BackupPath), "Expected SaveSlot backup path to still exist before RestoreBackup.");
                Assert(SaveStore.ListBackupsForSlot(root, "Save0.Save").Count == 20, "Expected pruning to keep exactly 20 backups for the slot before RestoreBackup.");
                var restoreRes = SaveStore.RestoreBackup(root, res.BackupPath, "Save0.Save");
                Assert(restoreRes.Success, "Expected RestoreBackup to succeed with pinned backups verification enabled.");
                Assert(File.Exists(restoreRes.BackupPath), "Expected RestoreBackup backup path to still exist.");
                Assert(SaveStore.ListBackupsForSlot(root, "Save0.Save").Count == 20, "Expected pruning to keep exactly 20 backups for the slot after RestoreBackup.");
                Assert(!SaveStore.IsBackupForSlot(Path.GetFileName(manualNotesPath), "Save0.Save"), "Manual notes .bak file must not be treated as a slot backup.");
                Assert(File.Exists(manualNotesPath), "Manual notes .bak file must still exist.");
                Assert(File.Exists(zeroManualNotesPath), "Zero-prefixed manual notes .bak file must still exist.");
                Assert(File.ReadAllText(manualNotesPath) == manualContent, "Manual notes .bak file must remain untouched.");
                Assert(File.ReadAllText(zeroManualNotesPath) == zeroManualContent, "Zero-prefixed manual notes .bak file must remain untouched.");

                Environment.SetEnvironmentVariable("TWX_VERIFY_PINNED_BACKUPS_SHARE_MODE", oldShareMode);

                File.WriteAllText(Path.Combine(juncRoot, "Save0.Save"), MakeSaveJson(100, 1, 1), utf8);
                for (int i = 0; i < 25; i++)
                {
                    string name = string.Format(CultureInfo.InvariantCulture, "{0}_20200101T000000{1:D7}Z_{2:x8}.bak", prefix, i, i + 100);
                    File.WriteAllText(Path.Combine(outsideBackups, name), MakeSaveJson(300 + i, 1, 1), utf8);
                }

                bool juncCreated = TryCreateJunction(juncBackups, outsideBackups);
                Assert(juncCreated, "Failed to create backups junction");
                var juncRes = SaveStore.SaveSlot(juncRoot, "Save0.Save", MakeSaveJson(999, 3, 3));
                Assert(!juncRes.Success && juncRes.Message == "REPARSE_POINT_REJECTED", "Expected SaveSlot to reject reparse-point backups directory.");
                Assert(Directory.GetFiles(outsideBackups, "*.bak", SearchOption.TopDirectoryOnly).Length == 25, "Expected junction target backups to remain untouched.");
            }
            finally
            {
                Environment.SetEnvironmentVariable("TWX_VERIFY_PINNED_BACKUPS_SHARE_MODE", oldShareMode);
                try
                {
                    if (Directory.Exists(juncBackups))
                        Directory.Delete(juncBackups, false);
                }
                catch { }
                DeleteDir(juncRoot);
                DeleteDir(outsideBackups);
                DeleteDir(root);
            }
        }

        private static string InsertTeamMemberList(string json, string arrayLiteral)
        {
            int lastBrace = json.LastIndexOf('}');
            if (lastBrace < 0) return json;
            return json.Substring(0, lastBrace) +
                   ",\"m_teamMemberList\":" + arrayLiteral +
                   json.Substring(lastBrace);
        }

        private static bool ContainsBytes(byte[] haystack, byte[] needle)
        {
            if (haystack == null || needle == null) return false;
            if (needle.Length == 0) return true;
            if (haystack.Length < needle.Length) return false;
            int last = haystack.Length - needle.Length;
            for (int i = 0; i <= last; i++)
            {
                bool ok = true;
                for (int j = 0; j < needle.Length; j++)
                {
                    if (haystack[i + j] != needle[j])
                    {
                        ok = false;
                        break;
                    }
                }
                if (ok) return true;
            }
            return false;
        }

        private static bool TryCreateHardLink(string linkPath, string targetPath)
        {
            try
            {
                var psi = new ProcessStartInfo("cmd.exe", string.Format(CultureInfo.InvariantCulture, "/c mklink /H \"{0}\" \"{1}\"", linkPath, targetPath));
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                using (Process p = Process.Start(psi))
                {
                    if (p == null) return false;
                    p.StandardOutput.ReadToEnd();
                    p.StandardError.ReadToEnd();
                    p.WaitForExit(5000);
                    return p.ExitCode == 0 && File.Exists(linkPath);
                }
            }
            catch { return false; }
        }

        private static void Test_StagedAndPostCommitVerifyAndChainedRootPin()
        {
            string origStaged = Environment.GetEnvironmentVariable("TWX_SIMULATE_STAGED_TEMP_TAMPER");
            string origPost = Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER");
            List<string> tempDirs = new List<string>();
            UTF8Encoding noBom = new UTF8Encoding(false);
            try
            {
                string root1 = CreateTempDir();
                tempDirs.Add(root1);
                File.WriteAllText(Path.Combine(root1, "Save0.Save"), MakeSaveJson(100, 1, 1), noBom);
                File.WriteAllText(Path.Combine(root1, "SaveTitle.SaveTitle"), MakeTitleJsonSlots(2), noBom);

                SaveWriteResult seedRes = SaveStore.SaveSlot(root1, "Save0.Save", MakeSaveJson(200, 2, 2));
                Assert(seedRes.Success, "seed save should succeed: " + (seedRes.Message ?? ""));
                string seedBak = seedRes.BackupPath;
                Assert(!string.IsNullOrEmpty(seedBak), "seed backup path should not be empty");

                byte[] origSave0 = File.ReadAllBytes(Path.Combine(root1, "Save0.Save"));
                byte[] origTitle = File.ReadAllBytes(Path.Combine(root1, "SaveTitle.SaveTitle"));

                string[] targets = new string[] { "slot", "title" };
                for (int i = 0; i < targets.Length; i++)
                {
                    string target = targets[i];

                    Environment.SetEnvironmentVariable("TWX_SIMULATE_STAGED_TEMP_TAMPER", target);
                    SaveWriteResult resSlot = SaveStore.SaveSlot(root1, "Save0.Save", MakeSaveJson(300, 3, 3));
                    Assert(!resSlot.Success, "staged tamper slot: SaveSlot should fail for target " + target);
                    Assert(resSlot.Message == "STAGED_OR_COMMITTED_FILE_MODIFIED", "staged tamper slot: wrong message for target " + target + " got " + (resSlot.Message ?? "null"));
                    Assert(BytesEqual(File.ReadAllBytes(Path.Combine(root1, "Save0.Save")), origSave0), "staged tamper slot: Save0.Save modified for target " + target);
                    Assert(BytesEqual(File.ReadAllBytes(Path.Combine(root1, "SaveTitle.SaveTitle")), origTitle), "staged tamper slot: SaveTitle.SaveTitle modified for target " + target);
                    Assert(Directory.GetFiles(root1, "*.tmp", SearchOption.AllDirectories).Length == 0, "staged tamper slot: tmp files remain for target " + target);
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_STAGED_TEMP_TAMPER", null);

                    Environment.SetEnvironmentVariable("TWX_SIMULATE_STAGED_TEMP_TAMPER", target);
                    SaveWriteResult resRestore = SaveStore.RestoreBackup(root1, seedBak, "Save0.Save");
                    Assert(!resRestore.Success, "staged tamper restore: RestoreBackup should fail for target " + target);
                    Assert(resRestore.Message == "STAGED_OR_COMMITTED_FILE_MODIFIED", "staged tamper restore: wrong message for target " + target + " got " + (resRestore.Message ?? "null"));
                    Assert(BytesEqual(File.ReadAllBytes(Path.Combine(root1, "Save0.Save")), origSave0), "staged tamper restore: Save0.Save modified for target " + target);
                    Assert(BytesEqual(File.ReadAllBytes(Path.Combine(root1, "SaveTitle.SaveTitle")), origTitle), "staged tamper restore: SaveTitle.SaveTitle modified for target " + target);
                    Assert(Directory.GetFiles(root1, "*.tmp", SearchOption.AllDirectories).Length == 0, "staged tamper restore: tmp files remain for target " + target);
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_STAGED_TEMP_TAMPER", null);
                }

                string rootPostTitle = CreateTempDir();
                tempDirs.Add(rootPostTitle);
                File.WriteAllText(Path.Combine(rootPostTitle, "Save0.Save"), MakeSaveJson(100, 1, 1), noBom);
                File.WriteAllText(Path.Combine(rootPostTitle, "SaveTitle.SaveTitle"), MakeTitleJsonSlots(2), noBom);
                byte[] origSave0PT = File.ReadAllBytes(Path.Combine(rootPostTitle, "Save0.Save"));

                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER", "title");
                SaveWriteResult ptRes = SaveStore.SaveSlot(rootPostTitle, "Save0.Save", MakeSaveJson(200, 2, 2));
                Assert(!ptRes.Success, "post commit title: SaveSlot should fail");
                Assert(ptRes.Message == "STAGED_OR_COMMITTED_FILE_MODIFIED", "post commit title: wrong message, got " + (ptRes.Message ?? "null"));
                Assert(BytesEqual(File.ReadAllBytes(Path.Combine(rootPostTitle, "Save0.Save")), origSave0PT), "post commit title: Save0.Save not rolled back");
                string tamperedTitle = File.ReadAllText(Path.Combine(rootPostTitle, "SaveTitle.SaveTitle"), noBom);
                Assert(tamperedTitle == "{\"tampered_title\":1}", "post commit title: tampered title not preserved, got " + tamperedTitle);
                Assert(File.Exists(ptRes.BackupPath), "post commit title: BackupPath file missing");
                Assert(BytesEqual(File.ReadAllBytes(ptRes.BackupPath), origSave0PT), "post commit title: BackupPath content mismatch");
                int bakCountPT = Directory.GetFiles(Path.Combine(rootPostTitle, "backups"), "*.bak").Length;
                Assert(bakCountPT >= 2, "post commit title: expected >=2 bak files, got " + bakCountPT.ToString(CultureInfo.InvariantCulture));
                Assert(Directory.GetFiles(rootPostTitle, "*.tmp", SearchOption.AllDirectories).Length == 0, "post commit title: tmp files remain");
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER", null);

                string rootPostSlot = CreateTempDir();
                tempDirs.Add(rootPostSlot);
                File.WriteAllText(Path.Combine(rootPostSlot, "Save0.Save"), MakeSaveJson(100, 1, 1), noBom);
                File.WriteAllText(Path.Combine(rootPostSlot, "SaveTitle.SaveTitle"), MakeTitleJsonSlots(2), noBom);
                byte[] origSave0PS = File.ReadAllBytes(Path.Combine(rootPostSlot, "Save0.Save"));
                byte[] origTitlePS = File.ReadAllBytes(Path.Combine(rootPostSlot, "SaveTitle.SaveTitle"));

                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER", "slot");
                SaveWriteResult psRes = SaveStore.SaveSlot(rootPostSlot, "Save0.Save", MakeSaveJson(200, 2, 2));
                Assert(!psRes.Success, "post commit slot: SaveSlot should fail");
                Assert(psRes.Message == "STAGED_OR_COMMITTED_FILE_MODIFIED", "post commit slot: wrong message, got " + (psRes.Message ?? "null"));
                Assert(BytesEqual(File.ReadAllBytes(Path.Combine(rootPostSlot, "SaveTitle.SaveTitle")), origTitlePS), "post commit slot: SaveTitle.SaveTitle not rolled back");
                string tamperedSlot = File.ReadAllText(Path.Combine(rootPostSlot, "Save0.Save"), noBom);
                Assert(tamperedSlot == "{\"tampered_slot\":1}", "post commit slot: tampered slot not preserved, got " + tamperedSlot);
                Assert(File.Exists(psRes.BackupPath), "post commit slot: BackupPath file missing");
                Assert(BytesEqual(File.ReadAllBytes(psRes.BackupPath), origSave0PS), "post commit slot: BackupPath content mismatch");
                int bakCountPS = Directory.GetFiles(Path.Combine(rootPostSlot, "backups"), "*.bak").Length;
                Assert(bakCountPS >= 2, "post commit slot: expected >=2 bak files, got " + bakCountPS.ToString(CultureInfo.InvariantCulture));
                Assert(Directory.GetFiles(rootPostSlot, "*.tmp", SearchOption.AllDirectories).Length == 0, "post commit slot: tmp files remain");
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER", null);

                string hostDir = CreateTempDir();
                tempDirs.Add(hostDir);
                string longRoot = Path.Combine(hostDir, "LongRootDirectoryName");
                Directory.CreateDirectory(longRoot);
                string save0PathLong = Path.Combine(longRoot, "Save0.Save");
                File.WriteAllText(save0PathLong, MakeSaveJson(100, 1, 1), noBom);
                byte[] origLongBytes = File.ReadAllBytes(save0PathLong);

                SaveStore.FileId rootIdLong = SaveStore.CaptureRootIdentity(longRoot);
                Assert(rootIdLong.IsValid, "long root identity should be valid");

                StringBuilder shortBuf = new StringBuilder(260);
                uint shortLen = GetShortPathNameW(longRoot, shortBuf, (uint)shortBuf.Capacity);
                Assert(shortLen > 0 && shortLen < shortBuf.Capacity, "short path not obtained for long root");
                string shortRoot = shortBuf.ToString(0, (int)shortLen);
                Assert(!string.Equals(Path.GetFileName(shortRoot), "LongRootDirectoryName", StringComparison.OrdinalIgnoreCase), "short root basename should differ");

                bool threw = false;
                try
                {
                    SaveStore.CaptureRootIdentity(shortRoot);
                }
                catch (Exception ex)
                {
                    threw = true;
                    Assert(ex.Message == "ALIAS_NAME_REJECTED", "short root identity exception message, got " + ex.Message);
                }
                Assert(threw, "short root identity should throw");

                SaveWriteResult aliasRes = SaveStore.SaveSlot(shortRoot, "Save0.Save", MakeSaveJson(999, 9, 9));
                Assert(!aliasRes.Success, "short root SaveSlot should fail");
                Assert(aliasRes.Message == "ALIAS_NAME_REJECTED", "short root SaveSlot message, got " + (aliasRes.Message ?? "null"));
                Assert(BytesEqual(File.ReadAllBytes(save0PathLong), origLongBytes), "long root Save0.Save modified after alias attempt");
            }
            finally
            {
                Environment.SetEnvironmentVariable("TWX_SIMULATE_STAGED_TEMP_TAMPER", origStaged);
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER", origPost);
                for (int i = 0; i < tempDirs.Count; i++)
                {
                    DeleteDir(tempDirs[i]);
                }
            }
        }

        private static void Test_TargetPinDuringStagedVerifyRollbackVerifyAndBackupRollback()
        {
            string oldExtWrite = Environment.GetEnvironmentVariable("TWX_SIMULATE_EXT_WRITE_DURING_STAGED_VERIFY");
            string oldPostTitleFail = Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL");
            string oldRbTempTamper = Environment.GetEnvironmentVariable("TWX_SIMULATE_RB_TEMP_TAMPER");
            string oldPostRbTamper = Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_RB_TAMPER");
            string oldPostCommitTamper = Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER");
            List<string> tempDirs = new List<string>();
            try
            {
                string rootA = CreateTempDir();
                tempDirs.Add(rootA);
                File.WriteAllText(Path.Combine(rootA, "Save0.Save"), MakeSaveJson(100, 1, 1));
                File.WriteAllText(Path.Combine(rootA, "SaveTitle.SaveTitle"), MakeTitleJsonSlots(2));
                SaveWriteResult seedRes = SaveStore.SaveSlot(rootA, "Save0.Save", MakeSaveJson(200, 2, 2));
                Assert(seedRes.Success, "seed SaveSlot for part A should succeed");
                string seedBak = seedRes.BackupPath;
                foreach (string tag in new string[] { "slot", "title" })
                {
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_EXT_WRITE_DURING_STAGED_VERIFY", tag);
                    SaveWriteResult aRes = SaveStore.SaveSlot(rootA, "Save0.Save", MakeSaveJson(300, 3, 3));
                    Assert(aRes.Success, "staged verify external write SaveSlot should succeed");
                    SaveWriteResult aRb = SaveStore.RestoreBackup(rootA, seedBak, "Save0.Save");
                    Assert(aRb.Success, "restore backup after staged verify external write should succeed");
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_EXT_WRITE_DURING_STAGED_VERIFY", null);
                }

                foreach (string mode in new string[] { "rb_temp", "post_rb" })
                {
                    string rootB = CreateTempDir();
                    tempDirs.Add(rootB);
                    File.WriteAllText(Path.Combine(rootB, "Save0.Save"), MakeSaveJson(100, 1, 1));
                    File.WriteAllText(Path.Combine(rootB, "SaveTitle.SaveTitle"), MakeTitleJsonSlots(2));
                    byte[] origSave0Bytes = File.ReadAllBytes(Path.Combine(rootB, "Save0.Save"));
                    byte[] origTitleBytes = File.ReadAllBytes(Path.Combine(rootB, "SaveTitle.SaveTitle"));
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", "1");
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_RB_TEMP_TAMPER", null);
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_RB_TAMPER", null);
                    if (mode == "rb_temp")
                    {
                        Environment.SetEnvironmentVariable("TWX_SIMULATE_RB_TEMP_TAMPER", "1");
                    }
                    else
                    {
                        Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_RB_TAMPER", "1");
                    }
                    SaveWriteResult bRes = SaveStore.SaveSlot(rootB, "Save0.Save", MakeSaveJson(400, 4, 4));
                    Assert(!bRes.Success, "SaveSlot should fail for post title simulation");
                    Assert(bRes.Message == "SIMULATED_POST_TITLE_FAIL", "SaveSlot failure message should be SIMULATED_POST_TITLE_FAIL");
                    Assert(Directory.GetFiles(rootB, "*.tmp", SearchOption.AllDirectories).Length == 0, "no temp files should remain after part B rollback");
                    string save0Bak = null;
                    string titleBak = null;
                    string backupsDirB = Path.Combine(rootB, "backups");
                    if (Directory.Exists(backupsDirB))
                    {
                        string[] baks = Directory.GetFiles(backupsDirB, "*.bak", SearchOption.TopDirectoryOnly);
                        foreach (string f in baks)
                        {
                            string fn = Path.GetFileName(f);
                            if (SaveStore.IsBackupForSlot(fn, "Save0.Save"))
                            {
                                save0Bak = f;
                            }
                            if (SaveStore.IsBackupForSlot(fn, "SaveTitle.SaveTitle"))
                            {
                                titleBak = f;
                            }
                        }
                    }
                    Assert(save0Bak != null, "rollback backup for Save0.Save should exist");
                    Assert(titleBak != null, "rollback backup for SaveTitle.SaveTitle should exist");
                    Assert(BytesEqual(File.ReadAllBytes(save0Bak), origSave0Bytes), "Save0.Save rollback backup bytes should match original");
                    Assert(BytesEqual(File.ReadAllBytes(titleBak), origTitleBytes), "SaveTitle.SaveTitle rollback backup bytes should match original");
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", null);
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_RB_TEMP_TAMPER", null);
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_RB_TAMPER", null);
                }

                string rootC1 = CreateTempDir();
                tempDirs.Add(rootC1);
                File.WriteAllText(Path.Combine(rootC1, "Save0.Save"), MakeSaveJson(100, 1, 1));
                File.WriteAllText(Path.Combine(rootC1, "SaveTitle.SaveTitle"), MakeTitleJsonSlots(2));
                byte[] origSave0C1 = File.ReadAllBytes(Path.Combine(rootC1, "Save0.Save"));
                byte[] origTitleC1 = File.ReadAllBytes(Path.Combine(rootC1, "SaveTitle.SaveTitle"));
                string backupsDirC1 = Path.Combine(rootC1, "backups");
                Directory.CreateDirectory(backupsDirC1);
                string prefixC1 = SaveStore.SlotBackupPrefix("Save0.Save");
                string[] futurePaths = new string[20];
                for (int i = 0; i < 20; i++)
                {
                    string futureName = string.Format(System.Globalization.CultureInfo.InvariantCulture, "{0}_99991231T235959{1:D7}Z_{2:x8}.bak", prefixC1, i, i);
                    futurePaths[i] = Path.Combine(backupsDirC1, futureName);
                    File.WriteAllText(futurePaths[i], futureName);
                }
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER", "backup");
                SaveWriteResult cRes = SaveStore.SaveSlot(rootC1, "Save0.Save", MakeSaveJson(777, 7, 7));
                Assert(!cRes.Success, "SaveSlot should fail when committed backup is tampered");
                Assert(cRes.Message == "STAGED_OR_COMMITTED_FILE_MODIFIED", "SaveSlot tamper failure message should be STAGED_OR_COMMITTED_FILE_MODIFIED");
                Assert(BytesEqual(File.ReadAllBytes(Path.Combine(rootC1, "Save0.Save")), origSave0C1), "Save0.Save bytes should remain original after backup tamper rollback");
                Assert(BytesEqual(File.ReadAllBytes(Path.Combine(rootC1, "SaveTitle.SaveTitle")), origTitleC1), "SaveTitle.SaveTitle bytes should remain original after backup tamper rollback");
                for (int i = 0; i < 20; i++)
                {
                    Assert(File.Exists(futurePaths[i]), "future backup file should remain after backup tamper rollback");
                }
                Assert(Directory.GetFiles(rootC1, "*.tmp", SearchOption.AllDirectories).Length == 0, "no temp files should remain after backup tamper rollback in SaveSlot");
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER", null);

                string rootC2 = CreateTempDir();
                tempDirs.Add(rootC2);
                File.WriteAllText(Path.Combine(rootC2, "Save0.Save"), MakeSaveJson(100, 1, 1));
                File.WriteAllText(Path.Combine(rootC2, "SaveTitle.SaveTitle"), MakeTitleJsonSlots(2));
                SaveWriteResult seedRes2 = SaveStore.SaveSlot(rootC2, "Save0.Save", MakeSaveJson(250, 2, 2));
                Assert(seedRes2.Success, "seed SaveSlot for part C2 should succeed");
                string validBak = seedRes2.BackupPath;
                byte[] origSave0C2 = File.ReadAllBytes(Path.Combine(rootC2, "Save0.Save"));
                byte[] origTitleC2 = File.ReadAllBytes(Path.Combine(rootC2, "SaveTitle.SaveTitle"));
                string backupsDirC2 = Path.Combine(rootC2, "backups");
                Directory.CreateDirectory(backupsDirC2);
                string prefixC2 = SaveStore.SlotBackupPrefix("Save0.Save");
                string[] futurePaths2 = new string[20];
                for (int i = 0; i < 20; i++)
                {
                    string futureName2 = string.Format(System.Globalization.CultureInfo.InvariantCulture, "{0}_99991231T235959{1:D7}Z_{2:x8}.bak", prefixC2, i, i);
                    futurePaths2[i] = Path.Combine(backupsDirC2, futureName2);
                    File.WriteAllText(futurePaths2[i], futureName2);
                }
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER", "backup");
                SaveWriteResult rRes = SaveStore.RestoreBackup(rootC2, validBak, "Save0.Save");
                Assert(!rRes.Success, "RestoreBackup should fail when committed backup is tampered");
                Assert(rRes.Message == "STAGED_OR_COMMITTED_FILE_MODIFIED", "RestoreBackup tamper failure message should be STAGED_OR_COMMITTED_FILE_MODIFIED");
                Assert(BytesEqual(File.ReadAllBytes(Path.Combine(rootC2, "Save0.Save")), origSave0C2), "Save0.Save bytes should remain post-seed state after restore backup tamper rollback");
                Assert(BytesEqual(File.ReadAllBytes(Path.Combine(rootC2, "SaveTitle.SaveTitle")), origTitleC2), "SaveTitle.SaveTitle bytes should remain post-seed state after restore backup tamper rollback");
                for (int i = 0; i < 20; i++)
                {
                    Assert(File.Exists(futurePaths2[i]), "future backup file should remain after restore backup tamper rollback");
                }
                Assert(File.Exists(validBak), "valid backup file should remain after restore backup tamper rollback");
                Assert(Directory.GetFiles(rootC2, "*.tmp", SearchOption.AllDirectories).Length == 0, "no temp files should remain after backup tamper rollback in RestoreBackup");
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER", null);
            }
            finally
            {
                Environment.SetEnvironmentVariable("TWX_SIMULATE_EXT_WRITE_DURING_STAGED_VERIFY", oldExtWrite);
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", oldPostTitleFail);
                Environment.SetEnvironmentVariable("TWX_SIMULATE_RB_TEMP_TAMPER", oldRbTempTamper);
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_RB_TAMPER", oldPostRbTamper);
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER", oldPostCommitTamper);
                foreach (string dir in tempDirs)
                {
                    DeleteDir(dir);
                }
            }
        }

        private static bool ContainsPathIgnoreCase(List<string> list, string target)
        {
            for (int i = 0; i < list.Count; i++)
            {
                if (string.Equals(list[i], target, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }
            return false;
        }

        private static void Test_ZeroGapMoveEntryPinAndSafeDiscoverRoots()
        {
            string oldPin = Environment.GetEnvironmentVariable("TWX_VERIFY_PIN_HELD_AT_MOVE_ENTRY", EnvironmentVariableTarget.Process);
            string oldSim = Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", EnvironmentVariableTarget.Process);
            string oldRoot = Environment.GetEnvironmentVariable("TWX_SAVE_ROOT", EnvironmentVariableTarget.Process);
            string oldPf86 = Environment.GetEnvironmentVariable("ProgramFiles(x86)", EnvironmentVariableTarget.Process);
            string oldPf = Environment.GetEnvironmentVariable("ProgramFiles", EnvironmentVariableTarget.Process);

            string rootA = null;
            string hostDir = null;
            string juncPf = null;

            try
            {
                Environment.SetEnvironmentVariable("TWX_VERIFY_PIN_HELD_AT_MOVE_ENTRY", "1", EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", null, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("TWX_SAVE_ROOT", null, EnvironmentVariableTarget.Process);

                rootA = CreateTempDir();
                File.WriteAllText(Path.Combine(rootA, "Save0.Save"), MakeSaveJson(100, 1, 1));
                File.WriteAllText(Path.Combine(rootA, "SaveTitle.SaveTitle"), MakeTitleJsonSlots(2));

                SaveWriteResult r1 = SaveStore.SaveSlot(rootA, "Save0.Save", MakeSaveJson(250, 2, 3));
                Assert(r1.Success, "seed commit should succeed");
                Assert(!string.IsNullOrEmpty(r1.BackupPath), "backup path should be non-empty");

                SaveWriteResult r2 = SaveStore.SaveSlot(rootA, "Save1.Save", MakeSaveJson(150, 1, 2));
                Assert(r2.Success, "new slot commit should succeed under move-entry pin");

                SaveWriteResult r3 = SaveStore.RestoreBackup(rootA, r1.BackupPath, "Save0.Save");
                Assert(r3.Success, "restore of seed backup should succeed");

                byte[] expectedSave0 = File.ReadAllBytes(Path.Combine(rootA, "Save0.Save"));
                byte[] expectedTitle = File.ReadAllBytes(Path.Combine(rootA, "SaveTitle.SaveTitle"));

                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", "1", EnvironmentVariableTarget.Process);

                SaveWriteResult r4 = SaveStore.SaveSlot(rootA, "Save0.Save", MakeSaveJson(999, 9, 9));
                Assert(!r4.Success, "simulated post-title fail should report failure");
                Assert(string.Equals(r4.Message, "SIMULATED_POST_TITLE_FAIL", StringComparison.Ordinal), "simulated fail message mismatch");

                byte[] actualSave0 = File.ReadAllBytes(Path.Combine(rootA, "Save0.Save"));
                byte[] actualTitle = File.ReadAllBytes(Path.Combine(rootA, "SaveTitle.SaveTitle"));
                Assert(BytesEqual(expectedSave0, actualSave0), "Save0.Save should be rolled back byte-for-byte");
                Assert(BytesEqual(expectedTitle, actualTitle), "SaveTitle.SaveTitle should be rolled back byte-for-byte");

                string[] leftoverTmp = Directory.GetFiles(rootA, "*.tmp", SearchOption.AllDirectories);
                Assert(leftoverTmp.Length == 0, "no *.tmp files should remain after rollback");

                Environment.SetEnvironmentVariable("TWX_VERIFY_PIN_HELD_AT_MOVE_ENTRY", null, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", null, EnvironmentVariableTarget.Process);

                hostDir = CreateTempDir();

                string realPf = Path.Combine(hostDir, "RealSteamRoot");
                string realRemote = Path.Combine(realPf, "Steam", "userdata", "100", "377530", "remote");
                Directory.CreateDirectory(realRemote);

                string juncTargetPf = Path.Combine(hostDir, "JunctionTargetRoot");
                string juncTargetRemote = Path.Combine(juncTargetPf, "Steam", "userdata", "200", "377530", "remote");
                Directory.CreateDirectory(juncTargetRemote);

                juncPf = Path.Combine(hostDir, "SteamJunctionPf");
                bool junctionOk = TryCreateJunction(juncPf, juncTargetPf);
                Assert(junctionOk, "junction creation for ProgramFiles(x86) should succeed");

                Environment.SetEnvironmentVariable("TWX_SAVE_ROOT", null, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("ProgramFiles(x86)", juncPf, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("ProgramFiles", realPf, EnvironmentVariableTarget.Process);

                List<string> rootsJunction = SaveStore.DiscoverRoots();
                Assert(ContainsPathIgnoreCase(rootsJunction, Path.GetFullPath(realRemote)), "real remote should be discovered when ProgramFiles(x86) is a junction");
                Assert(!ContainsPathIgnoreCase(rootsJunction, Path.GetFullPath(Path.Combine(juncPf, "Steam", "userdata", "200", "377530", "remote"))), "junction-resolved remote should be excluded");
                Assert(!ContainsPathIgnoreCase(rootsJunction, Path.GetFullPath(Path.Combine(juncTargetPf, "Steam", "userdata", "200", "377530", "remote"))), "junction-target remote should be excluded");

                string longPf = Path.Combine(hostDir, "LongSteamProgramFilesCandidate");
                string longRemote = Path.Combine(longPf, "Steam", "userdata", "300", "377530", "remote");
                Directory.CreateDirectory(longRemote);

                StringBuilder shortBuf = new StringBuilder(1024);
                uint shortLen = GetShortPathNameW(longPf, shortBuf, (uint)shortBuf.Capacity);
                Assert(shortLen > 0u, "GetShortPathNameW should return a positive length");
                Assert(shortLen < (uint)shortBuf.Capacity, "short path buffer should not have been truncated");
                string shortPf = shortBuf.ToString(0, (int)shortLen);
                Assert(!string.Equals(Path.GetFileName(shortPf), "LongSteamProgramFilesCandidate", StringComparison.OrdinalIgnoreCase), "short path component should differ from long candidate name");

                Environment.SetEnvironmentVariable("TWX_SAVE_ROOT", null, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("ProgramFiles(x86)", shortPf, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("ProgramFiles", realPf, EnvironmentVariableTarget.Process);

                List<string> rootsShort = SaveStore.DiscoverRoots();
                Assert(ContainsPathIgnoreCase(rootsShort, Path.GetFullPath(realRemote)), "real remote should be discovered when ProgramFiles(x86) is a short 8.3 path");
                Assert(!ContainsPathIgnoreCase(rootsShort, Path.GetFullPath(Path.Combine(shortPf, "Steam", "userdata", "300", "377530", "remote"))), "short-name remote should be excluded");
                Assert(!ContainsPathIgnoreCase(rootsShort, Path.GetFullPath(Path.Combine(longPf, "Steam", "userdata", "300", "377530", "remote"))), "long-name-derived remote should be excluded under short ProgramFiles(x86)");

                Assert(SaveStore.CaptureRootIdentity(Path.GetFullPath(realRemote)).IsValid, "CaptureRootIdentity on real remote should be valid");
            }
            finally
            {
                Environment.SetEnvironmentVariable("TWX_VERIFY_PIN_HELD_AT_MOVE_ENTRY", oldPin, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", oldSim, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("TWX_SAVE_ROOT", oldRoot, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("ProgramFiles(x86)", oldPf86, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("ProgramFiles", oldPf, EnvironmentVariableTarget.Process);

                if (juncPf != null && Directory.Exists(juncPf))
                {
                    try
                    {
                        Directory.Delete(juncPf, false);
                    }
                    catch
                    {
                    }
                }

                if (rootA != null)
                {
                    DeleteDir(rootA);
                }
                if (hostDir != null)
                {
                    DeleteDir(hostDir);
                }
            }
        }

        private static void Test_ExclusiveTempHandleRenameAndSafeRootCreate()
        {
            string oldExclusive = Environment.GetEnvironmentVariable("TWX_VERIFY_EXCLUSIVE_TEMP_RENAME", EnvironmentVariableTarget.Process);
            string oldPin = Environment.GetEnvironmentVariable("TWX_VERIFY_PIN_HELD_AT_MOVE_ENTRY", EnvironmentVariableTarget.Process);
            string oldFail = Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", EnvironmentVariableTarget.Process);

            string rootA = null;
            string hostDir = null;
            string juncDir = null;

            try
            {
                Environment.SetEnvironmentVariable("TWX_VERIFY_EXCLUSIVE_TEMP_RENAME", "1", EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("TWX_VERIFY_PIN_HELD_AT_MOVE_ENTRY", "1", EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", null, EnvironmentVariableTarget.Process);

                rootA = CreateTempDir();
                string save0Path = Path.Combine(rootA, "Save0.Save");
                string titlePath = Path.Combine(rootA, "SaveTitle.SaveTitle");
                File.WriteAllText(save0Path, MakeSaveJson(100, 1, 1));
                File.WriteAllText(titlePath, MakeTitleJsonSlots(3));

                SaveWriteResult r1 = SaveStore.SaveSlot(rootA, "Save0.Save", MakeSaveJson(250, 2, 3));
                Assert(r1.Success, "exclusive temp rename SaveSlot on existing Save0.Save failed: " + r1.Message);
                Assert(!string.IsNullOrEmpty(r1.BackupPath), "r1 backup path should be non-empty");

                SaveWriteResult r2 = SaveStore.SaveSlot(rootA, "Save2.Save", MakeSaveJson(350, 3, 4));
                Assert(r2.Success, "exclusive temp rename SaveSlot on new Save2.Save failed: " + r2.Message);

                SaveWriteResult r3 = SaveStore.RestoreBackup(rootA, r1.BackupPath, "Save0.Save");
                Assert(r3.Success, "exclusive temp rename RestoreBackup failed: " + r3.Message);

                byte[] expectedSave0 = File.ReadAllBytes(save0Path);
                byte[] expectedTitle = File.ReadAllBytes(titlePath);

                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", "1", EnvironmentVariableTarget.Process);
                SaveWriteResult r4 = SaveStore.SaveSlot(rootA, "Save0.Save", MakeSaveJson(999, 9, 9));
                Assert(!r4.Success, "rollback-triggering SaveSlot should report failure");
                Assert(string.Equals(r4.Message, "SIMULATED_POST_TITLE_FAIL", StringComparison.Ordinal), "unexpected failure message: " + r4.Message);
                Assert(BytesEqual(expectedSave0, File.ReadAllBytes(save0Path)), "Save0.Save should be rolled back byte-for-byte");
                Assert(BytesEqual(expectedTitle, File.ReadAllBytes(titlePath)), "SaveTitle.SaveTitle should be rolled back byte-for-byte");
                Assert(Directory.GetFiles(rootA, "*.tmp", SearchOption.AllDirectories).Length == 0, "no *.tmp residue should remain");

                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", null, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("TWX_VERIFY_EXCLUSIVE_TEMP_RENAME", null, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("TWX_VERIFY_PIN_HELD_AT_MOVE_ENTRY", null, EnvironmentVariableTarget.Process);

                hostDir = CreateTempDir();
                string victimDir = Path.Combine(hostDir, "VictimTarget");
                Directory.CreateDirectory(victimDir);
                juncDir = Path.Combine(hostDir, "RootJunction");
                Assert(TryCreateJunction(juncDir, victimDir), "junction creation should succeed");

                bool threw = false;
                string canon = null;
                try
                {
                    SaveStore.FileId ignored = SaveStore.EnsureSafeRootDirectory(Path.Combine(juncDir, "SubA", "SubB"), out canon);
                    Assert(!ignored.IsValid, "unreachable");
                }
                catch (InvalidOperationException ex)
                {
                    threw = true;
                    Assert(string.Equals(ex.Message, "REPARSE_POINT_REJECTED", StringComparison.Ordinal), "expected REPARSE_POINT_REJECTED but got: " + ex.Message);
                }
                Assert(threw, "EnsureSafeRootDirectory through junction ancestor must throw");
                Assert(!Directory.Exists(Path.Combine(victimDir, "SubA")), "zero directories should be created inside junction target");

                string realDir = Path.Combine(hostDir, "RealBase");
                Directory.CreateDirectory(realDir);
                SaveStore.FileId realId = SaveStore.EnsureSafeRootDirectory(Path.Combine(realDir, "NewSubA", "NewSubB"), out canon);
                Assert(realId.IsValid, "EnsureSafeRootDirectory on real path should return valid FileId");
                Assert(Directory.Exists(Path.Combine(realDir, "NewSubA", "NewSubB")), "NewSubA\\NewSubB should be created");
                Assert(!string.IsNullOrEmpty(canon), "canonicalRoot should be non-empty");
            }
            finally
            {
                Environment.SetEnvironmentVariable("TWX_VERIFY_EXCLUSIVE_TEMP_RENAME", oldExclusive, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("TWX_VERIFY_PIN_HELD_AT_MOVE_ENTRY", oldPin, EnvironmentVariableTarget.Process);
                Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL", oldFail, EnvironmentVariableTarget.Process);

                if (!string.IsNullOrEmpty(juncDir) && Directory.Exists(juncDir))
                {
                    try { Directory.Delete(juncDir, false); } catch { }
                }
                DeleteDir(rootA);
                DeleteDir(hostDir);
            }
        }

        private static void Test_FinalTitleVerificationHeldPinsAndBridgeServerSafeRoot()
        {
            string envTamperName = "TWX_SIMULATE_POST_COMMIT_TAMPER";
            string envHeldName = "TWX_VERIFY_FINAL_PINS_HELD_DURING_PRUNE";
            string origTamper = Environment.GetEnvironmentVariable(envTamperName);
            string origHeld = Environment.GetEnvironmentVariable(envHeldName);

            string workRoot = null;
            string bridgeHost = null;
            string juncDir = null;

            try
            {
                // Part (a) - final title verification tamper rollback in SaveSlot and RestoreBackup.
                workRoot = CreateTempDir();
                string save0Path = Path.Combine(workRoot, "Save0.Save");
                string titlePath = Path.Combine(workRoot, "SaveTitle.SaveTitle");
                UTF8Encoding utf8NoBom = new UTF8Encoding(false);
                File.WriteAllText(save0Path, MakeSaveJson(110, 1, 1), utf8NoBom);
                File.WriteAllText(titlePath, MakeTitleJsonSlots(3), utf8NoBom);

                SaveWriteResult seedRes = SaveStore.SaveSlot(workRoot, "Save0.Save", MakeSaveJson(220, 2, 2));
                Assert(seedRes.Success, "seed SaveSlot should succeed");
                Assert(!string.IsNullOrEmpty(seedRes.BackupPath), "seed SaveSlot BackupPath should be non-empty");

                byte[] origSave0Bytes = File.ReadAllBytes(save0Path);
                byte[] cleanTitleBytes = File.ReadAllBytes(titlePath);

                string backupsDir = Path.Combine(workRoot, "backups");
                Directory.CreateDirectory(backupsDir);
                string slotPrefix = SaveStore.SlotBackupPrefix("Save0.Save");
                string[] seededFutureBak = new string[20];
                for (int k = 0; k < 20; k++)
                {
                    string fn = string.Format(CultureInfo.InvariantCulture, "{0}_99991231T235958{1:D7}Z_{2:x8}.bak", slotPrefix, k, k + 100);
                    string bp = Path.Combine(backupsDir, fn);
                    File.WriteAllBytes(bp, new byte[] { 0x55, (byte)(k & 0xFF), 0x66 });
                    seededFutureBak[k] = bp;
                }

                Environment.SetEnvironmentVariable(envTamperName, "title_final");
                Environment.SetEnvironmentVariable(envHeldName, null);

                SaveWriteResult sTamper = SaveStore.SaveSlot(workRoot, "Save0.Save", MakeSaveJson(330, 3, 3));
                Assert(!sTamper.Success, "tampered SaveSlot should fail");
                string sTamperMsg = sTamper.Message == null ? "<null>" : sTamper.Message;
                Assert(sTamper.Message == "STAGED_OR_COMMITTED_FILE_MODIFIED", "tampered SaveSlot message mismatch: got '" + sTamperMsg + "'");
                Assert(BytesEqual(File.ReadAllBytes(save0Path), origSave0Bytes), "SaveSlot tamper rollback must be byte-for-byte");
                for (int k = 0; k < 20; k++)
                {
                    Assert(File.Exists(seededFutureBak[k]), "seeded future .bak must remain unpruned after tampered SaveSlot: " + seededFutureBak[k]);
                }
                Assert(Directory.GetFiles(workRoot, "*.tmp", SearchOption.AllDirectories).Length == 0, "no .tmp files should remain after tampered SaveSlot");

                File.WriteAllBytes(titlePath, cleanTitleBytes);

                SaveWriteResult rTamper = SaveStore.RestoreBackup(workRoot, seedRes.BackupPath, "Save0.Save");
                Assert(!rTamper.Success, "tampered RestoreBackup should fail");
                string rTamperMsg = rTamper.Message == null ? "<null>" : rTamper.Message;
                Assert(rTamper.Message == "STAGED_OR_COMMITTED_FILE_MODIFIED", "tampered RestoreBackup message mismatch: got '" + rTamperMsg + "'");
                Assert(BytesEqual(File.ReadAllBytes(save0Path), origSave0Bytes), "RestoreBackup tamper rollback must be byte-for-byte");
                for (int k = 0; k < 20; k++)
                {
                    Assert(File.Exists(seededFutureBak[k]), "seeded future .bak must remain unpruned after tampered RestoreBackup: " + seededFutureBak[k]);
                }
                Assert(Directory.GetFiles(workRoot, "*.tmp", SearchOption.AllDirectories).Length == 0, "no .tmp files should remain after tampered RestoreBackup");

                // Part (b) - continuous FILE_SHARE_READ handles held through PruneBackups and completion.
                File.WriteAllBytes(titlePath, cleanTitleBytes);
                Environment.SetEnvironmentVariable(envTamperName, null);
                Environment.SetEnvironmentVariable(envHeldName, "1");

                SaveWriteResult sHeld = SaveStore.SaveSlot(workRoot, "Save0.Save", MakeSaveJson(440, 4, 4));
                Assert(sHeld.Success, "held-pins SaveSlot should succeed");
                Assert(!string.IsNullOrEmpty(sHeld.BackupPath), "held-pins SaveSlot BackupPath should be non-empty");

                SaveWriteResult rHeld = SaveStore.RestoreBackup(workRoot, sHeld.BackupPath, "Save0.Save");
                Assert(rHeld.Success, "held-pins RestoreBackup should succeed");
                Assert(BytesEqual(File.ReadAllBytes(save0Path), origSave0Bytes), "held-pins RestoreBackup must restore orig bytes");

                Environment.SetEnvironmentVariable(envHeldName, null);

                // Part (c) - direct SaveEditor.LocalBridgeServer safe-root verification.
                bridgeHost = CreateTempDir();
                string victimDir = Path.Combine(bridgeHost, "BridgeVictim");
                string realDir = Path.Combine(bridgeHost, "BridgeReal");
                Directory.CreateDirectory(victimDir);
                Directory.CreateDirectory(realDir);
                juncDir = Path.Combine(bridgeHost, "BridgeJunc");
                bool junctionMade = TryCreateJunction(juncDir, victimDir);
                Assert(junctionMade, "junction creation for bridge root must succeed");

                bool threw = false;
                try
                {
                    SaveEditor.LocalBridgeServer rejected = new SaveEditor.LocalBridgeServer(Path.Combine(juncDir, "SubA", "SubB"));
                    rejected.Dispose();
                }
                catch (InvalidOperationException ex)
                {
                    threw = true;
                    string exMsg = ex.Message == null ? "<null>" : ex.Message;
                    Assert(ex.Message == "REPARSE_POINT_REJECTED", "bridge constructor rejection message mismatch: got '" + exMsg + "'");
                }
                Assert(threw, "LocalBridgeServer constructor must throw InvalidOperationException on reparse-point root");
                Assert(!Directory.Exists(Path.Combine(victimDir, "SubA")), "victim subdirectory must not be created under reparse-point root");

                using (SaveEditor.LocalBridgeServer srv = new SaveEditor.LocalBridgeServer(Path.Combine(realDir, "SubOk")))
                {
                    Assert(srv != null, "bridge server instance should be created");
                    Assert(Directory.Exists(Path.Combine(realDir, "SubOk")), "real bridge subdirectory should be created");
                }
            }
            finally
            {
                Environment.SetEnvironmentVariable(envTamperName, origTamper);
                Environment.SetEnvironmentVariable(envHeldName, origHeld);

                if (juncDir != null)
                {
                    try
                    {
                        if (Directory.Exists(juncDir))
                        {
                            Directory.Delete(juncDir, false);
                        }
                    }
                    catch
                    {
                    }
                }
                if (bridgeHost != null)
                {
                    try { DeleteDir(bridgeHost); }
                    catch { }
                }
                if (workRoot != null)
                {
                    try { DeleteDir(workRoot); }
                    catch { }
                }
            }
        }

        private static HttpStatusCode PostRawSaveRequest(SaveEditor.LocalBridgeServer srv, byte[] payload)
        {
            HttpWebRequest req = (HttpWebRequest)WebRequest.Create(srv.Url + "api/save");
            req.Method = "POST";
            req.ContentType = "application/json; charset=utf-8";
            req.Proxy = null;
            req.KeepAlive = false;
            req.Headers["X-TWX-Token"] = srv.Token;
            req.Headers["Origin"] = srv.Url.TrimEnd('/');
            req.ContentLength = payload.Length;
            using (Stream s = req.GetRequestStream()) { s.Write(payload, 0, payload.Length); }
            try
            {
                using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                {
                    return resp.StatusCode;
                }
            }
            catch (WebException wex)
            {
                HttpWebResponse er = wex.Response as HttpWebResponse;
                if (er != null)
                {
                    HttpStatusCode sc = er.StatusCode;
                    er.Close();
                    return sc;
                }
                throw;
            }
        }

        private static void AssertNoBackupsCreated(string root, string label)
        {
            string bk = Path.Combine(root, "backups");
            if (!Directory.Exists(bk)) return;
            int n = Directory.GetFiles(bk, "*.bak").Length;
            if (n != 0)
            {
                throw new InvalidOperationException(label + ": backups created (" + n.ToString(CultureInfo.InvariantCulture) + ")");
            }
        }

        private static void Test_StrictUtf8HttpSaveBodyAndSurrogateRejection()
        {
            string root = CreateTempDir();
            try
            {
                string slotPath = System.IO.Path.Combine(root, "Save0.Save");
                string titlePath = System.IO.Path.Combine(root, "SaveTitle.SaveTitle");

                System.IO.File.WriteAllText(slotPath, MakeSaveJson(1000, 1, 1), new System.Text.UTF8Encoding(true));
                System.IO.File.WriteAllText(titlePath, MakeTitleJson(), new System.Text.UTF8Encoding(false));

                byte[] origSlotBytes = System.IO.File.ReadAllBytes(slotPath);
                byte[] origTitleBytes = System.IO.File.ReadAllBytes(titlePath);
                string origSha = ComputeSha256(origSlotBytes);

                using (SaveEditor.LocalBridgeServer srv = new SaveEditor.LocalBridgeServer(root))
                {
                    srv.Start();
                    Assert(SaveEditor.LocalBridgeServer.MaxJsonEnvelopeBytes >= SaveStore.MaxSaveBytes * 6 + 1024 * 1024, "max-json-envelope-bytes-bound");

                    System.Web.Script.Serialization.JavaScriptSerializer ser = new System.Web.Script.Serialization.JavaScriptSerializer();
                    ser.MaxJsonLength = SaveEditor.LocalBridgeServer.MaxJsonEnvelopeBytes;
                    System.Text.UTF8Encoding utf8NoBom = new System.Text.UTF8Encoding(false);

                    string markerPayload = ser.Serialize(new Dictionary<string, object>
                    {
                        { "slot", "Save0.Save" },
                        { "text", MakeSaveJson(777777, 1, 1).Replace("\\uBBF8\\uBA85", "__BADUTF8__") },
                        { "baseSha256", origSha }
                    });

                    int markerIdx = markerPayload.IndexOf("__BADUTF8__", System.StringComparison.Ordinal);
                    Assert(markerIdx >= 0, "invalid-utf8-marker");

                    byte[] prefix = utf8NoBom.GetBytes(markerPayload.Substring(0, markerIdx));
                    byte[] suffix = utf8NoBom.GetBytes(markerPayload.Substring(markerIdx + "__BADUTF8__".Length));
                    byte[] badUtf8Bytes = new byte[prefix.Length + 2 + suffix.Length];
                    System.Buffer.BlockCopy(prefix, 0, badUtf8Bytes, 0, prefix.Length);
                    badUtf8Bytes[prefix.Length] = 0xFF;
                    badUtf8Bytes[prefix.Length + 1] = 0xFE;
                    System.Buffer.BlockCopy(suffix, 0, badUtf8Bytes, prefix.Length + 2, suffix.Length);

                    Assert(PostRawSaveRequest(srv, badUtf8Bytes) == System.Net.HttpStatusCode.BadRequest, "invalid-utf8-status");
                    Assert(BytesEqual(System.IO.File.ReadAllBytes(slotPath), origSlotBytes), "invalid-utf8-slot-unchanged");
                    Assert(BytesEqual(System.IO.File.ReadAllBytes(titlePath), origTitleBytes), "invalid-utf8-title-unchanged");
                    AssertNoBackupsCreated(root, "invalid-utf8");

                    string validPayloadJson = ser.Serialize(new Dictionary<string, object>
                    {
                        { "slot", "Save0.Save" },
                        { "text", MakeSaveJson(888888, 1, 1) },
                        { "baseSha256", origSha }
                    });

                    byte[] utf16Plain = System.Text.Encoding.Unicode.GetBytes(validPayloadJson);
                    byte[] utf16Bytes = new byte[2 + utf16Plain.Length];
                    utf16Bytes[0] = 0xFF;
                    utf16Bytes[1] = 0xFE;
                    System.Buffer.BlockCopy(utf16Plain, 0, utf16Bytes, 2, utf16Plain.Length);

                    Assert(PostRawSaveRequest(srv, utf16Bytes) == System.Net.HttpStatusCode.BadRequest, "utf16le-bom-status");
                    Assert(BytesEqual(System.IO.File.ReadAllBytes(slotPath), origSlotBytes), "utf16le-bom-slot-unchanged");
                    Assert(BytesEqual(System.IO.File.ReadAllBytes(titlePath), origTitleBytes), "utf16le-bom-title-unchanged");
                    AssertNoBackupsCreated(root, "utf16le-bom");

                    string c1Json = markerPayload.Replace("__BADUTF8__", "\\uD800");
                    byte[] c1Bytes = utf8NoBom.GetBytes(c1Json);
                    Assert(PostRawSaveRequest(srv, c1Bytes) == System.Net.HttpStatusCode.BadRequest, "outer-escaped-surrogate-status");
                    Assert(BytesEqual(System.IO.File.ReadAllBytes(slotPath), origSlotBytes), "outer-escaped-surrogate-slot-unchanged");
                    Assert(BytesEqual(System.IO.File.ReadAllBytes(titlePath), origTitleBytes), "outer-escaped-surrogate-title-unchanged");
                    AssertNoBackupsCreated(root, "outer-escaped-surrogate");

                    string c2Json = ser.Serialize(new Dictionary<string, object>
                    {
                        { "slot", "Save0.Save" },
                        { "text", MakeSaveJson(777777, 1, 1).Replace("\\uBBF8\\uBA85", "\\uD800") },
                        { "baseSha256", origSha }
                    });
                    byte[] c2Bytes = utf8NoBom.GetBytes(c2Json);
                    Assert(PostRawSaveRequest(srv, c2Bytes) == System.Net.HttpStatusCode.BadRequest, "inner-escaped-surrogate-status");
                    Assert(BytesEqual(System.IO.File.ReadAllBytes(slotPath), origSlotBytes), "inner-escaped-surrogate-slot-unchanged");
                    Assert(BytesEqual(System.IO.File.ReadAllBytes(titlePath), origTitleBytes), "inner-escaped-surrogate-title-unchanged");
                    AssertNoBackupsCreated(root, "inner-escaped-surrogate");

                    string loneCharSave = MakeSaveJson(777777, 1, 1).Replace("\\uBBF8\\uBA85", new string(new char[] { 'A', (char)0xD800, 'B' }));
                    SaveWriteResult badRes = SaveStore.SaveSlot(root, "Save0.Save", loneCharSave, origSha);
                    Assert(!badRes.Success, "direct-lone-surrogate-success");
                    Assert(BytesEqual(System.IO.File.ReadAllBytes(slotPath), origSlotBytes), "direct-lone-surrogate-slot-unchanged");
                    Assert(BytesEqual(System.IO.File.ReadAllBytes(titlePath), origTitleBytes), "direct-lone-surrogate-title-unchanged");
                    AssertNoBackupsCreated(root, "direct-lone-surrogate");

                    byte[] positiveBytes = utf8NoBom.GetBytes(validPayloadJson);
                    Assert(PostRawSaveRequest(srv, positiveBytes) == System.Net.HttpStatusCode.OK, "positive-control-status");

                    byte[] savedBytes = System.IO.File.ReadAllBytes(slotPath);
                    Assert(HasBom(savedBytes), "positive-control-bom");
                    string decodedSaved = new System.Text.UTF8Encoding(false, true).GetString(savedBytes, 3, savedBytes.Length - 3);
                    Assert(decodedSaved.IndexOf("\"m_iMoney\":888888", System.StringComparison.Ordinal) >= 0, "positive-control-content");

                    string postPositiveSha = ComputeSha256(savedBytes);

                    int repeatCount = 3200000;
                    string expectedLargeSave = MakeSaveJson(999999, 1, 1);
                    int expectedLargeBrace = expectedLargeSave.LastIndexOf('}');
                    expectedLargeSave = expectedLargeSave.Substring(0, expectedLargeBrace) + ",\"m_strNote\":\"" + new string('<', repeatCount) + "\"" + expectedLargeSave.Substring(expectedLargeBrace);

                    string largeTemplateSave = MakeSaveJson(999999, 1, 1);
                    int largeTemplateBrace = largeTemplateSave.LastIndexOf('}');
                    largeTemplateSave = largeTemplateSave.Substring(0, largeTemplateBrace) + ",\"m_strNote\":\"__LARGE_ESC__\"" + largeTemplateSave.Substring(largeTemplateBrace);

                    Dictionary<string, object> largeTemplate = new Dictionary<string, object>
                    {
                        { "slot", "Save0.Save" },
                        { "text", largeTemplateSave },
                        { "baseSha256", postPositiveSha }
                    };

                    char[] largeEscapeChars = new char[repeatCount * 6];
                    for (int i = 0; i < repeatCount; i++)
                    {
                        int offset = i * 6;
                        largeEscapeChars[offset] = '\\';
                        largeEscapeChars[offset + 1] = 'u';
                        largeEscapeChars[offset + 2] = '0';
                        largeEscapeChars[offset + 3] = '0';
                        largeEscapeChars[offset + 4] = '3';
                        largeEscapeChars[offset + 5] = 'C';
                    }
                    string largeEscape = new string(largeEscapeChars);

                    string largeEnvelopeTemplate = ser.Serialize(largeTemplate);
                    string largeEnvelopeJson = largeEnvelopeTemplate.Replace("__LARGE_ESC__", largeEscape);
                    byte[] largeEnvelopeBytes = utf8NoBom.GetBytes(largeEnvelopeJson);

                    Assert(largeEnvelopeBytes.Length > SaveStore.MaxSaveBytes + 1024 * 1024 && largeEnvelopeBytes.Length > 18 * 1024 * 1024, "large-envelope-over-18mib");
                    Assert(PostRawSaveRequest(srv, largeEnvelopeBytes) == System.Net.HttpStatusCode.OK, "large-envelope-status");

                    byte[] largeSavedBytes = System.IO.File.ReadAllBytes(slotPath);
                    Assert(HasBom(largeSavedBytes), "large-envelope-bom");
                    Assert(largeSavedBytes.Length <= SaveStore.MaxSaveBytes, "large-envelope-disk-cap");
                    string decodedLargeSaved = new System.Text.UTF8Encoding(false, true).GetString(largeSavedBytes, 3, largeSavedBytes.Length - 3);
                    Assert(decodedLargeSaved == expectedLargeSave, "large-envelope-content");
                }
            }
            finally
            {
                DeleteDir(root);
            }
        }

        private static void Test_DoubleBomRejectionAndRestoreCodecRoundtrip()
        {
            string root = CreateTempDir();
            try
            {
                string validSaveJson = MakeSaveJson(1000, 1, 1);
                string titleJson = MakeTitleJson();
                string slotPath = Path.Combine(root, "Save0.Save");
                string titlePath = Path.Combine(root, "SaveTitle.SaveTitle");
                File.WriteAllText(slotPath, validSaveJson, new UTF8Encoding(true));
                File.WriteAllText(titlePath, titleJson, new UTF8Encoding(false));
                byte[] origSlotBytes = File.ReadAllBytes(slotPath);
                byte[] origTitleBytes = File.ReadAllBytes(titlePath);
                string origSha = ComputeSha256(origSlotBytes);

                SaveWriteResult saveRes = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(2500, 2, 3), origSha);
                Assert(saveRes.Success, "initial-save-success");
                Assert(!string.IsNullOrEmpty(saveRes.BackupPath) && File.Exists(saveRes.BackupPath), "initial-save-backup-exists");
                SaveWriteResult res = SaveStore.RestoreBackup(root, saveRes.BackupPath, "Save0.Save");
                Assert(res.Success, "initial-restore-success");

                SaveLoadResult loaded = SaveStore.LoadSlot(root, "Save0.Save");
                Assert(loaded.Success && loaded.RawBytes != null, "loaded-success");
                Assert(HasBom(loaded.RawBytes), "loaded-has-bom");
                Assert(!(loaded.RawBytes.Length >= 6 && loaded.RawBytes[3] == 0xEF && loaded.RawBytes[4] == 0xBB && loaded.RawBytes[5] == 0xBF), "loaded-no-double-bom");
                Assert(SaveStore.ValidateSaveJson(new UTF8Encoding(false, true).GetString(loaded.RawBytes, 3, loaded.RawBytes.Length - 3)) == "save", "loaded-validate-save");
                Assert(BytesEqual(loaded.RawBytes, origSlotBytes), "loaded-original-bytes");

                string backupsDir = Path.Combine(root, "backups");
                Directory.CreateDirectory(backupsDir);
                string doubleBomJson = MakeSaveJson(4321, 3, 4);
                byte[] doubleBomNoBomBytes = new UTF8Encoding(false).GetBytes(doubleBomJson);
                byte[] doubleBomBytes = new byte[6 + doubleBomNoBomBytes.Length];
                doubleBomBytes[0] = 0xEF;
                doubleBomBytes[1] = 0xBB;
                doubleBomBytes[2] = 0xBF;
                doubleBomBytes[3] = 0xEF;
                doubleBomBytes[4] = 0xBB;
                doubleBomBytes[5] = 0xBF;
                Buffer.BlockCopy(doubleBomNoBomBytes, 0, doubleBomBytes, 6, doubleBomNoBomBytes.Length);
                string doubleBomSha = ComputeSha256(doubleBomBytes);
                string doubleBomBakName = SaveStore.SlotBackupPrefix("Save0.Save") + "_20260101T0000010Z_" + doubleBomSha.Substring(0, 8) + ".bak";
                Assert(SaveStore.IsBackupForSlot(doubleBomBakName, "Save0.Save"), "double-bom-backup-name-valid");
                string doubleBomBakPath = Path.Combine(backupsDir, doubleBomBakName);
                File.WriteAllBytes(doubleBomBakPath, doubleBomBytes);

                byte[] beforeSlotBytes = File.ReadAllBytes(slotPath);
                byte[] beforeTitleBytes = File.ReadAllBytes(titlePath);

                SaveWriteResult badRestore = SaveStore.RestoreBackup(root, doubleBomBakName, "Save0.Save");
                Assert(!badRestore.Success && badRestore.Message == "DOUBLE_UTF8_BOM", "double-bom-restore-rejected");
                Assert(BytesEqual(File.ReadAllBytes(slotPath), beforeSlotBytes), "double-bom-restore-slot-unchanged");
                Assert(BytesEqual(File.ReadAllBytes(titlePath), beforeTitleBytes), "double-bom-restore-title-unchanged");

                string save2Path = Path.Combine(root, "Save2.Save");
                File.WriteAllBytes(save2Path, doubleBomBytes);
                SaveLoadResult loadDoubleBom = SaveStore.LoadSlot(root, "Save2.Save");
                Assert(!loadDoubleBom.Success && loadDoubleBom.Message == "DOUBLE_UTF8_BOM", "double-bom-load-rejected");

                string save3Path = Path.Combine(root, "Save3.Save");
                byte[] utf16Payload = Encoding.Unicode.GetBytes(validSaveJson);
                byte[] utf16Bytes = new byte[2 + utf16Payload.Length];
                utf16Bytes[0] = 0xFF;
                utf16Bytes[1] = 0xFE;
                Buffer.BlockCopy(utf16Payload, 0, utf16Bytes, 2, utf16Payload.Length);
                File.WriteAllBytes(save3Path, utf16Bytes);
                SaveLoadResult utf16Load = SaveStore.LoadSlot(root, "Save3.Save");
                Assert(!utf16Load.Success && utf16Load.Message == "UNSUPPORTED_UTF_BOM", "utf16-bom-load-rejected");

                AssertThrows(delegate { SaveStore.ValidateSaveJson("\uFEFF\uFEFF" + validSaveJson); }, "double-bom-validate");

                string currentSlotSha = ComputeSha256(File.ReadAllBytes(slotPath));
                SaveWriteResult badSave = SaveStore.SaveSlot(root, "Save0.Save", "\uFEFF\uFEFF" + validSaveJson, currentSlotSha);
                Assert(!badSave.Success && badSave.Message == "DOUBLE_UTF8_BOM", "double-bom-save-rejected");
                Assert(BytesEqual(File.ReadAllBytes(slotPath), beforeSlotBytes), "double-bom-save-slot-unchanged");
                Assert(BytesEqual(File.ReadAllBytes(titlePath), beforeTitleBytes), "double-bom-save-title-unchanged");
            }
            finally
            {
                DeleteDir(root);
            }
        }

        private static void AssertStrictSyntaxError(string badJson, string label)
        {
            bool threw = false;
            try
            {
                SaveStore.ValidateSaveJson(badJson);
            }
            catch (System.IO.InvalidDataException ex)
            {
                threw = true;
                Assert(ex.Message == "STRICT_JSON_SYNTAX_ERROR", label + ": wrong message: " + ex.Message);
            }
            Assert(threw, label + ": expected InvalidDataException");
        }

        private static void VerifyStrictJsonSyntaxRejections()
        {
            string baseSave = MakeSaveJson(5000, 2, 6);

            AssertStrictSyntaxError(baseSave.Replace("\"m_strPlayerName\":\"\\uBBF8\\uBA85\\r\"", "\"m_strPlayerName\":'abc\\r'"), "single-quoted value");
            AssertStrictSyntaxError(baseSave.Replace("\"m_strVersion\":\"1.0.3.1\"", "'m_strVersion':\"1.0.3.1\""), "single-quoted key");
            AssertStrictSyntaxError(baseSave.Replace("\"m_strVersion\":\"1.0.3.1\"", "m_strVersion:\"1.0.3.1\""), "unquoted key");
            AssertStrictSyntaxError("[1,]", "trailing comma array");
            AssertStrictSyntaxError(baseSave.Replace("\"m_ItmeEffectNodeList\":[]", "\"m_ItmeEffectNodeList\":[1,]"), "trailing comma object array");
            AssertStrictSyntaxError(baseSave.Substring(0, baseSave.Length - 1) + ",}", "trailing comma object");
            AssertStrictSyntaxError("[1,,2]", "array elision");
            AssertStrictSyntaxError(baseSave.Replace("\"1.0.3.1\"", "\"1.0\\'3.1\""), "invalid escape");
            AssertStrictSyntaxError("{\"k\":\"a\tb\"}", "control char");
            AssertStrictSyntaxError(baseSave.Replace("\"m_iMoney\":5000", "\"m_iMoney\":01"), "leading zero");
            AssertStrictSyntaxError(baseSave.Replace("\"m_iMoney\":5000", "\"m_iMoney\":+100"), "plus sign");
            AssertStrictSyntaxError(baseSave.Replace("\"m_iMoney\":5000", "\"m_iMoney\":.5"), "leading decimal point");
            AssertStrictSyntaxError(baseSave.Replace("\"m_iMoney\":5000", "\"m_iMoney\":1."), "trailing decimal point");
            AssertStrictSyntaxError(baseSave.Replace("\"m_iMoney\":5000", "\"m_iMoney\":0x10"), "hex number");
            AssertStrictSyntaxError("{\"m_iMoney\":100}/*c*/", "block comment");
            AssertStrictSyntaxError(baseSave + "//c", "line comment");
            AssertStrictSyntaxError("\u00A0" + baseSave, "non-standard whitespace");
            AssertStrictSyntaxError(new string('[', 130) + new string(']', 130), "depth over limit");
        }

        private static void Test_StrictJsonSyntaxRejectsSingleQuotesAndNonStandardForms()
        {
            VerifyStrictJsonSyntaxRejections();
            string root = CreateTempDir();
            try
            {
                string slotPath = Path.Combine(root, "Save0.Save");
                string titlePath = Path.Combine(root, "SaveTitle.SaveTitle");
                UTF8Encoding utf8NoBom = new UTF8Encoding(false);
                File.WriteAllText(slotPath, MakeSaveJson(101L, 2, 3), new UTF8Encoding(true));
                File.WriteAllText(titlePath, MakeTitleJson(), utf8NoBom);
                byte[] origSlotBytes = File.ReadAllBytes(slotPath);
                byte[] origTitleBytes = File.ReadAllBytes(titlePath);
                string origSha = ComputeSha256(origSlotBytes);
                string singleQuotedSave = MakeSaveJson(101L, 2, 3).Replace("\"m_strPlayerName\":\"\\uBBF8\\uBA85\\r\"", "\"m_strPlayerName\":'abc\\r'");

                string badSlot2 = Path.Combine(root, "Save2.Save");
                File.WriteAllText(badSlot2, singleQuotedSave, utf8NoBom);
                SaveLoadResult loadBad = SaveStore.LoadSlot(root, "Save2.Save");
                Assert(!loadBad.Success && loadBad.Message == "STRICT_JSON_SYNTAX_ERROR", "LoadSlot must reject single-quoted JSON");
                File.Delete(badSlot2);

                using (SaveEditor.LocalBridgeServer srv = new SaveEditor.LocalBridgeServer(root))
                {
                    srv.Start();
                    JavaScriptSerializer js = new JavaScriptSerializer();
                    string badEnvelope = js.Serialize(new Dictionary<string, object> { { "slot", "Save0.Save" }, { "text", singleQuotedSave }, { "baseSha256", origSha } });
                    byte[] badBytes = utf8NoBom.GetBytes(badEnvelope);
                    Assert(PostRawSaveRequest(srv, badBytes) == HttpStatusCode.BadRequest, "single-quote save must be rejected");
                    Assert(BytesEqual(File.ReadAllBytes(slotPath), origSlotBytes), "slot changed after rejected save");
                    Assert(BytesEqual(File.ReadAllBytes(titlePath), origTitleBytes), "title changed after rejected save");
                    AssertNoBackupsCreated(root, "single-quote-save");

                    string jsonFxSave = MakeSaveJson(8888L, 3, 7)
                        .Replace("\"m_iFriendly\":60", "\"m_iFriendly\":-1")
                        .Replace("\"m_iValue\":80,\"m_iIndex\":0,\"m_iExp\":0", "\"m_iValue\":1.2E+5,\"m_iIndex\":0,\"m_iExp\":0")
                        .Replace("\"m_iYear\":3", "\"m_iYear\":3E+0");
                    string fx = ",\"m_fSciNeg\":30e-4,\"m_fSciPos\":1E+05,\"m_strBr\":\"\\u003Cbr>\",\"m_strEmoji\":\"\\uD83D\\uDE00\"";
                    int lastBrace = jsonFxSave.LastIndexOf('}');
                    jsonFxSave = jsonFxSave.Substring(0, lastBrace) + fx + jsonFxSave.Substring(lastBrace) + "\r\n";
                    Assert(SaveStore.ValidateSaveJson(jsonFxSave) == "save", "valid JsonFx constructs must pass ValidateSaveJson");

                    Environment.SetEnvironmentVariable("TWX_SIMULATE_BACKUP_NAME_RACE", "1");
                    try
                    {
                        string okEnvelope = js.Serialize(new Dictionary<string, object> { { "slot", "Save0.Save" }, { "text", jsonFxSave }, { "baseSha256", origSha } });
                        byte[] okBytes = new UTF8Encoding(false).GetBytes(okEnvelope);
                        Assert(PostRawSaveRequest(srv, okBytes) == HttpStatusCode.OK, "valid JsonFx save must succeed under backup name race");
                    }
                    finally
                    {
                        Environment.SetEnvironmentVariable("TWX_SIMULATE_BACKUP_NAME_RACE", null);
                    }
                    byte[] savedBytes = File.ReadAllBytes(slotPath);
                    Assert(HasBom(savedBytes), "saved file must preserve BOM");
                    string savedText = new UTF8Encoding(false, true).GetString(savedBytes, 3, savedBytes.Length - 3);
                    Assert(savedText == jsonFxSave, "saved UTF-8 body must preserve exact JsonFx tokens including 1.2E+5 and 3E+0");
                    Assert(SaveStore.LoadSlot(root, "Save0.Save").Success, "saved JsonFx slot must load");

                    string[] raceBaks = Directory.GetFiles(Path.Combine(root, "backups"), "*.bak");
                    int preExistingHits = 0;
                    int realSlotBakHits = 0;
                    for (int bi = 0; bi < raceBaks.Length; bi++)
                    {
                        string btxt = File.ReadAllText(raceBaks[bi], Encoding.UTF8);
                        if (btxt == "{\"preexisting_backup\":1}") preExistingHits++;
                        if (SaveStore.IsBackupForSlot(Path.GetFileName(raceBaks[bi]), "Save0.Save") && btxt != "{\"preexisting_backup\":1}") realSlotBakHits++;
                    }
                    Assert(preExistingHits >= 1 && realSlotBakHits >= 1, "Backup name race must preserve preexisting .bak and write collision-resolved .bak");

                    HttpWebRequest loadReq = (HttpWebRequest)WebRequest.Create(srv.Url + "api/load?slot=Save0.Save");
                    loadReq.Method = "GET";
                    loadReq.Proxy = null;
                    loadReq.KeepAlive = false;
                    loadReq.Headers["X-TWX-Token"] = srv.Token;
                    loadReq.Headers["Origin"] = srv.Url.TrimEnd('/');
                    using (HttpWebResponse loadResp = (HttpWebResponse)loadReq.GetResponse())
                    {
                        Assert(loadResp.StatusCode == HttpStatusCode.OK, "GET /api/load must accept 1.2E+5 and 3E+0");
                        using (StreamReader sr = new StreamReader(loadResp.GetResponseStream(), Encoding.UTF8))
                        {
                            string httpLoaded = sr.ReadToEnd();
                            Assert(httpLoaded.IndexOf("\"m_iValue\":1.2E+5", StringComparison.Ordinal) >= 0 && httpLoaded.IndexOf("\"m_iYear\":3E+0", StringComparison.Ordinal) >= 0, "GET /api/load must preserve 1.2E+5 and 3E+0");
                        }
                    }

                    byte[] beforeSwapSlot = File.ReadAllBytes(slotPath);
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_STAGED_TEMP_SWAP", "slot");
                    try
                    {
                        SaveWriteResult swapFail = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(9191L, 3, 7));
                        Assert(!swapFail.Success, "SaveSlot must reject swapped staged temp");
                    }
                    finally
                    {
                        Environment.SetEnvironmentVariable("TWX_SIMULATE_STAGED_TEMP_SWAP", null);
                    }
                    Assert(BytesEqual(File.ReadAllBytes(slotPath), beforeSwapSlot), "Save0.Save must remain untouched after staged temp swap");
                    string[] foreignTmps = Directory.GetFiles(root, "*.tmp");
                    int foreignHits = 0;
                    for (int fi = 0; fi < foreignTmps.Length; fi++)
                    {
                        if (File.ReadAllText(foreignTmps[fi], Encoding.UTF8) == "{\"foreign_at_tmp\":1}")
                        {
                            foreignHits++;
                            File.Delete(foreignTmps[fi]);
                        }
                    }
                    Assert(foreignHits == 1, "Swapped foreign file at .tmp path must not be deleted by cleanup");

                    Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER", "slot");
                    Environment.SetEnvironmentVariable("TWX_SIMULATE_RB_TEMP_SWAP", "1");
                    try
                    {
                        SaveWriteResult rbSwapFail = SaveStore.SaveSlot(root, "Save0.Save", MakeSaveJson(9292L, 3, 7));
                        Assert(!rbSwapFail.Success, "SaveSlot must fail when post-commit tamper and rb temp swap occur");
                    }
                    finally
                    {
                        Environment.SetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER", null);
                        Environment.SetEnvironmentVariable("TWX_SIMULATE_RB_TEMP_SWAP", null);
                    }
                    string[] rbForeignTmps = Directory.GetFiles(root, "*.tmp");
                    int rbForeignHits = 0;
                    for (int rfi = 0; rfi < rbForeignTmps.Length; rfi++)
                    {
                        if (File.ReadAllText(rbForeignTmps[rfi], Encoding.UTF8) == "{\"foreign_at_rb_tmp\":1}")
                        {
                            rbForeignHits++;
                            File.Delete(rbForeignTmps[rfi]);
                        }
                    }
                    Assert(rbForeignHits == 2, "Swapped foreign files at title + slot rollback .tmp paths must not be deleted by cleanup");

                    string csBakRoot = CreateTempDir();
                    try
                    {
                        string csBakDir = Path.Combine(csBakRoot, "backups");
                        Directory.CreateDirectory(csBakDir);
                        int csBakExit = TryEnableCaseSensitiveDir(csBakDir);
                        if (Environment.GetEnvironmentVariable("TWX_REQUIRE_CASE_SENSITIVE_DIR") == "1")
                            Assert(csBakExit == 0, "fsutil setCaseSensitiveInfo on backups failed");
                        File.WriteAllText(Path.Combine(csBakRoot, "Save0.Save"), MakeSaveJson(1000L, 1, 1), new UTF8Encoding(false));
                        SaveWriteResult mkBakRes = SaveStore.SaveSlot(csBakRoot, "Save0.Save", MakeSaveJson(2000L, 1, 2));
                        Assert(mkBakRes.Success && !string.IsNullOrEmpty(mkBakRes.BackupPath), "SaveSlot must create backup in csBakRoot");
                        string realBakFile = Path.GetFileName(mkBakRes.BackupPath);
                        string upperBakFile = realBakFile.Substring(0, realBakFile.Length - 4) + ".BAK";
                        SaveWriteResult wrongCaseRestore = SaveStore.RestoreBackup(csBakRoot, upperBakFile, "Save0.Save");
                        Assert(!wrongCaseRestore.Success && wrongCaseRestore.Message == "CASE_COLLISION_REJECTED", "RestoreBackup must reject wrong-case .BAK name");
                        if (csBakExit == 0)
                        {
                            File.WriteAllBytes(Path.Combine(csBakDir, upperBakFile), File.ReadAllBytes(mkBakRes.BackupPath));
                            SaveWriteResult sibRestore = SaveStore.RestoreBackup(csBakRoot, realBakFile, "Save0.Save");
                            Assert(!sibRestore.Success && sibRestore.Message == "CASE_COLLISION_REJECTED", "RestoreBackup must reject coexisting case-colliding .bak/.BAK siblings");
                        }
                    }
                    finally
                    {
                        DeleteDir(csBakRoot);
                    }

                    string upperBackupsRoot = CreateTempDir();
                    try
                    {
                        Directory.CreateDirectory(Path.Combine(upperBackupsRoot, "Backups"));
                        string ubSlotPath = Path.Combine(upperBackupsRoot, "Save0.Save");
                        string ubOrigJson = MakeSaveJson(1234L, 1, 1);
                        File.WriteAllText(ubSlotPath, ubOrigJson, new UTF8Encoding(false));
                        SaveWriteResult ubSaveRes = SaveStore.SaveSlot(upperBackupsRoot, "Save0.Save", MakeSaveJson(5678L, 2, 2));
                        Assert(!ubSaveRes.Success && ubSaveRes.Message == "CASE_COLLISION_REJECTED", "SaveSlot must reject pre-existing uppercase Backups directory before writing");
                        Assert(File.ReadAllText(ubSlotPath, Encoding.UTF8) == ubOrigJson, "Save0.Save must remain untouched when Backups case collision exists");
                        Assert(Directory.GetFiles(Path.Combine(upperBackupsRoot, "Backups")).Length == 0, "Backups directory must remain empty");
                    }
                    finally
                    {
                        DeleteDir(upperBackupsRoot);
                    }
                }
            }
            finally
            {
                DeleteDir(root);
            }
        }

        private static void Test_SubdirFileIdLockOrderAndCrossProcessPythonContention()
        {
            string hostDir = CreateTempDir();
            Process proc = null;
            UTF8Encoding utf8NoBom = new UTF8Encoding(false);
            try
            {
                string root = null;
                string sub = null;
                SaveStore.FileId rootId = default(SaveStore.FileId);
                SaveStore.FileId subId = default(SaveStore.FileId);

                for (int pairTry = 0; pairTry < 24; pairTry++)
                {
                    string bump = Path.Combine(hostDir, "bump_hi_" + pairTry.ToString(CultureInfo.InvariantCulture));
                    for (int b = 0; b < 32; b++)
                    {
                        Directory.CreateDirectory(bump);
                        Directory.Delete(bump, false);
                    }
                    string candRoot = Path.Combine(hostDir, "root_hi_" + pairTry.ToString(CultureInfo.InvariantCulture));
                    string candSub = Path.Combine(candRoot, "sub");
                    Directory.CreateDirectory(candRoot);
                    Directory.CreateDirectory(candSub);
                    SaveStore.FileId rId = SaveStore.CaptureRootIdentity(candRoot);
                    SaveStore.FileId sId = SaveStore.CaptureRootIdentity(candSub);
                    if (SaveStore.CompareFileIds(sId, rId) < 0)
                    {
                        root = candRoot;
                        sub = candSub;
                        rootId = rId;
                        subId = sId;
                        break;
                    }
                }
                Assert(root != null && SaveStore.CompareFileIds(subId, rootId) < 0, "Expected NTFS directory pair with subId < rootId");

                string root2 = null;
                string sub2 = null;
                SaveStore.FileId rootId2 = default(SaveStore.FileId);
                SaveStore.FileId subId2 = default(SaveStore.FileId);

                for (int pair2Try = 0; pair2Try < 24; pair2Try++)
                {
                    string candRoot2 = Path.Combine(hostDir, "root_lo_" + pair2Try.ToString(CultureInfo.InvariantCulture));
                    Directory.CreateDirectory(candRoot2);
                    string bump2 = Path.Combine(hostDir, "bump_lo_" + pair2Try.ToString(CultureInfo.InvariantCulture));
                    for (int b = 0; b < 32; b++)
                    {
                        Directory.CreateDirectory(bump2);
                        Directory.Delete(bump2, false);
                    }
                    string candSub2 = Path.Combine(candRoot2, "sub");
                    Directory.CreateDirectory(candSub2);
                    SaveStore.FileId rId2 = SaveStore.CaptureRootIdentity(candRoot2);
                    SaveStore.FileId sId2 = SaveStore.CaptureRootIdentity(candSub2);
                    if (SaveStore.CompareFileIds(rId2, sId2) < 0)
                    {
                        root2 = candRoot2;
                        sub2 = candSub2;
                        rootId2 = rId2;
                        subId2 = sId2;
                        break;
                    }
                }
                Assert(root2 != null && SaveStore.CompareFileIds(rootId2, subId2) < 0, "Expected NTFS directory pair with rootId2 < subId2");

                File.WriteAllText(Path.Combine(sub, "Save0.Save"), MakeSaveJson(1000, 1, 1), utf8NoBom);
                File.WriteAllText(Path.Combine(sub, "SaveTitle.SaveTitle"), MakeTitleJsonSlots(4), utf8NoBom);
                SaveWriteResult seed1 = SaveStore.SaveSlot(root, "sub/Save0.Save", MakeSaveJson(1500, 1, 2));
                Assert(seed1.Success, "seed1 SaveSlot failed: " + seed1.Message);

                File.WriteAllText(Path.Combine(sub2, "Save0.Save"), MakeSaveJson(1000, 1, 1), utf8NoBom);
                File.WriteAllText(Path.Combine(sub2, "SaveTitle.SaveTitle"), MakeTitleJsonSlots(4), utf8NoBom);
                SaveWriteResult seed2 = SaveStore.SaveSlot(root2, "sub/Save0.Save", MakeSaveJson(1500, 1, 2));
                Assert(seed2.Success, "seed2 SaveSlot failed: " + seed2.Message);

                SaveStore.BeginRecordLockOrder();
                SaveWriteResult sw1 = SaveStore.SaveSlot(root, "sub/Save0.Save", MakeSaveJson(2000, 2, 2));
                List<SaveStore.FileId> ordSw1 = SaveStore.EndRecordLockOrder();
                Assert(sw1.Success, "sw1 failed: " + sw1.Message);
                Assert(ordSw1.Count == 2 && ordSw1[0].EqualsId(subId) && ordSw1[1].EqualsId(rootId), "SaveSlot lock order mismatch for subId < rootId");

                SaveStore.BeginRecordLockOrder();
                SaveLoadResult lr1 = SaveStore.LoadSlot(root, "sub/Save0.Save");
                List<SaveStore.FileId> ordLr1 = SaveStore.EndRecordLockOrder();
                Assert(lr1.Success, "lr1 failed: " + lr1.Message);
                Assert(ordLr1.Count == 2 && ordLr1[0].EqualsId(subId) && ordLr1[1].EqualsId(rootId), "LoadSlot lock order mismatch for subId < rootId");

                SaveStore.BeginRecordLockOrder();
                List<BackupInfo> bk1 = SaveStore.ListBackupsForSlot(root, "sub/Save0.Save");
                List<SaveStore.FileId> ordBk1 = SaveStore.EndRecordLockOrder();
                Assert(bk1.Count >= 1, "Expected backup for sub/Save0.Save");
                Assert(ordBk1.Count == 2 && ordBk1[0].EqualsId(subId) && ordBk1[1].EqualsId(rootId), "ListBackupsForSlot lock order mismatch for subId < rootId");

                SaveStore.BeginRecordLockOrder();
                SaveWriteResult rb1 = SaveStore.RestoreBackup(root, seed1.BackupPath, "sub/Save0.Save");
                List<SaveStore.FileId> ordRb1 = SaveStore.EndRecordLockOrder();
                Assert(rb1.Success, "rb1 failed: " + rb1.Message);
                Assert(ordRb1.Count == 2 && ordRb1[0].EqualsId(subId) && ordRb1[1].EqualsId(rootId), "RestoreBackup lock order mismatch for subId < rootId");

                SaveStore.BeginRecordLockOrder();
                SaveWriteResult sw2 = SaveStore.SaveSlot(root2, "sub/Save0.Save", MakeSaveJson(2000, 2, 2));
                List<SaveStore.FileId> ordSw2 = SaveStore.EndRecordLockOrder();
                Assert(sw2.Success, "sw2 failed: " + sw2.Message);
                Assert(ordSw2.Count == 2 && ordSw2[0].EqualsId(rootId2) && ordSw2[1].EqualsId(subId2), "SaveSlot lock order mismatch for rootId2 < subId2");

                SaveStore.BeginRecordLockOrder();
                SaveWriteResult rb2 = SaveStore.RestoreBackup(root2, seed2.BackupPath, "sub/Save0.Save");
                List<SaveStore.FileId> ordRb2 = SaveStore.EndRecordLockOrder();
                Assert(rb2.Success, "rb2 failed: " + rb2.Message);
                Assert(ordRb2.Count == 2 && ordRb2[0].EqualsId(rootId2) && ordRb2[1].EqualsId(subId2), "RestoreBackup lock order mismatch for rootId2 < subId2");

                string pyScript = null;
                string[] searchDirs = new string[]
                {
                    Environment.CurrentDirectory,
                    AppDomain.CurrentDomain.BaseDirectory,
                    Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".."))
                };
                for (int d = 0; d < searchDirs.Length; d++)
                {
                    string candPy = Path.Combine(searchDirs[d], "twx_editor.py");
                    if (File.Exists(candPy))
                    {
                        pyScript = candPy;
                        break;
                    }
                }

                bool requirePy = Environment.GetEnvironmentVariable("TWX_REQUIRE_PY_CS_CONTENTION") == "1";
                if (requirePy)
                    Assert(!string.IsNullOrEmpty(pyScript) && File.Exists(pyScript), "twx_editor.py required for cross-process contention test");

                if (!string.IsNullOrEmpty(pyScript) && File.Exists(pyScript))
                {
                    string pyDir = Path.GetDirectoryName(Path.GetFullPath(pyScript));
                    string workerPy = Path.Combine(hostDir, "py_cs_contend_worker.py");
                    string workerCode =
                        "import contextlib, io, pathlib, sys\n" +
                        "sys.path.insert(0, sys.argv[1])\n" +
                        "import twx_editor as t\n" +
                        "root = pathlib.Path(sys.argv[2])\n" +
                        "sub_save = root / 'sub' / 'Save0.Save'\n" +
                        "for i in range(12):\n" +
                        "    with contextlib.redirect_stdout(io.StringIO()):\n" +
                        "        rc = t.main(['apply', str(sub_save), '--root', str(root), '--set-money', str(50000 + i)])\n" +
                        "    if rc != 0:\n" +
                        "        raise RuntimeError('apply failed: ' + str(rc))\n" +
                        "    raw = t.read_safe_bytes(root, 'sub/Save0.Save')\n" +
                        "    t.validate_data(t.parse_json_lossless(raw.decode('utf-8'))[0])\n" +
                        "print('PY_CONTEND_OK')\n";
                    File.WriteAllText(workerPy, workerCode, utf8NoBom);

                    StringBuilder pyOut = new StringBuilder();
                    StringBuilder pyErr = new StringBuilder();
                    ProcessStartInfo psi = new ProcessStartInfo("python", string.Format(CultureInfo.InvariantCulture, "-B \"{0}\" \"{1}\" \"{2}\"", workerPy, pyDir, root));
                    psi.CreateNoWindow = true;
                    psi.UseShellExecute = false;
                    psi.RedirectStandardOutput = true;
                    psi.RedirectStandardError = true;
                    psi.WorkingDirectory = pyDir;

                    proc = new Process();
                    proc.StartInfo = psi;
                    proc.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e)
                    {
                        if (e.Data != null)
                        {
                            lock (pyOut) { pyOut.AppendLine(e.Data); }
                        }
                    };
                    proc.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e)
                    {
                        if (e.Data != null)
                        {
                            lock (pyErr) { pyErr.AppendLine(e.Data); }
                        }
                    };
                    Assert(proc.Start(), "Failed to start python contention process");
                    proc.BeginOutputReadLine();
                    proc.BeginErrorReadLine();

                    for (int i = 0; i < 12; i++)
                    {
                        SaveWriteResult csw = SaveStore.SaveSlot(root, "sub/Save0.Save", MakeSaveJson(70000 + i, 2, 3));
                        Assert(csw.Success, "Concurrent C# SaveSlot failed (" + i.ToString(CultureInfo.InvariantCulture) + "): " + csw.Message);
                        SaveLoadResult clr = SaveStore.LoadSlot(root, "sub/Save0.Save");
                        Assert(clr.Success, "Concurrent C# LoadSlot failed (" + i.ToString(CultureInfo.InvariantCulture) + "): " + clr.Message);
                        List<BackupInfo> cbk = SaveStore.ListBackupsForSlot(root, "sub/Save0.Save");
                        Assert(cbk.Count >= 1, "Concurrent C# ListBackupsForSlot returned empty");
                    }

                    bool exited = proc.WaitForExit(30000);
                    Assert(exited, "Python contention process timed out");
                    proc.WaitForExit();
                    string outStr;
                    string errStr;
                    lock (pyOut) { outStr = pyOut.ToString(); }
                    lock (pyErr) { errStr = pyErr.ToString(); }
                    Assert(proc.ExitCode == 0 && outStr.IndexOf("PY_CONTEND_OK", StringComparison.Ordinal) >= 0,
                        "Python contention process failed (" + proc.ExitCode.ToString(CultureInfo.InvariantCulture) + "): " + errStr + " | " + outStr);

                    SaveLoadResult finalLoad = SaveStore.LoadSlot(root, "sub/Save0.Save");
                    Assert(finalLoad.Success, "Final LoadSlot after contention failed: " + finalLoad.Message);
                }
            }
            finally
            {
                if (proc != null)
                {
                    try { if (!proc.HasExited) proc.Kill(); } catch { }
                    try { proc.Dispose(); } catch { }
                }
                DeleteDir(hostDir);
            }
        }

        private static bool TryCreateJunction(string linkPath, string targetPath)
        {
            try
            {
                var psi = new ProcessStartInfo("cmd.exe", string.Format(CultureInfo.InvariantCulture, "/c mklink /J \"{0}\" \"{1}\"", linkPath, targetPath));
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                using (Process p = Process.Start(psi))
                {
                    if (p == null) return false;
                    p.WaitForExit(3000);
                    return p.ExitCode == 0 && Directory.Exists(linkPath);
                }
            }
            catch { return false; }
        }

        private static void Assert(bool cond, string msg)
        {
            if (!cond) throw new Exception(msg);
        }

        private static void AssertThrows(Action act, string msg)
        {
            try { act(); }
            catch { return; }
            throw new Exception("Expected exception: " + msg);
        }

        private static bool HasBom(byte[] b)
        {
            return b.Length >= 3 && b[0] == 0xEF && b[1] == 0xBB && b[2] == 0xBF;
        }

        private static bool BytesEqual(byte[] a, byte[] b)
        {
            if (a.Length != b.Length) return false;
            for (int i = 0; i < a.Length; i++)
            {
                if (a[i] != b[i]) return false;
            }
            return true;
        }

        private static string ComputeSha256(byte[] data)
        {
            using (SHA256 sha = SHA256.Create())
            {
                byte[] hash = sha.ComputeHash(data);
                var sb = new StringBuilder(hash.Length * 2);
                for (int i = 0; i < hash.Length; i++) sb.Append(hash[i].ToString("x2", CultureInfo.InvariantCulture));
                return sb.ToString();
            }
        }

        private static string CreateTempDir()
        {
            string dir = Path.Combine(Path.GetTempPath(), "twx_cstest_" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(dir);
            return dir;
        }

        private static void DeleteDir(string dir)
        {
            try { if (Directory.Exists(dir)) Directory.Delete(dir, true); }
            catch { }
        }
    }
}

namespace TaleOfWuxiaSaveEditor
{
    internal static class SaveStoreTests
    {
        private static int Main()
        {
            return TaleOfWuxiaSaveEditorTests.SaveStoreTests.Main();
        }
    }
}
