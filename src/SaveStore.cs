using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using Microsoft.Win32;
using Microsoft.Win32.SafeHandles;

namespace TaleOfWuxiaSaveEditor
{
    public sealed class SaveSlotInfo
    {
        public string FileName { get; set; }
        public string FullPath { get; set; }
        public string Kind { get; set; }
        public string SlotName { get; set; }
        public string Summary { get; set; }
        public long SizeBytes { get; set; }
        public DateTime LastWriteUtc { get; set; }
        public string Sha256 { get; set; }

        public SaveSlotInfo()
        {
            FileName = "";
            FullPath = "";
            Kind = "";
            SlotName = "";
            Summary = "";
            Sha256 = "";
        }
    }

    public sealed class BackupInfo
    {
        public string FullPath { get; set; }
        public string FileName { get; set; }
        public string SlotName { get; set; }
        public DateTime CreatedUtc { get; set; }
        public string Sha256 { get; set; }
        public long SizeBytes { get; set; }

        public BackupInfo()
        {
            FullPath = "";
            FileName = "";
            SlotName = "";
            Sha256 = "";
        }
    }

    public sealed class SaveWriteResult
    {
        public bool Success { get; set; }
        public string Message { get; set; }
        public string TargetPath { get; set; }
        public string BackupPath { get; set; }
        public string Sha256 { get; set; }

        public SaveWriteResult()
        {
            Message = "";
            TargetPath = "";
            BackupPath = "";
            Sha256 = "";
        }
    }

    public sealed class SaveLoadResult
    {
        public bool Success { get; set; }
        public string Message { get; set; }
        public string JsonText { get; set; }
        public byte[] RawBytes { get; set; }
        public SaveSlotInfo Slot { get; set; }
        public string Sha256 { get; set; }

        public SaveLoadResult()
        {
            Message = "";
            JsonText = "";
            RawBytes = new byte[0];
            Sha256 = "";
        }
    }

    public static class SaveStore
    {
        public const int MaxSaveBytes = 16 * 1024 * 1024;
        public const int MaxBackups = 20;

        public struct FileId
        {
            public uint VolumeSerialNumber;
            public uint FileIndexHigh;
            public uint FileIndexLow;
            public bool IsValid;

