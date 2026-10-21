using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using RedragonMini;

class ProtocolTests
{
    static int assertions;
    static byte[] Hex(string s) { return s.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries).Select(x => Convert.ToByte(x, 16)).ToArray(); }
    static void Assert(bool value, string label) { assertions++; if (!value) throw new Exception(label); }
    static void Bytes(byte[] actual, string expected, string label) { Assert(actual.SequenceEqual(Hex(expected)), label + ": " + Report.Hex(actual)); }
    static void Throws<T>(Action action, string label) where T : Exception
    { bool threw = false; try { action(); } catch (T) { threw = true; } Assert(threw, label); }

    sealed class FakeMouse : IReportTransport
    {
        public byte[][] Profiles = Enumerable.Range(0, 4).Select(i => Enumerable.Repeat((byte)(i * 11), 0x300).ToArray()).ToArray();
        public int Active = 1;
        public int Writes;
        public byte IdentityCid = 0x17, IdentityMid = 0x29, IdentityDeviceType = 2;
        public int IdentityCount = 8;
        public List<byte> Operations = new List<byte>();
        public bool CorruptWrites;
        public int FailReadProfile = -1;
        public int FailSelectProfile = -1;
        public int SwitchProfileAfterFirstWrite = -1;
        public IOException ReadFailure = new IOException("Simulated read failure");
        public List<int> WriteAddresses = new List<int>();
        public byte[] Exchange(byte[] request, int timeoutMs)
        {
            if (!Report.IsValid(request)) throw new InvalidDataException("Invalid request");
            byte op = request[1]; int address = (request[3] << 8) | request[4], n = request[5];
            Operations.Add(op);
            if (op == 1)
            {
                byte[] data = { 0xf6, 0x18, 0x30, 0xeb, IdentityCid, IdentityMid, IdentityDeviceType, 0 };
                return Report.Build(op, 0, IdentityCount, data.Take(IdentityCount).ToArray());
            }
            if (op == 0x0e) return Report.Build(op, 0, 1, new byte[] { (byte)Active });
            if (op == 0x0f)
            {
                if (request[6] == FailSelectProfile) throw new IOException("Simulated restore selection failure");
                Active = request[6]; return (byte[])request.Clone();
            }
            if (op == 0x02) return (byte[])request.Clone();
            if (op == 0x12) return Report.Build(op, 0, 2, new byte[] { 4, 1 });
            if (op == 0x08)
            {
                if (Active == FailReadProfile) { FailReadProfile = -1; throw ReadFailure; }
                return Report.Build(op, address, n, Profiles[Active].Skip(address).Take(n).ToArray());
            }
            if (op == 0x07)
            {
                Writes++; WriteAddresses.Add(address); Buffer.BlockCopy(request, 6, Profiles[Active], address, n);
                if (CorruptWrites) Profiles[Active][address] ^= 1;
                if (Writes == 1 && SwitchProfileAfterFirstWrite >= 0) Active = SwitchProfileAfterFirstWrite;
                return (byte[])request.Clone();
            }
            throw new InvalidOperationException("Unsupported fake operation");
        }
    }

    static void Main()
    {
        // These complete 17-byte frames were taken from the supplied USBPcap recordings.
        Bytes(Report.Build(8, 0x160, 10), "08 08 00 01 60 0a 00 00 00 00 00 00 00 00 00 00 da", "Captured read request");
        byte[] capturedRead = Hex("08 08 00 01 60 0a 04 80 01 00 81 06 00 41 06 00 87");
        Assert(Report.IsValid(capturedRead), "Captured Ctrl+C read checksum");
        Bytes(Report.Build(7, 0x220, 8, Hex("02 82 b5 00 42 b5 00 25")), "08 07 00 02 20 08 02 82 b5 00 42 b5 00 25 00 00 c7", "Captured media write");
        Bytes(Report.Build(7, 0x0c, 4, Hex("14 14 00 2d")), "08 07 00 00 0c 04 14 14 00 2d 00 00 00 00 00 00 e1", "Captured 2000 DPI write");
        Bytes(Report.Build(0x0f, 0, 1, new byte[] { 1 }), "08 0f 00 00 00 01 01 00 00 00 00 00 00 00 00 00 3c", "Captured profile selection");
        byte[] bad = (byte[])capturedRead.Clone(); bad[6] ^= 1;
        Assert(!Report.IsValid(bad), "Reject corrupted checksum");
        Assert(!Report.Matches(Report.Build(8, 0x180, 10), capturedRead), "Reject stale memory response");
        Assert(Report.Matches(Report.Build(8, 0x160, 10), capturedRead), "Match captured memory response");
        Bytes(KeyEncoding.Shortcut(1, 6), "04 80 01 00 81 06 00 41 06 00 40 01 00 c1", "Captured Ctrl+C encoding");
        Bytes(KeyEncoding.Shortcut(8, 0x19), "04 80 08 00 81 19 00 41 19 00 40 08 00 8d", "Captured GUI+V encoding");
        Bytes(KeyEncoding.Shortcut(8, 0x1e), "04 80 08 00 81 1e 00 41 1e 00 40 08 00 83", "Command+1 encoding");
        Bytes(KeyEncoding.Shortcut(0, 0x46), "02 81 46 00 41 46 00 05", "PrintScreen encoding");
        Bytes(KeyEncoding.KeyRecord(9), "09 00 00 4c", "Profile cycle key record");
        Assert(KeyEncoding.KeyAddress(6) == 0x84 && KeyEncoding.ShortcutAddress(6) == 0x220, "Physical button6 mapping");
        Assert(KeyEncoding.KeyAddress(7) == 0x88 && KeyEncoding.KeyAddress(5) == 0x6c, "Physical button7 and5 mapping");
        var identityMouse = new FakeMouse(); var identityProtocol = new DeviceProtocol(identityMouse);
        identityProtocol.ConfirmIdentity();
        Assert(identityMouse.Active == 1 && identityMouse.Writes == 0 && identityMouse.Operations.SequenceEqual(new byte[] { 1 }), "Wired identity leaves profile and memory untouched");
        identityProtocol.ConfirmIdentity(2);
        Assert(identityMouse.Writes == 0, "Explicit wired device type accepted");
        identityMouse.IdentityDeviceType = 0;
        identityProtocol.ConfirmIdentity();
        Assert(identityMouse.Active == 1 && identityMouse.Writes == 0, "Captured receiver identity is accepted without state changes");
        identityProtocol.ConfirmIdentity(0);
        Assert(identityMouse.Writes == 0, "Explicit receiver device type accepted");
        Throws<IOException>(() => identityProtocol.ConfirmIdentity(2), "Reject receiver when wired device expected");
        Throws<ArgumentOutOfRangeException>(() => identityProtocol.ConfirmIdentity(3), "Reject unsupported expected type before request");
        identityMouse.IdentityCid = 0x18;
        Throws<IOException>(() => identityProtocol.ConfirmIdentity(), "Reject mismatching model CID");
        identityMouse.IdentityCid = 0x17; identityMouse.IdentityMid = 0x28;
        Throws<IOException>(() => identityProtocol.ConfirmIdentity(), "Reject mismatching model MID");
        identityMouse.IdentityMid = 0x29; identityMouse.IdentityDeviceType = 1;
        Throws<IOException>(() => identityProtocol.ConfirmIdentity(), "Reject uncaptured device type");
        identityMouse.IdentityDeviceType = 2; identityMouse.IdentityCount = 7;
        Throws<IOException>(() => identityProtocol.ConfirmIdentity(), "Reject truncated identity response");
        Assert(identityMouse.Active == 1 && identityMouse.Writes == 0 && identityMouse.Operations.All(x => x == 1), "All identity failures leave profile and memory untouched");
        var mouse = new FakeMouse(); var protocol = new DeviceProtocol(mouse);
        MouseSnapshot snapshots = protocol.ReadProfiles(4);
        Assert(mouse.Active == 1 && snapshots.OriginalProfile == 1, "Restore original selection after backup");
        Assert(snapshots.Profiles.Length == 4 && snapshots.Profiles[3].Configuration[1] == 33, "Read distinct selected profiles");
        Assert(snapshots.Profiles.All(x => x.Configuration.Length == 0xc0 && x.InlineShortcuts.Length == 0x200), "Snapshot bounds");
        Assert(mouse.Writes == 0, "Backup never writes memory");
        mouse.Active = 3; mouse.FailReadProfile = 1;
        Throws<IOException>(() => protocol.ReadProfiles(2), "Propagate backup failure");
        Assert(mouse.Active == 3, "Restore selection after backup failure");
        mouse.Active = 1;
        ProfileSnapshot before = protocol.ReadSnapshot();
        byte[] allBefore = (byte[])mouse.Profiles[1].Clone();
        MemoryPatch[] patches = KeyEncoding.ShortcutPatches(before, 6, 8, 0x1e);
        protocol.ApplyPatches(1, patches);
        Assert(mouse.Writes == 3, "Chunk 14-byte shortcut into10+4 and write4-byte key");
        Assert(mouse.WriteAddresses.SequenceEqual(new[] { 0x220, 0x22a, 0x84 }), "Write only intended key and shortcut");
        byte[] expected = (byte[])allBefore.Clone();
        foreach (var patch in patches) Buffer.BlockCopy(patch.After, 0, expected, patch.Address, patch.After.Length);
        Assert(mouse.Profiles[1].SequenceEqual(expected), "Preserve every unrelated byte including RGB DPI button5 button7");
        int oldWrites = mouse.Writes;
        Throws<IOException>(() => protocol.ApplyPatches(1, patches), "Reject stale patch preimage");
        Assert(mouse.Writes == oldWrites, "Stale patch rejected before writing");
        mouse.CorruptWrites = true;
        Throws<IOException>(() => protocol.WriteMemory(0x88, KeyEncoding.KeyRecord(9)), "Detect failed write readback");
        var changedMouse = new FakeMouse(); var changedProtocol = new DeviceProtocol(changedMouse);
        ProfileSnapshot changeSnapshot = changedProtocol.ReadSnapshot();
        byte[] untouchedProfile = (byte[])changedMouse.Profiles[2].Clone();
        changedMouse.SwitchProfileAfterFirstWrite = 2;
        IOException profileChanged = null;
        try { changedProtocol.ApplyPatches(1, KeyEncoding.ShortcutPatches(changeSnapshot, 6, 8, 0x1e)); }
        catch (IOException ex) { profileChanged = ex; }
        Assert(profileChanged != null && profileChanged.Message.Contains("perfil mudou"), "Report active profile mismatch immediately after first write chunk");
        Assert(changedMouse.Writes == 1 && changedMouse.WriteAddresses.SequenceEqual(new[] { 0x220 }), "Block every subsequent write after hardware profile change");
        Assert(changedMouse.Profiles[2].SequenceEqual(untouchedProfile), "Never write remaining shortcut chunks or key to newly active profile");
        Assert(changedMouse.Profiles[1].Skip(0x22a).Take(4).SequenceEqual(changeSnapshot.Read(0x22a, 4)), "Shortcut second chunk remains unchanged after detected mismatch");
        Assert(changedMouse.Profiles[1].Skip(0x84).Take(4).SequenceEqual(changeSnapshot.Read(0x84, 4)), "Key record remains unchanged after detected mismatch");
        var cleanupMouse = new FakeMouse { Active = 3, FailReadProfile = 1, FailSelectProfile = 3 };
        var cleanupProtocol = new DeviceProtocol(cleanupMouse); var cleanupLog = new List<string>(); cleanupProtocol.Log = cleanupLog.Add;
        IOException primary = null;
        try { cleanupProtocol.ReadProfiles(2); } catch (IOException ex) { primary = ex; }
        Assert(Object.ReferenceEquals(primary, cleanupMouse.ReadFailure), "Preserve original read exception when restoring selected profile also fails");
        Assert(primary != null && (string)primary.Data["ProfileRestoreError"] == "Simulated restore selection failure", "Retain secondary restore failure on original exception");
        Assert(cleanupLog.Any(x => x.Contains("Simulated restore selection failure")), "Log secondary restoration failure");
        Assert(cleanupMouse.Writes == 0, "Combined backup and restoration failures never write memory");
        var cleanupOnlyMouse = new FakeMouse { Active = 3, FailSelectProfile = 3 };
        IOException cleanupOnly = null;
        try { new DeviceProtocol(cleanupOnlyMouse).ReadProfiles(2); } catch (IOException ex) { cleanupOnly = ex; }
        Assert(cleanupOnly != null && cleanupOnly.Message == "Simulated restore selection failure", "Report restore failure when primary backup succeeded");
        Console.WriteLine("PASS " + assertions + " protocol assertions");
    }
}
