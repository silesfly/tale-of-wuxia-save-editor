using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace TaleOfWuxiaSaveEditor
{
    internal static class SaveEditor
    {
        private const string AppDir = "TaleOfWuxiaSaveEditor";
        private static string s_html;
        private static string s_wvFolder;

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool SetDllDirectory(string lpPathName);

        [STAThread]
        private static int Main(string[] args)
        {
            InstallAssemblyResolve();
            s_wvFolder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), AppDir, "wv2");
            try { Directory.CreateDirectory(s_wvFolder); } catch { }
            ExtractLoader();
            s_html = LoadHtml();

            bool selfTest = args != null && args.Any(a => string.Equals(a, "--self-test", StringComparison.OrdinalIgnoreCase));
            if (selfTest)
            {
                try { return RunSelfTestEntry(args); }
                catch (Exception ex) { try { Console.Error.WriteLine(ex); } catch { } return 1; }
            }

            return RunGuiEntry();
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static int RunSelfTestEntry(string[] args)
        {
            return SelfTest.Run(args);
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static int RunGuiEntry()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
            return 0;
        }

        private static void InstallAssemblyResolve()
        {
            AppDomain.CurrentDomain.AssemblyResolve += OnResolve;
        }

        private static Assembly OnResolve(object sender, ResolveEventArgs e)
        {
            try
            {
                string simple = new AssemblyName(e.Name).Name + ".dll";
                if (!simple.StartsWith("Microsoft.Web.WebView2", StringComparison.OrdinalIgnoreCase))
                    return null;
                Assembly asm = Assembly.GetExecutingAssembly();
                foreach (string name in asm.GetManifestResourceNames())
                {
                    if (string.Equals(name, simple, StringComparison.OrdinalIgnoreCase) ||
                        name.EndsWith("." + simple, StringComparison.OrdinalIgnoreCase))
                    {
                        using (Stream s = asm.GetManifestResourceStream(name))
                        {
                            if (s == null) continue;
                            using (MemoryStream ms = new MemoryStream())
                            {
                                s.CopyTo(ms);
                                return Assembly.Load(ms.ToArray());
                            }
                        }
                    }
                }
                string basePath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, simple);
                if (File.Exists(basePath)) return Assembly.LoadFrom(basePath);
            }
            catch { }
            return null;
        }

        private static void ExtractLoader()
        {
            try
            {
                Assembly asm = Assembly.GetExecutingAssembly();
                string target = Path.Combine(s_wvFolder, "WebView2Loader.dll");
                foreach (string name in asm.GetManifestResourceNames())
                {
                    if (string.Equals(name, "WebView2Loader.dll", StringComparison.OrdinalIgnoreCase) ||
                        name.EndsWith(".WebView2Loader.dll", StringComparison.OrdinalIgnoreCase))
                    {
                        using (Stream s = asm.GetManifestResourceStream(name))
                        {
                            if (s != null)
                            {
                                using (FileStream f = File.Create(target))
                                    s.CopyTo(f);
                                break;
                            }
                        }
                    }
                }
                if (!File.Exists(target))
                {
                    string alt = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "WebView2Loader.dll");
                    if (File.Exists(alt) && !string.Equals(alt, target, StringComparison.OrdinalIgnoreCase))
                        File.Copy(alt, target, true);
                }
                SetDllDirectory(s_wvFolder);
            }
            catch { }
        }

        private static string LoadHtml()
        {
            Assembly asm = Assembly.GetExecutingAssembly();
            foreach (string name in asm.GetManifestResourceNames())
            {
                if (name.EndsWith("TaleOfWuxiaSaveEditor-v1.0.html", StringComparison.OrdinalIgnoreCase))
                {
                    using (Stream s = asm.GetManifestResourceStream(name))
                    {
                        if (s != null)
                        {
                            using (StreamReader r = new StreamReader(s, Encoding.UTF8))
                                return r.ReadToEnd();
                        }
                    }
                }
            }
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string[] candidates = new string[]
            {
                Path.Combine(baseDir, "TaleOfWuxiaSaveEditor-v1.0.html"),
                Path.Combine(baseDir, "dist", "TaleOfWuxiaSaveEditor-v1.0.html")
            };
            for (int i = 0; i < candidates.Length; i++)
            {
                if (File.Exists(candidates[i])) return File.ReadAllText(candidates[i], Encoding.UTF8);
            }
            throw new FileNotFoundException("Embedded HTML and dist fallback not found.");
        }

        internal static string Html { get { return s_html; } }

        internal static async Task InitializeWebViewAsync(WebView2 webView)
        {
            CoreWebView2Environment env = await CoreWebView2Environment.CreateAsync(null, s_wvFolder, null);
            await webView.EnsureCoreWebView2Async(env);
            CoreWebView2Settings settings = webView.CoreWebView2.Settings;
            settings.AreDevToolsEnabled = false;
            settings.AreDefaultContextMenusEnabled = false;
            settings.IsStatusBarEnabled = false;
            settings.AreHostObjectsAllowed = false;
        }

        internal sealed class LocalBridgeServer : IDisposable
        {
            internal const int MaxJsonEnvelopeBytes = SaveStore.MaxSaveBytes * 6 + 1024 * 1024;
            private readonly HttpListener _listener = new HttpListener();
            private readonly JavaScriptSerializer _json = new JavaScriptSerializer { MaxJsonLength = MaxJsonEnvelopeBytes };
            private readonly int _port;
            private readonly SaveStore.FileId _rootId;
            private CancellationTokenSource _cts;
            private Task _loop;

            public string Root { get; private set; }
            public string Token { get; private set; }
            public string Url { get; private set; }

            public LocalBridgeServer(string root)
            {
                string canonRoot;
                _rootId = SaveStore.EnsureSafeRootDirectory(root, out canonRoot);
                Root = canonRoot;
                _port = FindFreePort();
                Url = "http://127.0.0.1:" + _port.ToString(CultureInfo.InvariantCulture) + "/";
                _listener.Prefixes.Add(Url);
                Token = NewToken();
            }

            private static int FindFreePort()
            {
                TcpListener l = new TcpListener(IPAddress.Loopback, 0);
                l.Start();
                int port = ((IPEndPoint)l.LocalEndpoint).Port;
                l.Stop();
                return port;
            }

            private static string NewToken()
            {
                byte[] bytes = new byte[24];
                using (RNGCryptoServiceProvider rng = new RNGCryptoServiceProvider())
                    rng.GetBytes(bytes);
                var sb = new StringBuilder(bytes.Length);
                const string chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
                for (int i = 0; i < bytes.Length; i++) sb.Append(chars[bytes[i] % chars.Length]);
                return sb.ToString();
            }

            public void Start()
            {
                _cts = new CancellationTokenSource();
                _listener.Start();
                _loop = Task.Run(() => Loop(_cts.Token));
            }

            private async Task Loop(CancellationToken ct)
            {
                while (!ct.IsCancellationRequested)
                {
                    HttpListenerContext ctx;
                    try { ctx = await _listener.GetContextAsync(); }
                    catch { break; }
                    Task.Run(() => Handle(ctx));
                }
            }

            private bool IsValidHost(string host)
            {
                if (string.IsNullOrEmpty(host)) return false;
                string p = _port.ToString(CultureInfo.InvariantCulture);
                return string.Equals(host, "127.0.0.1:" + p, StringComparison.Ordinal) ||
                       string.Equals(host, "localhost:" + p, StringComparison.OrdinalIgnoreCase);
            }

            private bool IsValidOrigin(string origin)
            {
                if (string.IsNullOrEmpty(origin)) return true;
                string p = _port.ToString(CultureInfo.InvariantCulture);
                return string.Equals(origin, "http://127.0.0.1:" + p, StringComparison.Ordinal) ||
                       string.Equals(origin, "http://localhost:" + p, StringComparison.OrdinalIgnoreCase);
            }

            private static bool ConstantTimeEquals(string a, string b)
            {
                if (a == null || b == null || a.Length != b.Length) return false;
                int diff = 0;
                for (int i = 0; i < a.Length; i++) diff |= a[i] ^ b[i];
                return diff == 0;
            }

            private static void Write(HttpListenerResponse res, int code, string body, string mime)
            {
                byte[] data = new UTF8Encoding(false).GetBytes(body ?? "");
                WriteBytes(res, code, data, mime);
            }

            private static void WriteBytes(HttpListenerResponse res, int code, byte[] data, string mime)
            {
                byte[] payload = data ?? new byte[0];
                try
                {
                    res.StatusCode = code;
                    res.ContentType = mime ?? "application/json; charset=utf-8";
                    res.ContentEncoding = Encoding.UTF8;
                    res.AddHeader("Cache-Control", "no-store");
                    res.ContentLength64 = payload.Length;
                    res.OutputStream.Write(payload, 0, payload.Length);
                }
                catch { }
                finally { try { res.OutputStream.Close(); } catch { } }
            }

            private void Handle(HttpListenerContext ctx)
            {
                try
                {
                    if (!IsValidHost(ctx.Request.Headers["Host"]))
                    { Write(ctx.Response, 403, "{\"error\":\"FORBIDDEN_HOST\"}", null); return; }

                    if (!IsValidOrigin(ctx.Request.Headers["Origin"]))
                    { Write(ctx.Response, 403, "{\"error\":\"FORBIDDEN_ORIGIN\"}", null); return; }

                    string sfs = ctx.Request.Headers["Sec-Fetch-Site"];
                    if (!string.IsNullOrEmpty(sfs) && sfs != "same-origin" && sfs != "none")
                    { Write(ctx.Response, 403, "{\"error\":\"FORBIDDEN_FETCH_SITE\"}", null); return; }

                    string path = ctx.Request.Url.AbsolutePath;
                    if ((path == "/" || path == "/index.html") && ctx.Request.HttpMethod == "GET")
                    {
                        string html = (Html ?? "").Replace("connect-src 'none'", "connect-src 'self'");
                        string meta = "<meta name=\"twx-bridge-token\" content=\"" + Token + "\">";
                        int idx = html.IndexOf("<meta charset=\"utf-8\">", StringComparison.OrdinalIgnoreCase);
                        if (idx >= 0)
                        {
                            int insertPos = idx + "<meta charset=\"utf-8\">".Length;
                            html = html.Substring(0, insertPos) + "\n" + meta + html.Substring(insertPos);
                        }
                        Write(ctx.Response, 200, html, "text/html; charset=utf-8");
                        return;
                    }

                    if (path == "/api/health" && ctx.Request.HttpMethod == "GET")
                    {
                        var health = new Dictionary<string, object>
                        {
                            { "ok", true },
                            { "gameRunning", SaveStore.IsGameRunning() }
                        };
                        Write(ctx.Response, 200, _json.Serialize(health), null);
                        return;
                    }

                    if (!ConstantTimeEquals(ctx.Request.Headers["X-TWX-Token"], Token))
                    { Write(ctx.Response, 403, "{\"error\":\"INVALID_TOKEN\"}", null); return; }

                    if (path == "/api/slots" && ctx.Request.HttpMethod == "GET") { HandleSlots(ctx); return; }
                    if (path == "/api/load" && ctx.Request.HttpMethod == "GET") { HandleLoad(ctx); return; }
                    if (path == "/api/backups" && ctx.Request.HttpMethod == "GET") { HandleBackups(ctx); return; }
                    if (path == "/api/save" && ctx.Request.HttpMethod == "POST") { HandleSave(ctx); return; }
                    if (path == "/api/restore" && ctx.Request.HttpMethod == "POST") { HandleRestore(ctx); return; }

                    Write(ctx.Response, 404, "{\"error\":\"NOT_FOUND\"}", null);
                }
                catch (Exception ex)
                {
                    Write(ctx.Response, 500, _json.Serialize(new Dictionary<string, object> { { "error", ex.Message } }), null);
                }
            }

            private void HandleSlots(HttpListenerContext ctx)
            {
                List<SaveSlotInfo> slots;
                try { slots = SaveStore.ListSlots(Root, _rootId); }
                catch (Exception ex) { Write(ctx.Response, 400, _json.Serialize(new Dictionary<string, object> { { "error", ex.Message } }), null); return; }
                var items = new List<object>();
                for (int i = 0; i < slots.Count; i++)
                {
                    SaveSlotInfo s = slots[i];
                    items.Add(new Dictionary<string, object>
                    {
                        { "slot", s.FileName ?? "" },
                        { "label", s.SlotName ?? "" },
                        { "kind", s.Kind ?? "save" },
                        { "size", s.SizeBytes }
                    });
                }
                Write(ctx.Response, 200, _json.Serialize(new Dictionary<string, object> { { "ok", true }, { "slots", items } }), null);
            }

            private void HandleLoad(HttpListenerContext ctx)
            {
                string slot = ctx.Request.QueryString["slot"];
                if (string.IsNullOrEmpty(slot)) { Write(ctx.Response, 400, "{\"error\":\"SLOT_REQUIRED\"}", null); return; }
                SaveLoadResult res = SaveStore.LoadSlot(Root, slot, _rootId);
                if (!res.Success)
                {
                    int status = res.Message == "NOT_FOUND" ? 404 : 400;
                    Write(ctx.Response, status, _json.Serialize(new Dictionary<string, object> { { "error", res.Message } }), null);
                    return;
                }
                ctx.Response.AddHeader("X-TWX-Sha256", res.Sha256 ?? "");
                WriteBytes(ctx.Response, 200, res.RawBytes ?? new byte[0], "application/json; charset=utf-8");
            }

            private void HandleBackups(HttpListenerContext ctx)
            {
                string slot = ctx.Request.QueryString["slot"];
                List<BackupInfo> backups;
                try
                {
                    backups = string.IsNullOrEmpty(slot)
                        ? SaveStore.ListBackups(Root, _rootId)
                        : SaveStore.ListBackupsForSlot(Root, slot, _rootId);
                }
                catch (Exception ex)
                {
                    Write(ctx.Response, 400, _json.Serialize(new Dictionary<string, object> { { "error", ex.Message } }), null);
                    return;
                }
                var items = new List<object>();
                for (int i = 0; i < backups.Count; i++)
                {
                    BackupInfo b = backups[i];
                    items.Add(new Dictionary<string, object> { { "name", b.FileName }, { "size", b.SizeBytes } });
                }
                Write(ctx.Response, 200, _json.Serialize(new Dictionary<string, object> { { "ok", true }, { "backups", items } }), null);
            }

            private void HandleSave(HttpListenerContext ctx)
            {
                Dictionary<string, object> body = ReadJsonBody(ctx.Request);
                if (body == null) { Write(ctx.Response, 400, "{\"error\":\"INVALID_BODY\"}", null); return; }
                string slot = body.ContainsKey("slot") ? Convert.ToString(body["slot"], CultureInfo.InvariantCulture) : "";
                string text = body.ContainsKey("text") ? (body["text"] as string) : null;
                if (string.IsNullOrEmpty(slot) || text == null)
                { Write(ctx.Response, 400, "{\"error\":\"MISSING_FIELDS\"}", null); return; }
                if (!body.ContainsKey("baseSha256") || !(body["baseSha256"] is string))
                { Write(ctx.Response, 400, "{\"error\":\"MISSING_BASE_SHA256\"}", null); return; }

                SaveWriteResult res = SaveStore.SaveSlot(Root, slot, text, (string)body["baseSha256"], _rootId);
                if (!res.Success)
                {
                    int status = (res.Message == "GAME_RUNNING" || res.Message == "CONFLICT_MODIFIED") ? 409 : 400;
                    Write(ctx.Response, status, _json.Serialize(new Dictionary<string, object> { { "error", res.Message } }), null);
                    return;
                }
                string bname = string.IsNullOrEmpty(res.BackupPath) ? "" : Path.GetFileName(res.BackupPath);
                Write(ctx.Response, 200, _json.Serialize(new Dictionary<string, object> { { "ok", true }, { "backup", bname }, { "sha256", res.Sha256 } }), null);
            }

            private void HandleRestore(HttpListenerContext ctx)
            {
                Dictionary<string, object> body = ReadJsonBody(ctx.Request);
                if (body == null) { Write(ctx.Response, 400, "{\"error\":\"INVALID_BODY\"}", null); return; }
                string slot = body.ContainsKey("slot") ? Convert.ToString(body["slot"], CultureInfo.InvariantCulture) : "";
                string backup = body.ContainsKey("backup") ? Convert.ToString(body["backup"], CultureInfo.InvariantCulture) : "";
                if (string.IsNullOrEmpty(slot) || string.IsNullOrEmpty(backup))
                { Write(ctx.Response, 400, "{\"error\":\"MISSING_FIELDS\"}", null); return; }

                SaveWriteResult res = SaveStore.RestoreBackup(Root, backup, slot, _rootId);
                if (!res.Success)
                {
                    int status = (res.Message == "GAME_RUNNING" || res.Message == "CONFLICT_MODIFIED") ? 409 : 400;
                    Write(ctx.Response, status, _json.Serialize(new Dictionary<string, object> { { "error", res.Message } }), null);
                    return;
                }
                Write(ctx.Response, 200, "{\"ok\":true}", null);
            }

            private static readonly UTF8Encoding StrictUtf8 = new UTF8Encoding(false, true);

            private static bool ContainsUnpairedSurrogate(string s)
            {
                if (string.IsNullOrEmpty(s)) return false;
                for (int i = 0; i < s.Length; i++)
                {
                    if (char.IsHighSurrogate(s[i]))
                    {
                        if (i + 1 >= s.Length || !char.IsLowSurrogate(s[i + 1])) return true;
                        i++;
                    }
                    else if (char.IsLowSurrogate(s[i])) return true;
                }
                return false;
            }

            private static bool ContainsUnpairedSurrogateValue(object val)
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

            private Dictionary<string, object> ReadJsonBody(HttpListenerRequest req)
            {
                try
                {
                    if (req == null || req.InputStream == null) return null;

                    int maxBytes = MaxJsonEnvelopeBytes;

                    if (req.ContentLength64 == 0 || req.ContentLength64 > maxBytes) return null;

                    byte[] buffer = new byte[8192];
                    using (MemoryStream ms = new MemoryStream())
                    {
                        long total = 0;
                        int read;
                        while ((read = req.InputStream.Read(buffer, 0, buffer.Length)) > 0)
                        {
                            total += read;
                            if (total > maxBytes) return null;
                            ms.Write(buffer, 0, read);
                        }

                        if (total == 0 || (req.ContentLength64 > 0 && total != req.ContentLength64)) return null;

                        byte[] rawBytes = ms.ToArray();
                        int offset = 0;

                        if (rawBytes.Length >= 4 &&
                            ((rawBytes[0] == 0xFF && rawBytes[1] == 0xFE && rawBytes[2] == 0x00 && rawBytes[3] == 0x00) ||
                             (rawBytes[0] == 0x00 && rawBytes[1] == 0x00 && rawBytes[2] == 0xFE && rawBytes[3] == 0xFF)))
                            return null;

                        if (rawBytes.Length >= 2 &&
                            ((rawBytes[0] == 0xFF && rawBytes[1] == 0xFE) ||
                             (rawBytes[0] == 0xFE && rawBytes[1] == 0xFF)))
                            return null;

                        if (rawBytes.Length >= 3 && rawBytes[0] == 0xEF && rawBytes[1] == 0xBB && rawBytes[2] == 0xBF)
                        {
                            if (rawBytes.Length >= 6 && rawBytes[3] == 0xEF && rawBytes[4] == 0xBB && rawBytes[5] == 0xBF)
                                return null;
                            offset = 3;
                        }

                        if (rawBytes.Length - offset <= 0) return null;

                        string raw = StrictUtf8.GetString(rawBytes, offset, rawBytes.Length - offset);
                        if (ContainsUnpairedSurrogate(raw) || SaveStore.ContainsUnpairedJsonSurrogateEscape(raw)) return null;

                        Dictionary<string, object> dict = _json.Deserialize<Dictionary<string, object>>(raw);
                        if (dict == null || ContainsUnpairedSurrogateValue(dict)) return null;

                        return dict;
                    }
                }
                catch
                {
                    return null;
                }
            }

            public void Dispose()
            {
                try { if (_cts != null) _cts.Cancel(); } catch { }
                try { _listener.Stop(); } catch { }
                try { _listener.Close(); } catch { }
            }
        }

        internal static class SelfTest
        {
            private const string SeedJson = "{\"m_strVersion\":\"1.0.3.1\",\"m_strPlayerName\":\"\\uBBF8\\uBA85\\r\",\"m_strPlayerLastName\":\"\\uB3D9\\uBC29\\r\",\"m_PlayerIconID\":\"900005\",\"m_iMoney\":1000,\"m_iYear\":1,\"m_iMonth\":1,\"m_iMonthInterval\":0,\"m_iNowTime\":1,\"m_iPhysical\":10,\"m_iMood\":4,\"m_iBattleDifficulty\":1,\"m_strSceneName\":\"Develop\",\"m_PropertyGroupsNodeList\":[{\"m_iType\":0,\"m_GroupsNodwList\":[{\"m_iValue\":1.2E+5,\"m_iIndex\":0,\"m_iExp\":0,\"m_iMax\":500}]}],\"m_PlayerRoutineNodeList\":[],\"m_PlayerNeigongNodeList\":[],\"m_BackpackList\":[],\"m_NpcFriendlyNodeList\":[]}";

            public static int Run(string[] args)
            {
                string outDir = GetArg(args, "--out");
                if (string.IsNullOrEmpty(outDir))
                    outDir = Path.Combine(Path.GetTempPath(), "TwxSelfTest-" + DateTime.UtcNow.Ticks.ToString(CultureInfo.InvariantCulture));
                string seedPath = GetArg(args, "--seed");
                bool isSynthSeed = string.IsNullOrEmpty(seedPath);
                Directory.CreateDirectory(outDir);

                string testRoot = Path.Combine(outDir, "selftest_root");
                Directory.CreateDirectory(testRoot);

                string slotPath = Path.Combine(testRoot, "Save0.Save");
                bool expectedBom;
                if (isSynthSeed)
                {
                    File.WriteAllText(slotPath, SeedJson, new UTF8Encoding(true));
                    expectedBom = true;
                }
                else
                {
                    byte[] rawSeed = File.ReadAllBytes(seedPath);
                    File.WriteAllBytes(slotPath, rawSeed);
                    expectedBom = rawSeed.Length >= 3 && rawSeed[0] == 0xEF && rawSeed[1] == 0xBB && rawSeed[2] == 0xBF;
                }

                int exit = 1;
                using (Form form = new Form())
                {
                    form.ShowInTaskbar = false;
                    form.WindowState = FormWindowState.Minimized;
                    form.Opacity = 0.0;
                    form.Location = new Point(-32000, -32000);
                    form.FormBorderStyle = FormBorderStyle.None;
                    form.Size = new Size(1280, 900);
                    form.Load += async (s, e) => { exit = await RunAsync(form, outDir, testRoot, slotPath, expectedBom, isSynthSeed); };
                    Application.Run(form);
                }
                return exit;
            }

            private static async Task<int> RunAsync(Form host, string outDir, string testRoot, string slotPath, bool expectedBom, bool isSynthSeed)
            {
                var record = new Dictionary<string, object>();
                WebView2 webView = null;
                LocalBridgeServer server = null;
                try
                {
                    server = new LocalBridgeServer(testRoot);
                    server.Start();
                    webView = new WebView2 { Dock = DockStyle.Fill };
                    host.Controls.Add(webView);
                    await InitializeWebViewAsync(webView);

                    string baseUrl = server.Url;
                    webView.CoreWebView2.NavigationStarting += (s, e) =>
                    {
                        if (e.Uri != null && !e.Uri.StartsWith(baseUrl, StringComparison.OrdinalIgnoreCase))
                            e.Cancel = true;
                    };
                    webView.CoreWebView2.NewWindowRequested += (s, e) => { e.Handled = true; };

                    var navDone = new TaskCompletionSource<bool>();
                    webView.CoreWebView2.NavigationCompleted += (s, e) => { if (!navDone.Task.IsCompleted) navDone.TrySetResult(true); };
                    webView.CoreWebView2.Navigate(baseUrl);

                    Task finished = await Task.WhenAny(navDone.Task, Task.Delay(60000));
                    if (finished != navDone.Task) throw new TimeoutException("Navigation timed out.");

                    for (int w = 0; w < 30; w++)
                    {
                        string sv = Clean(await webView.CoreWebView2.ExecuteScriptAsync("((document.getElementById('slot-select')||{}).value)||''"));
                        string bg = Clean(await webView.CoreWebView2.ExecuteScriptAsync("((document.getElementById('status-badge')||{}).textContent)||''"));
                        string dis = Clean(await webView.CoreWebView2.ExecuteScriptAsync("String(!!((document.getElementById('btn-save')||{}).disabled))"));
                        if (sv == "Save0.Save" && bg == "\uC11C\uBC84 \uC5F0\uACB0\uB428" && dis == "false") break;
                        await Task.Delay(200);
                    }

                    string expInputSynced = "";
                    if (isSynthSeed)
                    {
                        expInputSynced = Clean(await webView.CoreWebView2.ExecuteScriptAsync("(function(){var t=document.getElementById('tab-btn-1');if(t)t.click();var i=document.querySelector('#tab-panel-1 .row-inline input:nth-child(2)');if(!i)return '';i.value='1e5';i.dispatchEvent(new Event('change',{bubbles:true}));return String(i.value||'');})()"));
                    }

                    await webView.CoreWebView2.ExecuteScriptAsync("(function(){var b=document.querySelector('[data-preset-id=\"max_money\"]')||document.querySelector('.preset-button');if(b)b.click();return true;})()");
                    string shaBefore = Clean(await webView.CoreWebView2.ExecuteScriptAsync("(window.__TWX_APP__&&window.__TWX_APP__.getState().baseSha256)||''"));
                    await webView.CoreWebView2.ExecuteScriptAsync("(function(){var r=document.getElementById('btn-refresh-slots');if(r)r.click();return true;})()");
                    for (int r = 0; r < 15; r++)
                    {
                        await Task.Delay(100);
                        string rnt = Clean(await webView.CoreWebView2.ExecuteScriptAsync("((document.getElementById('notice-bar')||{}).textContent)||''"));
                        if (rnt.IndexOf("\uC0C8\uB85C\uACE0\uCE68", StringComparison.Ordinal) >= 0) break;
                    }
                    string moneyAfterRefresh = Clean(await webView.CoreWebView2.ExecuteScriptAsync("String((window.__TWX_APP__&&window.__TWX_APP__.getState().data&&window.__TWX_APP__.getState().data.m_iMoney)||0)"));
                    string shaAfter = Clean(await webView.CoreWebView2.ExecuteScriptAsync("(window.__TWX_APP__&&window.__TWX_APP__.getState().baseSha256)||''"));
                    bool refreshPreservedOk = !string.IsNullOrEmpty(shaBefore) && shaBefore == shaAfter && moneyAfterRefresh == "9999999";

                    await webView.CoreWebView2.ExecuteScriptAsync("(function(){var s=document.getElementById('btn-save');if(s)s.click();return true;})()");
                    await Task.Delay(300);
                    await webView.CoreWebView2.ExecuteScriptAsync("(function(){var c=document.getElementById('modal-confirm');if(c)c.click();return true;})()");

                    for (int w = 0; w < 30; w++)
                    {
                        await Task.Delay(250);
                        string lv = Clean(await webView.CoreWebView2.ExecuteScriptAsync("(((document.getElementById('notice-bar')||{}).dataset)||{}).level||''"));
                        string nt = Clean(await webView.CoreWebView2.ExecuteScriptAsync("((document.getElementById('notice-bar')||{}).textContent)||''"));
                        if (lv == "ok" && nt.IndexOf("\uC800\uC7A5", StringComparison.Ordinal) >= 0) break;
                    }

                    string tabsJson = await webView.CoreWebView2.ExecuteScriptAsync("document.querySelectorAll('[role=\"tab\"]').length");
                    int tabCount = 0;
                    int.TryParse(tabsJson, out tabCount);
                    string badge = Clean(await webView.CoreWebView2.ExecuteScriptAsync("((document.getElementById('status-badge')||{}).textContent)||''"));
                    string noticeDbg = Clean(await webView.CoreWebView2.ExecuteScriptAsync("((document.getElementById('notice-bar')||{}).textContent)||''"));
                    string bodyText = Clean(await webView.CoreWebView2.ExecuteScriptAsync("document.body.innerText"));
                    int hanziCount = CountHanzi(bodyText);
                    int kanaCount = CountKana(bodyText);

                    byte[] savedBytes = File.Exists(slotPath) ? File.ReadAllBytes(slotPath) : new byte[0];
                    bool hasBom = savedBytes.Length >= 3 && savedBytes[0] == 0xEF && savedBytes[1] == 0xBB && savedBytes[2] == 0xBF;
                    bool noDoubleBom = !(hasBom && savedBytes.Length >= 6 && savedBytes[3] == 0xEF && savedBytes[4] == 0xBB && savedBytes[5] == 0xBF);
                    bool bomOk = (hasBom == expectedBom) && noDoubleBom;

                    string savedText = "";
                    bool utf8Ok = true;
                    try
                    {
                        int savedOffset = hasBom ? 3 : 0;
                        UTF8Encoding strictUtf8 = new UTF8Encoding(false, true);
                        savedText = strictUtf8.GetString(savedBytes, savedOffset, savedBytes.Length - savedOffset);
                    }
                    catch
                    {
                        utf8Ok = false;
                        savedText = "";
                    }
                    bool moneyOk = utf8Ok && savedText.IndexOf("\"m_iMoney\":9999999", StringComparison.Ordinal) >= 0;
                    bool sciRoundtripOk = !isSynthSeed || (utf8Ok && expInputSynced == "100000" && savedText.IndexOf("\"m_iValue\":1.2E+5,\"m_iIndex\":0,\"m_iExp\":100000", StringComparison.Ordinal) >= 0);
                    bool validateOk = false;
                    try { validateOk = utf8Ok && SaveStore.ValidateSaveJson(savedText) == "save"; } catch { }

                    string backupDir = Path.Combine(testRoot, "backups");
                    string[] baks = Directory.Exists(backupDir) ? Directory.GetFiles(backupDir, "*.bak") : new string[0];
                    bool backupExists = baks.Length > 0;

                    string wvVersion = "";
                    try { wvVersion = webView.CoreWebView2.Environment.BrowserVersionString ?? ""; } catch { }

                    bool ok = tabCount == 6 && badge == "\uC11C\uBC84 \uC5F0\uACB0\uB428" &&
                              hanziCount == 0 && kanaCount == 0 && moneyOk && sciRoundtripOk && backupExists && validateOk && bomOk && refreshPreservedOk;

                    record["ok"] = ok;
                    record["tabCount"] = tabCount;
                    record["badgeText"] = badge;
                    record["notice"] = noticeDbg;
                    record["hanziCount"] = hanziCount;
                    record["kanaCount"] = kanaCount;
                    record["moneyOk"] = moneyOk;
                    record["sciRoundtripOk"] = sciRoundtripOk;
                    record["backupExists"] = backupExists;
                    record["validateOk"] = validateOk;
                    record["bomOk"] = bomOk;
                    record["refreshPreservedOk"] = refreshPreservedOk;
                    record["webViewVersion"] = wvVersion;

                    var js = new JavaScriptSerializer { MaxJsonLength = LocalBridgeServer.MaxJsonEnvelopeBytes };
                    File.WriteAllText(Path.Combine(outDir, "receipt.json"), js.Serialize(record), new UTF8Encoding(false));
                    host.BeginInvoke(new Action(() => { try { host.Close(); } catch { } }));
                    return ok ? 0 : 1;
                }
                catch (Exception ex)
                {
                    record["ok"] = false;
                    record["error"] = ex.Message;
                    try
                    {
                        var js = new JavaScriptSerializer { MaxJsonLength = LocalBridgeServer.MaxJsonEnvelopeBytes };
                        File.WriteAllText(Path.Combine(outDir, "receipt.json"), js.Serialize(record), new UTF8Encoding(false));
                    }
                    catch { }
                    try { host.BeginInvoke(new Action(() => { try { host.Close(); } catch { } })); } catch { }
                    return 1;
                }
                finally
                {
                    if (webView != null) { try { webView.Dispose(); } catch { } }
                    if (server != null) { try { server.Dispose(); } catch { } }
                }
            }

            private static string Clean(string s)
            {
                if (s == null) return "";
                s = s.Trim();
                if (s.StartsWith("\"", StringComparison.Ordinal) && s.EndsWith("\"", StringComparison.Ordinal) && s.Length >= 2)
                    s = s.Substring(1, s.Length - 2);
                return s.Replace("\\\"", "\"").Replace("\\n", "\n").Replace("\\r", "");
            }

            private static int CountHanzi(string text)
            {
                if (string.IsNullOrEmpty(text)) return 0;
                int n = 0;
                for (int i = 0; i < text.Length; i++)
                {
                    char c = text[i];
                    if ((c >= '\u4E00' && c <= '\u9FFF') || (c >= '\u3400' && c <= '\u4DBF')) n++;
                }
                return n;
            }

            private static int CountKana(string text)
            {
                if (string.IsNullOrEmpty(text)) return 0;
                int n = 0;
                for (int i = 0; i < text.Length; i++)
                {
                    char c = text[i];
                    if (c >= '\u3040' && c <= '\u30FF') n++;
                }
                return n;
            }

            private static string GetArg(string[] args, string flag)
            {
                if (args == null) return null;
                for (int i = 0; i < args.Length - 1; i++)
                {
                    if (string.Equals(args[i], flag, StringComparison.OrdinalIgnoreCase))
                        return args[i + 1];
                }
                return null;
            }
        }
    }

    internal sealed class MainForm : Form
    {
        private readonly WebView2 _webView;
        private SaveEditor.LocalBridgeServer _server;

        public MainForm()
        {
            Text = "\uD611\uAC1D\uD48D\uC6B4\uC804 \uC138\uC774\uBE0C \uC5D0\uB514\uD130 v1.0";
            Width = 1280;
            Height = 860;
            _webView = new WebView2 { Dock = DockStyle.Fill };
            Controls.Add(_webView);
        }

        protected override async void OnLoad(EventArgs e)
        {
            base.OnLoad(e);
            try
            {
                List<string> roots = SaveStore.DiscoverRoots();
                string root = (roots != null && roots.Count > 0)
                    ? roots[0]
                    : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TaleOfWuxiaSaveEditor", "Saves");

                var srv = new SaveEditor.LocalBridgeServer(root);
                srv.Start();
                _server = srv;

                await SaveEditor.InitializeWebViewAsync(_webView);
                _webView.CoreWebView2.NewWindowRequested += (s, args) => { args.Handled = true; };
                _webView.CoreWebView2.NavigationStarting += (s, args) =>
                {
                    if (string.IsNullOrEmpty(args.Uri) || !args.Uri.StartsWith(srv.Url, StringComparison.OrdinalIgnoreCase))
                        args.Cancel = true;
                };
                _webView.CoreWebView2.Navigate(srv.Url);
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, ex.Message, "\uC624\uB958", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Close();
            }
        }

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            if (_server != null) { try { _server.Dispose(); } catch { } _server = null; }
            if (_webView != null) { try { _webView.Dispose(); } catch { } }
            base.OnFormClosed(e);
        }
    }
}
