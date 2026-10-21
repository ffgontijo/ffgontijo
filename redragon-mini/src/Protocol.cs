using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;

namespace RedragonMini
{
    public interface IReportTransport
    {
        byte[] Exchange(byte[] request, int timeoutMs);
    }

    /// <summary>Report 08 on HID interface 1. Captured commands only.</summary>
    public static class Report
    {
        public const int Length = 17;
        public const byte Id = 0x08;
        public const int ChecksumTotal = 0x55;

        public static byte[] Build(byte operation, int address = 0, int count = 0, byte[] data = null)
        {
            if (address < 0 || address > 0xffff) throw new ArgumentOutOfRangeException("address");
            if (count < 0 || count > 10) throw new ArgumentOutOfRangeException("count");
            if (data != null && data.Length > count) throw new ArgumentException("Data exceeds count.", "data");
            byte[] r = new byte[Length];
            r[0] = Id; r[1] = operation;
            r[3] = (byte)(address >> 8); r[4] = (byte)address; r[5] = (byte)count;
            if (data != null) Buffer.BlockCopy(data, 0, r, 6, data.Length);
            r[16] = Checksum(r, 0, 16);
            return r;
        }

        public static byte Checksum(byte[] bytes, int offset, int count)
        {
            int sum = 0;
            for (int i = 0; i < count; i++) sum += bytes[offset + i];
            return unchecked((byte)(ChecksumTotal - sum));
        }

        public static bool IsValid(byte[] report)
        {
            if (report == null || report.Length != Length || report[0] != Id || report[2] != 0) return false;
            int sum = 0; foreach (byte b in report) sum += b;
            return (sum & 0xff) == ChecksumTotal;
        }

        public static bool Matches(byte[] request, byte[] response)
        {
            if (!IsValid(response) || request == null || request.Length != Length || response[1] != request[1]) return false;
            if (request[1] == 0x07 || request[1] == 0x08)
                return response[3] == request[3] && response[4] == request[4] && response[5] == request[5];
            return true;
        }

        public static string Hex(byte[] bytes)
        {
            return BitConverter.ToString(bytes).Replace("-", " ");
        }
    }

    public sealed class ProfileSnapshot
    {
        public int ProfileIndex { get; set; }
        // All basic configuration, including RGB, DPI and sixteen key records.
        public byte[] Configuration { get; set; }
        // Sixteen inline shortcut slots, 32 bytes each. General custom macros are untouched.
        public byte[] InlineShortcuts { get; set; }

        public byte[] Read(int address, int count)
        {
            byte[] source; int offset;
            if (address >= 0 && address + count <= 0xc0) { source = Configuration; offset = address; }
            else if (address >= 0x100 && address + count <= 0x300) { source = InlineShortcuts; offset = address - 0x100; }
            else throw new ArgumentOutOfRangeException("address", "Region is not included in this snapshot.");
            if (source == null || offset + count > source.Length) throw new InvalidDataException("Incomplete profile snapshot.");
            byte[] result = new byte[count]; Buffer.BlockCopy(source, offset, result, 0, count); return result;
        }
    }

    public sealed class MouseSnapshot
    {
        public int OriginalProfile { get; set; }
        public ProfileSnapshot[] Profiles { get; set; }
    }

    public sealed class MemoryPatch
    {
        public int Address { get; private set; }
        public byte[] Before { get; private set; }
        public byte[] After { get; private set; }
        public string Description { get; private set; }

        public MemoryPatch(int address, byte[] before, byte[] after, string description)
        {
            if (before == null || after == null || before.Length != after.Length || after.Length == 0)
                throw new ArgumentException("A patch must preserve its region length.");
            Address = address; Before = (byte[])before.Clone(); After = (byte[])after.Clone(); Description = description;
        }
    }

    public static class KeyEncoding
    {
        // Physical button numbers refer to the manufacturer's drawing, not USB button bits.
        public static int HardwareIndex(int physicalButton)
        {
            int[] indices = { 0, 0, 1, 2, 4, 3, 9, 10, 5 };
            if (physicalButton < 1 || physicalButton > 8) throw new ArgumentOutOfRangeException("physicalButton");
            return indices[physicalButton];
        }
        public static int KeyAddress(int physicalButton) { return 0x60 + 4 * HardwareIndex(physicalButton); }
        public static int ShortcutAddress(int physicalButton) { return 0x100 + 0x20 * HardwareIndex(physicalButton); }
        public static byte[] KeyRecord(byte type, byte parameter1 = 0, byte parameter2 = 0)
        {
            byte[] r = { type, parameter1, parameter2, 0 };
            r[3] = Report.Checksum(r, 0, 3); return r;
        }

