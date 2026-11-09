using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

class ManagedRoute {
    static string Real;
    static string Provider, Model, Profile, LaunchId, Home;
    static readonly object Gate = new object();
    static readonly HashSet<string> Pending = new HashSet<string>();
    // Relay model catalog: every model the route offers, shown in the desktop picker.
    static List<string> Models = new List<string>();
    static readonly HashSet<string> ModelLists = new HashSet<string>();
    // account/rateLimits/read requests awaiting a reply; relay only.
    static readonly HashSet<string> RateReads = new HashSet<string>();
    // The official ChatGPT quota does not apply to relay turns. Report it as available
    // so the desktop neither locks the composer nor shows the usage banner.
    static void ClearQuota(object node) {
        var map = node as Dictionary<string, object>;
        if (map != null) {
            foreach (string k in new List<string>(map.Keys)) {
                object v = map[k];
                if (k == "usedPercent") map[k] = 0;
                else if (k == "rateLimitReachedType") map[k] = null;
                else if (v is bool && (bool)v && (k.EndsWith("Reached") || k.EndsWith("Exceeded") || k.EndsWith("Limited"))) map[k] = false;
                else if ((k == "hasCredits" || k.EndsWith("Allowed")) && v is bool) map[k] = true;
                else ClearQuota(v);
            }
            return;
        }
        var list = node as object[];
        if (list != null) foreach (object item in list) ClearQuota(item);
        var arr = node as System.Collections.ArrayList;
        if (arr != null) foreach (object item in arr) ClearQuota(item);
    }
    // Account plane for the relay. With the relay as the configured provider the server
    // has no ChatGPT login, so the desktop shows onboarding, hides projects and cannot get
    // its auth token. A second official server (native provider, never used for turns)
    // answers the account requests; thread and turn traffic still goes to the relay server.
    static readonly string[] NativeMethods = { "getAuthStatus", "account/read", "account/usage/read",
        "account/workspaceMessages/read", "account/rateLimits/read" };
    static readonly ManualResetEvent NativeReady = new ManualResetEvent(false);
    static volatile bool NativeOk;
    static TextWriter NativeIn;
    static Process Native;
    static readonly object NativeGate = new object();
    static readonly Dictionary<string, object[]> NativePending = new Dictionary<string, object[]>();
    static int NativeSeq;
    static TextWriter Out;
    static readonly object OutGate = new object();
    static void Emit(string line) { lock (OutGate) { Out.WriteLine(line); } }
    static void StartNative() {
        try {
            var args = new List<string>(); Config(args, "model_provider", "\"openai\""); args.Add("app-server");
            var start = new ProcessStartInfo(Real, string.Join(" ", args.ToArray()));
            start.UseShellExecute = false; start.CreateNoWindow = true;
            start.RedirectStandardInput = start.RedirectStandardOutput = start.RedirectStandardError = true;
            start.EnvironmentVariables["CODEX_CLI_PATH"] = Real;
            Native = Process.Start(start);
            Native.ErrorDataReceived += delegate { }; Native.BeginErrorReadLine();
            var writer = new StreamWriter(Native.StandardInput.BaseStream, new UTF8Encoding(false)); writer.AutoFlush = true;
            NativeIn = writer;
            var reader = new StreamReader(Native.StandardOutput.BaseStream, new UTF8Encoding(false));
            var pump = new Thread(delegate() {
                try { string line; while ((line = reader.ReadLine()) != null) NativeLine(line); } catch { }
                NativeOk = false; NativeReady.Set();
            }); pump.IsBackground = true; pump.Start();
            lock (NativeGate) { writer.WriteLine("{\"id\":\"route-init\",\"method\":\"initialize\",\"params\":{\"clientInfo\":{\"name\":\"route-bridge\",\"title\":\"route-bridge\",\"version\":\"1\"}}}"); }
            NativeTimer = new Timer(delegate { NativeReady.Set(); }, null, 20000, Timeout.Infinite);
        } catch { NativeReady.Set(); }
    }
    static Timer NativeTimer;
    static void NativeLine(string line) {
        try {
            var message = Json().DeserializeObject(line) as Dictionary<string, object>;
            if (message == null) return;
            object value;
            if (message.TryGetValue("method", out value)) {
                string method = value as string;
                if (method == "account/updated" || method == "account/login/completed") Emit(line);
                else if (method == "account/rateLimits/updated" && message.TryGetValue("params", out value)) { ClearQuota(value); Emit(Json().Serialize(message)); }
                return;
            }
            if (!message.TryGetValue("id", out value)) return;
            string key = Json().Serialize(value);
            if (key == "\"route-init\"") {
                lock (NativeGate) { NativeIn.WriteLine("{\"method\":\"initialized\"}"); }
                NativeOk = !message.ContainsKey("error"); NativeReady.Set(); return;
            }
            object[] pending;
            lock (Gate) { if (!NativePending.TryGetValue(key, out pending)) return; NativePending.Remove(key); }
            message["id"] = pending[0];
            if ((string)pending[1] == "account/rateLimits/read" && message.TryGetValue("result", out value)) ClearQuota(value);
            Emit(Json().Serialize(message));
        } catch { }
    }
    static bool ToNative(Dictionary<string, object> message, string method) {
        object id;
        if (!message.TryGetValue("id", out id) || !NativeReady.WaitOne(20000) || !NativeOk || NativeIn == null) return false;
        string nid = "route-" + Interlocked.Increment(ref NativeSeq);
        string key = Json().Serialize(nid);
        lock (Gate) { NativePending[key] = new object[] { id, method }; }
        message["id"] = nid;
        try { lock (NativeGate) { NativeIn.WriteLine(Json().Serialize(message)); } return true; }
        catch { lock (Gate) { NativePending.Remove(key); } message["id"] = id; return false; }
    }
    static string RelayQuota(string line) {
        if (Provider != "route_relay" || line.IndexOf("ateLimit", StringComparison.Ordinal) < 0 && RateReads.Count == 0) return line;
        try {
            var message = Json().DeserializeObject(line) as Dictionary<string, object>;
            if (message == null) return line;
            object value;
            if (message.TryGetValue("method", out value)) {
                if ((value as string) != "account/rateLimits/updated" || !message.TryGetValue("params", out value)) return line;
                ClearQuota(value);
                return Json().Serialize(message);
            }
            if (!message.TryGetValue("id", out value)) return line;
            lock (Gate) { if (!RateReads.Remove(Json().Serialize(value))) return line; }
            if (!message.TryGetValue("result", out value)) return line;
            ClearQuota(value);
            return Json().Serialize(message);
        } catch { return line; }
    }
    const string RelayModelDescription = "中转线路模型";
    static JavaScriptSerializer Json() { return new JavaScriptSerializer { MaxJsonLength = int.MaxValue }; }
    static bool CompleteBundle(string directory) {
        foreach (string name in new[] { "codex.exe", "codex-code-mode-host.exe",
            "codex-command-runner.exe", "codex-windows-sandbox-setup.exe" })
            if (!File.Exists(Path.Combine(directory, name))) return false;
        return true;
    }
    static string ResolveOfficialCli() {
        // Match the running desktop's bundled backend before considering cached versions.
        foreach (var desktop in Process.GetProcessesByName("ChatGPT")) {
            using (desktop) {
                try {
                    string resources = Path.Combine(Path.GetDirectoryName(desktop.MainModule.FileName), "resources");
                    if (CompleteBundle(resources)) return Path.Combine(resources, "codex.exe");
                } catch (System.ComponentModel.Win32Exception) { }
                  catch (InvalidOperationException) { }
            }
        }
        // A normal CLI launch may happen before the desktop is running.
        var query = new ProcessStartInfo(
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                @"WindowsPowerShell\v1.0\powershell.exe"),
            "-NoLogo -NoProfile -NonInteractive -Command \"[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-AppxPackage -Name OpenAI.Codex | Sort-Object Version -Descending | Select-Object -First 1 -ExpandProperty InstallLocation\"");
        query.UseShellExecute = false; query.CreateNoWindow = true;
        query.RedirectStandardOutput = query.RedirectStandardError = true;
        query.StandardOutputEncoding = Encoding.UTF8;
        try {
            using (var child = Process.Start(query)) {
                if (child.WaitForExit(10000)) {
                    string package = child.StandardOutput.ReadToEnd().Trim();
                    if (child.ExitCode == 0 && Path.IsPathRooted(package)) {
                        string resources = Path.Combine(package, "app", "resources");
                        if (CompleteBundle(resources)) return Path.Combine(resources, "codex.exe");
                    }
                } else child.Kill();
            }
        } catch (System.ComponentModel.Win32Exception) { }
          catch (InvalidOperationException) { }
        string cache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            @"OpenAI\Codex\bin");
        if (Directory.Exists(cache)) {
            var candidates = new List<DirectoryInfo>(new DirectoryInfo(cache).GetDirectories());
            candidates.Sort((a, b) => b.LastWriteTimeUtc.CompareTo(a.LastWriteTimeUtc));
            foreach (var candidate in candidates)
                if (CompleteBundle(candidate.FullName)) return Path.Combine(candidate.FullName, "codex.exe");
        }
        throw new InvalidOperationException("No complete official Codex bundle was found. Repair the official installation.");
    }
    static string Quote(string s) {
        var b = new StringBuilder("\""); int slashes = 0;
        foreach (char c in s) {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') { b.Append('\\', slashes * 2 + 1); b.Append(c); }
            else { b.Append('\\', slashes); b.Append(c); }
            slashes = 0;
        }
        b.Append('\\', slashes * 2); return b.Append('"').ToString();
    }
    static void Pump(Stream source, Stream destination) {
        byte[] buffer = new byte[8192];
        int count;
        while ((count = source.Read(buffer, 0, buffer.Length)) != 0) {
            destination.Write(buffer, 0, count);
            destination.Flush();
        }
    }
    static string Route(string line) {
        var message = Json().DeserializeObject(line) as Dictionary<string, object>;
        object value;
        if (message == null || !message.TryGetValue("method", out value)) return line;
        string method = value as string;
        bool relay = Provider == "route_relay";
        if (method == "model/list") {
            if (relay && Models.Count > 0 && message.TryGetValue("id", out value)) lock (Gate) { ModelLists.Add(Json().Serialize(value)); }
            return line;
        }
        if (relay && Array.IndexOf(NativeMethods, method) >= 0 && ToNative(message, method)) return null;
        if (relay && method == "account/rateLimits/read") {
            if (message.TryGetValue("id", out value)) lock (Gate) { RateReads.Add(Json().Serialize(value)); }
            return line;
        }
        bool thread = method == "thread/start" || method == "thread/resume" || method == "thread/fork";
        if (!thread && !(relay && method == "turn/start")) return line;
        var parameters = message.TryGetValue("params", out value) ? value as Dictionary<string, object> : null;
        if (parameters == null) return line;
        if (relay) {
            // Keep the model picked in the desktop when the relay offers it; otherwise fall back to the route default.
            string asked = parameters.TryGetValue("model", out value) ? value as string : null;
            if (!thread && asked == null) return line;
            parameters["model"] = asked != null && Models.Contains(asked) ? asked : Model;
        } else if (thread && !string.IsNullOrWhiteSpace(Model)) parameters["model"] = Model;
        if (!thread) return Json().Serialize(message);
        parameters["modelProvider"] = Provider;
        if (relay) parameters["serviceTier"] = null;
        if (message.TryGetValue("id", out value)) lock (Gate) { Pending.Add(Json().Serialize(value)); }
        return Json().Serialize(message);
    }
    static string Respond(string line) {
        Confirm(line);
        line = RelayQuota(line);
        // The relay server's own (empty) account state must not override the native one.
        if (NativeOk && line.IndexOf("\"account/updated\"", StringComparison.Ordinal) >= 0) return null;
        lock (Gate) { if (ModelLists.Count == 0) return line; }
        try {
            var message = Json().DeserializeObject(line) as Dictionary<string, object>;
            object value;
            if (message == null || !message.TryGetValue("id", out value)) return line;
            lock (Gate) { if (!ModelLists.Remove(Json().Serialize(value))) return line; }
            var result = message.TryGetValue("result", out value) ? value as Dictionary<string, object> : null;
            var list = result != null && result.TryGetValue("data", out value) ? value as object[] : null;
            var template = list != null && list.Length > 0 ? list[0] as Dictionary<string, object> : null;
            if (template == null) return line;
            // Clone an official entry so reasoning levels and other picker metadata keep the desktop's shape.
            string raw = Json().Serialize(template);
            var rows = new List<object>();
            foreach (string name in Models) {
                var row = Json().DeserializeObject(raw) as Dictionary<string, object>;
                row["id"] = name; row["model"] = name; row["displayName"] = name; row["description"] = RelayModelDescription;
                row["hidden"] = false; row["isDefault"] = name == Model;
                row["upgrade"] = null; row["upgradeInfo"] = null; row["availabilityNux"] = null;
                rows.Add(row);
            }
            result["data"] = rows.ToArray();
            result["nextCursor"] = null;
            return Json().Serialize(message);
        } catch { return line; }
    }
    static void Confirm(string line) {
        try {
            var message = Json().DeserializeObject(line) as Dictionary<string, object>;
            object value;
            if (message == null || !message.TryGetValue("id", out value)) return;
            lock (Gate) { if (!Pending.Remove(Json().Serialize(value))) return; }
            var result = message.TryGetValue("result", out value) ? value as Dictionary<string, object> : null;
            if (result == null) return;
            string provider = result.TryGetValue("modelProvider", out value) ? value as string : null;
            if (provider == null) {
                var thread = result.TryGetValue("thread", out value) ? value as Dictionary<string, object> : null;
                if (thread != null && thread.TryGetValue("modelProvider", out value)) provider = value as string;
            }
            if (provider != Provider || string.IsNullOrWhiteSpace(Home) || string.IsNullOrWhiteSpace(LaunchId)) return;
            Directory.CreateDirectory(Home);
            string path = Path.Combine(Home, "desktop-confirmation.json");
            string temporary = path + "." + Process.GetCurrentProcess().Id + ".tmp";
            File.WriteAllText(temporary, Json().Serialize(new Dictionary<string, object> {
                {"launchId", LaunchId}, {"profileId", Profile}, {"provider", Provider}, {"utc", DateTime.UtcNow.ToString("o")}
            }), new UTF8Encoding(false));
            lock (Gate) {
                if (File.Exists(path)) File.Replace(temporary, path, null);
                else File.Move(temporary, path);
            }
        } catch { /* Confirmation is advisory and must never break transport. */ }
    }
    static void Config(List<string> args, string key, string value) {
        args.Add("-c"); args.Add(Quote(key + "=" + value));
    }
    static bool NodeConfigured(string[] args) {
        foreach (string arg in args) if (arg.Contains("mcp_servers.node_repl")) return true;
        string home = Environment.GetEnvironmentVariable("CODEX_HOME");
        if (string.IsNullOrWhiteSpace(home)) home = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".codex");
        string config = Path.Combine(home, "config.toml");
        if (!File.Exists(config)) return false;
        foreach (string line in File.ReadLines(config)) {
            string value = line.Trim();
            if (value == "[mcp_servers.node_repl]" || value.StartsWith("[mcp_servers.node_repl.")) return true;
        }
        return false;
    }
    static int Main(string[] args) {
        try { return Run(args); }
        catch { Console.Error.WriteLine("Managed Codex route could not start. Check the configured route and official desktop installation."); return 2; }
    }
    static int Run(string[] args) {
        bool relay = Environment.GetEnvironmentVariable("CODEX_ROUTE_KIND") == "relay";
        Provider = relay ? "route_relay" : "openai";
        Model = Environment.GetEnvironmentVariable("CODEX_ROUTE_MODEL");
        Profile = Environment.GetEnvironmentVariable("CODEX_ROUTE_ID");
        LaunchId = Environment.GetEnvironmentVariable("CODEX_ROUTE_LAUNCH_ID");
        Home = Environment.GetEnvironmentVariable("CODEX_ROUTE_HOME");
        try {
            var listed = Json().DeserializeObject(Environment.GetEnvironmentVariable("CODEX_ROUTE_MODELS") ?? "[]") as object[];
            if (listed != null) foreach (object item in listed) { string name = item as string; if (!string.IsNullOrWhiteSpace(name) && !Models.Contains(name)) Models.Add(name); }
        } catch { Models.Clear(); }
        if (relay && !string.IsNullOrWhiteSpace(Model) && !Models.Contains(Model)) Models.Insert(0, Model);
        if (args.Length == 1 && args[0] == "--self-test") {
            // Synthetic contract check; no CLI, network or real user files are accessed.
            Provider = "route_relay"; Model = "fixture-model";
            var routed = Json().DeserializeObject(Route("{\"id\":1,\"method\":\"thread/start\",\"params\":{\"modelProvider\":\"custom\"}}")) as Dictionary<string, object>;
            var p = routed["params"] as Dictionary<string, object>;
            if ((string)p["modelProvider"] != Provider || (string)p["model"] != Model) return 3;
            Provider = "openai"; Model = null;
            string official = Route("{\"id\":2,\"method\":\"thread/resume\",\"params\":{\"modelProvider\":\"route_relay\"}}");
            if (!official.Contains("openai")) return 4;
            string untouched = "{\"method\":\"account/read\"}";
            if (Route(untouched) != untouched) return 5;
            // Relay picker: models the route offers are kept, anything else falls back to the default.
            Provider = "route_relay"; Model = "fixture-model"; Models = new List<string> { "fixture-model", "other-model" };
            Func<string, string> picked = request => ((Json().DeserializeObject(Route(request)) as Dictionary<string, object>)["params"] as Dictionary<string, object>)["model"] as string;
            if (picked("{\"id\":3,\"method\":\"thread/start\",\"params\":{\"model\":\"other-model\"}}") != "other-model") return 6;
            if (picked("{\"id\":4,\"method\":\"thread/start\",\"params\":{\"model\":\"gpt-official\"}}") != "fixture-model") return 7;
            if (picked("{\"id\":5,\"method\":\"turn/start\",\"params\":{\"model\":\"other-model\"}}") != "other-model") return 8;
            if (picked("{\"id\":6,\"method\":\"turn/start\",\"params\":{\"model\":\"gpt-official\"}}") != "fixture-model") return 9;
            string noModelTurn = "{\"id\":7,\"method\":\"turn/start\",\"params\":{\"input\":[]}}";
            if (Route(noModelTurn) != noModelTurn) return 10;
            Route("{\"id\":8,\"method\":\"model/list\",\"params\":{}}");
            var listed = Json().DeserializeObject(Respond("{\"id\":8,\"result\":{\"data\":[{\"id\":\"gpt-official\",\"model\":\"gpt-official\",\"displayName\":\"Official\",\"supportedReasoningEfforts\":[{\"reasoningEffort\":\"high\"}],\"isDefault\":true}],\"nextCursor\":\"next\"}}")) as Dictionary<string, object>;
            var rows = (listed["result"] as Dictionary<string, object>)["data"] as object[];
            if (rows.Length != 2 || (string)(rows[1] as Dictionary<string, object>)["model"] != "other-model" || !(bool)(rows[0] as Dictionary<string, object>)["isDefault"]
                || (rows[1] as Dictionary<string, object>)["supportedReasoningEfforts"] == null) return 11;
            string unrelated = "{\"id\":9,\"result\":{\"data\":[]}}";
            if (Respond(unrelated) != unrelated) return 12;
            // Relay quota: official exhaustion is reported as available, both on read and on push.
            Route("{\"id\":20,\"method\":\"account/rateLimits/read\",\"params\":null}");
            string read = Respond("{\"id\":20,\"result\":{\"rateLimits\":{\"primary\":{\"usedPercent\":100},\"rateLimitReachedType\":\"rate_limit_reached\",\"spendControlReached\":true,\"credits\":{\"hasCredits\":false,\"unlimited\":false}},\"rateLimitsByLimitId\":{\"codex\":{\"secondary\":{\"usedPercent\":100}}}}}");
            if (read.Contains("100") || read.Contains("rate_limit_reached") || read.Contains("spendControlReached\":true") || read.Contains("hasCredits\":false")) return 13;
            string push = Respond("{\"method\":\"account/rateLimits/updated\",\"params\":{\"rateLimits\":{\"primary\":{\"usedPercent\":97},\"rateLimitReachedType\":\"rate_limit_reached\"}}}");
            if (push.Contains("97") || push.Contains("rate_limit_reached")) return 14;
            // Account plane: without a native server account requests pass through unchanged;
            // with one they are answered under the desktop's own id, quota cleared.
            string acctRead = "{\"id\":30,\"method\":\"account/read\",\"params\":{}}";
            NativeReady.Set();
            if (Route(acctRead) != acctRead) return 16;
            var captured = new StringWriter(); Out = captured; NativeOk = true; NativeIn = new StringWriter();
            if (Route("{\"id\":31,\"method\":\"account/rateLimits/read\",\"params\":null}") != null) return 17;
            NativeLine("{\"id\":\"route-" + NativeSeq + "\",\"result\":{\"rateLimits\":{\"primary\":{\"usedPercent\":88},\"rateLimitReachedType\":\"rate_limit_reached\"}}}");
            string relayed = captured.ToString();
            if (!relayed.Contains("\"id\":31") || relayed.Contains("88") || relayed.Contains("rate_limit_reached")) return 18;
            if (Respond("{\"method\":\"account/updated\",\"params\":{\"authMode\":null}}") != null) return 19;
            NativeOk = false;
            Provider = "openai";
            string officialPush = "{\"method\":\"account/rateLimits/updated\",\"params\":{\"rateLimits\":{\"primary\":{\"usedPercent\":97}}}}";
            if (Respond(officialPush) != officialPush) return 15;
            Console.WriteLine("Route contract checks passed"); return 0;
        }
        Real = ResolveOfficialCli();
        if (args.Length == 1 && args[0] == "--wrapper-health") {
            Console.WriteLine(Json().Serialize(new Dictionary<string, object> {
                {"officialCli", Real}, {"completeBundle", CompleteBundle(Path.GetDirectoryName(Real))}
            })); return 0;
        }
        bool server = Array.IndexOf(args, "app-server") >= 0;
        string key = Environment.GetEnvironmentVariable("CODEX_ROUTE_KEY");
        string baseUrl = Environment.GetEnvironmentVariable("CODEX_ROUTE_BASE");
        Uri uri;
        if (server && relay && (string.IsNullOrWhiteSpace(key) || !Uri.TryCreate(baseUrl, UriKind.Absolute, out uri) || (uri.Scheme != "https" && !(uri.Scheme == "http" && uri.IsLoopback)))) return 2;
        var quoted = new List<string>(); foreach (string a in args) quoted.Add(Quote(a));
        if (server) {
            if (NodeConfigured(args)) Config(quoted, "mcp_servers.node_repl.env.CODEX_CLI_PATH", Json().Serialize(Real));
            // Keep desktop account/read on native ChatGPT authentication. Only
            // local thread start/resume/fork requests select the relay provider.
            // Newer official CLIs reject a turn when the thread's provider differs
            // from the server's configured provider, so the relay must be the default too.
            Config(quoted, "model_provider", Json().Serialize(relay ? "route_relay" : "openai"));
            if (!string.IsNullOrWhiteSpace(Model)) Config(quoted, "model", Json().Serialize(Model));
            if (relay) StartNative();
            if (relay) Config(quoted, "model_providers.route_relay", "{name=\"Managed relay\",base_url=" + Json().Serialize(baseUrl) + ",wire_api=\"responses\",env_key=\"CODEX_ROUTE_KEY\",requires_openai_auth=false,supports_websockets=false}");
        }
        if (server) { var stdout = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)); stdout.AutoFlush = true; Out = stdout; }
        var start = new ProcessStartInfo(Real, string.Join(" ", quoted.ToArray()));
        start.UseShellExecute = false; start.CreateNoWindow = true;
        start.EnvironmentVariables["CODEX_CLI_PATH"] = Real;
        start.RedirectStandardInput = start.RedirectStandardOutput = start.RedirectStandardError = true;
        using (var child = Process.Start(start)) {
            var input = new Thread(delegate() {
                try {
                    if (server) {
                        var reader = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false));
                        var writer = new StreamWriter(child.StandardInput.BaseStream, new UTF8Encoding(false)); writer.AutoFlush = true;
                        string line; while ((line = reader.ReadLine()) != null) { string routed = Route(line); if (routed != null) writer.WriteLine(routed); }
                    } else Pump(Console.OpenStandardInput(), child.StandardInput.BaseStream);
                    child.StandardInput.Close();
                } catch { try { child.StandardInput.Close(); } catch { } }
            }); input.IsBackground = true; input.Start();
            var output = new Thread(delegate() { try {
                if (server) {
                    var reader = new StreamReader(child.StandardOutput.BaseStream, new UTF8Encoding(false));
                    string line; while ((line = reader.ReadLine()) != null) { string answer = Respond(line); if (answer != null) Emit(answer); }
                } else Pump(child.StandardOutput.BaseStream, Console.OpenStandardOutput());
            } catch { } });
            var error = new Thread(delegate() { try { Pump(child.StandardError.BaseStream, Console.OpenStandardError()); } catch { } });
            output.Start(); error.Start(); child.WaitForExit(); output.Join(); error.Join();
            if (Native != null) try { Native.Kill(); } catch { }
            return child.ExitCode;
        }
    }
}
