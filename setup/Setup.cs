using System;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Diagnostics;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Drawing;

internal sealed class Setup : Form
{
    const string RuntimeUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.12.14%2B20260901-x86_64-pc-windows-msvc-install_only_stripped.tar.gz";
    const string RuntimeHash = "7c45c9622400d578709a9b2cddbe8124cc21d382409d9f13406d706d28e31b14";
    readonly Label stage = new Label();
    readonly TextBox log = new TextBox();
    readonly Button action = new Button();
    readonly string appRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","Csillagszemu-Juhasz");
    bool busy;
    bool checking;
    string checkLog;
    string installed;
    Setup()
    {
        Text = "Csillagszemű Juhász setup";
        ClientSize = new Size(612,328);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Segoe UI",10);
        var title = new Label {Text="Install Csillagszemű Juhász", Font=new Font("Segoe UI",18,FontStyle.Bold), AutoSize=true, Left=18, Top=14};
        stage.SetBounds(20,59,572,52);
        stage.Text="Windows x64 · Installs for your account. The first install downloads a private Python runtime, vision libraries and three models.";
        log.SetBounds(20,112,572,150);
        log.Multiline=true; log.ReadOnly=true; log.ScrollBars=ScrollBars.Vertical;
        action.SetBounds(418,278,174,32); action.Text="Install";
        action.Click += async delegate {
            if (installed!=null) { Launch(installed); Close(); return; }
            busy=true; action.Enabled=false;
            try {
                installed=await Task.Run((Func<string>)Install);
                stage.Text="Installation complete. Csillagszemű Juhász is also in your Start menu.";
                action.Text="Open Csillagszemű Juhász";
            } catch (Exception ex) {
                stage.Text="Installation stopped. The details below identify the failed step.";
                Note(ex.GetBaseException().Message); action.Text="Retry";
            } finally {busy=false; action.Enabled=true;}
        };
        FormClosing += (s,e) => {if(busy) e.Cancel=true;};
        Controls.AddRange(new Control[]{title,stage,log,action});
    }
    void Note(string text)
    {
        if(checking) {
            lock(log) File.AppendAllText(checkLog,text+Environment.NewLine);
            return;
        }
        if (InvokeRequired) { BeginInvoke((Action<string>)Note,text); return; }
        log.AppendText(text+Environment.NewLine);
    }
    void Step(string text)
    {
        if(!checking) Invoke((Action)(()=>stage.Text=text));
        Note(text);
    }
    static string Quote(string value) { return "\""+value+"\""; }
    static string Digest(Stream stream)
    {
        using(var sha=SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
    }
    static Stream Payload()
    {
        return Assembly.GetExecutingAssembly().GetManifestResourceStream("csillagszem.zip");
    }
    static void Unpack(string folder)
    {
        using(var stream=Payload())
        using(var zip=new ZipArchive(stream,ZipArchiveMode.Read)) zip.ExtractToDirectory(folder);
    }
    void Run(string exe,string args,string directory)
    {
        var info=new ProcessStartInfo(exe,args){WorkingDirectory=directory,UseShellExecute=false,CreateNoWindow=true,
                                               RedirectStandardOutput=true,RedirectStandardError=true};
        info.EnvironmentVariables["PYTHONNOUSERSITE"]="1";
        info.EnvironmentVariables.Remove("PYTHONPATH");
        info.EnvironmentVariables.Remove("PYTHONHOME");
        using(var proc=new Process{StartInfo=info}) {
            proc.OutputDataReceived+=(s,e)=>{if(e.Data!=null) Note(e.Data);};
            proc.ErrorDataReceived+=(s,e)=>{if(e.Data!=null) Note(e.Data);};
            proc.Start(); proc.BeginOutputReadLine(); proc.BeginErrorReadLine(); proc.WaitForExit();
            if(proc.ExitCode!=0) throw new IOException(Path.GetFileName(exe)+" exited with code "+proc.ExitCode+".");
        }
    }
    static void Shortcut(string folder)
    {
        Type shellType=Type.GetTypeFromProgID("WScript.Shell",true);
        dynamic shell=Activator.CreateInstance(shellType);
        string path=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),"Csillagszemű Juhász.lnk");
        dynamic link=shell.CreateShortcut(path);
        link.TargetPath=Path.Combine(folder,"python","pythonw.exe");
        link.Arguments="-E -s "+Quote(Path.Combine(folder,"run.py"));
        link.WorkingDirectory=folder;
        link.Description="Csillagszemű Juhász desktop eye tracker";
        link.Save();
    }
    string Install()
    {
        return InstallInto(appRoot);
    }
    string InstallInto(string targetRoot)
    {
        if(!Environment.Is64BitOperatingSystem) throw new PlatformNotSupportedException("Windows x64 is required.");
        Directory.CreateDirectory(targetRoot);
        string fingerprint;
        using(var stream=Payload()) fingerprint=Digest(stream).Substring(0,16);
        var destination=Path.Combine(targetRoot,"build-"+fingerprint);
        using(var lockFile=new FileStream(Path.Combine(targetRoot,"setup.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None)) {
            if(File.Exists(Path.Combine(destination,"ready"))) { if(!checking) Shortcut(destination); return destination; }
            var job=Path.Combine(targetRoot,"setup-"+Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(job);
            try {
                Step("Downloading the Windows runtime");
                var archive=Path.Combine(job,"runtime.tar.gz");
                ServicePointManager.SecurityProtocol=SecurityProtocolType.Tls12;
                using(var web=new WebClient()) {
                    web.Headers["User-Agent"]="Csillagszemu-Juhasz-Setup/0.1";
                    web.DownloadFile(RuntimeUrl,archive);
                }
                using(var file=File.OpenRead(archive))
                    if(Digest(file)!=RuntimeHash) throw new InvalidDataException("Runtime checksum mismatch.");
                Step("Preparing the application");
                Run(Path.Combine(Environment.SystemDirectory,"tar.exe"),"-xf "+Quote(archive)+" -C "+Quote(job),job);
                File.Delete(archive);
                Unpack(job);
                string python=Path.Combine(job,"python","python.exe");
                Step("Installing the vision libraries");
                Run(python,"-I -m pip --isolated install --disable-pip-version-check --only-binary=:all: -r "+Quote(Path.Combine(job,"requirements.txt")),job);
                Run(python,"-I -m pip check",job);
                Step("Downloading and verifying model weights");
                Run(python,"-I "+Quote(Path.Combine(job,"setup","assets.py")),job);
                Step("Checking the models and Windows interface");
                Run(python,"-E -s "+Quote(Path.Combine(job,"run.py"))+" --verify",job);
                File.WriteAllText(Path.Combine(job,"ready"),fingerprint);
                Directory.Move(job,destination);
                if(!checking) Shortcut(destination);
                return destination;
            } finally {
                // Only our newly allocated, GUID-named staging directory is eligible.
                if(Directory.Exists(job) && Path.GetDirectoryName(Path.GetFullPath(job))==Path.GetFullPath(targetRoot))
                    try {Directory.Delete(job,true);} catch(IOException) {} catch(UnauthorizedAccessException) {}
            }
        }
    }
    static void Launch(string folder)
    {
        var p=new ProcessStartInfo(Path.Combine(folder,"python","pythonw.exe"),"-E -s "+Quote(Path.Combine(folder,"run.py")));
        p.WorkingDirectory=folder; p.UseShellExecute=false; Process.Start(p);
    }
    [STAThread]
    static int Main(string[] args)
    {
        if(args.Length==2 && args[0]=="--extract") {Unpack(Path.GetFullPath(args[1])); return 0;}
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        if(args.Length==2 && args[0]=="--test-install") {
            string folder=Path.GetFullPath(args[1]);
            Directory.CreateDirectory(folder);
            using(var setup=new Setup()) {
                setup.checking=true;
                setup.checkLog=Path.Combine(folder,"installer.log");
                try {
                    string destination=setup.InstallInto(folder);
                    File.WriteAllText(Path.Combine(folder,"installed.txt"),destination);
                    return 0;
                } catch(Exception e) { setup.Note(e.ToString()); return 1; }
            }
        }
        Application.Run(new Setup());
        return 0;
    }
}