        /// <summary>Encode the same inline shortcut format captured for Ctrl+C and GUI+C.</summary>
        public static byte[] Shortcut(byte modifier, ushort keyboardUsage)
        {
            if (keyboardUsage == 0 || keyboardUsage > 0xff) throw new ArgumentOutOfRangeException("keyboardUsage");
            List<byte> r = new List<byte>();
            r.Add(modifier == 0 ? (byte)2 : (byte)4);
            if (modifier != 0) r.AddRange(new byte[] { 0x80, modifier, 0 });
            r.AddRange(new byte[] { 0x81, (byte)keyboardUsage, (byte)(keyboardUsage >> 8) });
            r.AddRange(new byte[] { 0x41, (byte)keyboardUsage, (byte)(keyboardUsage >> 8) });
            if (modifier != 0) r.AddRange(new byte[] { 0x40, modifier, 0 });
            byte[] body = r.ToArray(); r.Add(Report.Checksum(body, 0, body.Length)); return r.ToArray();
        }

        public static MemoryPatch[] ShortcutPatches(ProfileSnapshot snapshot, int physicalButton, byte modifier, ushort keyboardUsage)
        {
            int macroAddress = ShortcutAddress(physicalButton), keyAddress = KeyAddress(physicalButton);
            byte[] shortcut = Shortcut(modifier, keyboardUsage);
            return new[] {
                new MemoryPatch(macroAddress, snapshot.Read(macroAddress, shortcut.Length), shortcut, "Atalho do botão " + physicalButton),
                new MemoryPatch(keyAddress, snapshot.Read(keyAddress, 4), KeyRecord(5), "Vincular atalho ao botão " + physicalButton)
            };
        }
    }

    public sealed class DeviceProtocol
    {
        private readonly IReportTransport transport;
        private int? expectedWriteProfile;
        public const int TimeoutMs = 2000;
        public Action<string> Log { get; set; }
        public DeviceProtocol(IReportTransport transport)
        {
            if (transport == null) throw new ArgumentNullException("transport"); this.transport = transport;
        }

        public byte[] Exchange(byte operation, int address = 0, int count = 0, byte[] data = null)
        {
            byte[] request = Report.Build(operation, address, count, data);
            byte[] response = transport.Exchange(request, TimeoutMs);
            if (!Report.Matches(request, response)) throw new InvalidDataException("Mouse returned an invalid or unrelated report.");
            return response;
        }

        public void ConfirmIdentity(int expectedDeviceType = -1)
        {
            if (expectedDeviceType != -1 && expectedDeviceType != 0 && expectedDeviceType != 2)
                throw new ArgumentOutOfRangeException("expectedDeviceType");
            byte[] challenge = new byte[8], random = new byte[4];
            using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(random);
            Buffer.BlockCopy(random, 0, challenge, 0, random.Length);
            byte[] r = Exchange(1, 0, 8, challenge);
            // Original native CS_GetDeviceInfo extracts CID/MID/type from these offsets.
            // This confirms the model; it is not cryptographic authentication.
            if (r[5] != 8 || r[10] != 0x17 || r[11] != 0x29 || (r[12] != 0 && r[12] != 2) || (expectedDeviceType != -1 && r[12] != expectedDeviceType))
                throw new IOException("O dispositivo não confirmou o modelo M719-WL esperado (CID 23, MID 41). Nenhuma configuração foi gravada.");
        }

