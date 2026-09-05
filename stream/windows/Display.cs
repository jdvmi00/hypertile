// Windows CCD display operations. No window automation or process control.
using System;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class HypertileDisplay {
    [StructLayout(LayoutKind.Sequential)] public struct Luid { public uint low; public int high; }
    [StructLayout(LayoutKind.Sequential)] public struct Rational { public uint numerator, denominator; }
    [StructLayout(LayoutKind.Sequential)] public struct Source { public Luid adapter; public uint id, mode, flags; }
    [StructLayout(LayoutKind.Sequential)] public struct Target {
        public Luid adapter; public uint id, mode, technology, rotation, scaling;
        public Rational refresh; public uint scanline;
        [MarshalAs(UnmanagedType.Bool)] public bool available;
        public uint flags;
    }
    [StructLayout(LayoutKind.Sequential)] public struct DisplayPath { public Source source; public Target target; public uint flags; }
    [StructLayout(LayoutKind.Explicit, Size=64)] public struct Mode {
        [FieldOffset(0)] public uint type; [FieldOffset(4)] public uint id;
        [FieldOffset(8)] public Luid adapter;
        [FieldOffset(16)] public ulong a; [FieldOffset(24)] public ulong b;
        [FieldOffset(32)] public ulong c; [FieldOffset(40)] public ulong d;
        [FieldOffset(48)] public ulong e; [FieldOffset(56)] public ulong f;
    }
    [StructLayout(LayoutKind.Sequential)] public struct Header { public uint type, size; public Luid adapter; public uint id; }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] public struct TargetName {
        public Header header; public uint flags, technology; public ushort manufacturer, product; public uint connector;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=64)] public string friendly;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string path;
    }
    [DllImport("user32.dll")] static extern int GetDisplayConfigBufferSizes(uint flags, out uint paths, out uint modes);
    [DllImport("user32.dll")] static extern int QueryDisplayConfig(uint flags, ref uint np, [Out] DisplayPath[] paths, ref uint nm, [Out] Mode[] modes, IntPtr topology);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int DisplayConfigGetDeviceInfo(ref TargetName name);
    [DllImport("user32.dll")] static extern int SetDisplayConfig(uint np, DisplayPath[] paths, uint nm, Mode[] modes, uint flags);
    public class Display { public string id, name; public bool active, available, internalPanel, primary; public uint width, height; }
    public class Snapshot { public string paths, modes; public string[] ids; }
    class Config { public DisplayPath[] paths; public Mode[] modes; }
    static void Check(int code, string op) { if(code!=0) throw new InvalidOperationException(op+": Windows error "+code); }
    static Config Query(uint flags) {
        for(int i=0;i<5;i++) {
            uint np,nm; Check(GetDisplayConfigBufferSizes(flags,out np,out nm),"display inventory");
            var paths=new DisplayPath[np]; var modes=new Mode[nm];
            int code=QueryDisplayConfig(flags,ref np,paths,ref nm,modes,IntPtr.Zero);
            if(code==122) continue;
            Check(code,"display inventory");
            return new Config {paths=paths.Take((int)np).ToArray(), modes=modes.Take((int)nm).ToArray()};
        }
        throw new InvalidOperationException("display inventory changed repeatedly");
    }
    static TargetName Name(DisplayPath path) {
        var name=new TargetName(); name.header.type=2; name.header.size=(uint)Marshal.SizeOf(typeof(TargetName));
        name.header.adapter=path.target.adapter; name.header.id=path.target.id;
        Check(DisplayConfigGetDeviceInfo(ref name),"display identity"); return name;
    }
    public static Display[] Inspect() {
        var c=Query(1); var result=new Dictionary<string,Display>(StringComparer.OrdinalIgnoreCase);
        foreach(var p in c.paths) {
            var n=Name(p); if(String.IsNullOrEmpty(n.path)) continue;
            bool active=(p.flags&1)!=0;
            Display d;
            if(!result.TryGetValue(n.path,out d)) {
                d=new Display {id=n.path,name=n.friendly,available=p.target.available,
                    internalPanel=p.target.technology==0x80000000 || p.target.technology==6 || p.target.technology==11 || p.target.technology==13};
                result.Add(n.path,d);
            }
            d.available|=p.target.available; d.active|=active;
            if(active && p.source.mode<c.modes.Length) {
                var m=c.modes[p.source.mode];
                if(m.type==1) { d.width=(uint)m.a; d.height=(uint)(m.a>>32); d.primary=(int)(m.b>>32)==0 && (int)m.c==0; }
            }
        }
        return result.Values.ToArray();
    }
    static string Pack<T>(T[] values) {
        int size=Marshal.SizeOf(typeof(T)); byte[] data=new byte[checked(size*values.Length)]; IntPtr p=Marshal.AllocHGlobal(size);
        try { for(int i=0;i<values.Length;i++) {Marshal.StructureToPtr(values[i],p,false);Marshal.Copy(p,data,i*size,size);} }
        finally {Marshal.FreeHGlobal(p);} return Convert.ToBase64String(data);
    }
    static T[] Unpack<T>(string value) {
        byte[] data=Convert.FromBase64String(value); int size=Marshal.SizeOf(typeof(T));
        if(data.Length%size!=0 || data.Length>1048576) throw new InvalidOperationException("invalid display snapshot");
        T[] result=new T[data.Length/size]; IntPtr p=Marshal.AllocHGlobal(size);
        try {for(int i=0;i<result.Length;i++) {Marshal.Copy(data,i*size,p,size);result[i]=(T)Marshal.PtrToStructure(p,typeof(T));}}
        finally {Marshal.FreeHGlobal(p);} return result;
    }
    public static Snapshot Capture() {
        var c=Query(2); return new Snapshot {paths=Pack(c.paths),modes=Pack(c.modes),ids=c.paths.Select(p=>Name(p).path).Distinct(StringComparer.OrdinalIgnoreCase).ToArray()};
    }
    public static void Restore(string paths, string modes) {
        var ps=Unpack<DisplayPath>(paths); var ms=Unpack<Mode>(modes);
        if(ps.Length==0) throw new InvalidOperationException("empty physical display snapshot");
        Check(SetDisplayConfig((uint)ps.Length,ps,(uint)ms.Length,ms,0x60),"validate physical displays");
        Check(SetDisplayConfig((uint)ps.Length,ps,(uint)ms.Length,ms,0x2a0),"restore physical displays");
    }
    public static void Only(string id, bool persist) {
        var c=Query(1);
        var matches=c.paths.Where(p=>p.target.available && String.Equals(Name(p).path,id,StringComparison.OrdinalIgnoreCase)).ToArray();
        if(matches.Length==0) throw new InvalidOperationException("display unavailable");
        // Prefer the currently active path, which has a source known to work.
        var path=matches.OrderByDescending(p=>(p.flags&1)!=0).First();
        path.flags=1;path.source.mode=UInt32.MaxValue;path.target.mode=UInt32.MaxValue;
        var ps=new[]{path};
        // Use the target's saved mode first. If that topology has never existed,
        // let Windows choose a supported mode. Preparation does not persist it.
        int code=SetDisplayConfig(1,ps,0,null,0x50);
        if(code==0 && !persist) { Check(SetDisplayConfig(1,ps,0,null,0x90),"activate stream display"); return; }
        Check(SetDisplayConfig(1,ps,0,null,0x460),"validate display");
        Check(SetDisplayConfig(1,ps,0,null,persist ? 0x6a0u : 0x4a0u),"activate display");
    }
    public static void Remove(string id) {
        var c=Query(2); var ps=c.paths.Where(p=>!String.Equals(Name(p).path,id,StringComparison.OrdinalIgnoreCase)).ToArray();
        if(ps.Length==0) throw new InvalidOperationException("no physical display available");
        Check(SetDisplayConfig((uint)ps.Length,ps,(uint)c.modes.Length,c.modes,0x60),"validate physical displays");
        Check(SetDisplayConfig((uint)ps.Length,ps,(uint)c.modes.Length,c.modes,0x2a0),"deactivate stream display");
    }
}