            public bool EqualsId(FileId other)
            {
                return IsValid && other.IsValid &&
                       VolumeSerialNumber == other.VolumeSerialNumber &&
                       FileIndexHigh == other.FileIndexHigh &&
                       FileIndexLow == other.FileIndexLow;
            }
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct FILETIME
        {
            public uint dwLowDateTime;
            public uint dwHighDateTime;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct BY_HANDLE_FILE_INFORMATION
        {
            public uint FileAttributes;
            public FILETIME CreationTime;
            public FILETIME LastAccessTime;
            public FILETIME LastWriteTime;
            public uint VolumeSerialNumber;
            public uint FileSizeHigh;
            public uint FileSizeLow;
            public uint NumberOfLinks;
            public uint FileIndexHigh;
            public uint FileIndexLow;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct FILE_DISPOSITION_INFO
        {
            [MarshalAs(UnmanagedType.U1)]
            public bool DeleteFile;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateFileW(
            string lpFileName, uint dwDesiredAccess, uint dwShareMode,
            IntPtr lpSecurityAttributes, uint dwCreationDisposition,
            uint dwFlagsAndAttributes, IntPtr hTemplateFile);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr hObject);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetFileInformationByHandle(IntPtr hFile, out BY_HANDLE_FILE_INFORMATION lpFileInformation);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetFileInformationByHandle(IntPtr hFile, int FileInformationClass, ref FILE_DISPOSITION_INFO lpFileInformation, int dwBufferSize);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetFileInformationByHandle(IntPtr hFile, int FileInformationClass, IntPtr lpFileInformation, int dwBufferSize);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern uint GetFinalPathNameByHandleW(IntPtr hFile, StringBuilder lpszFilePath, int cchFilePath, uint dwFlags);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool MoveFileExW(string lpExistingFileName, string lpNewFileName, uint dwFlags);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool ReadFile(IntPtr hFile, byte[] lpBuffer, uint nNumberOfBytesToRead, out uint lpNumberOfBytesRead, IntPtr lpOverlapped);

        private const uint GENERIC_READ = 0x80000000;
        private const uint GENERIC_WRITE = 0x40000000u;
        private const uint DELETE_ACCESS = 0x00010000u;
        private const int FileRenameInfo = 3;
        private const int FileDispositionInfo = 4;
        private const uint FILE_SHARE_READ = 0x00000001u;
        private const uint FILE_SHARE_READ_WRITE = 0x00000003u;
        private const uint FILE_SHARE_ALL = 0x07;
        private const uint OPEN_EXISTING = 3;
        private const uint OPEN_ALWAYS = 4u;
        private const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000;
        private const uint FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000;
        private const uint FILE_ATTRIBUTE_REPARSE_POINT = 0x0400;
        private const uint FILE_ATTRIBUTE_NORMAL = 0x00000080u;
        private const uint MOVEFILE_REPLACE_EXISTING = 0x01;
        private const uint MOVEFILE_WRITE_THROUGH = 0x08;
        private static readonly IntPtr INVALID_HANDLE_VALUE = new IntPtr(-1);

        private static readonly HashSet<string> ReservedDevices = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "CON", "PRN", "AUX", "NUL",
            "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
        };

        private static readonly Regex ManualSaveRegex = new Regex(@"^Save(0|[1-9]|1[0-9])\.Save$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        private static readonly Regex AutoSaveRegex = new Regex(@"^AutomaticSave(0|[1-9]|1[0-9])\.Save$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        private static readonly Regex AutoDSaveRegex = new Regex(@"^AutomaticDSave(0|[1-9]|1[0-9])\.Save$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        private static readonly Regex GuidFileRegex = new Regex(@"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        private static readonly Regex BackupHashRegex = new Regex(@"_([0-9a-fA-F]{8})\.bak$", RegexOptions.CultureInvariant);

        public static List<string> DiscoverRoots()
        {
            var roots = new List<string>();
            string env = Environment.GetEnvironmentVariable("TWX_SAVE_ROOT");
            if (!string.IsNullOrEmpty(env) && env.Trim().Length > 0)
            {
                roots.Add(Path.GetFullPath(env.Trim()));
                return roots;
            }

            var steamDirs = new List<string>();
            string pf86 = Environment.GetEnvironmentVariable("ProgramFiles(x86)");
            string pf = Environment.GetEnvironmentVariable("ProgramFiles");
            if (!string.IsNullOrEmpty(pf86)) steamDirs.Add(Path.Combine(pf86, "Steam"));
            if (!string.IsNullOrEmpty(pf)) steamDirs.Add(Path.Combine(pf, "Steam"));

            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(@"Software\Valve\Steam"))
                {
                    if (key != null)
                    {
                        string sp = key.GetValue("SteamPath") as string;
                        if (!string.IsNullOrEmpty(sp)) steamDirs.Add(sp.Replace('/', '\\'));
                    }
                }
            }
            catch { }

            foreach (string sdir in steamDirs)
            {
                try
                {
                    string userdata = Path.Combine(sdir, "userdata");
                    if (Directory.Exists(userdata))
                    {
                        string[] userDirs = Directory.GetDirectories(userdata);
                        Array.Sort(userDirs, StringComparer.OrdinalIgnoreCase);
                        foreach (string userDir in userDirs)
                        {
                            string remote = Path.Combine(userDir, "377530", "remote");
                            if (Directory.Exists(remote) && IsSafeDiscoveredRoot(remote)) AddUniquePath(roots, Path.GetFullPath(remote));
                        }
                    }

                    string cfgSave = Path.Combine(sdir, "steamapps", "common", "Tale of Wuxia", "Config", "SaveData");
                    if (Directory.Exists(cfgSave) && IsSafeDiscoveredRoot(cfgSave)) AddUniquePath(roots, Path.GetFullPath(cfgSave));
                }
                catch { }
            }

            return roots;
        }

        private static void AddUniquePath(List<string> list, string path)
        {
            foreach (string existing in list)
            {
                if (string.Equals(existing, path, StringComparison.OrdinalIgnoreCase)) return;
            }
            list.Add(path);
        }

        private static bool IsSafeDiscoveredRoot(string candidate)
        {
            if (string.IsNullOrEmpty(candidate)) return false;
            try { FileId fid = CaptureRootIdentity(candidate); return fid.IsValid; } catch { return false; }
        }

        private static bool TryResolveExistingRoot(string root, FileId expectedRootId, out string rootFull)
        {
            rootFull = null;
            if (string.IsNullOrEmpty(root))
            {
                if (expectedRootId.IsValid) throw new InvalidOperationException("ROOT_IDENTITY_CHANGED");
                return false;
            }

            try { rootFull = Path.GetFullPath(root); }
            catch
            {
                if (expectedRootId.IsValid) throw;
                return false;
            }

            CheckNoReparseInAncestors(rootFull);

            string rootTrim = rootFull.TrimEnd('\\');
            string openRoot = (rootTrim.Length == 2 && rootTrim[1] == ':') ? (rootTrim + "\\") : rootTrim;
            if (!Directory.Exists(openRoot) && !IsReparsePoint(openRoot, true))
            {
                if (expectedRootId.IsValid) throw new InvalidOperationException("ROOT_IDENTITY_CHANGED");
                return false;
            }

            return true;
        }

        public static List<SaveSlotInfo> ListSlots(string root)
        {
            return ListSlots(root, default(FileId));
        }

        public static List<SaveSlotInfo> ListSlots(string root, FileId expectedRootId)
        {
            lock (StoreLock)
            {
                var result = new List<SaveSlotInfo>();
                string rootFull;
                if (!TryResolveExistingRoot(root, expectedRootId, out rootFull))
                    return result;

                using (PinnedRootLock rootLock = new PinnedRootLock(root, false, expectedRootId))
                {
                    string[] files;
                    try { files = Directory.GetFiles(rootFull, "*", SearchOption.TopDirectoryOnly); }
                    catch { return result; }

                    Array.Sort(files, delegate(string a, string b)
                    {
                        return StringComparer.Ordinal.Compare(Path.GetFileName(a), Path.GetFileName(b));
                    });

                    var lowerCounts = new Dictionary<string, int>(StringComparer.Ordinal);
                    for (int i = 0; i < files.Length; i++)
                    {
                        try
                        {
                            if (IsReparsePoint(files[i], false)) continue;
                            string ln = Path.GetFileName(files[i]).ToLowerInvariant();
                            int c;
                            if (lowerCounts.TryGetValue(ln, out c))
                                lowerCounts[ln] = c + 1;
                            else
                                lowerCounts[ln] = 1;
                        }
                        catch { }
                    }

                    foreach (string file in files)
                    {
                        try
                        {
                            if (IsReparsePoint(file, false)) continue;
                            string name = Path.GetFileName(file);
                            int nameCount;
                            if (lowerCounts.TryGetValue(name.ToLowerInvariant(), out nameCount) && nameCount > 1)
                                continue;

                            string kind = null;
                            string label = null;
                            Match m;

                            if ((m = ManualSaveRegex.Match(name)).Success)
                            {
                                int idx = int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
                                if (idx >= 0 && idx < 20)
                                {
                                    kind = "save";
                                    label = string.Format("\uC218\uB3D9 \uC2AC\uB86F {0} ({1})", idx + 1, name);
                                }
                            }
                            else if ((m = AutoSaveRegex.Match(name)).Success)
                            {
                                int idx = int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
                                if (idx >= 0 && idx < 20)
                                {
                                    kind = "save";
                                    label = string.Format("\uD544\uB4DC \uC790\uB3D9 \uC800\uC7A5 {0} ({1})", idx + 1, name);
                                }
                            }
                            else if ((m = AutoDSaveRegex.Match(name)).Success)
                            {
                                int idx = int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
                                if (idx >= 0 && idx < 20)
                                {
                                    kind = "save";
                                    label = string.Format("\uC721\uC131 \uC790\uB3D9 \uC800\uC7A5 {0} ({1})", idx + 1, name);
                                }
                            }
                            else if (string.Equals(name, "Round.dat", StringComparison.Ordinal))
                            {
                                kind = "round";
                                label = "\uC804\uC5ED \uC5C5\uC801 \u00B7 \uB2E4\uD68C\uCC28 \uAE30\uB85D (Round.dat)";
                            }
                            else if (GuidFileRegex.IsMatch(name))
                            {
                                kind = "guid";
                                label = string.Format("\uD68C\uCC28 \uACE0\uC720 \uAE30\uB85D ({0}\u2026)", name.Substring(0, 8));
                            }

                            if (kind == null) continue;
                            var fi = new FileInfo(file);
                            if (fi.Length > MaxSaveBytes) continue;
                            byte[] bytes;
                            using (PinnedDirectoryChain pin = PinnedDirectoryChain.Acquire(rootFull, fi.FullName, false, rootLock.RootId))
                            {
                                bytes = ReadVerifiedBytes(pin, fi.FullName);
                            }
                            result.Add(new SaveSlotInfo
                            {
                                FileName = name,
                                FullPath = fi.FullName,
                                Kind = kind,
                                SlotName = label,
                                Summary = label,
                                SizeBytes = bytes.Length,
                                LastWriteUtc = fi.LastWriteTimeUtc,
                                Sha256 = Sha256Hex(bytes)
                            });
                        }
                        catch (Exception ex)
                        {
                            if (ex.Message == "ROOT_IDENTITY_CHANGED")
                                throw;
                        }
                    }

                    return result;
                }
            }
        }

        private static void Check(bool cond, string msg)
        {
            if (!cond) throw new InvalidDataException(msg);
        }

        private static bool TryGetExactLong(object raw, out long val)
        {
            val = 0L;
            if (raw == null || raw is bool) return false;
            if (raw is int) { val = (int)raw; return true; }
            if (raw is long) { val = (long)raw; return true; }
            if (raw is decimal)
            {
                decimal dec = (decimal)raw;
                if (decimal.Truncate(dec) != dec || dec < long.MinValue || dec > long.MaxValue) return false;
                if (dec == 0m && (decimal.GetBits(dec)[3] & unchecked((int)0x80000000)) != 0) return false;
                val = (long)dec;
                return true;
            }
            if (raw is double)
            {
                double dbl = (double)raw;
                if (double.IsNaN(dbl) || double.IsInfinity(dbl) || Math.Truncate(dbl) != dbl) return false;
                if (dbl == 0.0 && BitConverter.DoubleToInt64Bits(dbl) < 0L) return false;
                if (dbl < -9007199254740991.0 || dbl > 9007199254740991.0) return false;
                val = (long)dbl;
                return true;
            }
            return false;
        }

        private static long ReqInt(Dictionary<string, object> dict, string key, long min, long max)
        {
            object raw = null;
            Check(dict != null && dict.TryGetValue(key, out raw) && raw != null, "MISSING_" + key);
            Check(!(raw is bool), "BOOL_NOT_INT_" + key);
            long val;
            if (!TryGetExactLong(raw, out val))
                throw new InvalidDataException("NOT_INTEGER_" + key);
            Check(val >= min && val <= max, "RANGE_" + key);
            return val;
        }

        private static string ReqString(Dictionary<string, object> dict, string key, bool nonEmpty)
        {
            object raw = null;
            Check(dict != null && dict.TryGetValue(key, out raw) && raw is string, "NOT_STRING_" + key);
            string s = (string)raw;
            Check(!nonEmpty || s.Length > 0, "EMPTY_" + key);
            return s;
        }

        private static object[] ReqArray(Dictionary<string, object> dict, string key)
        {
            object raw = null;
            Check(dict != null && dict.TryGetValue(key, out raw) && raw != null, "MISSING_ARRAY_" + key);
            return AsObjectArray(raw, key);
        }

        private static object[] AsObjectArray(object raw, string label)
        {
            var arr = raw as object[];
            if (arr != null) return arr;
            var list = raw as IList;
            if (list != null)
            {
                var copy = new object[list.Count];
                list.CopyTo(copy, 0);
                return copy;
            }
            throw new InvalidDataException("NOT_ARRAY_" + label);
        }

        private static string StripLeadingBom(string s, out bool hadLeadingBom)
        {
            hadLeadingBom = !string.IsNullOrEmpty(s) && s[0] == '\uFEFF';
            string clean = hadLeadingBom ? s.Substring(1) : (s ?? "");
            if (clean.Length > 0 && clean[0] == '\uFEFF')
                throw new InvalidDataException("DOUBLE_UTF8_BOM");
            return clean;
        }

        private const int MaxJsonNestingDepth = 128;
        private const byte ContainerObject = 1;
        private const byte ContainerArray = 2;
        private const int StateExpectValue = 0;
        private const int StateExpectObjectKeyOrEnd = 1;
        private const int StateExpectObjectKey = 2;
        private const int StateExpectArrayValueOrEnd = 3;
        private const int StateAfterValue = 4;

        private static void AssertStrictJsonSyntax(string text)
        {
            if (text == null) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
            int i = 0;
            SkipStrictJsonWhitespace(text, ref i);
            if (i >= text.Length) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");

            byte[] stack = new byte[MaxJsonNestingDepth];
            int depth = 0;
            int state = StateExpectValue;

            while (true)
            {
                if (state == StateExpectValue)
                {
                    SkipStrictJsonWhitespace(text, ref i);
                    if (i >= text.Length) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");

                    char c = text[i];
                    if (c == '{')
                    {
                        if (depth >= MaxJsonNestingDepth) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                        stack[depth++] = ContainerObject;
                        i++;
                        state = StateExpectObjectKeyOrEnd;
                    }
                    else if (c == '[')
                    {
                        if (depth >= MaxJsonNestingDepth) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                        stack[depth++] = ContainerArray;
                        i++;
                        state = StateExpectArrayValueOrEnd;
                    }
                    else if (c == '"')
                    {
                        ScanStrictJsonString(text, ref i);
                        state = StateAfterValue;
                    }
                    else if (c == 't')
                    {
                        if (i + 4 > text.Length || text[i + 1] != 'r' || text[i + 2] != 'u' || text[i + 3] != 'e') throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                        i += 4;
                        state = StateAfterValue;
                    }
                    else if (c == 'f')
                    {
                        if (i + 5 > text.Length || text[i + 1] != 'a' || text[i + 2] != 'l' || text[i + 3] != 's' || text[i + 4] != 'e') throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                        i += 5;
                        state = StateAfterValue;
                    }
                    else if (c == 'n')
                    {
                        if (i + 4 > text.Length || text[i + 1] != 'u' || text[i + 2] != 'l' || text[i + 3] != 'l') throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                        i += 4;
                        state = StateAfterValue;
                    }
                    else if (c == '-' || (c >= '0' && c <= '9'))
                    {
                        ScanStrictJsonNumber(text, ref i);
                        state = StateAfterValue;
                    }
                    else
                    {
                        throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                    }
                }
                else if (state == StateExpectObjectKeyOrEnd)
                {
                    SkipStrictJsonWhitespace(text, ref i);
                    if (i >= text.Length) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                    if (text[i] == '}')
                    {
                        i++;
                        depth--;
                        state = StateAfterValue;
                    }
                    else if (text[i] == '"')
                    {
                        ScanStrictJsonString(text, ref i);
                        SkipStrictJsonWhitespace(text, ref i);
                        if (i >= text.Length || text[i] != ':') throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                        i++;
                        state = StateExpectValue;
                    }
                    else
                    {
                        throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                    }
                }
                else if (state == StateExpectObjectKey)
                {
                    SkipStrictJsonWhitespace(text, ref i);
                    if (i >= text.Length || text[i] != '"') throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                    ScanStrictJsonString(text, ref i);
                    SkipStrictJsonWhitespace(text, ref i);
                    if (i >= text.Length || text[i] != ':') throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                    i++;
                    state = StateExpectValue;
                }
                else if (state == StateExpectArrayValueOrEnd)
                {
                    SkipStrictJsonWhitespace(text, ref i);
                    if (i >= text.Length) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                    if (text[i] == ']')
                    {
                        i++;
                        depth--;
                        state = StateAfterValue;
                    }
                    else
                    {
                        state = StateExpectValue;
                    }
                }
                else if (state == StateAfterValue)
                {
                    SkipStrictJsonWhitespace(text, ref i);
                    if (depth == 0)
                    {
                        if (i != text.Length) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                        return;
                    }
                    if (i >= text.Length) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");

                    char c = text[i];
                    if (c == ',')
                    {
                        if (stack[depth - 1] == ContainerObject)
                        {
                            i++;
                            state = StateExpectObjectKey;
                        }
                        else
                        {
                            i++;
                            state = StateExpectValue;
                        }
                    }
                    else if (c == '}')
                    {
                        if (stack[depth - 1] != ContainerObject) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                        i++;
                        depth--;
                        state = StateAfterValue;
                    }
                    else if (c == ']')
                    {
                        if (stack[depth - 1] != ContainerArray) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                        i++;
                        depth--;
                        state = StateAfterValue;
                    }
                    else
                    {
                        throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                    }
                }
                else
                {
                    throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                }
            }
        }

        private static void SkipStrictJsonWhitespace(string text, ref int i)
        {
            while (i < text.Length && IsJsonWhitespace(text[i])) i++;
        }

        private static void ScanStrictJsonString(string text, ref int i)
        {
            if (i >= text.Length || text[i] != '"') throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
            i++;
            while (i < text.Length)
            {
                char c = text[i];
                if (c == '"')
                {
                    i++;
                    return;
                }
                if (c < 0x20) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                if (c == '\\')
                {
                    i++;
                    if (i >= text.Length) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                    char e = text[i];
                    if (e == '"' || e == '\\' || e == '/' || e == 'b' || e == 'f' || e == 'n' || e == 'r' || e == 't')
                    {
                        i++;
                    }
                    else if (e == 'u')
                    {
                        int codeUnit = TryReadJsonHex4(text, i + 1);
                        if (codeUnit < 0) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                        i += 5;
                        if (codeUnit >= 0xD800 && codeUnit <= 0xDBFF)
                        {
                            if (i + 6 > text.Length || text[i] != '\\' || text[i + 1] != 'u') throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                            int low = TryReadJsonHex4(text, i + 2);
                            if (low < 0xDC00 || low > 0xDFFF) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                            i += 6;
                        }
                        else if (codeUnit >= 0xDC00 && codeUnit <= 0xDFFF)
                        {
                            throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                        }
                    }
                    else
                    {
                        throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                    }
                }
                else if (c >= 0xD800 && c <= 0xDBFF)
                {
                    if (i + 1 >= text.Length || text[i + 1] < 0xDC00 || text[i + 1] > 0xDFFF)
                        throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                    i += 2;
                }
                else if (c >= 0xDC00 && c <= 0xDFFF)
                {
                    throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                }
                else
                {
                    i++;
                }
            }
            throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
        }

        private static void ScanStrictJsonNumber(string text, ref int i)
        {
            int start = i;
            if (text[i] == '-')
            {
                i++;
                if (i >= text.Length) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
            }

            if (text[i] == '0')
            {
                i++;
                if (i < text.Length && ((text[i] >= '0' && text[i] <= '9') || text[i] == 'x' || text[i] == 'X'))
                {
                    throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                }
            }
            else if (text[i] >= '1' && text[i] <= '9')
            {
                i++;
                while (i < text.Length && text[i] >= '0' && text[i] <= '9') i++;
            }
            else
            {
                throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
            }

            if (i < text.Length && text[i] == '.')
            {
                i++;
                if (i >= text.Length || text[i] < '0' || text[i] > '9') throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                while (i < text.Length && text[i] >= '0' && text[i] <= '9') i++;
            }

            if (i < text.Length && (text[i] == 'e' || text[i] == 'E'))
            {
                i++;
                if (i < text.Length && (text[i] == '+' || text[i] == '-')) i++;
                if (i >= text.Length || text[i] < '0' || text[i] > '9') throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
                while (i < text.Length && text[i] >= '0' && text[i] <= '9') i++;
            }

            if (i == start) throw new InvalidDataException("STRICT_JSON_SYNTAX_ERROR");
        }

        public static string ValidateSaveJson(string jsonText)
        {
            bool hadBom;
            jsonText = StripLeadingBom(jsonText, out hadBom);
            if (string.IsNullOrEmpty(jsonText)) throw new InvalidDataException("EMPTY_JSON");
            AssertStrictJsonSyntax(jsonText);
            if (ContainsUnpairedSurrogate(jsonText) || ContainsUnpairedJsonSurrogateEscape(jsonText)) throw new InvalidDataException("INVALID_UTF8_SURROGATE");
            object parsed;
            try
            {
                var ser = new JavaScriptSerializer { MaxJsonLength = 64 * 1024 * 1024, RecursionLimit = 128 };
                parsed = ser.DeserializeObject(jsonText);
            }
            catch (Exception ex)
            {
                throw new InvalidDataException("INVALID_JSON: " + ex.Message);
            }

            Check(parsed != null, "NULL_JSON_ROOT");
            Check(!ContainsUnpairedSurrogateValue(parsed), "INVALID_UTF8_SURROGATE");

            if (parsed is object[] || parsed is IList)
            {
                object[] titleArr = AsObjectArray(parsed, "title");
                Check(titleArr.Length >= 1 && titleArr.Length <= 20, "INVALID_TITLE_LENGTH");
                for (int i = 0; i < titleArr.Length; i++)
                {
                    var item = titleArr[i] as Dictionary<string, object>;
                    object haveData = null;
                    Check(item != null && item.TryGetValue("m_bHaveData", out haveData) && haveData is bool, "INVALID_TITLE_ENTRY");
                }
                return "title";
            }

            var root = parsed as Dictionary<string, object>;
            Check(root != null, "ROOT_MUST_BE_OBJECT");

            bool isSave = root.ContainsKey("m_PropertyGroupsNodeList") || root.ContainsKey("m_strPlayerName") || root.ContainsKey("m_BackpackList");
            bool isRound = root.ContainsKey("achiFinishList") || root.ContainsKey("finishGuidList") || root.ContainsKey("iMasterLevelCount");
            bool isGuid = root.ContainsKey("guid") && (root.ContainsKey("openTalentList") || root.ContainsKey("openChestList") || root.ContainsKey("developQuestList"));

            if (isSave)
            {
                ReqInt(root, "m_iMoney", 0, 999999999);
                ReqInt(root, "m_iYear", 1, 20);
                ReqInt(root, "m_iMonth", 1, 12);
                ReqInt(root, "m_iMonthInterval", 0, 4);
                ReqInt(root, "m_iNowTime", 1, 12);
                ReqInt(root, "m_iPhysical", 0, 999);
                ReqInt(root, "m_iMood", 0, 999);
                if (root.ContainsKey("m_iBattleDifficulty"))
                    ReqInt(root, "m_iBattleDifficulty", 0, 3);
                ReqString(root, "m_strPlayerName", false);
                ReqString(root, "m_strPlayerLastName", false);

                object[] groups = ReqArray(root, "m_PropertyGroupsNodeList");
                for (int i = 0; i < groups.Length; i++)
                {
                    var g = groups[i] as Dictionary<string, object>;
                    Check(g != null, "INVALID_PROPERTY_GROUP");
                    ReqInt(g, "m_iType", 0, 99);
                    object[] nodes = ReqArray(g, "m_GroupsNodwList");
                    for (int j = 0; j < nodes.Length; j++)
                    {
                        var n = nodes[j] as Dictionary<string, object>;
                        Check(n != null, "INVALID_PROPERTY_NODE");
                        ReqInt(n, "m_iValue", 0, long.MaxValue);
                        ReqInt(n, "m_iIndex", 0, long.MaxValue);
                        ReqInt(n, "m_iExp", 0, long.MaxValue);
                        ReqInt(n, "m_iMax", 0, long.MaxValue);
                    }
                }

                object[] routines = ReqArray(root, "m_PlayerRoutineNodeList");
                for (int i = 0; i < routines.Length; i++)
                {
                    var r = routines[i] as Dictionary<string, object>;
                    Check(r != null, "INVALID_ROUTINE_NODE");
                    ReqInt(r, "m_iRoutineID", 1, long.MaxValue);
                    ReqInt(r, "m_iLV", 1, 10);
                    ReqInt(r, "m_iAccumulationExp", 0, long.MaxValue);
                }

                object[] neigongs = ReqArray(root, "m_PlayerNeigongNodeList");
                for (int i = 0; i < neigongs.Length; i++)
                {
                    var ng = neigongs[i] as Dictionary<string, object>;
                    Check(ng != null, "INVALID_NEIGONG_NODE");
                    ReqInt(ng, "m_iNeigongID", 1, long.MaxValue);
                    ReqInt(ng, "m_iLV", 1, 10);
                    ReqInt(ng, "m_iAccumulationExp", 0, long.MaxValue);
                }

                object[] backpack = ReqArray(root, "m_BackpackList");
                for (int i = 0; i < backpack.Length; i++)
                {
                    var bp = backpack[i] as Dictionary<string, object>;
                    Check(bp != null, "INVALID_BACKPACK_NODE");
                    ReqInt(bp, "m_iAmount", 1, long.MaxValue);
                    object itemRaw = null;
                    Check(bp.TryGetValue("_ItemDataNode", out itemRaw) && itemRaw is Dictionary<string, object>, "MISSING_ITEM_DATA_NODE");
                    var itemNode = (Dictionary<string, object>)itemRaw;
                    ReqInt(itemNode, "m_iItemID", 1, long.MaxValue);
                    ReqArray(itemNode, "m_ItmeEffectNodeList");
                }

                object[] friendly = ReqArray(root, "m_NpcFriendlyNodeList");
                for (int i = 0; i < friendly.Length; i++)
                {
                    var fn = friendly[i] as Dictionary<string, object>;
                    Check(fn != null, "INVALID_FRIENDLY_NODE");
                    ReqInt(fn, "m_iNpcID", 1, long.MaxValue);
                    ReqInt(fn, "m_iFriendly", -1, 999);
                }

                if (root.ContainsKey("m_teamMemberList"))
                {
                    object[] team = ReqArray(root, "m_teamMemberList");
                    Check(team.Length <= 9, "TEAM_LIMIT_EXCEEDED");
                    for (int i = 0; i < team.Length; i++)
                    {
                        long teamId;
                        bool ok = TryGetExactLong(team[i], out teamId) && teamId >= 1L;
                        Check(ok, "TEAM_MEMBER_INVALID_" + i.ToString(CultureInfo.InvariantCulture));
                    }
                }

                return "save";
            }

            if (isRound)
            {
                ReqInt(root, "iMasterLevelCount", 0, long.MaxValue);
                ReqInt(root, "iProLevelCount", 0, long.MaxValue);
                ReqInt(root, "iNormalLevelCount", 0, long.MaxValue);
                ReqInt(root, "iStartBegger", 0, long.MaxValue);
                ReqArray(root, "achiFinishList");
                object[] counts = ReqArray(root, "achiCountList");
                for (int i = 0; i < counts.Length; i++)
                {
                    var cn = counts[i] as Dictionary<string, object>;
                    Check(cn != null, "INVALID_ACHI_COUNT");
                    ReqInt(cn, "m_iID", 1, long.MaxValue);
                    ReqInt(cn, "m_iNow", 0, long.MaxValue);
                }
                return "round";
            }

            if (isGuid)
            {
                ReqString(root, "guid", true);
                ReqInt(root, "iDifficulty", 0, 3);
                ReqArray(root, "openTalentList");
                ReqArray(root, "openChestList");
                return "guid";
            }

            throw new InvalidDataException("UNKNOWN_SCHEMA");
        }

        private static bool IsReservedSegment(string segment)
        {
            if (string.IsNullOrEmpty(segment)) return false;
            string trimmed = segment.TrimEnd(' ', '.');
            int dot = trimmed.IndexOf('.');
            string stem = dot >= 0 ? trimmed.Substring(0, dot) : trimmed;
            return ReservedDevices.Contains(stem);
        }

        public static string ResolveSafePath(string root, string path)
        {
            if (string.IsNullOrEmpty(root)) throw new ArgumentException("ROOT_EMPTY");
            if (string.IsNullOrEmpty(path)) throw new ArgumentException("PATH_EMPTY");
            for (int i = 0; i < path.Length; i++)
            {
                if (path[i] < 32) throw new ArgumentException("CONTROL_CHAR_REJECTED");
            }
            if (path.IndexOf(':') >= 0) throw new ArgumentException("ADS_OR_DRIVE_COLON_REJECTED");
            if (path.StartsWith("/", StringComparison.Ordinal) || path.StartsWith("\\", StringComparison.Ordinal) || Path.IsPathRooted(path))
                throw new ArgumentException("ABSOLUTE_PATH_REJECTED");

            string[] segs = path.Replace('/', '\\').Split('\\');
            for (int i = 0; i < segs.Length; i++)
            {
                string s = segs[i];
                if (s.Length == 0 || s == "." || s == "..")
                    throw new ArgumentException("TRAVERSAL_SEGMENT_REJECTED");
                if (s.StartsWith(".", StringComparison.Ordinal))
                    throw new ArgumentException("DOTFILE_SEGMENT_REJECTED");
                if (s[s.Length - 1] == ' ' || s[s.Length - 1] == '.')
                    throw new ArgumentException("TRAILING_DOT_OR_SPACE_REJECTED");
                if (IsReservedSegment(s))
                    throw new ArgumentException("RESERVED_DEVICE_NAME: " + s);
            }

            string rootFull = Path.GetFullPath(root);
            string rootSep = rootFull.EndsWith(Path.DirectorySeparatorChar.ToString(), StringComparison.Ordinal)
                ? rootFull
                : rootFull + Path.DirectorySeparatorChar;

            string combined = rootSep + string.Join("\\", segs);
            string checkedFull = Path.GetFullPath(combined);
            if (!checkedFull.StartsWith(rootSep, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(checkedFull, rootFull, StringComparison.OrdinalIgnoreCase))
            {
                throw new ArgumentException("PATH_OUTSIDE_ROOT");
            }
            return combined;
        }

        private static string StripLongPrefix(string p)
        {
            if (p.StartsWith(@"\\?\", StringComparison.Ordinal)) return p.Substring(4);
            if (p.StartsWith(@"\??\", StringComparison.Ordinal)) return p.Substring(4);
            return p;
        }

        private static bool IsReparsePoint(string path, bool isDir)
        {
            uint flags = FILE_FLAG_OPEN_REPARSE_POINT | (isDir ? FILE_FLAG_BACKUP_SEMANTICS : 0u);
            IntPtr h = CreateFileW(path, 0, FILE_SHARE_ALL, IntPtr.Zero, OPEN_EXISTING, flags, IntPtr.Zero);
            if (h == INVALID_HANDLE_VALUE) return false;
            try
            {
                BY_HANDLE_FILE_INFORMATION bi;
                if (!GetFileInformationByHandle(h, out bi)) return false;
                return (bi.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0;
            }
            finally { CloseHandle(h); }
        }

        private static string ReadFinalPathByHandle(IntPtr h)
        {
            StringBuilder sb = new StringBuilder(1024);
            uint len = GetFinalPathNameByHandleW(h, sb, sb.Capacity, 0);
            while (len >= (uint)sb.Capacity)
            {
                int newCap = (int)len + 2;
                if (newCap <= sb.Capacity)
                    throw new InvalidOperationException("CANON_PATH_FAILED");
                sb = new StringBuilder(newCap);
                len = GetFinalPathNameByHandleW(h, sb, sb.Capacity, 0);
            }
            if (len == 0)
                throw new InvalidOperationException("CANON_PATH_FAILED");

            string rawFinal = sb.ToString(0, (int)len);
            if (rawFinal.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("UNC_PATH_REJECTED");

            return StripLongPrefix(rawFinal);
        }

        private static string GetCanonicalPath(string path, bool isDir)
        {
            uint flags = FILE_FLAG_OPEN_REPARSE_POINT | (isDir ? FILE_FLAG_BACKUP_SEMANTICS : 0u);
            IntPtr h = CreateFileW(path, 0, FILE_SHARE_ALL, IntPtr.Zero, OPEN_EXISTING, flags, IntPtr.Zero);
            if (h == INVALID_HANDLE_VALUE) throw new InvalidOperationException("OPEN_CANON_FAILED");
            try
            {
                BY_HANDLE_FILE_INFORMATION bi;
                if (!GetFileInformationByHandle(h, out bi)) throw new InvalidOperationException("INFO_CANON_FAILED");
                if ((bi.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                    throw new InvalidOperationException("REPARSE_POINT_REJECTED");

                return ReadFinalPathByHandle(h);
            }
            finally { CloseHandle(h); }
        }

        private static void CheckNoReparseInAncestors(string dirFull)
        {
            if (string.IsNullOrEmpty(dirFull))
                throw new ArgumentException("ROOT_EMPTY");

            string cur = Path.GetFullPath(dirFull).TrimEnd('\\');
            while (!string.IsNullOrEmpty(cur))
            {
                bool isDriveRoot = (cur.Length == 2 && cur[1] == ':');
                string checkPath = isDriveRoot ? (cur + "\\") : cur;
                if (Directory.Exists(checkPath) || IsReparsePoint(checkPath, true))
                {
                    WinCheckDirectory(checkPath);
                }
                if (isDriveRoot)
                    break;

                string parent = Path.GetDirectoryName(cur);
                if (string.IsNullOrEmpty(parent))
                    break;
                string next = parent.TrimEnd('\\');
                if (string.Equals(next, cur, StringComparison.OrdinalIgnoreCase))
                    break;
                cur = next;
            }
        }

        private static bool IsUncLikePath(string path)
        {
            if (string.IsNullOrEmpty(path))
                return false;
            if (path.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase))
                return true;
            if (path.StartsWith(@"\??\UNC\", StringComparison.OrdinalIgnoreCase))
                return true;
            return path.Length >= 2 && path[0] == '\\' && path[1] == '\\';
        }

        private static bool IsAsciiLetter(char ch)
        {
            return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z');
        }

        private static string GetDrivePrefix(string path)
        {
            if (string.IsNullOrEmpty(path) || path.Length < 2 || !IsAsciiLetter(path[0]) || path[1] != ':')
                throw new ArgumentException("INVALID_ROOT_PATH");
            return path.Substring(0, 2);
        }

        private static IntPtr OpenChainedRootDirectory(
            string rootInput,
            bool createDir,
            FileId expectedRootId,
            out FileId rootId,
            out string rootCanon)
        {
            rootId = default(FileId);
            rootCanon = "";

            if (string.IsNullOrEmpty(rootInput))
                throw new ArgumentException("ROOT_EMPTY");

            for (int i = 0; i < rootInput.Length; i++)
            {
                char ch = rootInput[i];
                if (ch < 32 || ch == '"' || ch == '|' || ch == '*' || ch == '?' || ch == '<' || ch == '>')
                    throw new ArgumentException("INVALID_ROOT_PATH");
            }

            string normalized = rootInput.Replace('/', '\\');
            if (IsUncLikePath(normalized))
                throw new InvalidOperationException("UNC_PATH_REJECTED");

            if (normalized.StartsWith(@"\\?\", StringComparison.Ordinal) ||
                normalized.StartsWith(@"\??\", StringComparison.Ordinal))
            {
                normalized = normalized.Substring(4);
            }

            if (IsUncLikePath(normalized))
                throw new InvalidOperationException("UNC_PATH_REJECTED");

            if (normalized.Length == 0)
                throw new ArgumentException("ROOT_EMPTY");

            for (int i = 0; i < normalized.Length; i++)
            {
                if (normalized[i] == ':')
                {
                    if (i != 1 || normalized.Length < 2 || !IsAsciiLetter(normalized[0]))
                        throw new ArgumentException("ADS_OR_DRIVE_COLON_REJECTED");
                }
            }

            string working = normalized;
            if (working.Length >= 3 && IsAsciiLetter(working[0]) && working[1] == ':' && working[2] == '\\')
            {
                // Already drive-rooted (X:\...)
            }
            else if (working.Length >= 1 && working[0] == '\\')
            {
                string cwd = Directory.GetCurrentDirectory();
                working = GetDrivePrefix(cwd) + working;
            }
            else if (working.Length >= 2 && IsAsciiLetter(working[0]) && working[1] == ':')
            {
                string drivePrefix = working.Substring(0, 2);
                string currentForDrive = Path.GetFullPath(drivePrefix + ".").TrimEnd('\\');
                string rest = working.Substring(2);
                if (rest.Length == 0)
                    working = (currentForDrive.Length == 2 && currentForDrive[1] == ':') ? (currentForDrive + "\\") : currentForDrive;
                else
                    working = currentForDrive + "\\" + rest.TrimStart('\\');
            }
            else
            {
                string cwd = Directory.GetCurrentDirectory().TrimEnd('\\');
                string rel = working.TrimStart('\\');
                working = cwd + "\\" + rel;
            }

            if (working.Length < 3 || !IsAsciiLetter(working[0]) || working[1] != ':' || working[2] != '\\')
                throw new ArgumentException("INVALID_ROOT_PATH");

            string driveRoot = working.Substring(0, 3);
            string remaining = working.Substring(3);
            string[] segments = remaining.Split(new char[] { '\\' }, StringSplitOptions.RemoveEmptyEntries);

            for (int i = 0; i < segments.Length; i++)
            {
                string seg = segments[i];
                if (seg.Length == 0)
                    throw new ArgumentException("INVALID_ROOT_PATH");
                if (seg == "." || seg == "..")
                    throw new ArgumentException("TRAVERSAL_SEGMENT_REJECTED");
                char last = seg[seg.Length - 1];
                if (last == ' ' || last == '.')
                    throw new ArgumentException("TRAILING_DOT_OR_SPACE_REJECTED");
            }

            IntPtr prevH = INVALID_HANDLE_VALUE;
            bool success = false;
            try
            {
                prevH = CreateFileW(
                    driveRoot,
                    GENERIC_READ,
                    FILE_SHARE_READ_WRITE,
                    IntPtr.Zero,
                    OPEN_EXISTING,
                    FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
                    IntPtr.Zero);
                if (prevH == INVALID_HANDLE_VALUE)
                    throw new InvalidOperationException("OPEN_DIR_FAILED");

                BY_HANDLE_FILE_INFORMATION curBi;
                if (!GetFileInformationByHandle(prevH, out curBi))
                    throw new InvalidOperationException("INFO_DIR_FAILED");
                if ((curBi.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                    throw new InvalidOperationException("REPARSE_POINT_REJECTED");
                if ((curBi.FileAttributes & 0x10u) == 0)
                    throw new InvalidOperationException("NOT_DIRECTORY");

                string curCanon = ReadFinalPathByHandle(prevH).TrimEnd('\\');
                if (curCanon.Length == 0)
                    throw new InvalidOperationException("CANON_PATH_FAILED");

                for (int i = 0; i < segments.Length; i++)
                {
                    string seg = segments[i];
                    string listDir = (curCanon.Length == 2 && curCanon[1] == ':') ? (curCanon + "\\") : curCanon;
                    string nextPath = curCanon + "\\" + seg;

                    bool foundExact = false;
                    string[] entries = Directory.GetFileSystemEntries(listDir);
                    for (int j = 0; j < entries.Length; j++)
                    {
                        string leaf = Path.GetFileName(entries[j]);
                        if (string.Equals(leaf, seg, StringComparison.Ordinal))
                            foundExact = true;
                        else if (string.Equals(leaf, seg, StringComparison.OrdinalIgnoreCase))
                            throw new InvalidOperationException("CASE_COLLISION_REJECTED");
                    }

                    if (!foundExact)
                    {
                        if (File.Exists(nextPath) ||
                            Directory.Exists(nextPath) ||
                            IsReparsePoint(nextPath, false) ||
                            IsReparsePoint(nextPath, true))
                        {
                            throw new InvalidOperationException("ALIAS_NAME_REJECTED");
                        }
                        if (expectedRootId.IsValid)
                            throw new InvalidOperationException("ROOT_IDENTITY_CHANGED");
                        if (!createDir)
                            throw new DirectoryNotFoundException("DIR_NOT_FOUND");
                        Directory.CreateDirectory(nextPath);
                    }

                    IntPtr nextH = CreateFileW(
                        nextPath,
                        GENERIC_READ,
                        FILE_SHARE_READ_WRITE,
                        IntPtr.Zero,
                        OPEN_EXISTING,
                        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
                        IntPtr.Zero);
                    if (nextH == INVALID_HANDLE_VALUE)
                        throw new InvalidOperationException("OPEN_DIR_FAILED");

                    bool transferred = false;
                    try
                    {
                        BY_HANDLE_FILE_INFORMATION nextBi;
                        if (!GetFileInformationByHandle(nextH, out nextBi))
                            throw new InvalidOperationException("INFO_DIR_FAILED");
                        if ((nextBi.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                            throw new InvalidOperationException("REPARSE_POINT_REJECTED");
                        if ((nextBi.FileAttributes & 0x10u) == 0)
                            throw new InvalidOperationException("NOT_DIRECTORY");

                        string nextCanon = ReadFinalPathByHandle(nextH).TrimEnd('\\');
                        if (!nextCanon.StartsWith(curCanon + "\\", StringComparison.OrdinalIgnoreCase))
                            throw new InvalidOperationException("CANONICAL_PARENT_MISMATCH");

                        string actualLeaf = Path.GetFileName(nextCanon);
                        if (!string.Equals(actualLeaf, seg, StringComparison.Ordinal))
                        {
                            if (string.Equals(actualLeaf, seg, StringComparison.OrdinalIgnoreCase))
                                throw new InvalidOperationException("CASE_COLLISION_REJECTED");
                            throw new InvalidOperationException("ALIAS_NAME_REJECTED");
                        }

                        CloseHandle(prevH);
                        prevH = nextH;
                        transferred = true;
                        curBi = nextBi;
                        curCanon = nextCanon;
                    }
                    finally
                    {
                        if (!transferred)
                            CloseHandle(nextH);
                    }
                }

                FileId rid = new FileId();
                rid.VolumeSerialNumber = curBi.VolumeSerialNumber;
                rid.FileIndexHigh = curBi.FileIndexHigh;
                rid.FileIndexLow = curBi.FileIndexLow;
                rid.IsValid = true;

                if (expectedRootId.IsValid && !rid.EqualsId(expectedRootId))
                    throw new InvalidOperationException("ROOT_IDENTITY_CHANGED");

                rootId = rid;
                rootCanon = curCanon;
                IntPtr ret = prevH;
                prevH = INVALID_HANDLE_VALUE;
                success = true;
                return ret;
            }
            finally
            {
                if (!success && prevH != INVALID_HANDLE_VALUE && prevH != IntPtr.Zero)
                    CloseHandle(prevH);
            }
        }

        public static FileId CaptureRootIdentity(string root)
        {
            string rootCanon;
            return OpenRootIdentityCore(root, false, out rootCanon);
        }

        public static FileId EnsureSafeRootDirectory(string root, out string canonicalRoot)
        {
            return OpenRootIdentityCore(root, true, out canonicalRoot);
        }

        private static FileId OpenRootIdentityCore(string root, bool createDir, out string canonicalRoot)
        {
            FileId rootId;
            IntPtr h = OpenChainedRootDirectory(root, createDir, default(FileId), out rootId, out canonicalRoot);
            try
            {
                return rootId;
            }
            finally
            {
                if (h != INVALID_HANDLE_VALUE && h != IntPtr.Zero)
                    CloseHandle(h);
            }
        }

        public static FileId CaptureFileIdentity(string fullPath)
        {
            IntPtr h = CreateFileW(Path.GetFullPath(fullPath), 0, FILE_SHARE_ALL,
                IntPtr.Zero, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, IntPtr.Zero);
            if (h == INVALID_HANDLE_VALUE)
                throw new IOException("OPEN_FILE_FAILED_" + Marshal.GetLastWin32Error().ToString(CultureInfo.InvariantCulture));
            try
            {
                BY_HANDLE_FILE_INFORMATION bi;
                if (!GetFileInformationByHandle(h, out bi))
                    throw new InvalidOperationException("INFO_FILE_FAILED");
                if ((bi.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                    throw new InvalidOperationException("REPARSE_POINT_REJECTED");
                if ((bi.FileAttributes & 0x10u) != 0)
                    throw new InvalidOperationException("IS_DIRECTORY");
                FileId fid;
                fid.VolumeSerialNumber = bi.VolumeSerialNumber;
                fid.FileIndexHigh = bi.FileIndexHigh;
                fid.FileIndexLow = bi.FileIndexLow;
                fid.IsValid = true;
                return fid;
            }
            finally
            {
                CloseHandle(h);
            }
        }

        private static string[] SplitPreservedRelativeSegments(string rootFull, string targetFull, out string fullRoot)
        {
            fullRoot = Path.GetFullPath(rootFull).TrimEnd('\\');
            string checkedTarget = Path.GetFullPath(targetFull).TrimEnd('\\');
            if (string.Equals(checkedTarget, fullRoot, StringComparison.OrdinalIgnoreCase))
                return new string[0];
            if (!checkedTarget.StartsWith(fullRoot + "\\", StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("PATH_OUTSIDE_ROOT");

            string normRoot = rootFull.Replace('/', '\\').TrimEnd('\\');
            string normTarget = targetFull.Replace('/', '\\').TrimEnd('\\');

            string rel;
            if (normTarget.StartsWith(fullRoot + "\\", StringComparison.OrdinalIgnoreCase))
                rel = normTarget.Substring(fullRoot.Length + 1);
            else if (normRoot.Length > 0 && normTarget.StartsWith(normRoot + "\\", StringComparison.OrdinalIgnoreCase))
                rel = normTarget.Substring(normRoot.Length + 1);
            else
                rel = checkedTarget.Substring(fullRoot.Length + 1);

            string[] segs = rel.Split(new char[] { '\\' }, StringSplitOptions.RemoveEmptyEntries);
            for (int i = 0; i < segs.Length; i++)
            {
                if (segs[i] == "." || segs[i] == "..")
                    throw new ArgumentException("TRAVERSAL_SEGMENT_REJECTED");
            }
            return segs;
        }

        public static void AssertNoCaseCollision(string rootFull, string targetFull)
        {
            string fullRoot;
            string[] segs = SplitPreservedRelativeSegments(rootFull, targetFull, out fullRoot);
            if (segs.Length == 0)
                return;

            string curDir = (fullRoot.Length == 2 && fullRoot[1] == ':') ? (fullRoot + "\\") : fullRoot;

            for (int i = 0; i < segs.Length; i++)
            {
                string seg = segs[i];
                if (Directory.Exists(curDir))
                {
                    bool foundExact = false;
                    string[] entries = Directory.GetFileSystemEntries(curDir);
                    for (int j = 0; j < entries.Length; j++)
                    {
                        string e = Path.GetFileName(entries[j]);
                        if (string.Equals(e, seg, StringComparison.Ordinal))
                            foundExact = true;
                        if (string.Equals(e, seg, StringComparison.OrdinalIgnoreCase) &&
                            !string.Equals(e, seg, StringComparison.Ordinal))
                        {
                            throw new InvalidOperationException("CASE_COLLISION_REJECTED");
                        }
                    }

                    string nextPath = Path.Combine(curDir, seg);
                    if (!foundExact && (File.Exists(nextPath) || Directory.Exists(nextPath) || IsReparsePoint(nextPath, false) || IsReparsePoint(nextPath, true)))
                        throw new InvalidOperationException("ALIAS_NAME_REJECTED");
                }
                curDir = Path.Combine(curDir, seg);
            }
        }

        private sealed class PinnedRootLock : IDisposable
        {
            private IntPtr _rootHandle = INVALID_HANDLE_VALUE;
            private FileStream _lockStream;
            private FileId _rootId;
            private string _rootCanon = "";

            public IntPtr RootHandle { get { return _rootHandle; } }
            public FileId RootId { get { return _rootId; } }
            public string RootCanon { get { return _rootCanon; } }

            public PinnedRootLock(string rootFull, bool createDir, FileId expectedRootId)
            {
                try
                {
                    _rootHandle = OpenChainedRootDirectory(rootFull, createDir, expectedRootId, out _rootId, out _rootCanon);

                    string lockPath = _rootCanon + "\\.twx_store.lock";
                    Stopwatch sw = Stopwatch.StartNew();
                    IntPtr lh = INVALID_HANDLE_VALUE;
                    SafeFileHandle lsfh = null;
                    try
                    {
                        while (true)
                        {
                            if (IsReparsePoint(lockPath, false) || IsReparsePoint(lockPath, true) || Directory.Exists(lockPath))
                                throw new InvalidOperationException("REPARSE_POINT_REJECTED");

                            lh = CreateFileW(
                                lockPath,
                                GENERIC_READ | GENERIC_WRITE,
                                0u,
                                IntPtr.Zero,
                                OPEN_ALWAYS,
                                FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
                                IntPtr.Zero);

                            if (lh == INVALID_HANDLE_VALUE)
                            {
                                int err = Marshal.GetLastWin32Error();
                                if (IsReparsePoint(lockPath, false) || IsReparsePoint(lockPath, true) || Directory.Exists(lockPath))
                                    throw new InvalidOperationException("REPARSE_POINT_REJECTED");

                                if (err == 32 || err == 33 || err == 5)
                                {
                                    if (sw.ElapsedMilliseconds >= 10000)
                                        throw new IOException("STORE_LOCK_TIMEOUT");
                                    Thread.Sleep(25);
                                    continue;
                                }

                                throw new IOException("OPEN_LOCK_FILE_FAILED_" + err.ToString(CultureInfo.InvariantCulture));
                            }

                            break;
                        }

                        lsfh = new SafeFileHandle(lh, true);
                        lh = INVALID_HANDLE_VALUE;

                        BY_HANDLE_FILE_INFORMATION lbi;
                        if (!GetFileInformationByHandle(lsfh.DangerousGetHandle(), out lbi))
                            throw new InvalidOperationException("INFO_LOCK_FILE_FAILED");
                        if ((lbi.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                            throw new InvalidOperationException("REPARSE_POINT_REJECTED");
                        if ((lbi.FileAttributes & 0x10u) != 0)
                            throw new InvalidOperationException("IS_DIRECTORY");
                        if (lbi.NumberOfLinks > 1)
                            throw new InvalidOperationException("HARD_LINK_REJECTED");

                        string lockFinal = ReadFinalPathByHandle(lsfh.DangerousGetHandle());
                        if (!string.Equals(lockFinal, _rootCanon + "\\.twx_store.lock", StringComparison.OrdinalIgnoreCase))
                            throw new InvalidOperationException("CANONICAL_MISMATCH");

                        _lockStream = new FileStream(lsfh, FileAccess.ReadWrite);
                        lsfh = null;
                        if (_recordedLockOrder != null)
                            _recordedLockOrder.Add(_rootId);
                    }
                    finally
                    {
                        if (lsfh != null)
                        {
                            try { lsfh.Dispose(); } catch { }
                        }
                        if (lh != INVALID_HANDLE_VALUE && lh != IntPtr.Zero)
                        {
                            CloseHandle(lh);
                        }
                    }
                }
                catch
                {
                    Dispose();
                    throw;
                }
            }

            public void Dispose()
            {
                if (_lockStream != null)
                {
                    try { _lockStream.Dispose(); } catch { }
                    _lockStream = null;
                }
                if (_rootHandle != INVALID_HANDLE_VALUE && _rootHandle != IntPtr.Zero)
                {
                    CloseHandle(_rootHandle);
                    _rootHandle = INVALID_HANDLE_VALUE;
                }
            }
        }

        [ThreadStatic]
        private static List<FileId> _recordedLockOrder;

        public static void BeginRecordLockOrder()
        {
            _recordedLockOrder = new List<FileId>();
        }

        public static List<FileId> EndRecordLockOrder()
        {
            List<FileId> res = _recordedLockOrder != null ? new List<FileId>(_recordedLockOrder) : new List<FileId>();
            _recordedLockOrder = null;
            return res;
        }

        public static int CompareFileIds(FileId a, FileId b)
        {
            if (a.VolumeSerialNumber != b.VolumeSerialNumber)
                return a.VolumeSerialNumber < b.VolumeSerialNumber ? -1 : 1;
            if (a.FileIndexHigh != b.FileIndexHigh)
                return a.FileIndexHigh < b.FileIndexHigh ? -1 : 1;
            if (a.FileIndexLow != b.FileIndexLow)
                return a.FileIndexLow < b.FileIndexLow ? -1 : 1;
            return 0;
        }

        private sealed class PinnedSlotLockScope : IDisposable
        {
            private PinnedRootLock _firstLock;
            private PinnedRootLock _secondLock;
            private PinnedRootLock _rootLock;
            private PinnedDirectoryChain _pin;

            public PinnedRootLock RootLock { get { return _rootLock; } }
            public FileId RootId { get { return _rootLock != null ? _rootLock.RootId : default(FileId); } }
            public PinnedDirectoryChain Pin { get { return _pin; } }

            public static PinnedSlotLockScope Acquire(
                string root,
                string rootFull,
                string targetFull,
                bool createMissingDirs,
                FileId expectedRootId,
                string requiredExistingBackupDir,
                string requiredExistingBackupFile)
            {
                string rootTrim = rootFull.TrimEnd('\\');
                string targetDir = Path.GetDirectoryName(targetFull);
                bool isSubdir = !string.IsNullOrEmpty(targetDir) &&
                                targetDir.Length > rootTrim.Length &&
                                targetDir.StartsWith(rootTrim + "\\", StringComparison.OrdinalIgnoreCase);

                if (!isSubdir)
                {
                    PinnedSlotLockScope singleScope = new PinnedSlotLockScope();
                    try
                    {
                        PinnedRootLock rLock = new PinnedRootLock(root, createMissingDirs && !expectedRootId.IsValid, expectedRootId);
                        singleScope._firstLock = rLock;
                        singleScope._rootLock = rLock;
                        AssertNoCaseCollision(rootFull, targetFull);
                        if (requiredExistingBackupDir != null)
                        {
                            if (requiredExistingBackupFile != null)
                                AssertNoCaseCollision(rootFull, requiredExistingBackupFile);
                            if (!Directory.Exists(requiredExistingBackupDir) && !IsReparsePoint(requiredExistingBackupDir, true))
                                throw new FileNotFoundException("BACKUP_NOT_FOUND");
                            if (!File.Exists(requiredExistingBackupFile) && !IsReparsePoint(requiredExistingBackupFile, false))
                                throw new FileNotFoundException("BACKUP_NOT_FOUND");
                        }
                        singleScope._pin = PinnedDirectoryChain.Acquire(rootFull, targetFull, false, rLock.RootId);
                        return singleScope;
                    }
                    catch
                    {
                        singleScope.Dispose();
                        throw;
                    }
                }

                for (int attempt = 0; attempt < 4; attempt++)
                {
                    FileId rootId;
                    string rootCanon;
                    IntPtr tmpRoot = INVALID_HANDLE_VALUE;
                    try
                    {
                        tmpRoot = OpenChainedRootDirectory(root, createMissingDirs && !expectedRootId.IsValid, expectedRootId, out rootId, out rootCanon);
                    }
                    finally
                    {
                        if (tmpRoot != INVALID_HANDLE_VALUE && tmpRoot != IntPtr.Zero)
                            CloseHandle(tmpRoot);
                    }

                    AssertNoCaseCollision(rootFull, targetFull);
                    bool subExists = Directory.Exists(targetDir) || IsReparsePoint(targetDir, true);
                    if (!subExists)
                    {
                        if (!createMissingDirs)
                        {
                            PinnedRootLock rootOnly = new PinnedRootLock(root, false, rootId);
                            bool transferred = false;
                            try
                            {
                                AssertNoCaseCollision(rootFull, targetFull);
                                if (!(Directory.Exists(targetDir) || IsReparsePoint(targetDir, true)))
                                {
                                    PinnedSlotLockScope noSubScope = new PinnedSlotLockScope();
                                    noSubScope._firstLock = rootOnly;
                                    noSubScope._rootLock = rootOnly;
                                    noSubScope._pin = null;
                                    transferred = true;
                                    return noSubScope;
                                }
                            }
                            finally
                            {
                                if (!transferred)
                                    rootOnly.Dispose();
                            }
                            continue;
                        }

                        using (PinnedRootLock tmpRootLock = new PinnedRootLock(root, false, rootId))
                        {
                            AssertNoCaseCollision(rootFull, targetFull);
                            if (requiredExistingBackupDir != null)
                            {
                                if (requiredExistingBackupFile != null)
                                    AssertNoCaseCollision(rootFull, requiredExistingBackupFile);
                                if (!Directory.Exists(requiredExistingBackupDir) && !IsReparsePoint(requiredExistingBackupDir, true))
                                    throw new FileNotFoundException("BACKUP_NOT_FOUND");
                                if (!File.Exists(requiredExistingBackupFile) && !IsReparsePoint(requiredExistingBackupFile, false))
                                    throw new FileNotFoundException("BACKUP_NOT_FOUND");
                            }
                            using (PinnedDirectoryChain createPin = PinnedDirectoryChain.Acquire(rootFull, targetFull, true, rootId))
                            {
                            }
                        }
                    }

                    FileId subId = default(FileId);
                    using (PinnedDirectoryChain probePin = PinnedDirectoryChain.Acquire(rootFull, targetFull, false, rootId))
                    {
                        subId = probePin.LeafParentId;
                    }

                    PinnedRootLock firstLock = null;
                    PinnedRootLock secondLock = null;
                    PinnedRootLock rLockFinal = null;
                    PinnedRootLock sLockFinal = null;
                    PinnedDirectoryChain pin = null;
                    try
                    {
                        if (rootId.EqualsId(subId))
                        {
                            rLockFinal = new PinnedRootLock(root, false, rootId);
                            firstLock = rLockFinal;
                        }
                        else if (CompareFileIds(rootId, subId) < 0)
                        {
                            rLockFinal = new PinnedRootLock(root, false, rootId);
                            firstLock = rLockFinal;
                            sLockFinal = new PinnedRootLock(targetDir, false, subId);
                            secondLock = sLockFinal;
                        }
                        else
                        {
                            sLockFinal = new PinnedRootLock(targetDir, false, subId);
                            firstLock = sLockFinal;
                            rLockFinal = new PinnedRootLock(root, false, rootId);
                            secondLock = rLockFinal;
                        }

                        pin = PinnedDirectoryChain.Acquire(rootFull, targetFull, false, rLockFinal.RootId);
                        if (sLockFinal != null && !pin.LeafParentId.EqualsId(sLockFinal.RootId))
                            throw new InvalidOperationException("SUBDIR_IDENTITY_CHANGED");
                        AssertNoCaseCollision(rootFull, targetFull);
                        if (requiredExistingBackupDir != null)
                        {
                            if (requiredExistingBackupFile != null)
                                AssertNoCaseCollision(rootFull, requiredExistingBackupFile);
                            if (!Directory.Exists(requiredExistingBackupDir) && !IsReparsePoint(requiredExistingBackupDir, true))
                                throw new FileNotFoundException("BACKUP_NOT_FOUND");
                            if (!File.Exists(requiredExistingBackupFile) && !IsReparsePoint(requiredExistingBackupFile, false))
                                throw new FileNotFoundException("BACKUP_NOT_FOUND");
                        }

                        PinnedSlotLockScope scope = new PinnedSlotLockScope();
                        scope._firstLock = firstLock;
                        scope._secondLock = secondLock;
                        scope._rootLock = rLockFinal;
                        scope._pin = pin;
                        return scope;
                    }
                    catch (DirectoryNotFoundException)
                    {
                        if (pin != null) pin.Dispose();
                        if (secondLock != null) secondLock.Dispose();
                        if (firstLock != null) firstLock.Dispose();
                        if (attempt < 3)
                        {
                            if (expectedRootId.IsValid)
                            {
                                FileId verifyId = CaptureRootIdentity(root);
                                if (!verifyId.EqualsId(expectedRootId))
                                    throw new InvalidOperationException("ROOT_IDENTITY_CHANGED");
                            }
                            continue;
                        }
                        throw;
                    }
                    catch (InvalidOperationException ex)
                    {
                        if (pin != null) pin.Dispose();
                        if (secondLock != null) secondLock.Dispose();
                        if (firstLock != null) firstLock.Dispose();
                        if (ex.Message == "SUBDIR_IDENTITY_CHANGED" && attempt < 3)
                        {
                            if (expectedRootId.IsValid)
                            {
                                FileId verifyId = CaptureRootIdentity(root);
                                if (!verifyId.EqualsId(expectedRootId))
                                    throw new InvalidOperationException("ROOT_IDENTITY_CHANGED");
                            }
                            continue;
                        }
                        throw;
                    }
                    catch
                    {
                        if (pin != null) pin.Dispose();
                        if (secondLock != null) secondLock.Dispose();
                        if (firstLock != null) firstLock.Dispose();
                        throw;
                    }
                }

                throw new IOException("LOCK_RETRY_EXHAUSTED");
            }

            public void Dispose()
            {
                if (_pin != null) { try { _pin.Dispose(); } catch { } _pin = null; }
                if (_secondLock != null) { try { _secondLock.Dispose(); } catch { } _secondLock = null; }
                if (_firstLock != null) { try { _firstLock.Dispose(); } catch { } _firstLock = null; }
                _rootLock = null;
            }
        }

        private sealed class PinnedDirectoryChain : IDisposable
        {
            private readonly List<IntPtr> _handles = new List<IntPtr>();
            private string _rootCanon = "";
            private FileId _rootId;
            private FileId _leafParentId;

            public string RootCanon { get { return _rootCanon; } }
            public FileId RootId { get { return _rootId; } }
            public FileId LeafParentId { get { return _leafParentId; } }

            public static PinnedDirectoryChain Acquire(string rootFull, string targetFull, bool createMissing)
            {
                return Acquire(rootFull, targetFull, createMissing, default(FileId));
            }

            public static PinnedDirectoryChain Acquire(string rootFull, string targetFull, bool createMissing, FileId expectedRootId)
            {
                PinnedDirectoryChain chain = new PinnedDirectoryChain();
                try
                {
                    string fullRoot = Path.GetFullPath(rootFull);
                    CheckNoReparseInAncestors(fullRoot);

                    string rootTrim = fullRoot.TrimEnd('\\');
                    string openRoot = (rootTrim.Length == 2 && rootTrim[1] == ':') ? (rootTrim + "\\") : rootTrim;

                    string fullTarget = Path.GetFullPath(targetFull);
                    string parentDir = Path.GetDirectoryName(fullTarget);
                    if (string.IsNullOrEmpty(parentDir))
                        throw new InvalidOperationException("OPEN_DIR_FAILED");
                    string parentTrim = parentDir.TrimEnd('\\');

                    chain.OpenAndVerify(openRoot, true, expectedRootId);

                    if (parentTrim.Length > rootTrim.Length &&
                        parentTrim.StartsWith(rootTrim + "\\", StringComparison.OrdinalIgnoreCase))
                    {
                        string dummyRoot;
                        string[] allSegs = SplitPreservedRelativeSegments(rootFull, targetFull, out dummyRoot);
                        string cur = rootTrim;
                        for (int i = 0; i < allSegs.Length - 1; i++)
                        {
                            cur = cur + "\\" + allSegs[i];
                            if (!Directory.Exists(cur) && !IsReparsePoint(cur, true))
                            {
                                if (!createMissing)
                                    throw new DirectoryNotFoundException("DIR_NOT_FOUND");
                                Directory.CreateDirectory(cur);
                            }
                            chain.OpenAndVerify(cur, false, default(FileId));
                        }
                    }
                    else if (!string.Equals(parentTrim, rootTrim, StringComparison.OrdinalIgnoreCase))
                    {
                        throw new InvalidOperationException("PATH_OUTSIDE_ROOT");
                    }

                    return chain;
                }
                catch
                {
                    chain.Dispose();
                    throw;
                }
            }

            private void OpenAndVerify(string dirPath, bool isRoot, FileId expectedRootId)
            {
                IntPtr h = CreateFileW(dirPath, GENERIC_READ, FILE_SHARE_READ_WRITE, IntPtr.Zero,
                    OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, IntPtr.Zero);
                if (h == INVALID_HANDLE_VALUE)
                    throw new InvalidOperationException("OPEN_DIR_FAILED");

                try
                {
                    BY_HANDLE_FILE_INFORMATION bi;
                    if (!GetFileInformationByHandle(h, out bi))
                        throw new InvalidOperationException("INFO_DIR_FAILED");
                    if ((bi.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                        throw new InvalidOperationException("REPARSE_POINT_REJECTED");
                    if ((bi.FileAttributes & 0x10u) == 0)
                        throw new InvalidOperationException("NOT_DIRECTORY");

                    FileId currentId = new FileId();
                    currentId.VolumeSerialNumber = bi.VolumeSerialNumber;
                    currentId.FileIndexHigh = bi.FileIndexHigh;
                    currentId.FileIndexLow = bi.FileIndexLow;
                    currentId.IsValid = true;

                    string canon = ReadFinalPathByHandle(h).TrimEnd('\\');
                    if (isRoot)
                    {
                        _rootId = currentId;
                        if (expectedRootId.IsValid && !_rootId.EqualsId(expectedRootId))
                            throw new InvalidOperationException("ROOT_IDENTITY_CHANGED");
                        _rootCanon = canon;
                    }
                    else
                    {
                        if (!canon.StartsWith(_rootCanon + "\\", StringComparison.OrdinalIgnoreCase))
                            throw new InvalidOperationException("CANONICAL_PARENT_MISMATCH");
                        if (!string.Equals(Path.GetFileName(canon), Path.GetFileName(dirPath), StringComparison.OrdinalIgnoreCase))
                            throw new InvalidOperationException("ALIAS_NAME_REJECTED");
                    }

                    _leafParentId = currentId;

                    _handles.Add(h);
                    h = INVALID_HANDLE_VALUE;
                }
                finally
                {
                    if (h != INVALID_HANDLE_VALUE)
                        CloseHandle(h);
                }
            }

            public void Dispose()
            {
                for (int i = _handles.Count - 1; i >= 0; i--)
                {
                    CloseHandle(_handles[i]);
                }
                _handles.Clear();
            }
        }

        private static void WinCheckDirectory(string dirPath)
        {
            IntPtr h = CreateFileW(dirPath, 0, FILE_SHARE_ALL, IntPtr.Zero, OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, IntPtr.Zero);
            if (h == INVALID_HANDLE_VALUE) throw new InvalidOperationException("OPEN_DIR_FAILED");
            try
            {
                BY_HANDLE_FILE_INFORMATION bi;
                if (!GetFileInformationByHandle(h, out bi)) throw new InvalidOperationException("INFO_DIR_FAILED");
                if ((bi.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                    throw new InvalidOperationException("REPARSE_POINT_REJECTED");
            }
            finally { CloseHandle(h); }
        }

        private static SafeFileHandle OpenVerifiedReadPin(PinnedDirectoryChain pin, string fullPath, out byte[] bytes)
        {
            FileId dummyId;
            return OpenVerifiedReadPin(pin, fullPath, GENERIC_READ, out bytes, out dummyId);
        }

        private static SafeFileHandle OpenVerifiedReadPin(PinnedDirectoryChain pin, string fullPath, uint desiredAccess, out byte[] bytes)
        {
            FileId dummyId;
            return OpenVerifiedReadPin(pin, fullPath, desiredAccess, out bytes, out dummyId);
        }

        private static SafeFileHandle OpenVerifiedReadPin(PinnedDirectoryChain pin, string fullPath, out byte[] bytes, out FileId openedId)
        {
            return OpenVerifiedReadPin(pin, fullPath, GENERIC_READ, out bytes, out openedId);
        }

        private static SafeFileHandle OpenVerifiedReadPin(PinnedDirectoryChain pin, string fullPath, uint desiredAccess, out byte[] bytes, out FileId openedId)
        {
            return OpenVerifiedHandleCore(pin, fullPath, desiredAccess, FILE_SHARE_READ, false, false, default(FileId), null, out bytes, out openedId);
        }

        private static SafeFileHandle OpenVerifiedExclusiveTempForRename(PinnedDirectoryChain pin, string tmpFull, FileId expectedId, string expectedSha)
        {
            byte[] bytes;
            FileId openedId;
            return OpenVerifiedHandleCore(pin, tmpFull, GENERIC_READ | DELETE_ACCESS, 0u, true, true, expectedId, expectedSha, out bytes, out openedId);
        }

        private static SafeFileHandle OpenVerifiedHandleCore(PinnedDirectoryChain pin, string fullPath, uint desiredAccess, uint shareMode, bool requireSingleLink, bool verifyExpected, FileId expectedId, string expectedSha, out byte[] bytes, out FileId openedId)
        {
            bytes = null;
            openedId = default(FileId);
            if (pin == null || string.IsNullOrEmpty(pin.RootCanon))
                throw new InvalidOperationException("CANON_ROOT_EMPTY");
            string canonicalRoot = pin.RootCanon.TrimEnd('\\');

            IntPtr h = CreateFileW(fullPath, desiredAccess, shareMode, IntPtr.Zero, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, IntPtr.Zero);
            if (h == INVALID_HANDLE_VALUE)
            {
                throw new IOException("OPEN_FILE_FAILED_" + Marshal.GetLastWin32Error().ToString(CultureInfo.InvariantCulture));
            }

            SafeFileHandle sfh = new SafeFileHandle(h, true);
            try
            {
                BY_HANDLE_FILE_INFORMATION bi;
                if (!GetFileInformationByHandle(sfh.DangerousGetHandle(), out bi))
                    throw new InvalidOperationException("INFO_FILE_FAILED");

                if ((bi.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                    throw new InvalidOperationException("REPARSE_POINT_REJECTED");
                if ((bi.FileAttributes & 0x10u) != 0)
                    throw new InvalidOperationException("IS_DIRECTORY");
                if (requireSingleLink ? (bi.NumberOfLinks != 1u) : (bi.NumberOfLinks > 1u))
                    throw new InvalidOperationException("HARD_LINK_REJECTED");

                FileId openedFid;
                openedFid.VolumeSerialNumber = bi.VolumeSerialNumber;
                openedFid.FileIndexHigh = bi.FileIndexHigh;
                openedFid.FileIndexLow = bi.FileIndexLow;
                openedFid.IsValid = true;
                openedId = openedFid;

                long size = ((long)bi.FileSizeHigh << 32) | (long)bi.FileSizeLow;
                if (size < 0 || size > MaxSaveBytes)
                    throw new InvalidOperationException("SAVE_TOO_LARGE");

                string finalPath = ReadFinalPathByHandle(sfh.DangerousGetHandle());
                if (!finalPath.StartsWith(canonicalRoot + "\\", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("CANONICAL_MISMATCH");
                if (!string.Equals(Path.GetFileName(finalPath), Path.GetFileName(fullPath), StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("ALIAS_NAME_REJECTED");

                if (verifyExpected && !openedId.EqualsId(expectedId))
                    throw new InvalidOperationException("STAGED_OR_COMMITTED_FILE_MODIFIED");

                using (MemoryStream ms = new MemoryStream())
                {
                    byte[] buffer = new byte[81920];
                    long total = 0;
                    while (true)
                    {
                        uint bytesRead;
                        if (!ReadFile(sfh.DangerousGetHandle(), buffer, (uint)buffer.Length, out bytesRead, IntPtr.Zero))
                            throw new IOException("READ_FILE_FAILED_" + Marshal.GetLastWin32Error().ToString(CultureInfo.InvariantCulture));
                        if (bytesRead == 0)
                            break;
                        total += (long)bytesRead;
                        if (total > MaxSaveBytes)
                            throw new InvalidOperationException("SAVE_TOO_LARGE");
                        ms.Write(buffer, 0, (int)bytesRead);
                    }
                    bytes = ms.ToArray();
                }

                if (verifyExpected && !string.Equals(Sha256Hex(bytes), expectedSha, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("STAGED_OR_COMMITTED_FILE_MODIFIED");

                GC.KeepAlive(sfh);
                return sfh;
            }
            catch
            {
                sfh.Dispose();
                throw;
            }
        }

        private static void RenameByOpenHandle(SafeFileHandle exclusiveTmpHandle, string targetFull, bool allowReplace)
        {
            byte[] nameBytes = Encoding.Unicode.GetBytes(targetFull);
            int rootOffset = IntPtr.Size;
            int lenOffset = rootOffset + IntPtr.Size;
            int nameOffset = lenOffset + 4;
            int totalSize = nameOffset + nameBytes.Length + 2;
            IntPtr buf = IntPtr.Zero;

            try
            {
                buf = Marshal.AllocHGlobal(totalSize);
                for (int i = 0; i < totalSize; i++)
                {
                    Marshal.WriteByte(buf, i, 0);
                }

                Marshal.WriteByte(buf, 0, allowReplace ? (byte)1 : (byte)0);
                Marshal.WriteIntPtr(buf, rootOffset, IntPtr.Zero);
                Marshal.WriteInt32(buf, lenOffset, nameBytes.Length);
                Marshal.Copy(nameBytes, 0, IntPtr.Add(buf, nameOffset), nameBytes.Length);

                bool ok = SetFileInformationByHandle(exclusiveTmpHandle.DangerousGetHandle(), FileRenameInfo, buf, totalSize);
                GC.KeepAlive(exclusiveTmpHandle);

                if (!ok)
                {
                    int err = Marshal.GetLastWin32Error();
                    if (!allowReplace && (err == 80 || err == 183))
                        throw new InvalidOperationException("CONFLICT_MODIFIED");
                    throw new IOException("RENAME_BY_HANDLE_FAILED_" + err.ToString(CultureInfo.InvariantCulture));
                }
            }
            finally
            {
                if (buf != IntPtr.Zero)
                    Marshal.FreeHGlobal(buf);
            }
        }

        private static void AssertExclusiveTempLocked(string tmpPath)
        {
            if (Environment.GetEnvironmentVariable("TWX_VERIFY_EXCLUSIVE_TEMP_RENAME") != "1")
                return;

            bool writeBlocked = false;
            try
            {
                using (FileStream w = new FileStream(tmpPath, FileMode.Open, FileAccess.Write, FileShare.ReadWrite | FileShare.Delete))
                {
                }
            }
            catch (IOException)
            {
                writeBlocked = true;
            }

            if (!writeBlocked)
                throw new InvalidOperationException("EXCLUSIVE_TEMP_WRITE_NOT_BLOCKED");

            if (MoveFileExW(tmpPath, tmpPath + ".hijack", MOVEFILE_REPLACE_EXISTING))
                throw new InvalidOperationException("EXCLUSIVE_TEMP_MOVE_NOT_BLOCKED");
        }

        private static void AssertTargetPinHeldAtMoveEntry(string targetFull)
        {
            if (Environment.GetEnvironmentVariable("TWX_VERIFY_PIN_HELD_AT_MOVE_ENTRY") != "1")
                return;

            bool pinHeld = false;
            try
            {
                using (FileStream probe = new FileStream(targetFull, FileMode.Open, FileAccess.Write, FileShare.ReadWrite))
                {
                    probe.Flush();
                }
            }
            catch (IOException)
            {
                pinHeld = true;
            }

            if (!pinHeld)
                throw new InvalidOperationException("PIN_NOT_HELD_AT_MOVE_ENTRY");
        }

        private static byte[] ReadVerifiedBytes(PinnedDirectoryChain pin, string fullPath)
        {
            byte[] bytes;
            using (SafeFileHandle sfh = OpenVerifiedReadPin(pin, fullPath, out bytes))
            {
                return bytes;
            }
        }

        private static string AsciiLower(string s)
        {
            if (s == null) return null;
            char[] chars = s.ToCharArray();
            for (int i = 0; i < chars.Length; i++)
            {
                char c = chars[i];
                if (c >= 'A' && c <= 'Z')
                    chars[i] = (char)(c + 32);
            }
            return new string(chars);
        }

        public static string NormalizeRelSlotKey(string relSlot)
        {
            if (string.IsNullOrEmpty(relSlot)) return null;
            if (relSlot.IndexOf(':') >= 0) return null;
            if (relSlot.IndexOf('/') == 0 || relSlot.IndexOf('\\') == 0) return null;
            for (int i = 0; i < relSlot.Length; i++)
            {
                if (relSlot[i] < 32) return null;
            }

            string[] parts = relSlot.Split(new char[] { '/', '\\' });
            for (int i = 0; i < parts.Length; i++)
            {
                if (parts[i].Length == 0 || parts[i] == "." || parts[i] == "..")
                    return null;
                if (parts[i][parts[i].Length - 1] == ' ' || parts[i][parts[i].Length - 1] == '.')
                    return null;
            }
            return AsciiLower(string.Join("/", parts));
        }

        public static string SlotBackupPrefix(string relSlot)
        {
            string key = NormalizeRelSlotKey(relSlot);
            if (string.IsNullOrEmpty(key)) return null;

            string slotTag = Sha256Hex(new UTF8Encoding(false).GetBytes(key)).Substring(0, 16);
            string fileName = Path.GetFileName(key);
            int lastDot = fileName.LastIndexOf('.');
            string rawStem = (lastDot > 0) ? fileName.Substring(0, lastDot) : fileName;
            var sb = new StringBuilder(rawStem.Length);
            for (int i = 0; i < rawStem.Length; i++)
            {
                char c = rawStem[i];
                if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-')
                {
                    sb.Append(c);
                }
                else if (char.IsHighSurrogate(c) && i + 1 < rawStem.Length && char.IsLowSurrogate(rawStem[i + 1]))
                {
                    sb.Append('_');
                    i++;
                }
                else
                {
                    sb.Append('_');
                }
            }
            string safeStem = sb.ToString().TrimStart('.');
            if (safeStem.Length == 0) safeStem = "slot";
            return safeStem + "__s" + slotTag;
        }

        private static string GetRelSlotFromFull(string rootFull, string targetFull)
        {
            string rootSep = rootFull.TrimEnd('\\') + "\\";
            return targetFull.Substring(rootSep.Length).Replace('\\', '/');
        }

        public static void AssertNotBackupsSlot(string rootFull, string targetFull)
        {
            string rel = GetRelSlotFromFull(rootFull, targetFull);
            if (string.Equals(rel, "backups", StringComparison.OrdinalIgnoreCase) ||
                rel.StartsWith("backups/", StringComparison.OrdinalIgnoreCase))
            {
                throw new ArgumentException("BACKUPS_DIR_RESERVED");
            }
        }

        public static bool IsBackupForSlot(string backupFileName, string relSlot)
        {
            if (string.IsNullOrEmpty(backupFileName) || string.IsNullOrEmpty(relSlot)) return false;
            string prefix = SlotBackupPrefix(relSlot);
            if (string.IsNullOrEmpty(prefix)) return false;

            string pattern = "^" + Regex.Escape(prefix) + @"_\d{8}T\d+Z(?:_[0-9a-fA-F]{4})?_[0-9a-fA-F]{8}\.bak$";
            return Regex.IsMatch(backupFileName, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        }

        private static void VerifyCanonicalParentForNewFile(string rootFull, string targetFull)
        {
            string existingDir = Path.GetDirectoryName(targetFull);
            while (!string.IsNullOrEmpty(existingDir) && !Directory.Exists(existingDir))
                existingDir = Path.GetDirectoryName(existingDir);
            if (string.IsNullOrEmpty(existingDir))
                throw new InvalidOperationException("PARENT_DIR_MISSING");

            string rootCanon = GetCanonicalPath(rootFull, true).TrimEnd('\\');
            string dirCanon = GetCanonicalPath(existingDir, true).TrimEnd('\\');
            if (!string.Equals(dirCanon, rootCanon, StringComparison.OrdinalIgnoreCase) &&
                !dirCanon.StartsWith(rootCanon + "\\", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("CANONICAL_PARENT_MISMATCH");
            }

            string parent = Path.GetDirectoryName(targetFull);
            if (!string.IsNullOrEmpty(parent) && !Directory.Exists(parent))
                Directory.CreateDirectory(parent);
        }

        public static bool IsGameRunning()
        {
            if (Environment.GetEnvironmentVariable("TWX_SIMULATE_GAME_RUNNING") == "1") return true;
            Process[] procs = null;
            try
            {
                procs = Process.GetProcessesByName("wuxia");
                return procs != null && procs.Length > 0;
            }
            catch { return false; }
            finally
            {
                if (procs != null)
                {
                    for (int i = 0; i < procs.Length; i++)
                    {
                        try { procs[i].Dispose(); } catch { }
                    }
                }
            }
        }

        private static List<BackupInfo> EnumerateBackupsLocked(string rootFull, FileId rootId, string filterRelNorm)
        {
            var result = new List<BackupInfo>();
            string bdir;
            try { bdir = Path.Combine(rootFull, "backups"); } catch { return result; }
            AssertNoCaseCollision(rootFull, bdir);
            if (!Directory.Exists(bdir) && !IsReparsePoint(bdir, true)) return result;

            try
            {
                using (PinnedDirectoryChain bpin = PinnedDirectoryChain.Acquire(rootFull, Path.Combine(bdir, "probe.bak"), false, rootId))
                {
                    string[] files;
                    try { files = Directory.GetFiles(bdir, "*.bak", SearchOption.TopDirectoryOnly); }
                    catch { return result; }

                    foreach (string f in files)
                    {
                        try
                        {
                            if (IsReparsePoint(f, false)) continue;
                            var fi = new FileInfo(f);
                            if (!string.IsNullOrEmpty(filterRelNorm) && !IsBackupForSlot(fi.Name, filterRelNorm)) continue;
                            string sha8 = "";
                            Match m = BackupHashRegex.Match(fi.Name);
                            if (m.Success) sha8 = m.Groups[1].Value.ToLowerInvariant();
                            int sep = fi.Name.IndexOf('_');
                            result.Add(new BackupInfo
                            {
                                FullPath = fi.FullName,
                                FileName = fi.Name,
                                SlotName = sep > 0 ? fi.Name.Substring(0, sep) : fi.Name,
                                CreatedUtc = fi.LastWriteTimeUtc,
                                SizeBytes = fi.Length,
                                Sha256 = sha8
                            });
                        }
                        catch { }
                    }
                }
            }
            catch (DirectoryNotFoundException)
            {
                return result;
            }

            result.Sort(delegate(BackupInfo a, BackupInfo b) { return StringComparer.Ordinal.Compare(b.FileName, a.FileName); });
            return result;
        }

        public static List<BackupInfo> ListBackups(string root)
        {
            return ListBackups(root, default(FileId));
        }

        public static List<BackupInfo> ListBackups(string root, FileId expectedRootId)
        {
            lock (StoreLock)
            {
                string rootFull;
                if (!TryResolveExistingRoot(root, expectedRootId, out rootFull))
                    return new List<BackupInfo>();

                using (PinnedRootLock rootLock = new PinnedRootLock(root, false, expectedRootId))
                {
                    return EnumerateBackupsLocked(rootFull, rootLock.RootId, null);
                }
            }
        }

        public static List<BackupInfo> ListBackupsForSlot(string root, string slot)
        {
            return ListBackupsForSlot(root, slot, default(FileId));
        }

        public static List<BackupInfo> ListBackupsForSlot(string root, string slot, FileId expectedRootId)
        {
            if (string.IsNullOrEmpty(slot)) return ListBackups(root, expectedRootId);

            lock (StoreLock)
            {
                var empty = new List<BackupInfo>();
                string rootFull = Path.GetFullPath(root);
                string targetFull = ResolveSafePath(rootFull, slot);
                AssertNotBackupsSlot(rootFull, targetFull);

                string resolvedRoot;
                if (!TryResolveExistingRoot(root, expectedRootId, out resolvedRoot))
                    return empty;

                using (PinnedSlotLockScope scope = PinnedSlotLockScope.Acquire(root, rootFull, targetFull, false, expectedRootId, null, null))
                {
                    return EnumerateBackupsLocked(rootFull, scope.RootId, GetRelSlotFromFull(rootFull, targetFull));
                }
            }
        }

        public static SaveLoadResult LoadSlot(string root, string path)
        {
            return LoadSlot(root, path, default(FileId));
        }

        public static SaveLoadResult LoadSlot(string root, string path, FileId expectedRootId)
        {
            lock (StoreLock)
            {
                var res = new SaveLoadResult();
                try
                {
                    string rootFull = Path.GetFullPath(root);
                    string full = ResolveSafePath(rootFull, path);
                    AssertNotBackupsSlot(rootFull, full);
                    CheckNoReparseInAncestors(rootFull);
                    if (!Directory.Exists(rootFull) && !IsReparsePoint(rootFull.TrimEnd('\\'), true))
                    {
                        if (expectedRootId.IsValid)
                            throw new InvalidOperationException("ROOT_IDENTITY_CHANGED");
                        res.Message = "NOT_FOUND";
                        return res;
                    }

                    using (PinnedSlotLockScope scope = PinnedSlotLockScope.Acquire(root, rootFull, full, false, expectedRootId, null, null))
                    {
                        if (scope.Pin == null || (!File.Exists(full) && !IsReparsePoint(full, false)))
                        {
                            res.Message = "NOT_FOUND";
                            return res;
                        }

                        byte[] bytes = ReadVerifiedBytes(scope.Pin, full);
                        string text = DecodeText(bytes);
                        string kind = ValidateSaveJson(text);
                        string expKind = ExpectedSlotKind(Path.GetFileName(full));
                        if (expKind != null && kind != expKind)
                            throw new InvalidDataException("SLOT_SCHEMA_MISMATCH");
                        string sha = Sha256Hex(bytes);

                        res.JsonText = text;
                        res.RawBytes = bytes;
                        res.Sha256 = sha;
                        res.Slot = new SaveSlotInfo
                        {
                            FileName = Path.GetFileName(full),
                            FullPath = full,
                            Kind = kind,
                            SlotName = Path.GetFileName(full),
                            SizeBytes = bytes.Length,
                            Sha256 = sha
                        };
                        res.Success = true;
                    }
                }
                catch (Exception ex) { res.Message = ex.Message; }
                return res;
            }
        }

        private static readonly object StoreLock = new object();

        private sealed class CompanionTitlePlan : IDisposable
        {
            public string TitleFullPath;
            public byte[] OrigTitleBytes;
            public byte[] NewTitleBytes;
            public SafeFileHandle PinnedTitleHandle;

            public void Dispose()
            {
                if (PinnedTitleHandle != null)
                {
                    try { PinnedTitleHandle.Dispose(); } catch { }
                    PinnedTitleHandle = null;
                }
            }
        }

        public static string ExpectedSlotKind(string fileName)
        {
            if (string.IsNullOrEmpty(fileName)) return null;
            Match m;
            if ((m = ManualSaveRegex.Match(fileName)).Success)
            {
                int idx = int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
                return (idx >= 0 && idx < 20) ? "save" : null;
            }
            if ((m = AutoSaveRegex.Match(fileName)).Success)
            {
                int idx = int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
                return (idx >= 0 && idx < 20) ? "save" : null;
            }
            if ((m = AutoDSaveRegex.Match(fileName)).Success)
            {
                int idx = int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
                return (idx >= 0 && idx < 20) ? "save" : null;
            }
            if (string.Equals(fileName, "Round.dat", StringComparison.OrdinalIgnoreCase))
                return "round";
            if (GuidFileRegex.IsMatch(fileName))
                return "guid";
            if (fileName.EndsWith(".SaveTitle", StringComparison.OrdinalIgnoreCase))
                return "title";
            return null;
        }

        public static SaveWriteResult SaveSlot(string root, string path, string jsonText)
        {
            return SaveSlot(root, path, jsonText, null, default(FileId));
        }

        public static SaveWriteResult SaveSlot(string root, string path, string jsonText, string expectedOrigSha256)
        {
            return SaveSlot(root, path, jsonText, expectedOrigSha256, default(FileId));
        }

        public static SaveWriteResult SaveSlot(string root, string path, string jsonText, string expectedOrigSha256, FileId expectedRootId)
        {
            lock (StoreLock)
            {
                var res = new SaveWriteResult();
                string titleBackupPath = null;
                string titleFullPath = null;
                FileId writtenTitleId = default(FileId);
                try
                {
                    if (IsGameRunning()) { res.Message = "GAME_RUNNING"; return res; }
                    string rootFull = Path.GetFullPath(root);
                    string full = ResolveSafePath(rootFull, path);
                    AssertNotBackupsSlot(rootFull, full);
                    string kind = ValidateSaveJson(jsonText);
                    string expKind = ExpectedSlotKind(Path.GetFileName(full));
                    if (expKind != null && kind != expKind)
                        throw new InvalidDataException("SLOT_SCHEMA_MISMATCH");

                    using (PinnedSlotLockScope scope = PinnedSlotLockScope.Acquire(root, rootFull, full, true, expectedRootId, null, null))
                    {
                        PinnedRootLock rootLock = scope.RootLock;
                        PinnedDirectoryChain pin = scope.Pin;
                        {
                            {
                                if (IsGameRunning()) { res.Message = "GAME_RUNNING"; return res; }
                                AssertNoCaseCollision(rootFull, full);
                                AssertNoCaseCollision(rootFull, Path.Combine(rootFull, "backups"));

                                bool existed = File.Exists(full) || IsReparsePoint(full, false);
                                byte[] originalBytes = null;
                                byte[] newBytes = null;
                                CompanionTitlePlan titlePlan = null;
                                SafeFileHandle pinnedOrig = null;
                                string stagedTmp = null;
                                string stagedTitleTmp = null;
                                FileId writtenSlotId = default(FileId);
                                FileId slotBackupId = default(FileId);
                                FileId titleBackupId = default(FileId);
                                string origSlotSha = "";
                                string origTitleSha = "";
                                string verifiedSlotSha = "";
                                PinnedDirectoryChain bpin = null;
                                PinnedFinalVerificationSet finalPins = new PinnedFinalVerificationSet();

                                try
                                {
                                    try
                                    {
                                        if (existed)
                                        {
                                            pinnedOrig = OpenVerifiedReadPin(pin, full, out originalBytes);
                                        }

                                        string actualSha = existed ? Sha256Hex(originalBytes) : "";
                                        origSlotSha = actualSha;
                                        if (expectedOrigSha256 != null &&
                                            !string.Equals(actualSha, expectedOrigSha256, StringComparison.OrdinalIgnoreCase))
                                        {
                                            res.Message = "CONFLICT_MODIFIED";
                                            return res;
                                        }

                                        if (Environment.GetEnvironmentVariable("TWX_VERIFY_PINNED_SHARE_MODE") == "1" && pinnedOrig != null)
                                        {
                                            bool shareModeEnforced = false;
                                            try
                                            {
                                                using (FileStream probe = new FileStream(full, FileMode.Open, FileAccess.Write, FileShare.ReadWrite))
                                                {
                                                    probe.Flush();
                                                }
                                            }
                                            catch (IOException)
                                            {
                                                shareModeEnforced = true;
                                            }
                                            if (!shareModeEnforced)
                                                throw new InvalidOperationException("PINNED_SHARE_MODE_NOT_ENFORCED");
                                        }

                                        newBytes = EncodeText(jsonText, originalBytes);
                                        if (newBytes.Length > MaxSaveBytes) throw new InvalidOperationException("SAVE_TOO_LARGE");
                                        string expectedNewSlotSha = Sha256Hex(newBytes);

                                        titlePlan = kind == "save"
                                            ? PrepareCompanionTitle(rootFull, full, jsonText, rootLock.RootId)
                                            : null;
                                        string expectedNewTitleSha = "";
                                        if (titlePlan != null)
                                        {
                                            titleFullPath = titlePlan.TitleFullPath;
                                            origTitleSha = Sha256Hex(titlePlan.OrigTitleBytes);
                                            expectedNewTitleSha = Sha256Hex(titlePlan.NewTitleBytes);
                                        }

                                        if (Environment.GetEnvironmentVariable("TWX_VERIFY_PINNED_SHARE_MODE") == "1" &&
                                            titlePlan != null && titlePlan.PinnedTitleHandle != null)
                                        {
                                            bool titleShareModeEnforced = false;
                                            try
                                            {
                                                using (FileStream titleProbe = new FileStream(titlePlan.TitleFullPath, FileMode.Open, FileAccess.Write, FileShare.ReadWrite))
                                                {
                                                    titleProbe.Flush();
                                                }
                                            }
                                            catch (IOException)
                                            {
                                                titleShareModeEnforced = true;
                                            }
                                            if (!titleShareModeEnforced)
                                                throw new InvalidOperationException("PINNED_SHARE_MODE_NOT_ENFORCED");
                                        }

                                        if (existed || titlePlan != null)
                                        {
                                            string bdir = Path.Combine(rootFull, "backups");
                                            bpin = PinnedDirectoryChain.Acquire(rootFull, Path.Combine(bdir, "probe.bak"), true, rootLock.RootId);
                                        }

                                        if (existed)
                                            res.BackupPath = CreateVerifiedBackup(bpin, rootFull, full, originalBytes, out slotBackupId);
                                        if (titlePlan != null)
                                            titleBackupPath = CreateVerifiedBackup(bpin, rootFull, titleFullPath, titlePlan.OrigTitleBytes, out titleBackupId);

                                        if (titlePlan != null)
                                            stagedTitleTmp = StageTempBytes(pin.RootCanon, titleFullPath, titlePlan.NewTitleBytes, out writtenTitleId);

                                        stagedTmp = StageTempBytes(pin.RootCanon, full, newBytes, out writtenSlotId);

                                        if (!existed && Environment.GetEnvironmentVariable("TWX_SIMULATE_NEW_FILE_RACE") == "1")
                                            File.WriteAllText(full, "{\"race\":1}", new UTF8Encoding(false));

                                        CommitVerifiedStagedTemp(pin, stagedTmp, writtenSlotId, expectedNewSlotSha, full, existed, "slot", pinnedOrig);
                                        stagedTmp = null;
                                        pinnedOrig = null;

                                        if (titlePlan != null)
                                        {
                                            bool titleCommitted = false;
                                            try
                                            {
                                                if (Environment.GetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL") == "1")
                                                    throw new IOException("SIMULATED_TITLE_WRITE_FAIL");
                                                CommitVerifiedStagedTemp(pin, stagedTitleTmp, writtenTitleId, expectedNewTitleSha, titleFullPath, true, "title", titlePlan);
                                                stagedTitleTmp = null;
                                                titleCommitted = true;
                                                if (Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL") == "1")
                                                    throw new IOException("SIMULATED_POST_TITLE_FAIL");
                                                if (string.Equals(Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER"), "title", StringComparison.Ordinal))
                                                    File.WriteAllText(titleFullPath, "{\"tampered_title\":1}", new UTF8Encoding(false));
                                                VerifyPinnedFileIdentityAndSha(pin, titleFullPath, writtenTitleId, expectedNewTitleSha);
                                            }
                                            catch
                                            {
                                                if (titleCommitted)
                                                {
                                                    try { TryRollbackReplacedSlot(pin, titleFullPath, true, titlePlan.OrigTitleBytes, titlePlan.NewTitleBytes, writtenTitleId); } catch { }
                                                }
                                                try { TryRollbackReplacedSlot(pin, full, existed, originalBytes, newBytes, writtenSlotId); } catch { }
                                                throw;
                                            }
                                        }

                                        verifiedSlotSha = VerifyPostCommitAndBackupsOrRollback(pin, bpin, full, existed, originalBytes, newBytes, writtenSlotId, expectedNewSlotSha, res.BackupPath, slotBackupId, origSlotSha, titlePlan, titleFullPath, writtenTitleId, titleBackupPath, titleBackupId, origTitleSha, expectedNewTitleSha, finalPins);
                                    }
                                    finally
                                    {
                                        if (pinnedOrig != null)
                                        {
                                            try { pinnedOrig.Dispose(); } catch { }
                                            pinnedOrig = null;
                                        }
                                        if (titlePlan != null)
                                        {
                                            try { titlePlan.Dispose(); } catch { }
                                            titlePlan = null;
                                        }
                                        if (stagedTmp != null)
                                        {
                                            DeleteTempIfIdMatches(pin != null ? pin.RootCanon : null, stagedTmp, writtenSlotId);
                                        }
                                        if (stagedTitleTmp != null)
                                        {
                                            DeleteTempIfIdMatches(pin != null ? pin.RootCanon : null, stagedTitleTmp, writtenTitleId);
                                        }
                                    }

                                    FinalizeVerifiedWriteAndPrune(res, bpin, rootFull, full, titleFullPath, titleBackupPath, verifiedSlotSha);
                                }
                                finally
                                {
                                    DisposeFinalCommitResources(ref finalPins, ref bpin);
                                }
                            }
                        }
                    }
                }
                catch (Exception ex) { res.Message = ex.Message; }
                return res;
            }
        }

        public static SaveWriteResult RestoreBackup(string root, string backupPath, string targetPath)
        {
            return RestoreBackup(root, backupPath, targetPath, default(FileId));
        }

        public static SaveWriteResult RestoreBackup(string root, string backupPath, string targetPath, FileId expectedRootId)
        {
            lock (StoreLock)
            {
                var res = new SaveWriteResult();
                string titleBackupPath = null;
                string titleFullPath = null;
                FileId writtenTitleId = default(FileId);
                try
                {
                    if (IsGameRunning()) { res.Message = "GAME_RUNNING"; return res; }
                    string rootFull = Path.GetFullPath(root);
                    string bdir = Path.Combine(rootFull, "backups");
                    string bname = Path.GetFileName(backupPath);
                    if (string.IsNullOrEmpty(bname)) throw new ArgumentException("BACKUP_EMPTY");

                    string targetFull = ResolveSafePath(rootFull, targetPath);
                    AssertNotBackupsSlot(rootFull, targetFull);
                    string relNorm = GetRelSlotFromFull(rootFull, targetFull);
                    if (!IsBackupForSlot(bname, relNorm))
                        throw new InvalidOperationException("BACKUP_SLOT_MISMATCH");

                    string bfull = ResolveSafePath(bdir, bname);
                    using (PinnedSlotLockScope scope = PinnedSlotLockScope.Acquire(root, rootFull, targetFull, true, expectedRootId, bdir, bfull))
                    {
                        PinnedRootLock rootLock = scope.RootLock;
                        PinnedDirectoryChain tpin = scope.Pin;
                        PinnedDirectoryChain bpin = null;
                        PinnedFinalVerificationSet finalPins = new PinnedFinalVerificationSet();
                        try
                        {
                            bpin = PinnedDirectoryChain.Acquire(rootFull, bfull, false, rootLock.RootId);
                            {
                                {
                                    if (IsGameRunning()) { res.Message = "GAME_RUNNING"; return res; }
                                    AssertNoCaseCollision(rootFull, targetFull);
                                    AssertNoCaseCollision(rootFull, bfull);

                                    byte[] backupBytes = ReadVerifiedBytes(bpin, bfull);
                                    if (backupBytes.Length > MaxSaveBytes) throw new InvalidOperationException("BACKUP_TOO_LARGE");
                                    string bsha = Sha256Hex(backupBytes);
                                    Match m = BackupHashRegex.Match(bname);
                                    if (!m.Success || !bsha.StartsWith(m.Groups[1].Value, StringComparison.OrdinalIgnoreCase))
                                        throw new InvalidDataException("BACKUP_HASH_CORRUPTED");

                                    string backupText = DecodeText(backupBytes);
                                    string kind = ValidateSaveJson(backupText);

                                    string expKind = ExpectedSlotKind(Path.GetFileName(targetFull));
                                    if (expKind != null && kind != expKind)
                                        throw new InvalidDataException("SLOT_SCHEMA_MISMATCH");

                                    bool existed = File.Exists(targetFull) || IsReparsePoint(targetFull, false);
                                    byte[] curBytes = null;
                                    SafeFileHandle pinnedCur = null;
                                    CompanionTitlePlan titlePlan = null;
                                    string stagedSlotTmp = null;
                                    string stagedTitleTmp = null;
                                    FileId writtenSlotId = default(FileId);
                                    FileId slotBackupId = default(FileId);
                                    FileId titleBackupId = default(FileId);
                                    string origSlotSha = "";
                                    string origTitleSha = "";
                                    string verifiedSlotSha = "";

                                    try
                                    {
                                        if (existed)
                                        {
                                            pinnedCur = OpenVerifiedReadPin(tpin, targetFull, out curBytes);
                                            origSlotSha = Sha256Hex(curBytes);
                                        }

                                        titlePlan = kind == "save"
                                            ? PrepareCompanionTitle(rootFull, targetFull, backupText, rootLock.RootId)
                                            : null;
                                        string expectedNewTitleSha = "";
                                        if (titlePlan != null)
                                        {
                                            titleFullPath = titlePlan.TitleFullPath;
                                            origTitleSha = Sha256Hex(titlePlan.OrigTitleBytes);
                                            expectedNewTitleSha = Sha256Hex(titlePlan.NewTitleBytes);
                                        }

                                        if (existed)
                                            res.BackupPath = CreateVerifiedBackup(bpin, rootFull, targetFull, curBytes, out slotBackupId);
                                        if (titlePlan != null)
                                            titleBackupPath = CreateVerifiedBackup(bpin, rootFull, titleFullPath, titlePlan.OrigTitleBytes, out titleBackupId);

                                        if (titlePlan != null)
                                            stagedTitleTmp = StageTempBytes(tpin.RootCanon, titleFullPath, titlePlan.NewTitleBytes, out writtenTitleId);

                                        stagedSlotTmp = StageTempBytes(tpin.RootCanon, targetFull, backupBytes, out writtenSlotId);

                                        CommitVerifiedStagedTemp(tpin, stagedSlotTmp, writtenSlotId, bsha, targetFull, existed, "slot", pinnedCur);
                                        pinnedCur = null;
                                        stagedSlotTmp = null;

                                        if (titlePlan != null)
                                        {
                                            bool titleCommitted = false;
                                            try
                                            {
                                                if (Environment.GetEnvironmentVariable("TWX_SIMULATE_TITLE_WRITE_FAIL") == "1")
                                                    throw new IOException("SIMULATED_TITLE_WRITE_FAIL");
                                                CommitVerifiedStagedTemp(tpin, stagedTitleTmp, writtenTitleId, expectedNewTitleSha, titleFullPath, true, "title", titlePlan);
                                                stagedTitleTmp = null;
                                                titleCommitted = true;
                                                if (Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_TITLE_FAIL") == "1")
                                                    throw new IOException("SIMULATED_POST_TITLE_FAIL");
                                                if (string.Equals(Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER"), "title", StringComparison.Ordinal))
                                                    File.WriteAllText(titleFullPath, "{\"tampered_title\":1}", new UTF8Encoding(false));
                                                VerifyPinnedFileIdentityAndSha(tpin, titleFullPath, writtenTitleId, expectedNewTitleSha);
                                            }
                                            catch
                                            {
                                                if (titleCommitted)
                                                {
                                                    try { TryRollbackReplacedSlot(tpin, titleFullPath, true, titlePlan.OrigTitleBytes, titlePlan.NewTitleBytes, writtenTitleId); } catch { }
                                                }
                                                try { TryRollbackReplacedSlot(tpin, targetFull, existed, curBytes, backupBytes, writtenSlotId); } catch { }
                                                throw;
                                            }
                                        }

                                        verifiedSlotSha = VerifyPostCommitAndBackupsOrRollback(tpin, bpin, targetFull, existed, curBytes, backupBytes, writtenSlotId, bsha, res.BackupPath, slotBackupId, origSlotSha, titlePlan, titleFullPath, writtenTitleId, titleBackupPath, titleBackupId, origTitleSha, expectedNewTitleSha, finalPins);
                                    }
                                    finally
                                    {
                                        if (pinnedCur != null)
                                        {
                                            try { pinnedCur.Dispose(); } catch { }
                                            pinnedCur = null;
                                        }
                                        if (titlePlan != null)
                                        {
                                            try { titlePlan.Dispose(); } catch { }
                                            titlePlan = null;
                                        }
                                        if (stagedSlotTmp != null)
                                        {
                                            DeleteTempIfIdMatches(tpin != null ? tpin.RootCanon : null, stagedSlotTmp, writtenSlotId);
                                        }
                                        if (stagedTitleTmp != null)
                                        {
                                            DeleteTempIfIdMatches(tpin != null ? tpin.RootCanon : null, stagedTitleTmp, writtenTitleId);
                                        }
                                    }

                                    FinalizeVerifiedWriteAndPrune(res, bpin, rootFull, targetFull, titleFullPath, titleBackupPath, verifiedSlotSha);
                                }
                            }
                        }
                        finally
                        {
                            DisposeFinalCommitResources(ref finalPins, ref bpin);
                        }
                    }
                }
                catch (Exception ex) { res.Message = ex.Message; }
                return res;
            }
        }

        private static void SimulateSameBytesExternalReplace(string rootCanon, string targetFull, byte[] writtenBytes)
        {
            FileId extTmpId;
            string extTmp = StageTempBytes(rootCanon, targetFull, writtenBytes, out extTmpId);
            CommitStagedTemp(rootCanon, extTmp, extTmpId, targetFull, true);
        }

        private static bool TryRollbackReplacedSlot(PinnedDirectoryChain pin, string targetFull, bool existed, byte[] origBytes, byte[] writtenBytes, FileId writtenId)
        {
            if (pin == null || string.IsNullOrEmpty(pin.RootCanon) || writtenBytes == null || (existed && origBytes == null))
                return false;

            string writtenSha = Sha256Hex(writtenBytes);

            if (existed)
            {
                FileId rbStagedId = default(FileId);
                string origSha = Sha256Hex(origBytes);
                string rbTmp = null;
                SafeFileHandle readPin = null;

                try
                {
                    rbTmp = StageTempBytes(pin.RootCanon, targetFull, origBytes, out rbStagedId);

                    if (Environment.GetEnvironmentVariable("TWX_SIMULATE_RB_TEMP_TAMPER") == "1")
                        File.WriteAllText(rbTmp, "{\"rb_tampered\":1}", new UTF8Encoding(false));
                    if (Environment.GetEnvironmentVariable("TWX_SIMULATE_RB_TEMP_SWAP") == "1")
                    {
                        File.Delete(rbTmp);
                        File.WriteAllText(rbTmp, "{\"foreign_at_rb_tmp\":1}", new UTF8Encoding(false));
                    }

                    using (SafeFileHandle rbHandle = OpenVerifiedExclusiveTempForRename(pin, rbTmp, rbStagedId, origSha))
                    {
                        if (Environment.GetEnvironmentVariable("TWX_SIMULATE_EXT_WRITE_DURING_RB_STAGE") == "1")
                            File.WriteAllText(targetFull, "{\"ext_rb_stage\":1}", new UTF8Encoding(false));

                        if (Environment.GetEnvironmentVariable("TWX_SIMULATE_EXT_SAME_BYTES_DURING_RB_STAGE") == "1")
                            SimulateSameBytesExternalReplace(pin.RootCanon, targetFull, writtenBytes);

                        byte[] currentOnDisk;
                        FileId currentId;
                        readPin = OpenVerifiedReadPin(pin, targetFull, out currentOnDisk, out currentId);
                        bool unchanged = (!writtenId.IsValid || currentId.EqualsId(writtenId)) &&
                                         string.Equals(Sha256Hex(currentOnDisk), writtenSha, StringComparison.OrdinalIgnoreCase);

                        if (!unchanged)
                            return false;

                        AssertExclusiveTempLocked(rbTmp);
                        AssertTargetPinHeldAtMoveEntry(targetFull);

                        SafeFileHandle pinToRelease = readPin;
                        readPin = null;
                        pinToRelease.Dispose();
                        RenameByOpenHandle(rbHandle, targetFull, true);
                        rbTmp = null;
                    }

                    if (Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_RB_TAMPER") == "1")
                        File.WriteAllText(targetFull, "{\"post_rb_tampered\":1}", new UTF8Encoding(false));

                    VerifyPinnedFileIdentityAndSha(pin, targetFull, rbStagedId, origSha);

                    return true;
                }
                catch
                {
                    return false;
                }
                finally
                {
                    if (readPin != null)
                    {
                        try { readPin.Dispose(); } catch { }
                    }

                    if (rbTmp != null)
                    {
                        DeleteTempIfIdMatches(pin.RootCanon, rbTmp, rbStagedId);
                    }
                }
            }

            if (Environment.GetEnvironmentVariable("TWX_SIMULATE_EXT_WRITE_DURING_RB_STAGE") == "1")
                File.WriteAllText(targetFull, "{\"ext_rb_stage_new\":1}", new UTF8Encoding(false));

            if (Environment.GetEnvironmentVariable("TWX_SIMULATE_EXT_SAME_BYTES_DURING_RB_STAGE") == "1")
                SimulateSameBytesExternalReplace(pin.RootCanon, targetFull, writtenBytes);

            try
            {
                byte[] currentOnDisk;
                FileId currentId;
                bool deleted = false;
                using (SafeFileHandle sfh = OpenVerifiedReadPin(pin, targetFull, GENERIC_READ | DELETE_ACCESS, out currentOnDisk, out currentId))
                {
                    bool same = (!writtenId.IsValid || currentId.EqualsId(writtenId)) &&
                                string.Equals(Sha256Hex(currentOnDisk), writtenSha, StringComparison.OrdinalIgnoreCase);
                    if (!same)
                        return false;

                    FILE_DISPOSITION_INFO disp = new FILE_DISPOSITION_INFO();
                    disp.DeleteFile = true;
                    deleted = SetFileInformationByHandle(sfh.DangerousGetHandle(), FileDispositionInfo, ref disp, Marshal.SizeOf(typeof(FILE_DISPOSITION_INFO)));
                    GC.KeepAlive(sfh);
                }

                if (!deleted || File.Exists(targetFull) || IsReparsePoint(targetFull, false))
                    return false;

                return true;
            }
            catch
            {
                return false;
            }
        }

        private static CompanionTitlePlan PrepareCompanionTitle(string rootFull, string saveFullPath, string saveJsonText, FileId expectedRootId)
        {
            string saveFileName = Path.GetFileName(saveFullPath);
            string titleFile = null;
            int slotIndex = -1;
            Match m;
            if ((m = ManualSaveRegex.Match(saveFileName)).Success)
            {
                slotIndex = int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
                titleFile = "SaveTitle.SaveTitle";
            }
            else if ((m = AutoSaveRegex.Match(saveFileName)).Success)
            {
                slotIndex = int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
                titleFile = "SaveAutomaticTitle.SaveTitle";
            }
            else if ((m = AutoDSaveRegex.Match(saveFileName)).Success)
            {
                slotIndex = int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
                titleFile = "SaveAutomaticDTitle.SaveTitle";
            }
            if (titleFile == null || slotIndex < 0 || slotIndex >= 20) return null;

            string saveDir = Path.GetDirectoryName(saveFullPath);
            string titleCandidate = Path.Combine(saveDir, titleFile);
            string relTitle = GetRelSlotFromFull(rootFull, titleCandidate);
            string titleFull = ResolveSafePath(rootFull, relTitle);
            AssertNoCaseCollision(rootFull, titleFull);
            if (!File.Exists(titleFull) && !IsReparsePoint(titleFull, false)) return null;

            byte[] origTitleBytes;
            SafeFileHandle titleHandle = null;
            try
            {
                using (PinnedDirectoryChain tpin = PinnedDirectoryChain.Acquire(rootFull, titleFull, false, expectedRootId))
                {
                    titleHandle = OpenVerifiedReadPin(tpin, titleFull, out origTitleBytes);
                }
                string titleJsonText = DecodeText(origTitleBytes);
                if (ValidateSaveJson(titleJsonText) != "title")
                    throw new InvalidDataException("INVALID_COMPANION_TITLE");

                bool titleHadBom;
                string cleanTitleJson = StripLeadingBom(titleJsonText, out titleHadBom);
                bool saveHadBom;
                string cleanSaveJson = StripLeadingBom(saveJsonText, out saveHadBom);

                var ser = new JavaScriptSerializer { MaxJsonLength = 64 * 1024 * 1024, RecursionLimit = 128 };
                object[] titleArr = AsObjectArray(ser.DeserializeObject(cleanTitleJson), "title");
                if (slotIndex >= titleArr.Length)
                    throw new InvalidDataException("COMPANION_TITLE_SLOT_OUT_OF_RANGE");
                var entry = titleArr[slotIndex] as Dictionary<string, object>;
                var saveDict = ser.DeserializeObject(cleanSaveJson) as Dictionary<string, object>;
                if (entry == null || saveDict == null)
                    throw new InvalidDataException("INVALID_COMPANION_TITLE_ENTRY");

                string lastName = saveDict.ContainsKey("m_strPlayerLastName") ? Convert.ToString(saveDict["m_strPlayerLastName"], CultureInfo.InvariantCulture) : "";
                string firstName = saveDict.ContainsKey("m_strPlayerName") ? Convert.ToString(saveDict["m_strPlayerName"], CultureInfo.InvariantCulture) : "";
                string scene = saveDict.ContainsKey("m_strSceneName") && saveDict["m_strSceneName"] != null
                    ? Convert.ToString(saveDict["m_strSceneName"], CultureInfo.InvariantCulture)
                    : "Develop";
                long yrVal;
                string yearStr = (saveDict.ContainsKey("m_iYear") && TryGetExactLong(saveDict["m_iYear"], out yrVal))
                    ? yrVal.ToString(CultureInfo.InvariantCulture)
                    : "1";
                string iconId = saveDict.ContainsKey("m_PlayerIconID") && saveDict["m_PlayerIconID"] != null
                    ? Convert.ToString(saveDict["m_PlayerIconID"], CultureInfo.InvariantCulture)
                    : "900005";

                Dictionary<string, object> updates = new Dictionary<string, object>(StringComparer.Ordinal);
                List<string> updateKeyOrder = new List<string>();

                updates["m_bHaveData"] = true;
                updateKeyOrder.Add("m_bHaveData");

                updates["m_strPlayerName"] = lastName + firstName;
                updateKeyOrder.Add("m_strPlayerName");

                updates["m_strPlaceName"] = scene;
                updateKeyOrder.Add("m_strPlaceName");

                updates["m_strYear"] = yearStr;
                updateKeyOrder.Add("m_strYear");

                updates["m_strPlayerIconName"] = iconId;
                updateKeyOrder.Add("m_strPlayerIconName");

                if (scene == "Develop")
                {
                    string[] intervals = new string[] { "\uCD08", "\uC0C1\uC21C", "\uC911\uC21C", "\uD558\uC21C", "\uB9D0" };
                    long moVal;
                    int month = (saveDict.ContainsKey("m_iMonth") && TryGetExactLong(saveDict["m_iMonth"], out moVal)) ? (int)moVal : 1;
                    long ivVal;
                    int iv = (saveDict.ContainsKey("m_iMonthInterval") && TryGetExactLong(saveDict["m_iMonthInterval"], out ivVal)) ? (int)ivVal : 0;
                    string ivLabel = (iv >= 0 && iv < intervals.Length) ? intervals[iv] : intervals[0];

                    updates["m_strTime"] = "";
                    updateKeyOrder.Add("m_strTime");

                    updates["m_strMonth"] = string.Format(CultureInfo.InvariantCulture, "{0}\uC6D4\r{1}\r", month, ivLabel);
                    updateKeyOrder.Add("m_strMonth");
                }
                if (!entry.ContainsKey("m_strTrueTime") || string.IsNullOrEmpty(Convert.ToString(entry["m_strTrueTime"], CultureInfo.InvariantCulture)))
                {
                    updates["m_strTrueTime"] = "12\uFF1A00";
                    updateKeyOrder.Add("m_strTrueTime");
                }
                if (!entry.ContainsKey("m_strTrueYear") || string.IsNullOrEmpty(Convert.ToString(entry["m_strTrueYear"], CultureInfo.InvariantCulture)))
                {
                    updates["m_strTrueYear"] = "2026/11/18";
                    updateKeyOrder.Add("m_strTrueYear");
                }

                string updatedTitleText = UpdateTitleSlotLossless(titleJsonText, slotIndex, updates, updateKeyOrder);
                byte[] newTitleBytes = EncodeText(updatedTitleText, origTitleBytes);
                var plan = new CompanionTitlePlan();
                plan.TitleFullPath = titleFull;
                plan.OrigTitleBytes = origTitleBytes;
                plan.NewTitleBytes = newTitleBytes;
                plan.PinnedTitleHandle = titleHandle;
                titleHandle = null;
                return plan;
            }
            finally
            {
                if (titleHandle != null)
                {
                    try { titleHandle.Dispose(); } catch { }
                }
            }
        }

        private struct TitleJsonMember
        {
            public string Key;
            public int ValStart;
            public int ValEnd;
        }

        private struct TitleJsonReplacement
        {
            public int Start;
            public int End;
            public string Text;

            public TitleJsonReplacement(int start, int end, string text)
            {
                Start = start;
                End = end;
                Text = text;
            }
        }

        private static string UpdateTitleSlotLossless(string titleJsonText, int slotIndex, Dictionary<string, object> updates, List<string> updateKeyOrder)
        {
            bool titleHadBom;
            titleJsonText = StripLeadingBom(titleJsonText, out titleHadBom);

            int arrayOpen;
            int arrayClose;
            FindTopLevelArrayBounds(titleJsonText, out arrayOpen, out arrayClose);

            int elemStart;
            int elemEnd;
            FindArrayElementBounds(titleJsonText, arrayOpen + 1, arrayClose, slotIndex, out elemStart, out elemEnd);

            string elemJson = titleJsonText.Substring(elemStart, elemEnd - elemStart);
            List<TitleJsonMember> members = ScanTitleObjectMembers(elemJson);

            int objectOpen;
            int objectClose;
            FindObjectBounds(elemJson, out objectOpen, out objectClose);

            HashSet<string> present = new HashSet<string>(StringComparer.Ordinal);
            for (int i = 0; i < members.Count; i++)
            {
                present.Add(members[i].Key);
            }

            StringBuilder missing = new StringBuilder();
            if (updateKeyOrder != null && updates != null)
            {
                for (int i = 0; i < updateKeyOrder.Count; i++)
                {
                    string key = updateKeyOrder[i];
                    if (key == null || present.Contains(key) || !updates.ContainsKey(key))
                        continue;

                    if (members.Count > 0 || missing.Length > 0)
                        missing.Append(',');

                    AppendJsonFxString(key, missing);
                    missing.Append(':');
                    AppendJsonFxValue(updates[key], missing);
                    present.Add(key);
                }
            }

            StringBuilder elemSb = new StringBuilder(elemJson);
            if (missing.Length > 0)
            {
                int insertAt = members.Count > 0 ? members[members.Count - 1].ValEnd : objectClose;
                elemSb.Insert(insertAt, missing.ToString());
            }

            List<TitleJsonReplacement> replacements = new List<TitleJsonReplacement>();
            for (int i = 0; i < members.Count; i++)
            {
                TitleJsonMember member = members[i];
                if (updates != null && updates.ContainsKey(member.Key))
                {
                    StringBuilder valueSb = new StringBuilder();
                    AppendJsonFxValue(updates[member.Key], valueSb);
                    replacements.Add(new TitleJsonReplacement(member.ValStart, member.ValEnd, valueSb.ToString()));
                }
            }

            replacements.Sort(delegate(TitleJsonReplacement a, TitleJsonReplacement b)
            {
                return b.Start.CompareTo(a.Start);
            });

            for (int i = 0; i < replacements.Count; i++)
            {
                TitleJsonReplacement r = replacements[i];
                elemSb.Remove(r.Start, r.End - r.Start);
                elemSb.Insert(r.Start, r.Text);
            }

            string updated = titleJsonText.Substring(0, elemStart) + elemSb.ToString() + titleJsonText.Substring(elemEnd);
            return titleHadBom ? ("\uFEFF" + updated) : updated;
        }

        private static void FindTopLevelArrayBounds(string json, out int open, out int close)
        {
            open = -1;
            close = -1;
            bool inString = false;
            bool escape = false;
            int depth = 0;

            for (int i = 0; i < json.Length; i++)
            {
                char c = json[i];
                if (inString)
                {
                    if (escape) escape = false;
                    else if (c == '\\') escape = true;
                    else if (c == '"') inString = false;
                    continue;
                }

                if (c == '"')
                {
                    inString = true;
                    continue;
                }

                if (c == '[')
                {
                    if (open < 0)
                    {
                        open = i;
                        depth = 1;
                    }
                    else
                    {
                        depth++;
                    }
                }
                else if (c == ']')
                {
                    depth--;
                    if (open >= 0 && depth == 0)
                    {
                        close = i;
                        break;
                    }
                }
            }

            if (open < 0 || close < 0 || close <= open)
                throw new InvalidDataException("INVALID_COMPANION_TITLE");
        }

        private static void FindArrayElementBounds(string json, int start, int endExclusive, int elementIndex, out int elemStart, out int elemEnd)
        {
            elemStart = -1;
            elemEnd = -1;

            int current = 0;
            int i = start;
            while (i < endExclusive)
            {
                while (i < endExclusive && IsJsonWhitespace(json[i]))
                    i++;
                if (i >= endExclusive)
                    break;

                int itemStart = i;
                int itemEnd = ScanJsonValueEnd(json, i, endExclusive);

                if (current == elementIndex)
                {
                    elemStart = itemStart;
                    elemEnd = itemEnd;
                    return;
                }

                current++;
                i = itemEnd;
                while (i < endExclusive && IsJsonWhitespace(json[i]))
                    i++;
                if (i < endExclusive && json[i] == ',')
                    i++;
            }

            throw new InvalidDataException("COMPANION_TITLE_SLOT_OUT_OF_RANGE");
        }

        private static void FindObjectBounds(string elemJson, out int open, out int close)
        {
            open = -1;
            close = -1;
            bool inString = false;
            bool escape = false;
            int depth = 0;

            for (int i = 0; i < elemJson.Length; i++)
            {
                char c = elemJson[i];
                if (inString)
                {
                    if (escape) escape = false;
                    else if (c == '\\') escape = true;
                    else if (c == '"') inString = false;
                    continue;
                }

                if (c == '"')
                {
                    inString = true;
                    continue;
                }

                if (c == '{')
                {
                    if (open < 0)
                    {
                        open = i;
                        depth = 1;
                    }
                    else
                    {
                        depth++;
                    }
                }
                else if (c == '}')
                {
                    depth--;
                    if (open >= 0 && depth == 0)
                    {
                        close = i;
                        break;
                    }
                }
            }

            if (open < 0 || close < 0 || close <= open)
                throw new InvalidDataException("INVALID_COMPANION_TITLE_ENTRY");
        }

        private static List<TitleJsonMember> ScanTitleObjectMembers(string elemJson)
        {
            List<TitleJsonMember> result = new List<TitleJsonMember>();
            int open;
            int close;
            FindObjectBounds(elemJson, out open, out close);

            int i = open + 1;
            while (i < close)
            {
                while (i < close && IsJsonWhitespace(elemJson[i]))
                    i++;
                if (i >= close)
                    break;

                if (elemJson[i] != '"')
                    throw new InvalidDataException("INVALID_COMPANION_TITLE_ENTRY");

                int keyStart = i;
                int keyEnd = ScanJsonStringEnd(elemJson, i);
                string key = DecodeJsonString(elemJson.Substring(keyStart, keyEnd - keyStart));

                i = keyEnd;
                while (i < close && IsJsonWhitespace(elemJson[i]))
                    i++;
                if (i >= close || elemJson[i] != ':')
                    throw new InvalidDataException("INVALID_COMPANION_TITLE_ENTRY");
                i++;
                while (i < close && IsJsonWhitespace(elemJson[i]))
                    i++;

                int valStart = i;
                int valEnd = ScanJsonValueEnd(elemJson, i, close);

                TitleJsonMember member = new TitleJsonMember();
                member.Key = key;
                member.ValStart = valStart;
                member.ValEnd = valEnd;
                result.Add(member);

                i = valEnd;
                while (i < close && IsJsonWhitespace(elemJson[i]))
                    i++;
                if (i < close)
                {
                    if (elemJson[i] != ',')
                        throw new InvalidDataException("INVALID_COMPANION_TITLE_ENTRY");
                    i++;
                }
            }

            return result;
        }

        private static int ScanJsonValueEnd(string json, int start, int endExclusive)
        {
            int i = start;
            while (i < endExclusive && IsJsonWhitespace(json[i]))
                i++;
            if (i >= endExclusive)
                throw new InvalidDataException("INVALID_COMPANION_TITLE");

            char c = json[i];
            if (c == '"')
                return ScanJsonStringEnd(json, i);

            if (c == '{' || c == '[')
            {
                int depth = 0;
                bool inString = false;
                bool escape = false;

                for (; i < endExclusive; i++)
                {
                    char ch = json[i];
                    if (inString)
                    {
                        if (escape) escape = false;
                        else if (ch == '\\') escape = true;
                        else if (ch == '"') inString = false;
                        continue;
                    }

                    if (ch == '"')
                    {
                        inString = true;
                        continue;
                    }

                    if (ch == '{' || ch == '[')
                    {
                        depth++;
                    }
                    else if (ch == '}' || ch == ']')
                    {
                        depth--;
                        if (depth == 0)
                            return i + 1;
                    }
                }

                throw new InvalidDataException("INVALID_COMPANION_TITLE");
            }

            while (i < endExclusive)
            {
                char ch = json[i];
                if (ch == ',' || ch == '}' || ch == ']' || IsJsonWhitespace(ch))
                    break;
                i++;
            }
            return i;
        }

        private static int ScanJsonStringEnd(string json, int start)
        {
            if (start >= json.Length || json[start] != '"')
                throw new InvalidDataException("INVALID_COMPANION_TITLE");

            bool escape = false;
            for (int i = start + 1; i < json.Length; i++)
            {
                char c = json[i];
                if (escape) escape = false;
                else if (c == '\\') escape = true;
                else if (c == '"') return i + 1;
            }

            throw new InvalidDataException("INVALID_COMPANION_TITLE");
        }

        private static string DecodeJsonString(string quoted)
        {
            if (quoted == null || quoted.Length < 2 || quoted[0] != '"' || quoted[quoted.Length - 1] != '"')
                throw new InvalidDataException("INVALID_COMPANION_TITLE_ENTRY");

            StringBuilder sb = new StringBuilder(quoted.Length);
            for (int i = 1; i < quoted.Length - 1; i++)
            {
                char c = quoted[i];
                if (c != '\\')
                {
                    sb.Append(c);
                    continue;
                }

                i++;
                if (i >= quoted.Length - 1)
                    throw new InvalidDataException("INVALID_COMPANION_TITLE_ENTRY");

                char e = quoted[i];
                switch (e)
                {
                    case '"': sb.Append('"'); break;
                    case '\\': sb.Append('\\'); break;
                    case '/': sb.Append('/'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'u':
                        if (i + 4 >= quoted.Length)
                            throw new InvalidDataException("INVALID_COMPANION_TITLE_ENTRY");
                        int code = 0;
                        for (int j = 0; j < 4; j++)
                        {
                            i++;
                            int hv = HexValue(quoted[i]);
                            if (hv < 0)
                                throw new InvalidDataException("INVALID_COMPANION_TITLE_ENTRY");
                            code = (code << 4) | hv;
                        }
                        sb.Append((char)code);
                        break;
                    default:
                        sb.Append(e);
                        break;
                }
            }

            return sb.ToString();
        }

        private static int HexValue(char c)
        {
            if (c >= '0' && c <= '9') return c - '0';
            if (c >= 'a' && c <= 'f') return c - 'a' + 10;
            if (c >= 'A' && c <= 'F') return c - 'A' + 10;
            return -1;
        }

        private static bool IsJsonWhitespace(char c)
        {
            return c == ' ' || c == '\t' || c == '\r' || c == '\n';
        }

        private static void AppendJsonFxString(string s, StringBuilder sb)
        {
            if (s == null) { sb.Append("null"); return; }
            sb.Append('"');
            for (int i = 0; i < s.Length; i++)
            {
                char c = s[i];
                if (c == '"') sb.Append("\\\"");
                else if (c == '\\') sb.Append("\\\\");
                else if (c == '\b') sb.Append("\\b");
                else if (c == '\f') sb.Append("\\f");
                else if (c == '\n') sb.Append("\\n");
                else if (c == '\r') sb.Append("\\r");
                else if (c == '\t') sb.Append("\\t");
                else if (c == '<') sb.Append("\\u003C");
                else if (c < 0x20 || c > 0x7E) sb.Append(string.Format(CultureInfo.InvariantCulture, "\\u{0:X4}", (int)c));
                else sb.Append(c);
            }
            sb.Append('"');
        }

        private static void AppendJsonFxValue(object val, StringBuilder sb)
        {
            if (val == null) { sb.Append("null"); return; }
            if (val is bool) { sb.Append(((bool)val) ? "true" : "false"); return; }
            if (val is string) { AppendJsonFxString((string)val, sb); return; }
            if (val is int || val is long || val is double || val is float || val is decimal)
            {
                sb.Append(Convert.ToString(val, CultureInfo.InvariantCulture));
                return;
            }
            var dict = val as IDictionary;
            if (dict != null)
            {
                sb.Append('{');
                bool first = true;
                foreach (DictionaryEntry de in dict)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    AppendJsonFxString(Convert.ToString(de.Key, CultureInfo.InvariantCulture), sb);
                    sb.Append(':');
                    AppendJsonFxValue(de.Value, sb);
                }
                sb.Append('}');
                return;
            }
            var list = val as IEnumerable;
            if (list != null)
            {
                sb.Append('[');
                bool first = true;
                foreach (object item in list)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    AppendJsonFxValue(item, sb);
                }
                sb.Append(']');
                return;
            }
            AppendJsonFxString(Convert.ToString(val, CultureInfo.InvariantCulture), sb);
        }

        private static string CreateVerifiedBackup(PinnedDirectoryChain bpin, string rootFull, string targetFull, byte[] originalBytes)
        {
            FileId dummyId;
            return CreateVerifiedBackup(bpin, rootFull, targetFull, originalBytes, out dummyId);
        }

        private static string CreateVerifiedBackup(PinnedDirectoryChain bpin, string rootFull, string targetFull, byte[] originalBytes, out FileId backupId)
        {
            backupId = default(FileId);
            if (bpin == null || string.IsNullOrEmpty(bpin.RootCanon))
                throw new InvalidOperationException("PINNED_BACKUP_CONTEXT_REQUIRED");

            string canonBdir = bpin.RootCanon.TrimEnd('\\') + "\\backups";
            string relSlot = GetRelSlotFromFull(rootFull, targetFull);
            string prefix = SlotBackupPrefix(relSlot);
            if (string.IsNullOrEmpty(prefix))
                throw new InvalidOperationException("INVALID_BACKUP_SLOT");
            string ts = DateTime.UtcNow.ToString("yyyyMMdd'T'HHmmssfffffff'Z'", CultureInfo.InvariantCulture);
            string origHash = Sha256Hex(originalBytes);
            string sha8 = origHash.Substring(0, 8);

            for (int attempt = 0; attempt < 33; attempt++)
            {
                string bakName = attempt == 0
                    ? (prefix + "_" + ts + "_" + sha8 + ".bak")
                    : (prefix + "_" + ts + "_" + Guid.NewGuid().ToString("N").Substring(0, 4) + "_" + sha8 + ".bak");
                string bakPath = Path.Combine(canonBdir, bakName);
                if (File.Exists(bakPath) || Directory.Exists(bakPath) || IsReparsePoint(bakPath, false))
                    continue;

                FileId stagedBakId;
                string tmp = StageTempBytes(bpin.RootCanon, bakPath, originalBytes, out stagedBakId);
                if (attempt == 0 && Environment.GetEnvironmentVariable("TWX_SIMULATE_BACKUP_NAME_RACE") == "1")
                {
                    if (!File.Exists(bakPath))
                        File.WriteAllText(bakPath, "{\"preexisting_backup\":1}", new UTF8Encoding(false));
                }

                try
                {
                    CommitVerifiedStagedTemp(bpin, tmp, stagedBakId, origHash, bakPath, false, "");
                }
                catch (InvalidOperationException ex)
                {
                    if (string.Equals(ex.Message, "CONFLICT_MODIFIED", StringComparison.Ordinal))
                        continue;
                    throw;
                }

                byte[] writtenBytes;
                using (SafeFileHandle sfh = OpenVerifiedReadPin(bpin, bakPath, out writtenBytes, out backupId))
                {
                }
                if (!backupId.EqualsId(stagedBakId) || !string.Equals(Sha256Hex(writtenBytes), origHash, StringComparison.OrdinalIgnoreCase))
                    throw new IOException("BACKUP_HASH_MISMATCH");

                return bakPath;
            }

            throw new IOException("BACKUP_NAME_COLLISION_EXHAUSTED");
        }

        private sealed class PinnedFinalVerificationSet : IDisposable
        {
            private readonly List<SafeFileHandle> _handles = new List<SafeFileHandle>();
            private bool _disposed;

            public void Add(SafeFileHandle h)
            {
                if (h != null)
                    _handles.Add(h);
            }

            public void Dispose()
            {
                if (_disposed)
                    return;
                _disposed = true;
                for (int i = _handles.Count - 1; i >= 0; i--)
                {
                    try { _handles[i].Dispose(); } catch { }
                }
                _handles.Clear();
            }
        }

        private static string OpenAndVerifyPinnedFile(PinnedDirectoryChain pin, string filePath, FileId expectedId, string expectedSha, PinnedFinalVerificationSet holdSet)
        {
            byte[] bytes;
            FileId actualId;
            SafeFileHandle sfh = OpenVerifiedReadPin(pin, filePath, out bytes, out actualId);
            try
            {
                string actualSha = Sha256Hex(bytes);
                bool idOk = !expectedId.IsValid || actualId.EqualsId(expectedId);
                bool shaOk = string.Equals(actualSha, expectedSha, StringComparison.OrdinalIgnoreCase);
                if (!(idOk && shaOk))
                    throw new InvalidOperationException("STAGED_OR_COMMITTED_FILE_MODIFIED");
                if (holdSet != null)
                {
                    holdSet.Add(sfh);
                    sfh = null;
                }
                return actualSha;
            }
            finally
            {
                if (sfh != null)
                {
                    try { sfh.Dispose(); } catch { }
                }
            }
        }

        private static string VerifyPinnedFileIdentityAndSha(PinnedDirectoryChain pin, string filePath, FileId expectedId, string expectedSha)
        {
            return OpenAndVerifyPinnedFile(pin, filePath, expectedId, expectedSha, null);
        }

        private static void CommitVerifiedStagedTemp(
            PinnedDirectoryChain pin,
            string tmp,
            FileId expectedId,
            string expectedSha,
            string targetFull,
            bool allowReplace,
            string tamperTag)
        {
            CommitVerifiedStagedTemp(
                pin,
                tmp,
                expectedId,
                expectedSha,
                targetFull,
                allowReplace,
                tamperTag,
                null);
        }

        private static bool DeleteTempIfIdMatches(string rootCanon, string tmpPath, FileId expectedId)
        {
            if (string.IsNullOrEmpty(tmpPath) || !expectedId.IsValid || string.IsNullOrEmpty(rootCanon))
                return false;

            string normRoot = rootCanon.TrimEnd('\\');
            IntPtr h = CreateFileW(tmpPath, GENERIC_READ | DELETE_ACCESS, 0u, IntPtr.Zero, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, IntPtr.Zero);
            if (h == INVALID_HANDLE_VALUE)
                return false;

            try
            {
                using (SafeFileHandle sfh = new SafeFileHandle(h, true))
                {
                    BY_HANDLE_FILE_INFORMATION bi;
                    if (!GetFileInformationByHandle(sfh.DangerousGetHandle(), out bi))
                        return false;
                    if ((bi.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                        return false;
                    if ((bi.FileAttributes & 0x10u) != 0)
                        return false;
                    if (bi.NumberOfLinks != 1u)
                        return false;

                    FileId openedFid;
                    openedFid.VolumeSerialNumber = bi.VolumeSerialNumber;
                    openedFid.FileIndexHigh = bi.FileIndexHigh;
                    openedFid.FileIndexLow = bi.FileIndexLow;
                    openedFid.IsValid = true;
                    if (!openedFid.EqualsId(expectedId))
                        return false;

                    string finalPath = ReadFinalPathByHandle(sfh.DangerousGetHandle());
                    if (!finalPath.StartsWith(normRoot + "\\", StringComparison.OrdinalIgnoreCase))
                        return false;
                    if (!string.Equals(Path.GetFileName(finalPath), Path.GetFileName(tmpPath), StringComparison.OrdinalIgnoreCase))
                        return false;

                    FILE_DISPOSITION_INFO disp = new FILE_DISPOSITION_INFO();
                    disp.DeleteFile = true;
                    bool deleted = SetFileInformationByHandle(sfh.DangerousGetHandle(), FileDispositionInfo, ref disp, Marshal.SizeOf(typeof(FILE_DISPOSITION_INFO)));
                    GC.KeepAlive(sfh);
                    return deleted;
                }
            }
            catch
            {
                return false;
            }
        }

        private static void CommitVerifiedStagedTemp(
            PinnedDirectoryChain pin,
            string tmp,
            FileId expectedId,
            string expectedSha,
            string targetFull,
            bool allowReplace,
            string tamperTag,
            IDisposable releaseBeforeMove)
        {
            bool renamed = false;
            try
            {
                if (!string.IsNullOrEmpty(tamperTag) &&
                    string.Equals(Environment.GetEnvironmentVariable("TWX_SIMULATE_STAGED_TEMP_TAMPER"), tamperTag, StringComparison.Ordinal))
                {
                    File.WriteAllText(tmp, "{\"tampered\":1}", new UTF8Encoding(false));
                }
                if (!string.IsNullOrEmpty(tamperTag) &&
                    string.Equals(Environment.GetEnvironmentVariable("TWX_SIMULATE_STAGED_TEMP_SWAP"), tamperTag, StringComparison.Ordinal))
                {
                    File.Delete(tmp);
                    File.WriteAllText(tmp, "{\"foreign_at_tmp\":1}", new UTF8Encoding(false));
                }

                using (SafeFileHandle tmpHandle = OpenVerifiedExclusiveTempForRename(pin, tmp, expectedId, expectedSha))
                {
                    if (releaseBeforeMove != null &&
                        !string.IsNullOrEmpty(tamperTag) &&
                        string.Equals(Environment.GetEnvironmentVariable("TWX_SIMULATE_EXT_WRITE_DURING_STAGED_VERIFY"), tamperTag, StringComparison.Ordinal))
                    {
                        bool probeSucceeded = false;
                        try
                        {
                            using (FileStream probe = new FileStream(targetFull, FileMode.Open, FileAccess.Write, FileShare.ReadWrite))
                            {
                                probe.Flush();
                                probeSucceeded = true;
                            }
                        }
                        catch (IOException)
                        {
                        }

                        if (probeSucceeded)
                            throw new InvalidOperationException("TARGET_PIN_NOT_HELD_DURING_STAGED_VERIFY");
                    }

                    AssertExclusiveTempLocked(tmp);

                    CommitStagedTemp(pin, tmpHandle, tmp, targetFull, allowReplace, releaseBeforeMove);
                    renamed = true;
                }
            }
            catch
            {
                if (!renamed)
                {
                    DeleteTempIfIdMatches(pin != null ? pin.RootCanon : null, tmp, expectedId);
                }
                throw;
            }
        }

        private static string VerifyPostCommitAndBackupsOrRollback(
            PinnedDirectoryChain slotPin,
            PinnedDirectoryChain bpin,
            string slotFullPath,
            bool existed,
            byte[] origSlotBytes,
            byte[] writtenSlotBytes,
            FileId writtenSlotId,
            string expectedNewSlotSha,
            string slotBackupPath,
            FileId slotBackupId,
            string origSlotSha,
            CompanionTitlePlan titlePlan,
            string titleFullPath,
            FileId writtenTitleId,
            string titleBackupPath,
            FileId titleBackupId,
            string origTitleSha,
            string expectedNewTitleSha,
            PinnedFinalVerificationSet holdSet)
        {
            try
            {
                if (string.Equals(Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER"), "slot", StringComparison.Ordinal))
                    File.WriteAllText(slotFullPath, "{\"tampered_slot\":1}", new UTF8Encoding(false));

                if (string.Equals(Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER"), "title_final", StringComparison.Ordinal) &&
                    titlePlan != null &&
                    !string.IsNullOrEmpty(titleFullPath))
                {
                    File.WriteAllText(titleFullPath, "{\"tampered_title_final\":1}", new UTF8Encoding(false));
                }

                if (string.Equals(Environment.GetEnvironmentVariable("TWX_SIMULATE_POST_COMMIT_TAMPER"), "backup", StringComparison.Ordinal) &&
                    !string.IsNullOrEmpty(slotBackupPath))
                {
                    File.WriteAllText(slotBackupPath, "{\"tampered_backup\":1}", new UTF8Encoding(false));
                }

                string verifiedSlotSha = OpenAndVerifyPinnedFile(slotPin, slotFullPath, writtenSlotId, expectedNewSlotSha, holdSet);

                if (titlePlan != null && !string.IsNullOrEmpty(titleFullPath))
                {
                    OpenAndVerifyPinnedFile(slotPin, titleFullPath, writtenTitleId, expectedNewTitleSha, holdSet);
                }

                if (!string.IsNullOrEmpty(slotBackupPath))
                    OpenAndVerifyPinnedFile(bpin, slotBackupPath, slotBackupId, origSlotSha, holdSet);

                if (!string.IsNullOrEmpty(titleBackupPath))
                    OpenAndVerifyPinnedFile(bpin, titleBackupPath, titleBackupId, origTitleSha, holdSet);

                return verifiedSlotSha;
            }
            catch
            {
                if (holdSet != null)
                {
                    holdSet.Dispose();
                }

                if (titlePlan != null)
                {
                    try
                    {
                        TryRollbackReplacedSlot(slotPin, titleFullPath, true, titlePlan.OrigTitleBytes, titlePlan.NewTitleBytes, writtenTitleId);
                    }
                    catch { }
                }

                try
                {
                    TryRollbackReplacedSlot(slotPin, slotFullPath, existed, origSlotBytes, writtenSlotBytes, writtenSlotId);
                }
                catch { }

                throw;
            }
        }

        private static void AssertFinalPinWriteBlocked(string path)
        {
            try
            {
                using (FileStream probe = new FileStream(path, FileMode.Open, FileAccess.Write, FileShare.ReadWrite))
                {
                }
            }
            catch (IOException)
            {
                return;
            }
            throw new InvalidOperationException("FINAL_PIN_NOT_HELD_THROUGH_COMPLETION");
        }

        private static void FinalizeVerifiedWriteAndPrune(SaveWriteResult res, PinnedDirectoryChain bpin, string rootFull, string slotFullPath, string titleFullPath, string titleBackupPath, string verifiedSlotSha)
        {
            res.TargetPath = slotFullPath;

            if (!string.IsNullOrEmpty(res.BackupPath))
            {
                string slotRel = GetRelSlotFromFull(rootFull, slotFullPath);
                PruneBackups(bpin, slotRel, System.IO.Path.GetFileName(res.BackupPath));
            }

            if (!string.IsNullOrEmpty(titleBackupPath) && !string.IsNullOrEmpty(titleFullPath))
            {
                string titleRel = GetRelSlotFromFull(rootFull, titleFullPath);
                PruneBackups(bpin, titleRel, System.IO.Path.GetFileName(titleBackupPath));
            }

            if (string.Equals(Environment.GetEnvironmentVariable("TWX_VERIFY_FINAL_PINS_HELD_DURING_PRUNE"), "1", StringComparison.Ordinal))
            {
                AssertFinalPinWriteBlocked(slotFullPath);
                if (!string.IsNullOrEmpty(titleFullPath))
                    AssertFinalPinWriteBlocked(titleFullPath);
                if (!string.IsNullOrEmpty(res.BackupPath))
                    AssertFinalPinWriteBlocked(res.BackupPath);
                if (!string.IsNullOrEmpty(titleBackupPath))
                    AssertFinalPinWriteBlocked(titleBackupPath);
            }

            res.Sha256 = verifiedSlotSha;
            res.Success = true;
        }

        private static void DisposeFinalCommitResources(ref PinnedFinalVerificationSet finalPins, ref PinnedDirectoryChain bpin)
        {
            if (finalPins != null)
            {
                try { finalPins.Dispose(); } catch { }
                finalPins = null;
            }

            if (bpin != null)
            {
                try { bpin.Dispose(); } catch { }
                bpin = null;
            }
        }

        private static void PruneBackups(PinnedDirectoryChain bpin, string relSlot, string keepFileName)
        {
            if (bpin == null || string.IsNullOrEmpty(bpin.RootCanon) || string.IsNullOrEmpty(relSlot))
                return;

            string canonBdir = bpin.RootCanon.TrimEnd('\\') + "\\backups";
            if (!Directory.Exists(canonBdir))
                return;

            if (Environment.GetEnvironmentVariable("TWX_VERIFY_PINNED_BACKUPS_SHARE_MODE") == "1")
            {
                string probe = canonBdir + "_hijack_probe";
                bool enforced = true;
                try
                {
                    Directory.Move(canonBdir, probe);
                    enforced = false;
                }
                catch (IOException)
                {
                    enforced = !Directory.Exists(probe) && Directory.Exists(canonBdir);
                }
                catch (UnauthorizedAccessException)
                {
                    enforced = !Directory.Exists(probe) && Directory.Exists(canonBdir);
                }
                if (!enforced)
                {
                    if (Directory.Exists(probe) && !Directory.Exists(canonBdir))
                    {
                        try { Directory.Move(probe, canonBdir); } catch { }
                    }
                    throw new InvalidOperationException("PINNED_BACKUPS_NOT_ENFORCED");
                }
            }

            try
            {
                if (IsReparsePoint(canonBdir, true) || !Directory.Exists(canonBdir)) return;
                string[] files = Directory.GetFiles(canonBdir, "*.bak", SearchOption.TopDirectoryOnly);
                List<string> matched = new List<string>();
                for (int i = 0; i < files.Length; i++)
                {
                    if (IsBackupForSlot(Path.GetFileName(files[i]), relSlot))
                        matched.Add(files[i]);
                }
                matched.Sort(delegate(string a, string b) { return StringComparer.Ordinal.Compare(Path.GetFileName(a), Path.GetFileName(b)); });
                int remaining = matched.Count;
                for (int i = 0; i < matched.Count && remaining > MaxBackups; i++)
                {
                    if (!string.IsNullOrEmpty(keepFileName) && string.Equals(Path.GetFileName(matched[i]), keepFileName, StringComparison.OrdinalIgnoreCase))
                        continue;
                    string candidateFull = matched[i];
                    try
                    {
                        byte[] dummyBytes = null;
                        using (SafeFileHandle sfh = OpenVerifiedReadPin(bpin, candidateFull, GENERIC_READ | DELETE_ACCESS, out dummyBytes))
                        {
                            string finalPath = ReadFinalPathByHandle(sfh.DangerousGetHandle());
                            if (!finalPath.StartsWith(canonBdir + "\\", StringComparison.OrdinalIgnoreCase))
                                throw new InvalidOperationException("BACKUP_PATH_ESCAPE");
                            FILE_DISPOSITION_INFO disp = new FILE_DISPOSITION_INFO();
                            disp.DeleteFile = true;
                            if (!SetFileInformationByHandle(sfh.DangerousGetHandle(), FileDispositionInfo, ref disp, Marshal.SizeOf(typeof(FILE_DISPOSITION_INFO))))
                                throw new IOException("BACKUP_DELETE_FAILED");
                            GC.KeepAlive(sfh);
                            remaining--;
                        }
                    }
                    catch { }
                }
            }
            catch { }
        }

        private static string StageTempBytes(string rootCanon, string targetFull, byte[] payload)
        {
            FileId dummyId;
            return StageTempBytes(rootCanon, targetFull, payload, out dummyId);
        }

        private static string StageTempBytes(string rootCanon, string targetFull, byte[] payload, out FileId stagedId)
        {
            stagedId = default(FileId);
            if (string.IsNullOrEmpty(rootCanon))
                throw new InvalidOperationException("CANON_ROOT_EMPTY");
            string normRoot = rootCanon.TrimEnd('\\');
            string dir = Path.GetDirectoryName(targetFull);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir)) Directory.CreateDirectory(dir);
            string tmp = Path.Combine(dir, "." + Path.GetFileName(targetFull) + "." + Guid.NewGuid().ToString("N") + ".tmp");
            FileId createdId = default(FileId);
            bool staged = false;
            try
            {
                using (var fs = new FileStream(tmp, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    IntPtr h = fs.SafeFileHandle.DangerousGetHandle();
                    BY_HANDLE_FILE_INFORMATION bi;
                    if (!GetFileInformationByHandle(h, out bi))
                        throw new InvalidOperationException("INFO_TEMP_FILE_FAILED");
                    FileId initFid;
                    initFid.VolumeSerialNumber = bi.VolumeSerialNumber;
                    initFid.FileIndexHigh = bi.FileIndexHigh;
                    initFid.FileIndexLow = bi.FileIndexLow;
                    initFid.IsValid = true;
                    createdId = initFid;

                    if ((bi.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                        throw new InvalidOperationException("REPARSE_POINT_REJECTED");
                    if (bi.NumberOfLinks > 1)
                        throw new InvalidOperationException("HARD_LINK_REJECTED");

                    StringBuilder sb = new StringBuilder(1024);
                    uint len = GetFinalPathNameByHandleW(h, sb, sb.Capacity, 0);
                    while (len >= (uint)sb.Capacity)
                    {
                        int newCap = (int)len + 2;
                        if (newCap <= sb.Capacity)
                            throw new InvalidOperationException("FINAL_PATH_FAILED");
                        sb = new StringBuilder(newCap);
                        len = GetFinalPathNameByHandleW(h, sb, sb.Capacity, 0);
                    }
                    if (len == 0)
                        throw new InvalidOperationException("FINAL_PATH_FAILED");

                    string rawFinal = sb.ToString();
                    if (rawFinal.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase))
                        throw new InvalidOperationException("UNC_PATH_REJECTED");

                    string finalTmp = StripLongPrefix(rawFinal);
                    if (!finalTmp.StartsWith(normRoot + "\\", StringComparison.OrdinalIgnoreCase))
                        throw new InvalidOperationException("CANONICAL_MISMATCH");

                    fs.Write(payload, 0, payload.Length);

                    if (!GetFileInformationByHandle(h, out bi))
                        throw new InvalidOperationException("INFO_TEMP_FILE_FAILED");
                    if ((bi.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                        throw new InvalidOperationException("REPARSE_POINT_REJECTED");
                    if (bi.NumberOfLinks > 1)
                        throw new InvalidOperationException("HARD_LINK_REJECTED");

                    fs.Flush(true);
                    if (!GetFileInformationByHandle(h, out bi))
                        throw new InvalidOperationException("INFO_TEMP_FILE_FAILED");
                    FileId stagedFid;
                    stagedFid.VolumeSerialNumber = bi.VolumeSerialNumber;
                    stagedFid.FileIndexHigh = bi.FileIndexHigh;
                    stagedFid.FileIndexLow = bi.FileIndexLow;
                    stagedFid.IsValid = true;
                    stagedId = stagedFid;
                }
                staged = true;
                return tmp;
            }
            finally
            {
                if (!staged)
                {
                    DeleteTempIfIdMatches(normRoot, tmp, createdId);
                }
            }
        }

        private static void CommitStagedTemp(string rootCanon, string tmp, FileId expectedId, string targetFull, bool allowReplace)
        {
            bool renamed = false;
            try
            {
                if (allowReplace)
                {
                    if (IsReparsePoint(targetFull, false) || IsReparsePoint(targetFull, true))
                        throw new InvalidOperationException("REPARSE_POINT_REJECTED");
                }

                IntPtr h = CreateFileW(tmp, GENERIC_READ | DELETE_ACCESS, 0u, IntPtr.Zero, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, IntPtr.Zero);
                if (h == INVALID_HANDLE_VALUE)
                    throw new IOException("OPEN_FILE_FAILED_" + Marshal.GetLastWin32Error().ToString(CultureInfo.InvariantCulture));

                using (SafeFileHandle sfh = new SafeFileHandle(h, true))
                {
                    BY_HANDLE_FILE_INFORMATION bi;
                    if (!GetFileInformationByHandle(sfh.DangerousGetHandle(), out bi))
                        throw new InvalidOperationException("INFO_FILE_FAILED");
                    if ((bi.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
                        throw new InvalidOperationException("REPARSE_POINT_REJECTED");
                    if ((bi.FileAttributes & 0x10u) != 0)
                        throw new InvalidOperationException("IS_DIRECTORY");
                    if (bi.NumberOfLinks != 1u)
                        throw new InvalidOperationException("HARD_LINK_REJECTED");

                    FileId openedFid;
                    openedFid.VolumeSerialNumber = bi.VolumeSerialNumber;
                    openedFid.FileIndexHigh = bi.FileIndexHigh;
                    openedFid.FileIndexLow = bi.FileIndexLow;
                    openedFid.IsValid = true;
                    if (expectedId.IsValid && !openedFid.EqualsId(expectedId))
                        throw new InvalidOperationException("STAGED_OR_COMMITTED_FILE_MODIFIED");

                    AssertExclusiveTempLocked(tmp);
                    RenameByOpenHandle(sfh, targetFull, allowReplace);
                    renamed = true;
                }
            }
            finally
            {
                if (!renamed)
                {
                    DeleteTempIfIdMatches(rootCanon, tmp, expectedId);
                }
            }
        }

        private static void CommitStagedTemp(PinnedDirectoryChain pin, SafeFileHandle exclusiveTmpHandle, string tmpPathForCleanup, string targetFull, bool allowReplace, IDisposable releaseImmediatelyBeforeMove)
        {
            try
            {
                if (allowReplace && releaseImmediatelyBeforeMove == null)
                {
                    if (IsReparsePoint(targetFull, false) || IsReparsePoint(targetFull, true))
                        throw new InvalidOperationException("REPARSE_POINT_REJECTED");
                }

                if (releaseImmediatelyBeforeMove != null)
                    AssertTargetPinHeldAtMoveEntry(targetFull);

                AssertExclusiveTempLocked(tmpPathForCleanup);

                if (releaseImmediatelyBeforeMove != null)
                    releaseImmediatelyBeforeMove.Dispose();
                RenameByOpenHandle(exclusiveTmpHandle, targetFull, allowReplace);
            }
            finally
            {
                if (releaseImmediatelyBeforeMove != null)
                {
                    try { releaseImmediatelyBeforeMove.Dispose(); } catch { }
                }
                if (exclusiveTmpHandle != null)
                {
                    try { exclusiveTmpHandle.Dispose(); } catch { }
                }
            }
        }

        private static void AtomicWriteBytes(string rootCanon, string targetFull, byte[] payload)
        {
            FileId tmpId;
            string tmp = StageTempBytes(rootCanon, targetFull, payload, out tmpId);
            CommitStagedTemp(rootCanon, tmp, tmpId, targetFull, true);
        }

        private static string DecodeText(byte[] bytes)
        {
            if (bytes == null || bytes.Length == 0) return "";
            if ((bytes.Length >= 4 && ((bytes[0] == 0xFF && bytes[1] == 0xFE && bytes[2] == 0x00 && bytes[3] == 0x00) || (bytes[0] == 0x00 && bytes[1] == 0x00 && bytes[2] == 0xFE && bytes[3] == 0xFF))) || (bytes.Length >= 2 && ((bytes[0] == 0xFF && bytes[1] == 0xFE) || (bytes[0] == 0xFE && bytes[1] == 0xFF))))
                throw new InvalidDataException("UNSUPPORTED_UTF_BOM");
            if (bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF)
            {
                if (bytes.Length >= 6 && bytes[3] == 0xEF && bytes[4] == 0xBB && bytes[5] == 0xBF)
                    throw new InvalidDataException("DOUBLE_UTF8_BOM");
                string decoded = new UTF8Encoding(false, true).GetString(bytes, 3, bytes.Length - 3);
                if (decoded.Length > 0 && decoded[0] == '\uFEFF')
                    throw new InvalidDataException("DOUBLE_UTF8_BOM");
                return decoded;
            }
            string plain = new UTF8Encoding(false, true).GetString(bytes);
            return plain;
        }

        private static byte[] EncodeText(string text, byte[] originalBytes)
        {
            bool textHadBom;
            string clean = StripLeadingBom(text, out textHadBom);
            if (ContainsUnpairedSurrogate(clean)) throw new ArgumentException("INVALID_UTF8_SURROGATE");
            byte[] body = new UTF8Encoding(false, true).GetBytes(clean);
            bool origHadBom = originalBytes != null && originalBytes.Length >= 3 &&
                originalBytes[0] == 0xEF && originalBytes[1] == 0xBB && originalBytes[2] == 0xBF;
            if (textHadBom || origHadBom)
            {
                byte[] withBom = new byte[body.Length + 3];
                withBom[0] = 0xEF;
                withBom[1] = 0xBB;
                withBom[2] = 0xBF;
                Buffer.BlockCopy(body, 0, withBom, 3, body.Length);
                return withBom;
            }
            return body;
        }

        internal static bool ContainsUnpairedSurrogate(string s)
        {
            if (string.IsNullOrEmpty(s)) return false;
            for (int i = 0; i < s.Length; i++)
            {
                char c = s[i];
                if (char.IsHighSurrogate(c))
                {
                    if (i + 1 >= s.Length || !char.IsLowSurrogate(s[i + 1])) return true;
                    i++;
                }
                else if (char.IsLowSurrogate(c))
                {
                    return true;
                }
            }
            return false;
        }

        internal static bool ContainsUnpairedSurrogateValue(object val)
        {
            if (val == null) return false;
            string text = val as string;
            if (text != null) return ContainsUnpairedSurrogate(text);
            if (val is char) return char.IsSurrogate((char)val);
            if (val is System.Collections.IDictionary)
            {
                System.Collections.IDictionary dictionary = (System.Collections.IDictionary)val;
                foreach (System.Collections.DictionaryEntry entry in dictionary)
                {
                    if (ContainsUnpairedSurrogateValue(entry.Key) || ContainsUnpairedSurrogateValue(entry.Value))
                    {
                        return true;
                    }
                }
                return false;
            }
            else if (val is System.Collections.IEnumerable)
            {
                System.Collections.IEnumerable enumerable = (System.Collections.IEnumerable)val;
                foreach (object item in enumerable)
                {
                    if (ContainsUnpairedSurrogateValue(item))
                    {
                        return true;
                    }
                }
            }
            return false;
        }

        private static int HexDigitValue(char c)
        {
            if (c >= '0' && c <= '9') return c - '0';
            if (c >= 'a' && c <= 'f') return c - 'a' + 10;
            if (c >= 'A' && c <= 'F') return c - 'A' + 10;
            return -1;
        }

        private static int TryReadJsonHex4(string s, int index)
        {
            if (s == null || index < 0 || index + 4 > s.Length) return -1;
            int value = 0;
            for (int i = 0; i < 4; i++)
            {
                int digit = HexDigitValue(s[index + i]);
                if (digit < 0) return -1;
                value = (value << 4) | digit;
            }
            return value;
        }

        internal static bool ContainsUnpairedJsonSurrogateEscape(string json)
        {
            if (string.IsNullOrEmpty(json)) return false;
            int i = 0;
            while (i < json.Length)
            {
                if (json[i] != '\\')
                {
                    i++;
                    continue;
                }

                int slashCount = 0;
                int j = i;
                while (j < json.Length && json[j] == '\\')
                {
                    slashCount++;
                    j++;
                }

                if ((slashCount & 1) == 1 && j + 4 < json.Length && json[j] == 'u')
                {
                    int codeUnit = TryReadJsonHex4(json, j + 1);
                    if (codeUnit >= 0)
                    {
                        char c = (char)codeUnit;
                        if (char.IsHighSurrogate(c))
                        {
                            int next = j + 5;
                            if (next + 5 < json.Length && json[next] == '\\' && json[next + 1] == 'u')
                            {
                                int lowCodeUnit = TryReadJsonHex4(json, next + 2);
                                if (lowCodeUnit >= 0 && char.IsLowSurrogate((char)lowCodeUnit))
                                {
                                    i = next + 6;
                                    continue;
                                }
                            }
                            return true;
                        }
                        if (char.IsLowSurrogate(c)) return true;
                    }
                }

                i = j;
            }
            return false;
        }

        private static string Sha256Hex(byte[] bytes)
        {
            using (SHA256 sha = SHA256.Create())
            {
                byte[] hash = sha.ComputeHash(bytes ?? new byte[0]);
                var sb = new StringBuilder(hash.Length * 2);
                for (int i = 0; i < hash.Length; i++)
                    sb.Append(hash[i].ToString("x2", CultureInfo.InvariantCulture));
                return sb.ToString();
            }
        }
    }
}
