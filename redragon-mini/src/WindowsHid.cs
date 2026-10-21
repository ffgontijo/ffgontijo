using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace RedragonMini
{
    public sealed class HidDeviceInfo
    {
        public string Path { get; internal set; }
        public ushort VendorId { get; internal set; }
        public ushort ProductId { get; internal set; }
        public ushort UsagePage { get; internal set; }
        public ushort Usage { get; internal set; }
        public ushort InputReportLength { get; internal set; }
        public ushort OutputReportLength { get; internal set; }
        public ushort FeatureReportLength { get; internal set; }
        public string ProductName { get; internal set; }

        public bool CanExchange
        {
            get
            {
                return VendorId == 0x3554 &&
                    (ProductId == 0xF55E || ProductId == 0xF5D5) &&
                    Path.IndexOf("&mi_01", StringComparison.OrdinalIgnoreCase) >= 0 &&
                    Path.IndexOf("&col05", StringComparison.OrdinalIgnoreCase) >= 0 &&
                    InputReportLength == 17 && OutputReportLength == 17;
            }
        }

        public override string ToString()
        {
            string connection = ProductId == 0xF55E ? "USB com cabo" : "Receptor USB";
            return string.Format("{0} — {1} (3554:{2:X4}, uso {3:X4}:{4:X4})",
                string.IsNullOrWhiteSpace(ProductName) ? "Redragon M719-WL" : ProductName,
                connection, ProductId, UsagePage, Usage);
        }
    }

    /// <summary>
    /// Windows HID transport for the exact 17-byte output/interrupt-input protocol
    /// observed in the supplied USB captures. No custom driver is installed.
    /// </summary>
    public sealed class WindowsHid : IReportTransport, IDisposable
    {
        const uint GenericRead = 0x80000000;
        const uint GenericWrite = 0x40000000;
        const uint ShareReadWrite = 3;
        const uint OpenExisting = 3;
        const uint FileFlagOverlapped = 0x40000000;
        const uint DigcfPresent = 2;
        const uint DigcfDeviceInterface = 0x10;
        const int ErrorNoMoreItems = 259;
        const int ErrorInsufficientBuffer = 122;
        const int ErrorIoPending = 997;
        const uint WaitObject0 = 0;
        const uint WaitTimeout = 258;
        const uint WaitFailed = 0xFFFFFFFF;

        readonly object gate = new object();
        SafeFileHandle handle;
        bool disposed;
        public HidDeviceInfo Device { get; private set; }

        public static IReadOnlyList<HidDeviceInfo> Enumerate()
        {
            var result = new List<HidDeviceInfo>();
            Guid hidGuid;
            HidD_GetHidGuid(out hidGuid);
            IntPtr set = SetupDiGetClassDevs(ref hidGuid, null, IntPtr.Zero,
                DigcfPresent | DigcfDeviceInterface);
            if (set == new IntPtr(-1)) throw NativeError("Não foi possível enumerar os dispositivos HID");
            try
            {
                for (uint index = 0; ; index++)
                {
                    var data = new SpDeviceInterfaceData();
                    data.Size = Marshal.SizeOf(typeof(SpDeviceInterfaceData));
                    if (!SetupDiEnumDeviceInterfaces(set, IntPtr.Zero, ref hidGuid, index, ref data))
                    {
                        int error = Marshal.GetLastWin32Error();
                        if (error == ErrorNoMoreItems) break;
                        throw new Win32Exception(error, "Não foi possível enumerar uma interface HID");
                    }
                    uint required;
                    SetupDiGetDeviceInterfaceDetail(set, ref data, IntPtr.Zero, 0, out required, IntPtr.Zero);
                    int detailError = Marshal.GetLastWin32Error();
                    if (required < 6 || detailError != ErrorInsufficientBuffer) continue;
                    IntPtr detail = Marshal.AllocHGlobal((int)required);
                    try
                    {
                        // SP_DEVICE_INTERFACE_DETAIL_DATA_W.cbSize is 8 on x64,
                        // 6 on x86; DevicePath itself starts at offset 4 on both.
                        Marshal.WriteInt32(detail, IntPtr.Size == 8 ? 8 : 6);
                        if (!SetupDiGetDeviceInterfaceDetail(set, ref data, detail, required, out required, IntPtr.Zero))
                            continue;
                        string path = Marshal.PtrToStringUni(IntPtr.Add(detail, 4));
                        if (string.IsNullOrEmpty(path) ||
                            path.IndexOf("vid_3554", StringComparison.OrdinalIgnoreCase) < 0 ||
                            (path.IndexOf("pid_f55e", StringComparison.OrdinalIgnoreCase) < 0 &&
                             path.IndexOf("pid_f5d5", StringComparison.OrdinalIgnoreCase) < 0)) continue;
                        using (SafeFileHandle query = CreateFile(path, 0, ShareReadWrite,
                            IntPtr.Zero, OpenExisting, 0, IntPtr.Zero))
                        {
                            if (query.IsInvalid) continue;
                            HidDeviceInfo info = QueryDevice(query, path);
                            if (info != null) result.Add(info);
                        }
                    }
                    finally { Marshal.FreeHGlobal(detail); }
                }
            }
            finally { SetupDiDestroyDeviceInfoList(set); }
            return result.AsReadOnly();
        }

        public WindowsHid(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) throw new ArgumentException("Selecione o mouse USB.", "path");
            SafeFileHandle opened = CreateFile(path, GenericRead | GenericWrite, ShareReadWrite,
                IntPtr.Zero, OpenExisting, FileFlagOverlapped, IntPtr.Zero);
            if (opened.IsInvalid)
            {
                int error = Marshal.GetLastWin32Error();
                opened.Dispose();
                throw new Win32Exception(error, "Não foi possível abrir o mouse. Feche o aplicativo original e tente novamente.");
            }
            try
            {
                Device = QueryDevice(opened, path);
                if (Device == null || !Device.CanExchange)
                    throw new IOException("Esta interface não corresponde ao protocolo USB de 17 bytes do M719-WL.");
                handle = opened;
            }
            catch { opened.Dispose(); throw; }
        }

        static HidDeviceInfo QueryDevice(SafeFileHandle device, string path)
        {
            var attributes = new HiddAttributes();
            attributes.Size = Marshal.SizeOf(typeof(HiddAttributes));
            if (!HidD_GetAttributes(device, ref attributes)) return null;
            IntPtr preparsed;
            if (!HidD_GetPreparsedData(device, out preparsed)) return null;
            try
            {
                HidpCaps caps;
                if (HidP_GetCaps(preparsed, out caps) != 0x00110000) return null;
                var info = new HidDeviceInfo
                {
                    Path = path, VendorId = attributes.VendorId, ProductId = attributes.ProductId,
                    UsagePage = caps.UsagePage, Usage = caps.Usage,
                    InputReportLength = caps.InputReportByteLength,
                    OutputReportLength = caps.OutputReportByteLength,
                    FeatureReportLength = caps.FeatureReportByteLength,
                    ProductName = ""
                };
                IntPtr name = Marshal.AllocHGlobal(256);
                try
                {
                    Marshal.WriteInt16(name, 0);
                    if (HidD_GetProductString(device, name, 256)) info.ProductName = Marshal.PtrToStringUni(name) ?? "";
                }
                finally { Marshal.FreeHGlobal(name); }
                return info;
            }
            finally { HidD_FreePreparsedData(preparsed); }
        }

        public byte[] Exchange(byte[] output, int timeoutMs = 1500)
        {
            if (output == null) throw new ArgumentNullException("output");
            if (output.Length != 17 || output[0] != 8) throw new ArgumentException("O relatório deve ter 17 bytes e ID 08.", "output");
            if (timeoutMs < 1 || timeoutMs > 30000) throw new ArgumentOutOfRangeException("timeoutMs");
            lock (gate)
            {
                if (disposed) throw new ObjectDisposedException("WindowsHid");
                if (!HidD_FlushQueue(handle)) throw NativeError("Não foi possível limpar a fila de respostas HID");
                var elapsed = Stopwatch.StartNew();
                using (var read = new PendingRead(handle))
                {
                    // Arm the interrupt input read before issuing SET_REPORT so a
                    // fast device response cannot be missed.
                    read.Start();
                    if (!HidD_SetOutputReport(handle, output, output.Length))
                        throw NativeError("Não foi possível enviar SET_REPORT ao mouse");
                    for (;;)
                    {
                        int remaining = timeoutMs - (int)elapsed.ElapsedMilliseconds;
                        if (remaining <= 0) throw new TimeoutException("O mouse não respondeu ao comando USB no prazo esperado.");
                        byte[] response = read.Complete(remaining);
                        if (Matches(output, response)) return response;
                        read.Start();
                    }
                }
            }
        }

        static bool Matches(byte[] request, byte[] response)
        {
            if (response.Length != 17 || response[0] != 8 || response[1] != request[1] || response[2] != 0) return false;
            int checksum = 0;
            for (int i = 0; i < response.Length; i++) checksum += response[i];
            if ((checksum & 255) != 0x55) return false;
            if ((request[1] == 7 || request[1] == 8) &&
                (response[3] != request[3] || response[4] != request[4] || response[5] != request[5])) return false;
            return true;
        }

        public void Dispose()
        {
            lock (gate)
            {
                if (disposed) return;
                disposed = true;
                if (handle != null) handle.Dispose();
            }
        }

        sealed class PendingRead : IDisposable
        {
            readonly SafeFileHandle file;
            readonly SafeWaitHandle signal;
            readonly IntPtr buffer;
            readonly IntPtr overlapped;
            bool pending;

            public PendingRead(SafeFileHandle file)
            {
                this.file = file;
                signal = CreateEvent(IntPtr.Zero, true, false, null);
                if (signal.IsInvalid) throw NativeError("Não foi possível criar o evento de leitura USB");
                buffer = Marshal.AllocHGlobal(17);
                overlapped = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(NativeOverlapped)));
                var state = new NativeOverlapped { Event = signal.DangerousGetHandle() };
                Marshal.StructureToPtr(state, overlapped, false);
            }

            public void Start()
            {
                if (pending) throw new InvalidOperationException("Uma leitura USB já está em andamento.");
                if (!ResetEvent(signal)) throw NativeError("Não foi possível preparar a leitura USB");
                bool completed = ReadFile(file, buffer, 17, IntPtr.Zero, overlapped);
                if (!completed && Marshal.GetLastWin32Error() != ErrorIoPending)
                    throw NativeError("Não foi possível iniciar a leitura do mouse");
                pending = true;
            }

            public byte[] Complete(int timeoutMs)
            {
                if (!pending) throw new InvalidOperationException("Não existe leitura USB em andamento.");
                uint wait = WaitForSingleObject(signal, (uint)timeoutMs);
                if (wait == WaitTimeout) throw new TimeoutException("O mouse não respondeu ao comando USB no prazo esperado.");
                if (wait == WaitFailed) throw NativeError("Falha aguardando a resposta USB");
                if (wait != WaitObject0) throw new IOException("Estado inesperado durante a leitura USB.");
                uint received;
                bool ok = GetOverlappedResult(file, overlapped, out received, false);
                pending = false;
                if (!ok) throw NativeError("Não foi possível receber a resposta do mouse");
                var result = new byte[received];
                if (received != 0) Marshal.Copy(buffer, result, 0, (int)received);
                return result;
            }

            public void Dispose()
            {
                if (pending)
                {
                    CancelIoEx(file, overlapped);
                    // OVERLAPPED storage must remain alive until cancellation is
                    // acknowledged by Windows; freeing it earlier corrupts memory.
                    uint ignored;
                    GetOverlappedResult(file, overlapped, out ignored, true);
                    pending = false;
                }
                Marshal.FreeHGlobal(overlapped);
                Marshal.FreeHGlobal(buffer);
                signal.Dispose();
            }
        }

        static Win32Exception NativeError(string message)
        {
            return new Win32Exception(Marshal.GetLastWin32Error(), message);
        }

        [StructLayout(LayoutKind.Sequential)]
        struct SpDeviceInterfaceData
        {
            public int Size;
            public Guid InterfaceClassGuid;
            public uint Flags;
            public UIntPtr Reserved;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct HiddAttributes
        {
            public int Size;
            public ushort VendorId;
            public ushort ProductId;
            public ushort VersionNumber;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct HidpCaps
        {
            public ushort Usage;
            public ushort UsagePage;
            public ushort InputReportByteLength;
            public ushort OutputReportByteLength;
            public ushort FeatureReportByteLength;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 17)] public ushort[] Reserved;
            public ushort NumberLinkCollectionNodes;
            public ushort NumberInputButtonCaps;
            public ushort NumberInputValueCaps;
            public ushort NumberInputDataIndices;
            public ushort NumberOutputButtonCaps;
            public ushort NumberOutputValueCaps;
            public ushort NumberOutputDataIndices;
            public ushort NumberFeatureButtonCaps;
            public ushort NumberFeatureValueCaps;
            public ushort NumberFeatureDataIndices;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct NativeOverlapped
        {
            public UIntPtr Internal;
            public UIntPtr InternalHigh;
            public uint Offset;
            public uint OffsetHigh;
            public IntPtr Event;
        }

        [DllImport("hid.dll")] static extern void HidD_GetHidGuid(out Guid guid);
        [DllImport("hid.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.U1)] static extern bool HidD_GetAttributes(SafeFileHandle file, ref HiddAttributes attributes);
        [DllImport("hid.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.U1)] static extern bool HidD_GetPreparsedData(SafeFileHandle file, out IntPtr preparsed);
        [DllImport("hid.dll")] [return: MarshalAs(UnmanagedType.U1)] static extern bool HidD_FreePreparsedData(IntPtr preparsed);
        [DllImport("hid.dll")] static extern int HidP_GetCaps(IntPtr preparsed, out HidpCaps caps);
        [DllImport("hid.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.U1)] static extern bool HidD_GetProductString(SafeFileHandle file, IntPtr buffer, int length);
        [DllImport("hid.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.U1)] static extern bool HidD_FlushQueue(SafeFileHandle file);
        [DllImport("hid.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.U1)] static extern bool HidD_SetOutputReport(SafeFileHandle file, byte[] report, int length);
        [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr SetupDiGetClassDevs(ref Guid guid, string enumerator, IntPtr parent, uint flags);
        [DllImport("setupapi.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] static extern bool SetupDiEnumDeviceInterfaces(IntPtr set, IntPtr device, ref Guid guid, uint index, ref SpDeviceInterfaceData data);
        [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] static extern bool SetupDiGetDeviceInterfaceDetail(IntPtr set, ref SpDeviceInterfaceData data, IntPtr detail, uint size, out uint required, IntPtr deviceInfo);
        [DllImport("setupapi.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] static extern bool SetupDiDestroyDeviceInfoList(IntPtr set);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr security, uint disposition, uint flags, IntPtr template);
        [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] static extern bool ReadFile(SafeFileHandle file, IntPtr buffer, uint length, IntPtr received, IntPtr overlapped);
        [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] static extern bool GetOverlappedResult(SafeFileHandle file, IntPtr overlapped, out uint received, [MarshalAs(UnmanagedType.Bool)] bool wait);
        [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] static extern bool CancelIoEx(SafeFileHandle file, IntPtr overlapped);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern SafeWaitHandle CreateEvent(IntPtr attributes, [MarshalAs(UnmanagedType.Bool)] bool manualReset, [MarshalAs(UnmanagedType.Bool)] bool initialState, string name);
        [DllImport("kernel32.dll", SetLastError = true)] static extern uint WaitForSingleObject(SafeWaitHandle handle, uint milliseconds);
        [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] static extern bool ResetEvent(SafeWaitHandle handle);
    }
}
