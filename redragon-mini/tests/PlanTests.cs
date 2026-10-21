using System;
using System.IO;
using System.Linq;
using RedragonMini;

internal static class PlanTests
{
    static int assertions;

    static void Assert(bool value, string label)
    {
        assertions++;
        if (!value) throw new Exception(label);
    }

    static void Throws<T>(Action action, string label) where T : Exception
    {
        bool threw = false;
        try { action(); }
        catch (T) { threw = true; }
        Assert(threw, label);
    }

    static MouseSnapshot Snapshot(int count)
    {
        return new MouseSnapshot {
            OriginalProfile = 3,
            Profiles = Enumerable.Range(0, count).Select(i => {
                var configuration = Enumerable.Range(0, 0xc0).Select(n => (byte)((n + i * 31) & 255)).ToArray();
                // Use ordinary mouse button records, never accidental macro types.
                for (int key = 0; key < 16; key++)
                    Buffer.BlockCopy(KeyEncoding.KeyRecord(1, (byte)(key + 1)), 0, configuration, 0x60 + key * 4, 4);
                return new ProfileSnapshot {
                    ProfileIndex = i, Configuration = configuration,
                    InlineShortcuts = Enumerable.Range(0, 0x200).Select(n => (byte)((n + i * 47) & 255)).ToArray()
                };
            }).ToArray()
        };
    }

    static byte[][] Capture(MouseSnapshot snapshot)
    {
        return snapshot.Profiles.Select(p => p.Configuration.Concat(p.InlineShortcuts).ToArray()).ToArray();
    }

    static bool Unchanged(MouseSnapshot snapshot, byte[][] before)
    {
        return snapshot.Profiles.Select((p, i) => p.Configuration.Concat(p.InlineShortcuts).SequenceEqual(before[i])).All(x => x);
    }

    static bool SameOutside(byte[] before, byte[] after, params int[][] ranges)
    {
        return Enumerable.Range(0, before.Length).All(i => ranges.Any(r => i >= r[0] && i < r[0] + r[1]) || before[i] == after[i]);
    }

    static bool IsReserved(int address)
    {
        return address >= 0x54 && address < 0x60 || address >= 0xbb && address < 0xc0;
    }

    static bool FunctionallyEqual(byte[] first, byte[] second)
    {
        return Enumerable.Range(0, first.Length).All(i => IsReserved(i) || first[i] == second[i]);
    }

