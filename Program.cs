using System.Diagnostics;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace GlassInterpreter;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        var exe = Environment.ProcessPath ?? throw new InvalidOperationException("No pude encontrar el ejecutable.");
        var name = Path.GetFileNameWithoutExtension(exe);
        var vm = Regex.Match(name, @"^GlassInterpreter-VM-(\d{1,3}(?:\.\d{1,3}){3})(?:-Beta2)?$", RegexOptions.IgnoreCase);
        if (vm.Success) { new Wizard(vm.Groups[1].Value).RunVm(); return; }
        if (name.Equals("GlassInterpreter-Host", StringComparison.OrdinalIgnoreCase)) { RunHost(exe); return; }
        new Wizard(null).RunHost();
    }

    private static void RunHost(string exe)
    {
        var root = Path.GetDirectoryName(exe)!;
        var scripts = Path.Combine(root, ".venv", "Scripts");
        var translator = Process.Start(Hidden(Path.Combine(scripts, "libretranslate.exe"), "--host 127.0.0.1 --port 5000 --load-only en,es", root, false));
        var viewer = Process.Start(Hidden(Path.Combine(scripts, "pythonw.exe"), "\"" + Path.Combine(root, "Host", "host.py") + "\"", root, false));
        viewer?.WaitForExit();
        try { if (translator is { HasExited: false }) translator.Kill(true); } catch { }
    }

    internal static ProcessStartInfo Hidden(string exe, string args, string? cwd = null, bool redirect = true) => new(exe, args)
    {
        UseShellExecute = false,
        CreateNoWindow = true,
        WindowStyle = ProcessWindowStyle.Hidden,
        WorkingDirectory = cwd ?? Path.GetDirectoryName(exe) ?? Environment.CurrentDirectory,
        RedirectStandardOutput = redirect,
        RedirectStandardError = redirect,
    };
}

internal sealed class Wizard
{
    private readonly string? vmHostIp;
    private readonly string currentExe = Environment.ProcessPath ?? throw new InvalidOperationException("No pude encontrar el ejecutable.");
    private Form form = null!;
    private TextBox destination = null!;
    private ComboBox hostIp = null!;
    private Label status = null!;
    private ProgressBar progress = null!;
    private Button action = null!;
    private Button cancelButton = null!;
    private string installRoot = "";
    private string? pythonExe;

    internal Wizard(string? ip) => vmHostIp = ip;

