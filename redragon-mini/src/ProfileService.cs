using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;

namespace RedragonMini
{
    [DataContract]
    public sealed class BackupDocument
    {
        [DataMember] public int FormatVersion = 1;
        [DataMember] public string CreatedUtc;
        [DataMember] public int VendorId;
        [DataMember] public int ProductId;
        [DataMember] public string DevicePath;
        [DataMember] public int OriginalProfile;
        [DataMember] public BackupProfile[] Profiles;

        public static BackupDocument Create(MouseSnapshot snapshot, HidDeviceInfo device)
        {
            return new BackupDocument {
                CreatedUtc = DateTime.UtcNow.ToString("o"), VendorId = device.VendorId,
                ProductId = device.ProductId, DevicePath = device.Path,
                OriginalProfile = snapshot.OriginalProfile,
                Profiles = snapshot.Profiles.Select(p => new BackupProfile {
                    Index = p.ProfileIndex, Configuration = p.Configuration,
                    InlineShortcuts = p.InlineShortcuts
                }).ToArray()
            };
        }
        public MouseSnapshot ToSnapshot()
        {
            if (FormatVersion != 1 || VendorId != 0x3554 || (ProductId != 0xf55e && ProductId != 0xf5d5) ||
                OriginalProfile < 0 || OriginalProfile > 3 || Profiles == null || (Profiles.Length != 2 && Profiles.Length != 4))
                throw new InvalidDataException("Arquivo de backup incompatível.");
            for (int i = 0; i < Profiles.Length; i++)
            {
                var p = Profiles[i];
                if (p == null || p.Index != i || p.Configuration == null || p.Configuration.Length != 0xc0 ||
                    p.InlineShortcuts == null || p.InlineShortcuts.Length != 0x200)
                    throw new InvalidDataException("Backup incompleto ou fora de ordem.");
            }
            return new MouseSnapshot { OriginalProfile = OriginalProfile, Profiles = Profiles.Select(p =>
                new ProfileSnapshot { ProfileIndex = p.Index, Configuration = p.Configuration, InlineShortcuts = p.InlineShortcuts }).ToArray() };
        }
        public void Save(string path)
        {
            var serializer = new DataContractJsonSerializer(typeof(BackupDocument));
            using (var file = new FileStream(path, FileMode.CreateNew, FileAccess.Write)) { serializer.WriteObject(file, this); file.Flush(true); }
            // Reopen before any device write: a backup that could not be read is not useful.
            Load(path).ToSnapshot();
        }
        public static BackupDocument Load(string path)
        {
            var info = new FileInfo(path);
            if (info.Length > 128 * 1024) throw new InvalidDataException("Arquivo de backup grande demais.");
            using (var file = File.OpenRead(path))
                return (BackupDocument)new DataContractJsonSerializer(typeof(BackupDocument)).ReadObject(file);
        }
    }
    [DataContract]
    public sealed class BackupProfile
    {
        [DataMember] public int Index;
        [DataMember] public byte[] Configuration;
        [DataMember] public byte[] InlineShortcuts;
    }

    public sealed class ButtonChoice
    {
        public string Name;
        public byte[] Record;
        public byte? Modifier;
        public ushort Usage;
        public override string ToString() { return Name; }
        public static ButtonChoice Keep() { return new ButtonChoice { Name = "Manter configuração atual" }; }
        public static ButtonChoice Shortcut(string name, byte modifier, ushort usage) { return new ButtonChoice { Name = name, Modifier = modifier, Usage = usage }; }
        public static ButtonChoice Action(string name, byte type, byte p1) { return new ButtonChoice { Name = name, Record = KeyEncoding.KeyRecord(type, p1) }; }
        public void Apply(ProfileSnapshot profile, int button)
        {
            int address = KeyEncoding.KeyAddress(button);
            if (Modifier.HasValue)
            {
                byte[] shortcut = KeyEncoding.Shortcut(Modifier.Value, Usage);
                Buffer.BlockCopy(shortcut, 0, profile.InlineShortcuts, KeyEncoding.ShortcutAddress(button) - 0x100, shortcut.Length);
                Buffer.BlockCopy(KeyEncoding.KeyRecord(5), 0, profile.Configuration, address, 4);
            }
            else if (Record != null) Buffer.BlockCopy(Record, 0, profile.Configuration, address, 4);
        }
    }