    static void Main()
    {
        var original = Snapshot(4);
        byte[][] captured = Capture(original);
        var plan = ProfilePlan.Create(original, true, ButtonChoice.Keep(), ButtonChoice.Shortcut("Win copy", 1, 6));
        Assert(plan.Length == 4, "Experimental plan has four physical slots");
        Assert(Unchanged(original, captured), "Planning does not mutate original snapshot");
        for (int i = 0; i < 4; i++)
        {
            ProfileSnapshot source = original.Profiles[i % 2], desired = plan[i];
            Assert(desired.ProfileIndex == i, "Physical slot index preserved " + i);
            Assert(desired.Configuration.Take(0x54).SequenceEqual(source.Configuration.Take(0x54)), "DPI/RGB settings come only from matching source " + i);
            Assert(desired.Configuration.Skip(0xa0).Take(0x1b).SequenceEqual(source.Configuration.Skip(0xa0).Take(0x1b)), "Known configuration tail comes from matching source " + i);
            Assert(desired.Configuration.Skip(0x54).Take(12).SequenceEqual(original.Profiles[i].Configuration.Skip(0x54).Take(12)), "First reserved region preserved from destination " + i);
            Assert(desired.Configuration.Skip(0xbb).Take(5).SequenceEqual(original.Profiles[i].Configuration.Skip(0xbb).Take(5)), "Final reserved region preserved from destination " + i);
            int[] button5 = { KeyEncoding.KeyAddress(5), 4 }, button6 = { KeyEncoding.KeyAddress(6), 4 }, button7 = { KeyEncoding.KeyAddress(7), 4 };
            Assert(SameOutside(source.Configuration, desired.Configuration, button5, button6, button7, new[] { 0x54, 12 }, new[] { 0xbb, 5 }), "Only intended key records and destination reserved bytes differ from source " + i);
            Assert(desired.Configuration.Skip(button7[0]).Take(4).SequenceEqual(KeyEncoding.KeyRecord(9)), "Button7 firmware cycle record " + i);
            int shortcut6Offset = KeyEncoding.ShortcutAddress(6) - 0x100;
            byte[] expected6 = KeyEncoding.Shortcut(i % 2 == 0 ? (byte)8 : (byte)0, i % 2 == 0 ? (ushort)0x1e : (ushort)0x46);
            Assert(desired.InlineShortcuts.Skip(shortcut6Offset).Take(expected6.Length).SequenceEqual(expected6), "Button6 platform shortcut " + i);
            Assert(ProfilePlan.Diff(original.Profiles[i], desired).All(p => p.Address >= 0x100 ||
                Enumerable.Range(0, p.Before.Length).All(n => !IsReserved(p.Address + n) || p.Before[n] == p.After[n])), "No planned change modifies a destination reserved byte " + i);
        }
        Assert(FunctionallyEqual(plan[0].Configuration, plan[2].Configuration) && FunctionallyEqual(plan[1].Configuration, plan[3].Configuration), "Four slots alternate only two functional configurations");
        Assert(plan[0].InlineShortcuts.SequenceEqual(plan[2].InlineShortcuts) && plan[1].InlineShortcuts.SequenceEqual(plan[3].InlineShortcuts), "Four slots alternate only two shortcut banks");
        plan[2].Configuration[0] ^= 1;
        plan[2].InlineShortcuts[0] ^= 1;
        Assert(plan[0].Configuration[0] != plan[2].Configuration[0] && plan[0].InlineShortcuts[0] != plan[2].InlineShortcuts[0], "Duplicate target slots own independent buffers");
        Assert(Unchanged(original, captured), "Mutating plan does not mutate source buffers");

        var two = Snapshot(2);
        var normal = ProfilePlan.Create(two, false, ButtonChoice.Keep(), ButtonChoice.Keep());
        for (int i = 0; i < 2; i++)
        {
            Assert(SameOutside(two.Profiles[i].Configuration, normal[i].Configuration, new[] { KeyEncoding.KeyAddress(6), 4 }), "Normal mode preserves every key except button6 " + i);
            Assert(normal[i].Configuration.Skip(KeyEncoding.KeyAddress(7)).Take(4).SequenceEqual(two.Profiles[i].Configuration.Skip(KeyEncoding.KeyAddress(7)).Take(4)), "Normal mode preserves button7 " + i);
            Assert(ProfilePlan.Diff(two.Profiles[i], normal[i]).All(p => p.Address == KeyEncoding.KeyAddress(6) || p.Address == KeyEncoding.ShortcutAddress(6)), "Normal patch list contains only button6 regions " + i);
            Assert(ProfilePlan.Diff(two.Profiles[i], normal[i]).Select(p => p.Address).SequenceEqual(new[] { KeyEncoding.ShortcutAddress(6), KeyEncoding.KeyAddress(6) }), "Shortcut data is planned before binding the button " + i);
        }
        Throws<InvalidDataException>(() => ProfilePlan.Create(two, true, ButtonChoice.Keep(), ButtonChoice.Keep()), "Experimental mode requires four backed-up slots");
        original.Profiles[0].Configuration[0x60] = 6;
        Throws<InvalidOperationException>(() => ProfilePlan.Create(original, true, ButtonChoice.Keep(), ButtonChoice.Keep()), "Long macro reference prevents cloning unbacked macro memory");
        two.Profiles[0].Configuration[0x60] = 6;
        Assert(ProfilePlan.Create(two, false, ButtonChoice.Keep(), ButtonChoice.Keep()).Length == 2, "Normal mode can preserve existing long macro references");

        var device = new HidDeviceInfo {
            Path = @"\\?\hid#vid_3554&pid_f55e&mi_01&col05#test",
            VendorId = 0x3554, ProductId = 0xf55e, InputReportLength = 17, OutputReportLength = 17
        };
        Assert(device.CanExchange, "Exact known wired HID collection accepted");
        device.Path = device.Path.Replace("col05", "col04");
        Assert(!device.CanExchange, "Other HID collection rejected");
        device.Path = device.Path.Replace("col04", "col05");
        string folder = Path.Combine(Path.GetTempPath(), "RedragonMiniTests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        try
        {
            string path = Path.Combine(folder, "backup.json");
            var document = BackupDocument.Create(original, device);
            document.Save(path);
            MouseSnapshot restored = BackupDocument.Load(path).ToSnapshot();
            Assert(restored.OriginalProfile == original.OriginalProfile, "Backup retains originally selected profile");
            Assert(Capture(restored).Select((p, i) => p.SequenceEqual(Capture(original)[i])).All(x => x), "Backup roundtrip retains every configuration and shortcut byte");
            Throws<IOException>(() => document.Save(path), "Saving backup refuses to overwrite an existing recovery file");
            document.FormatVersion = 2;
            Throws<InvalidDataException>(() => document.ToSnapshot(), "Backup rejects unknown format version");
            document.FormatVersion = 1;
            document.Profiles[1].Configuration = new byte[1];
            Throws<InvalidDataException>(() => document.ToSnapshot(), "Backup rejects truncated configuration region");
            File.WriteAllBytes(Path.Combine(folder, "oversized.json"), new byte[128 * 1024 + 1]);
            Throws<InvalidDataException>(() => BackupDocument.Load(Path.Combine(folder, "oversized.json")), "Backup loader bounds file size");
        }
        finally { Directory.Delete(folder, true); }
        Console.WriteLine("PASS " + assertions + " profile planning and backup assertions");
    }
}