    internal void RunHost()
    {
        MakeWindow("Asistente de instalación de Glass Interpreter", 680, 520);
        Text("Instalación en el Host", 28, 22, 610, 34, 20, true);
        Text("Abre Windows 11 Subtítulos en vivo en ambos equipos. Configura el Host en inglés y la VM en español.\n\nLa primera instalación necesita internet para descargar Python, LibreTranslate y los modelos EN↔ES. Después, la traducción se procesa en el Host; los subtítulos de la VM solo viajan por tu red local. Glass no los manda a servicios externos.\n\nElige la carpeta donde se crearán Host y VM.", 30, 70, 610, 148, 10);
        destination = new TextBox { Left = 30, Top = 230, Width = 500, Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "Glass Interpreter") };
        form.Controls.Add(destination);
        BrowseButton(540, 228, destination, "Elige la carpeta de Glass Interpreter en el Host");
        Text("Dirección IPv4 del Host a la que se conectará la VM:", 30, 274, 570, 22, 10, true);
        hostIp = new ComboBox { Left = 30, Top = 300, Width = 610, DropDownStyle = ComboBoxStyle.DropDown };
        var addresses = HostIPv4Candidates();
        foreach (var item in addresses) hostIp.Items.Add($"{item.Ip} — {item.Adapter}");
        if (hostIp.Items.Count > 0) hostIp.SelectedIndex = 0;
        form.Controls.Add(hostIp);
        progress = new ProgressBar { Left = 30, Top = 350, Width = 610, Height = 16, Style = ProgressBarStyle.Marquee, Visible = false };
        form.Controls.Add(progress);
        status = Text(addresses.Length > 0
            ? $"Dirección detectada automáticamente: {addresses[0].Ip} ({addresses[0].Adapter}). Puedes elegir otra si tu VM usa otra red."
            : "No pude detectar una IPv4 privada. Escribe la dirección del adaptador al que se conecta tu VM.", 30, 378, 610, 42, 9);
        action = new Button { Text = "Instalar", Left = 510, Top = 440, Width = 130, Height = 34 };
        action.Click += async (_, _) => { if (action.Text == "Terminar") { form.Close(); return; } await InstallHost(); };
        form.Controls.Add(action);
        AddCancelButton(380, 440);
        Application.Run(form);
    }

    internal void RunVm()
    {
        if (MessageBox.Show("¿ESTÁS EJECUTANDO ESTO DESDE LA VM?", "Glass Interpreter VM", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
        {
            MessageBox.Show("Este instalador debe ejecutarse dentro de la máquina virtual.", "Glass Interpreter", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        MakeWindow("Instalación de Glass Interpreter en la VM", 620, 460);
        Text("Instalación en la VM", 28, 22, 560, 34, 20, true);
        Text($"Se configurará la conexión con el Host en {vmHostIp}.\n\nAbre Windows 11 Subtítulos en vivo en esta VM y configúralo en español.\n\nSe necesita internet para instalar Python y los componentes de captura. Después, la VM solo enviará el texto al Host por la red local; no traducirá.", 30, 75, 550, 155, 10);
        destination = new TextBox { Left = 30, Top = 248, Width = 445, Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "Glass Interpreter VM") };
        form.Controls.Add(destination);
        BrowseButton(485, 246, destination, "Elige dónde instalar Glass Interpreter VM");
        progress = new ProgressBar { Left = 30, Top = 305, Width = 540, Height = 16, Style = ProgressBarStyle.Marquee, Visible = false };
        form.Controls.Add(progress);
        status = Text("Se creará un acceso directo con el icono Glass para iniciar la captura con doble clic.", 30, 332, 540, 34, 9);
        action = new Button { Text = "Instalar", Left = 450, Top = 375, Width = 120, Height = 34 };
        action.Click += async (_, _) => { if (action.Text == "Terminar") { form.Close(); return; } await InstallVm(); };
        form.Controls.Add(action);
        AddCancelButton(320, 375);
        Application.Run(form);
    }

    private void MakeWindow(string title, int width, int height)
    {
        form = new Form { Text = title, Width = width, Height = height, StartPosition = FormStartPosition.CenterScreen,
            FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, Font = new System.Drawing.Font("Segoe UI", 9) };
        try { form.Icon = new System.Drawing.Icon(new MemoryStream(ReadBytes("Assets.Glass.ico"))); } catch { }
    }

    private void AddCancelButton(int x, int y)
    {
        cancelButton = new Button { Text = "Cancelar", Left = x, Top = y, Width = 110, Height = 34, DialogResult = DialogResult.Cancel };
        cancelButton.Click += (_, _) => form.Close();
        form.CancelButton = cancelButton;
        form.Controls.Add(cancelButton);
    }

    private Label Text(string value, int x, int y, int width, int height, float size = 10, bool bold = false)
    {
        var label = new Label { Text = value, Left = x, Top = y, Width = width, Height = height,
            Font = new System.Drawing.Font("Segoe UI", size, bold ? System.Drawing.FontStyle.Bold : System.Drawing.FontStyle.Regular) };
        form.Controls.Add(label);
        return label;
    }

    private void BrowseButton(int x, int y, TextBox target, string description)
    {
        var button = new Button { Text = "Examinar…", Left = x, Top = y, Width = 100, Height = 28 };
        button.Click += (_, _) =>
        {
            using var picker = new FolderBrowserDialog { SelectedPath = target.Text, ShowNewFolderButton = true, Description = description };
            if (picker.ShowDialog(form) == DialogResult.OK) target.Text = picker.SelectedPath;
        };
        form.Controls.Add(button);
    }

    private async Task InstallHost()
    {
        if (string.IsNullOrWhiteSpace(destination.Text)) return;
        installRoot = Path.GetFullPath(destination.Text);
        if (Directory.Exists(installRoot) && Directory.EnumerateFileSystemEntries(installRoot).Any() &&
            MessageBox.Show("La carpeta ya contiene archivos. ¿Quieres continuar allí?", "Confirmar carpeta", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
        var selectedIp = hostIp.Text.Split('—', 2)[0].Trim();
        if (!IPAddress.TryParse(selectedIp, out var parsedIp) || parsedIp.AddressFamily != AddressFamily.InterNetwork)
        {
            MessageBox.Show(form, "Elige o escribe la IPv4 privada del adaptador de red al que se conecta la VM.", "Revisar dirección del Host", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        Busy("Preparando la instalación del Host…");
        try
        {
            await Task.Run(async () =>
            {
                Directory.CreateDirectory(Path.Combine(installRoot, "Host"));
                Directory.CreateDirectory(Path.Combine(installRoot, "VM"));
                WriteTextAsset("Assets.host.py", Path.Combine(installRoot, "Host", "host.py"));
                CopyAsset("Assets.Glass.ico", Path.Combine(installRoot, "Host", "Glass.ico"));
                UpdateStatus("Buscando Python 3.12…");
                EnsurePython();
                var venv = Path.Combine(installRoot, ".venv");
                if (!File.Exists(Path.Combine(venv, "Scripts", "python.exe"))) await RunAsync(pythonExe!, "-m venv \"" + venv + "\"", installRoot);
                var py = Path.Combine(venv, "Scripts", "python.exe");
                UpdateStatus("Instalando LibreTranslate y los componentes del Host…");
                await RunAsync(py, "-m pip install --upgrade pip", installRoot);
                await RunAsync(py, "-m pip install libretranslate==1.9.6 comtypes uiautomation \"chardet<6\"", installRoot);
                UpdateStatus("Preparando los modelos de traducción inglés ↔ español…");
                var cli = Process.Start(Program.Hidden(Path.Combine(venv, "Scripts", "libretranslate.exe"), "--host 127.0.0.1 --port 5000 --load-only en,es", installRoot))!;
                try { await WarmModels(cli); } finally { try { if (!cli.HasExited) cli.Kill(true); } catch { } }
                File.Copy(currentExe, Path.Combine(installRoot, "GlassInterpreter-Host.exe"), true);
                // The versioned name also gives Explorer a fresh icon-cache key after replacing an older installer.
                File.Copy(currentExe, Path.Combine(installRoot, "VM", $"GlassInterpreter-VM-{selectedIp}-Beta2.exe"), true);
                CreateShortcut("Glass Interpreter", Path.Combine(installRoot, "GlassInterpreter-Host.exe"), installRoot, "", Path.Combine(installRoot, "Host", "Glass.ico"));
            });
            Done("Instalación lista. Abre Glass Interpreter en el Escritorio. Copia el instalador de la carpeta VM a la máquina virtual y ejecútalo allí.");
        }
        catch (Exception ex) { Error(ex); }
    }

    private async Task InstallVm()
    {
        if (vmHostIp == null || string.IsNullOrWhiteSpace(destination.Text)) return;
        installRoot = Path.GetFullPath(destination.Text);
        if (Directory.Exists(installRoot) && Directory.EnumerateFileSystemEntries(installRoot).Any() &&
            MessageBox.Show("La carpeta ya contiene archivos. ¿Quieres continuar allí?", "Confirmar carpeta", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
        Busy("Preparando la instalación de la VM…");
        try
        {
            await Task.Run(async () =>
            {
                Directory.CreateDirectory(installRoot);
                UpdateStatus("Buscando Python 3.12…");
                EnsurePython();
                var venv = Path.Combine(installRoot, ".venv");
                if (!File.Exists(Path.Combine(venv, "Scripts", "python.exe"))) await RunAsync(pythonExe!, "-m venv \"" + venv + "\"", installRoot);
                var py = Path.Combine(venv, "Scripts", "python.exe");
                UpdateStatus("Instalando los componentes de captura…");
                await RunAsync(py, "-m pip install --upgrade pip", installRoot);
                await RunAsync(py, "-m pip install comtypes uiautomation \"chardet<6\"", installRoot);
                var vmScript = ReadTextAsset("Assets.vm.pyw").Replace("__GLASS_HOST_IP__", vmHostIp);
                File.WriteAllText(Path.Combine(installRoot, "glass_translator_vm.pyw"), vmScript, new UTF8Encoding(false));
                WriteTextAsset("Assets.send_caption.py", Path.Combine(installRoot, "send_caption.py"));
                CopyAsset("Assets.Glass.ico", Path.Combine(installRoot, "Glass.ico"));
                var vmIcon = Path.Combine(installRoot, "Glass-VM-Beta2.ico");
                CopyAsset("Assets.Glass.ico", vmIcon);
                CreateShortcut("Glass Interpreter VM", Path.Combine(venv, "Scripts", "pythonw.exe"), installRoot,
                    "\"" + Path.Combine(installRoot, "glass_translator_vm.pyw") + "\"", vmIcon);
            });
            Done("La VM quedó lista. Abre Subtítulos en vivo en español y haz doble clic en Glass Interpreter VM del Escritorio.");
        }
        catch (Exception ex) { Error(ex); }
    }

    private void EnsurePython()
    {
        pythonExe = FindPython();
        if (pythonExe != null) return;
        UpdateStatus("Descargando Python 3.12…");
        var winget = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Microsoft", "WindowsApps", "winget.exe");
        if (!File.Exists(winget)) winget = "winget.exe";
        RunAsync(winget, "install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements", installRoot).GetAwaiter().GetResult();
        pythonExe = FindPython();
        if (pythonExe == null) throw new InvalidOperationException("Python 3.12 no quedó disponible. Instálalo desde python.org y vuelve a abrir el instalador.");
    }

    private static string? FindPython()
    {
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        return new[] { Path.Combine(local, "Programs", "Python", "Python312", "python.exe"),
            Path.Combine(local, "Python", "pythoncore-3.12-64", "python.exe"), Path.Combine(programFiles, "Python312", "python.exe") }
            .FirstOrDefault(File.Exists);
    }

    private static async Task RunAsync(string exe, string args, string cwd)
    {
        using var process = new Process { StartInfo = Program.Hidden(exe, args, cwd) };
        var stdout = new StringBuilder(); var stderr = new StringBuilder();
        process.OutputDataReceived += (_, e) => { if (e.Data != null) stdout.AppendLine(e.Data); };
        process.ErrorDataReceived += (_, e) => { if (e.Data != null) stderr.AppendLine(e.Data); };
        if (!process.Start()) throw new InvalidOperationException("No se pudo iniciar " + Path.GetFileName(exe));
        process.BeginOutputReadLine(); process.BeginErrorReadLine();
        await process.WaitForExitAsync(); process.WaitForExit();
        if (process.ExitCode != 0) throw new InvalidOperationException((stderr.Length > 0 ? stderr.ToString() : stdout.ToString()).Trim());
    }

    private async Task WarmModels(Process process)
    {
        var output = new StringBuilder(); var gate = new object();
        void Collect(object? _, DataReceivedEventArgs e) { if (!string.IsNullOrWhiteSpace(e.Data)) lock (gate) { if (output.Length > 6000) output.Remove(0, output.Length - 6000); output.AppendLine(e.Data); } }
        process.OutputDataReceived += Collect; process.ErrorDataReceived += Collect;
        process.BeginOutputReadLine(); process.BeginErrorReadLine();
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
        var until = DateTime.UtcNow.AddMinutes(20); Exception? last = null;
        while (DateTime.UtcNow < until)
        {
            if (process.HasExited)
            {
                process.WaitForExit(); string detail; lock (gate) detail = output.ToString().Trim();
                throw new InvalidOperationException("LibreTranslate se cerró al iniciar (código " + process.ExitCode + "). " + detail);
            }
            try
            {
                var health = await http.GetAsync("http://127.0.0.1:5000/languages");
                if (health.IsSuccessStatusCode)
                {
                    foreach (var pair in new[] { ("es", "en", "Hola, ¿cómo estás?"), ("en", "es", "Hello, how are you?") })
                    {
                        UpdateStatus($"Comprobando traducción {pair.Item1.ToUpperInvariant()} → {pair.Item2.ToUpperInvariant()}…");
                        using var body = new FormUrlEncodedContent(new Dictionary<string, string> { ["q"] = pair.Item3, ["source"] = pair.Item1, ["target"] = pair.Item2, ["format"] = "text" });
                        using var response = await http.PostAsync("http://127.0.0.1:5000/translate", body);
                        response.EnsureSuccessStatusCode();
                    }
                    if (!process.HasExited) return;
                }
            }
            catch (Exception ex) { last = ex; }
            await Task.Delay(1500);
        }
        throw new TimeoutException("LibreTranslate no terminó de preparar los modelos en 20 minutos. " + last?.Message);
    }

    private sealed record HostAddress(string Ip, string Adapter, int Priority);

    private static HostAddress[] HostIPv4Candidates()
    {
        var results = new List<HostAddress>();
        foreach (var nic in NetworkInterface.GetAllNetworkInterfaces().Where(n => n.OperationalStatus == OperationalStatus.Up))
        {
            IPInterfaceProperties properties;
            try { properties = nic.GetIPProperties(); } catch { continue; }
            var adapterLabel = string.IsNullOrWhiteSpace(nic.Description) || nic.Description == nic.Name
                ? nic.Name : $"{nic.Name} ({nic.Description})";
            var vmware = (nic.Name + " " + nic.Description).Contains("VMware", StringComparison.OrdinalIgnoreCase);
            var vmnet1 = vmware && Regex.IsMatch(nic.Name + " " + nic.Description, @"VMnet\s*1\b", RegexOptions.IgnoreCase);
            var vmnet8 = vmware && Regex.IsMatch(nic.Name + " " + nic.Description, @"VMnet\s*8\b", RegexOptions.IgnoreCase);
            var vmnetOther = vmware && Regex.IsMatch(nic.Name + " " + nic.Description, @"VMnet\s*\d+\b", RegexOptions.IgnoreCase);
            var isVirtual = nic.NetworkInterfaceType == NetworkInterfaceType.Tunnel ||
                Regex.IsMatch(nic.Name + " " + nic.Description, @"Virtual|Hyper-V|vEthernet|VirtualBox|TAP|VPN|WSL", RegexOptions.IgnoreCase);
            var hasGateway = properties.GatewayAddresses.Any(g => g.Address.AddressFamily == AddressFamily.InterNetwork && !g.Address.Equals(IPAddress.Any));
            var physicalEthernet = nic.NetworkInterfaceType == NetworkInterfaceType.Ethernet && !vmware && !isVirtual;
            var priority = physicalEthernet && hasGateway ? 0 : physicalEthernet ? 1 : vmnet8 ? 2 : vmnet1 ? 3 : vmware && vmnetOther ? 4 : !isVirtual && hasGateway ? 5 : !isVirtual ? 6 : 7;

            foreach (var item in properties.UnicastAddresses)
            {
                var address = item.Address;
                if (address.AddressFamily != AddressFamily.InterNetwork || IPAddress.IsLoopback(address) || !IsPrivateIPv4(address)) continue;
                results.Add(new HostAddress(address.ToString(), adapterLabel, priority));
            }
        }
        return results.GroupBy(x => x.Ip, StringComparer.Ordinal).Select(g => g.OrderBy(x => x.Priority).First())
            .OrderBy(x => x.Priority).ThenBy(x => x.Adapter, StringComparer.OrdinalIgnoreCase).ToArray();
    }

    private static bool IsPrivateIPv4(IPAddress address)
    {
        var b = address.GetAddressBytes();
        return b[0] == 10 || (b[0] == 192 && b[1] == 168) || (b[0] == 172 && b[1] >= 16 && b[1] <= 31);
    }

    private static byte[] ReadBytes(string name)
    { using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name) ?? throw new FileNotFoundException(name); using var memory = new MemoryStream(); stream.CopyTo(memory); return memory.ToArray(); }
    private static string ReadTextAsset(string name) => Encoding.UTF8.GetString(ReadBytes(name));
    private static void WriteTextAsset(string name, string path) => File.WriteAllText(path, ReadTextAsset(name), new UTF8Encoding(false));
    private static void CopyAsset(string name, string path) => File.WriteAllBytes(path, ReadBytes(name));

    private static void CreateShortcut(string name, string target, string cwd, string args, string icon)
    {
        var desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        Directory.CreateDirectory(desktop);
        var path = Path.Combine(desktop, name + ".lnk");
        var type = Type.GetTypeFromProgID("WScript.Shell") ?? throw new InvalidOperationException("No pude crear el acceso directo.");
        dynamic shell = Activator.CreateInstance(type)!;
        dynamic shortcut = shell.CreateShortcut(path);
        shortcut.TargetPath = target; shortcut.Arguments = args; shortcut.WorkingDirectory = cwd;
        shortcut.IconLocation = icon + ",0"; shortcut.Save();
        if (!File.Exists(path)) throw new InvalidOperationException("No se creó el acceso directo del Escritorio.");
        SHChangeNotify(0x00002000, 0x0005, path, IntPtr.Zero);
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, EntryPoint = "SHChangeNotify")]
    private static extern void SHChangeNotify(uint eventId, uint flags, string path, IntPtr item2);

    private void Busy(string text) { action.Enabled = false; cancelButton.Enabled = false; progress.Visible = true; status.Text = text; Application.DoEvents(); }
    private void UpdateStatus(string text)
    {
        if (form.IsDisposed || !form.IsHandleCreated) return;
        if (form.InvokeRequired) form.BeginInvoke(new Action(() => { if (!form.IsDisposed) status.Text = text; }));
        else status.Text = text;
    }
    private void Done(string text) { progress.Visible = false; status.Text = text; action.Text = "Terminar"; action.Enabled = true; cancelButton.Enabled = true; }
    private void Error(Exception ex) { progress.Visible = false; status.Text = "No se pudo completar la instalación."; action.Enabled = true; cancelButton.Enabled = true; MessageBox.Show(form, ex.Message, "Instalación incompleta", MessageBoxButtons.OK, MessageBoxIcon.Error); }
}