    public static class ProfilePlan
    {
        public static ProfileSnapshot[] Create(MouseSnapshot original, bool experimentalCycle, ButtonChoice macButton5, ButtonChoice winButton5)
        {
            if (original.Profiles.Length != (experimentalCycle ? 4 : 2)) throw new InvalidDataException("Quantidade de perfis inesperada.");
            // General macros live outside the backed-up regions. Never clone a reference to uncopied macro data.
            if (experimentalCycle)
                foreach (var p in original.Profiles.Take(2))
                    for (int key = 0; key < 16; key++)
                        if (p.Configuration[0x60 + key * 4] == 6)
                            throw new InvalidOperationException("O perfil " + (p.ProfileIndex + 1) + " usa uma macro longa. A duplicação experimental ainda não copia macros longas. Use atalhos de teclado ou o modo de dois perfis.");
            var result = new ProfileSnapshot[original.Profiles.Length];
            for (int i = 0; i < result.Length; i++)
            {
                var source = original.Profiles[experimentalCycle ? i % 2 : i];
                var p = new ProfileSnapshot { ProfileIndex = i, Configuration = (byte[])source.Configuration.Clone(), InlineShortcuts = (byte[])source.InlineShortcuts.Clone() };
                if (experimentalCycle)
                {
                    // The original parser does not identify these reserved bytes.
                    Buffer.BlockCopy(original.Profiles[i].Configuration, 0x54, p.Configuration, 0x54, 12);
                    Buffer.BlockCopy(original.Profiles[i].Configuration, 0xbb, p.Configuration, 0xbb, 5);
                }
                (i % 2 == 0 ? macButton5 : winButton5).Apply(p, 5);
                ButtonChoice.Shortcut("Print", i % 2 == 0 ? (byte)8 : (byte)0, i % 2 == 0 ? (ushort)0x1e : (ushort)0x46).Apply(p, 6);
                if (experimentalCycle) Buffer.BlockCopy(KeyEncoding.KeyRecord(9), 0, p.Configuration, KeyEncoding.KeyAddress(7), 4);
                result[i] = p;
            }
            return result;
        }
        public static MemoryPatch[] Diff(ProfileSnapshot before, ProfileSnapshot after)
        {
            var patches = new List<MemoryPatch>();
            AddDiff(patches, 0x100, before.InlineShortcuts, after.InlineShortcuts);
            AddDiff(patches, 0, before.Configuration, after.Configuration);
            return patches.ToArray();
        }
        private static void AddDiff(List<MemoryPatch> patches, int start, byte[] before, byte[] after)
        {
            if (before.Length != after.Length) throw new InvalidDataException("Regiões incompatíveis.");
            // Keep logical records together; shortcut slots are 32-byte records.
            int unit = start == 0 ? 4 : 32;
            for (int i = 0; i < before.Length; i += unit)
            {
                byte[] b = before.Skip(i).Take(unit).ToArray(), a = after.Skip(i).Take(unit).ToArray();
                if (!b.SequenceEqual(a)) patches.Add(new MemoryPatch(start + i, b, a, "Gravando região 0x" + (start + i).ToString("X4")));
            }
        }
    }