        public void EnterConfiguration()
        {
            byte[] response = Exchange(0x02, 0, 1, new byte[] { 1 });
            if (response[5] != 1 || response[6] != 1) throw new IOException("Mouse did not acknowledge configuration mode.");
        }
        public void LeaveConfiguration()
        {
            byte[] response = Exchange(0x02, 0, 1, new byte[] { 0 });
            if (response[5] != 1 || response[6] != 0) throw new IOException("Mouse did not acknowledge leaving configuration mode.");
        }
        public byte[] ReadVersion() { return Exchange(0x12); }
        public byte[] QueryVersion() { return ReadVersion(); }
        public byte[] QueryConnection() { return Exchange(0x03); }
        public int ReadCurrentProfile()
        {
            byte[] r = Exchange(0x0e);
            if (r[5] != 1 || r[6] > 3) throw new InvalidDataException("Unexpected profile index.");
            return r[6];
        }
        public void SelectProfile(int profileIndex)
        {
            if (profileIndex < 0 || profileIndex > 3) throw new ArgumentOutOfRangeException("profileIndex");
            byte[] r = Exchange(0x0f, 0, 1, new byte[] { (byte)profileIndex });
            if (r[5] != 1 || r[6] != profileIndex) throw new IOException("Mouse did not acknowledge profile selection.");
            if (ReadCurrentProfile() != profileIndex) throw new IOException("Profile selection could not be verified.");
        }
        public byte[] ReadMemory(int address, int length)
        {
            CheckMemoryRange(address, length);
            byte[] result = new byte[length];
            for (int offset = 0; offset < length; offset += 10)
            {
                int count = Math.Min(10, length - offset);
                byte[] r = Exchange(0x08, address + offset, count);
                Buffer.BlockCopy(r, 6, result, offset, count);
            }
            return result;
        }
        public void WriteMemory(int address, byte[] bytes)
        {
            if (bytes == null) throw new ArgumentNullException("bytes"); CheckMemoryRange(address, bytes.Length);
            for (int offset = 0; offset < bytes.Length; offset += 10)
            {
                CheckWriteProfile();
                int count = Math.Min(10, bytes.Length - offset);
                byte[] chunk = new byte[count]; Buffer.BlockCopy(bytes, offset, chunk, 0, count);
                byte[] request = Report.Build(0x07, address + offset, count, chunk);
                byte[] ack = transport.Exchange(request, TimeoutMs);
                if (ack == null || !request.SequenceEqual(ack)) throw new IOException("Mouse did not acknowledge memory write at " + (address + offset).ToString("X4") + ".");
                CheckWriteProfile();
            }
            if (!ReadMemory(address, bytes.Length).SequenceEqual(bytes))
                throw new IOException("Memory verification failed at " + address.ToString("X4") + ".");
        }
        private void CheckWriteProfile()
        {
            if (expectedWriteProfile.HasValue && ReadCurrentProfile() != expectedWriteProfile.Value)
                throw new IOException("O perfil mudou durante a gravação. Não pressione o botão 7 durante a operação USB.");
        }
        public ProfileSnapshot ReadSnapshot()
        {
            int current = ReadCurrentProfile();
            if (Log != null) Log("Lendo perfil " + (current + 1) + "...");
            ProfileSnapshot snapshot = new ProfileSnapshot { ProfileIndex = current, Configuration = ReadMemory(0, 0xc0), InlineShortcuts = ReadMemory(0x100, 0x200) };
            if (ReadCurrentProfile() != current) throw new IOException("Profile changed during backup. Close the original app and try again.");
            return snapshot;
        }
        public MouseSnapshot ReadBothProfiles() { return ReadProfiles(2); }
        public MouseSnapshot ReadProfiles(int profileCount)
        {
            if (profileCount < 1 || profileCount > 4) throw new ArgumentOutOfRangeException("profileCount");
            int original = ReadCurrentProfile();
            MouseSnapshot snapshot = new MouseSnapshot { OriginalProfile = original, Profiles = new ProfileSnapshot[profileCount] };
            Exception failure = null;
            try
            {
                for (int i = 0; i < profileCount; i++) { SelectProfile(i); snapshot.Profiles[i] = ReadSnapshot(); }
                return snapshot;
            }
            catch (Exception ex) { failure = ex; throw; }
            finally
            {
                try { SelectProfile(original); }
                catch (Exception cleanup)
                {
                    if (failure == null) throw;
                    failure.Data["ProfileRestoreError"] = cleanup.Message;
                    if (Log != null) Log("Também não foi possível restaurar a seleção inicial: " + cleanup.Message);
                }
            }
        }
        public void ApplyPatches(int profileIndex, IEnumerable<MemoryPatch> patches)
        {
            SelectProfile(profileIndex);
            MemoryPatch[] list = patches.ToArray();
            // Check every preimage before the first write to avoid applying a stale backup.
            foreach (MemoryPatch patch in list)
                if (!ReadMemory(patch.Address, patch.Before.Length).SequenceEqual(patch.Before))
                    throw new IOException("Profile changed since backup at " + patch.Address.ToString("X4") + ". Read it again before applying.");
            int? previous = expectedWriteProfile;
            expectedWriteProfile = profileIndex;
            try
            {
                foreach (MemoryPatch patch in list)
                {
                    if (patch.Before.SequenceEqual(patch.After)) continue;
                    if (Log != null) Log(patch.Description);
                    WriteMemory(patch.Address, patch.After);
                }
            }
            finally { expectedWriteProfile = previous; }
        }
        private static void CheckMemoryRange(int address, int length)
        {
            if (address < 0 || length < 0 || (long)address + length > 0x10000) throw new ArgumentOutOfRangeException("address");
        }
    }
}
