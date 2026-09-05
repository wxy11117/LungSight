// 本地启动器：只管理本次启动的子进程，不结束用户已有的服务。
using System;
using System.IO;
using System.Diagnostics;
using System.Drawing;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

class Launcher : Form {
    const string Url = "http://127.0.0.1:18000/auth";
    static string Identity = "LungSight.Desktop." + Environment.UserName;
    static EventWaitHandle stop;
    string root = AppDomain.CurrentDomain.BaseDirectory;
    string dataRoot = Environment.GetEnvironmentVariable("LUNGSIGHT_DESKTOP_DATA_ROOT") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "LungSight");
    Process backend, frontend;
    IntPtr job;
    Label status = new Label();
    Button open = new Button();
    Button retry = new Button();
    bool headless, closing;
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr a, string name);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr h, int c, ref JobLimits info, uint size);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr h, IntPtr p);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    [StructLayout(LayoutKind.Sequential)] struct BasicLimits {public long a,b; public uint flags; public UIntPtr min,max; public uint active; public UIntPtr affinity; public uint priority,scheduling;}
    [StructLayout(LayoutKind.Sequential)] struct IoCounters {public ulong a,b,c,d,e,f;}
    [StructLayout(LayoutKind.Sequential)] struct JobLimits {public BasicLimits basic; public IoCounters io; public UIntPtr a,b,c,d;}
    [STAThread] static int Main(string[] args) {
        if (Array.IndexOf(args,"--shutdown") >= 0) {
            try { using(var ev=EventWaitHandle.OpenExisting(Identity+".Stop")) ev.Set(); } catch(WaitHandleCannotBeOpenedException) {}
            // 卸载器必须等待我们自己的启动器释放文件。
            for(int i=0;i<100;i++) { try { using(var m=Mutex.OpenExisting(Identity+".Mutex")) {Thread.Sleep(100);} } catch(WaitHandleCannotBeOpenedException) {return 0;} }
            return 1;
        }
        bool created;
        using(var mutex=new Mutex(true,Identity+".Mutex",out created)) {
            if(!created) { Process.Start(Url); return 0; }
            using(stop=new EventWaitHandle(false,EventResetMode.ManualReset,Identity+".Stop")) {
                Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                var f=new Launcher(Array.IndexOf(args,"--headless")>=0); Application.Run(f);
            }
        }
        return 0;
    }
    Launcher(bool silent) {
        headless=silent; Text="LungSight · 公共测试版本"; Size=new Size(560,290); MinimumSize=Size;
        StartPosition=FormStartPosition.CenterScreen; BackColor=Color.FromArgb(243,249,250);
        Font=new Font("Microsoft YaHei UI",10); MaximizeBox=false;
        var title=new Label {Text="LungSight",Font=new Font("Segoe UI",24,FontStyle.Bold),Location=new Point(28,20),AutoSize=true}; Controls.Add(title);
        status.SetBounds(30,82,485,68); status.Text="正在准备本地工作区…"; Controls.Add(status);
        open.Text="打开工作区"; open.SetBounds(30,165,150,40); open.Enabled=false; open.Click+=(s,e)=>Process.Start(Url); Controls.Add(open);
        retry.Text="重新启动"; retry.SetBounds(190,165,130,40); retry.Enabled=false; retry.Click+=async(s,e)=>await StartServices(); Controls.Add(retry);
        var logs=new Button {Text="查看日志",Bounds=new Rectangle(330,165,130,40)}; logs.Click+=(s,e)=>Process.Start(Path.Combine(dataRoot,"logs")); Controls.Add(logs);
        Controls.Add(new Label {Text="关闭此窗口将停止服务。仅供科研与辅助信息分析。",Bounds=new Rectangle(30,219,490,25),ForeColor=Color.DimGray});
        Shown+=async(s,e)=>{if(headless) Hide(); await StartServices();};
        FormClosing+=(s,e)=>{closing=true; StopServices();};
        var timer=new System.Windows.Forms.Timer {Interval=500};
        timer.Tick+=(s,e)=>{if(stop.WaitOne(0)) Close(); else if(open.Enabled && ((backend!=null && backend.HasExited)||(frontend!=null && frontend.HasExited))) { StopServices(); open.Enabled=false; retry.Enabled=true; status.Text="服务意外停止。请查看日志，然后重新启动。"; }};
        timer.Start();
    }
    bool Free(int port) {try {var l=new TcpListener(IPAddress.Loopback,port); l.Start(); l.Stop(); return true;} catch(SocketException) {return false;}}
    Process StartChild(string exe,string args,string cwd,string logfile,bool node) {
        var info=new ProcessStartInfo(exe,args) {WorkingDirectory=cwd,UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,RedirectStandardOutput=true,RedirectStandardError=true};
        info.StandardOutputEncoding=System.Text.Encoding.UTF8; info.StandardErrorEncoding=System.Text.Encoding.UTF8;
        foreach(string name in new[]{"PYTHONHOME","PYTHONPATH","LUNGSIGHT_CREDENTIAL_SECRET","LUNGSIGHT_AUTH_DISABLED","LUNGSIGHT_DATABASE_PATH","NODE_OPTIONS"}) info.EnvironmentVariables.Remove(name);
        info.EnvironmentVariables["PYTHONNOUSERSITE"]="1"; info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"]="1";
        info.EnvironmentVariables["PYTHONUTF8"]="1";
        info.EnvironmentVariables["LUNGSIGHT_DATA_DIR"]=Path.Combine(dataRoot,"data"); info.EnvironmentVariables["LUNGSIGHT_COOKIE_SECURE"]="0";
        info.EnvironmentVariables["PORT"]="18000"; info.EnvironmentVariables["HOST"]="127.0.0.1"; info.EnvironmentVariables["NODE_ENV"]="production";
        var p=new Process {StartInfo=info}; var sync=new object();
        DataReceivedEventHandler log=(s,e)=>{if(e.Data!=null) lock(sync) {try {File.AppendAllText(logfile,DateTime.Now.ToString("s")+" "+e.Data+Environment.NewLine);} catch(IOException) {}}};
        p.OutputDataReceived+=log; p.ErrorDataReceived+=log; p.Start();
        if(!AssignProcessToJobObject(job,p.Handle)) {p.Kill(); throw new Exception("无法安全管理服务进程，请重新启动软件。");}
        p.BeginOutputReadLine(); p.BeginErrorReadLine(); return p;
    }
    async Task StartServices() {
        StopServices(); open.Enabled=false; retry.Enabled=false;
        try {
            Directory.CreateDirectory(Path.Combine(dataRoot,"logs"));
            if(!Free(18000)||!Free(18001)) throw new Exception("端口 18000 或 18001 已被其他程序占用。请关闭冲突程序后重试；不会自动结束其他程序。");
            job=CreateJobObject(IntPtr.Zero,null); var limits=new JobLimits(); limits.basic.flags=0x2000;
            if(job==IntPtr.Zero || !SetInformationJobObject(job,9,ref limits,(uint)Marshal.SizeOf(limits))) throw new Exception("无法创建安全的服务进程组。");
            status.Text="正在加载五折模型，首次启动可能需要约 1 分钟…";
            backend=StartChild(Path.Combine(root,"runtime","python","python.exe"),"-u desktop_backend.py",Path.Combine(root,"lung-vision-site","backend"),Path.Combine(dataRoot,"logs","backend.log"),false);
            frontend=StartChild(Path.Combine(root,"runtime","node.exe"),"server.js",Path.Combine(root,"frontend"),Path.Combine(dataRoot,"logs","frontend.log"),true);
            bool ready=false;
            for(int i=0;i<180 && !closing;i++) {
                if(backend.HasExited || frontend.HasExited) throw new Exception("服务启动失败。请通过“查看日志”检查具体原因。");
                ready=await Task.Run(()=>Healthy()); if(ready) break; await Task.Delay(1000);
            }
            if(closing) return;
            if(!ready) throw new Exception("等待模型启动超时，请查看日志并重试。");
            status.Text="服务已就绪 · 五折模型已加载\n本机记录独立保存；AI 问答 API Key 请在设置中配置。";
            open.Enabled=true; if(!headless) Process.Start(Url);
        } catch(Exception ex) {StopServices(); status.Text=ex.Message; retry.Enabled=true;}
    }
    bool Healthy() {
        try {
            var r=(HttpWebRequest)WebRequest.Create("http://127.0.0.1:18001/api/health"); r.Timeout=1500; r.Proxy=null;
            string body; using(var res=r.GetResponse()) using(var reader=new StreamReader(res.GetResponseStream())) body=reader.ReadToEnd();
            if(!body.Replace(" ","").Contains("\"models_loaded\":5")) return false;
            var f=(HttpWebRequest)WebRequest.Create(Url); f.Timeout=1500; f.Proxy=null; using(var res=f.GetResponse()) return ((HttpWebResponse)res).StatusCode==HttpStatusCode.OK;
        } catch(WebException) {return false;}
    }
    void StopServices() {if(job!=IntPtr.Zero) {CloseHandle(job); job=IntPtr.Zero;} foreach(var p in new[]{backend,frontend}) if(p!=null) {try {if(!p.HasExited) p.Kill(); p.WaitForExit(3000); p.Dispose();} catch(InvalidOperationException) {}} backend=null; frontend=null;}
}