    public sealed class ProfileService
    {
        public Action<string> Log;
        private DeviceProtocol OpenProtocol(WindowsHid hid)
        {
            var protocol = new DeviceProtocol(hid) { Log = Log };
            protocol.ConfirmIdentity(hid.Device.ProductId == 0xf5d5 ? 0 : 2);
            return protocol;
        }
        private void Say(string message) { if (Log != null) Log(message); }
        private T WithConfiguration<T>(DeviceProtocol protocol, Func<T> action)
        {
            Exception failure = null;
            try { protocol.EnterConfiguration(); return action(); }
            catch (Exception ex) { failure = ex; throw; }
            finally
            {
                try { protocol.LeaveConfiguration(); }
                catch (Exception cleanup)
                {
                    if (failure == null) throw new IOException("A operação USB terminou, mas não foi possível encerrar o modo de configuração: " + cleanup.Message + ". Consulte o backup no registro.", cleanup);
                    failure.Data["ConfigurationCleanupError"] = cleanup.Message;
                    Say("Falha adicional ao encerrar o modo de configuração: " + cleanup.Message);
                }
            }
        }
        public static string BackupDirectory()
        {
            string path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "backups");
            try { Directory.CreateDirectory(path); string probe = Path.Combine(path, ".probe-" + Guid.NewGuid().ToString("N")); File.WriteAllText(probe, ""); File.Delete(probe); return path; }
            catch (UnauthorizedAccessException) { }
            catch (IOException) { }
            path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "RedragonMini", "backups");
            Directory.CreateDirectory(path); return path;
        }
        private string SaveBackup(MouseSnapshot snapshot, HidDeviceInfo device)
        {
            string path = Path.Combine(BackupDirectory(), "M719-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N").Substring(0, 6) + ".json");
            BackupDocument.Create(snapshot, device).Save(path); Say("Backup: " + path); return path;
        }
        public string Backup(HidDeviceInfo device, int count)
        {
            using (var hid = new WindowsHid(device.Path))
            {
                var protocol = OpenProtocol(hid);
                return WithConfiguration(protocol, () => SaveBackup(protocol.ReadProfiles(count), device));
            }
        }
        public string Program(HidDeviceInfo device, bool experimentalCycle, ButtonChoice mac5, ButtonChoice win5)
        {
            using (var hid = new WindowsHid(device.Path))
            {
                var protocol = OpenProtocol(hid);
                return WithConfiguration(protocol, () =>
                {
                    MouseSnapshot before = protocol.ReadProfiles(experimentalCycle ? 4 : 2);
                    ProfileSnapshot[] desired = ProfilePlan.Create(before, experimentalCycle, mac5, win5);
                    string backup = SaveBackup(before, device);
                    try
                    {
                        for (int i = 0; i < desired.Length; i++)
                        {
                            Say("Aplicando perfil " + (i + 1) + "...");
                            protocol.ApplyPatches(i, ProfilePlan.Diff(before.Profiles[i], desired[i]));
                        }
                        protocol.SelectProfile(0);
                    }
                    catch (Exception failure)
                    {
                        Say("Falha na gravação. Tentando restaurar os perfis alterados...");
                        var errors = new List<string>();
                        for (int i = before.Profiles.Length - 1; i >= 0; i--)
                            try { RestoreProfile(protocol, before.Profiles[i]); }
                            catch (Exception rollback) { errors.Add("Perfil " + (i + 1) + ": " + rollback.Message); }
                        try { protocol.SelectProfile(before.OriginalProfile); } catch (Exception ex) { errors.Add(ex.Message); }
                        throw new IOException(failure.Message + "\r\nBackup: " + backup + "\r\n" + (errors.Count == 0 ? "Regiões alteradas restauradas e verificadas." : "Restauração incompleta: " + string.Join("; ", errors)), failure);
                    }
                    Say("Gravação e releitura concluídas. Perfil 1 (macOS) selecionado.");
                    return backup;
                });
            }
        }
        private static void RestoreProfile(DeviceProtocol protocol, ProfileSnapshot original)
        {
            protocol.SelectProfile(original.ProfileIndex);
            var current = protocol.ReadSnapshot();
            protocol.ApplyPatches(original.ProfileIndex, ProfilePlan.Diff(current, original));
        }
        public void Restore(HidDeviceInfo device, string path)
        {
            var document = BackupDocument.Load(path); var target = document.ToSnapshot();
            if (document.VendorId != device.VendorId || document.ProductId != device.ProductId)
                throw new InvalidDataException("O backup é de outro tipo de conexão. Use o mesmo cabo ou receptor usado no backup.");
            using (var hid = new WindowsHid(device.Path))
            {
                var protocol = OpenProtocol(hid);
                WithConfiguration(protocol, () =>
                {
                    var before = protocol.ReadProfiles(target.Profiles.Length);
                    string recovery = SaveBackup(before, device);
                    Say("Backup anterior à restauração: " + recovery);
                    try
                    {
                        foreach (var p in target.Profiles) RestoreProfile(protocol, p);
                        protocol.SelectProfile(target.OriginalProfile);
                    }
                    catch (Exception ex) { throw new IOException("A restauração não terminou. Reaplique o backup após reconectar. Backup da situação anterior: " + recovery, ex); }
                    return true;
                });
            }
        }
        public void Select(HidDeviceInfo device, int index)
        {
            using (var hid = new WindowsHid(device.Path))
            {
                var protocol = OpenProtocol(hid);
                WithConfiguration(protocol, () => { protocol.SelectProfile(index); Say("Perfil " + (index + 1) + " selecionado."); return true; });
            }
        }
    }
}
