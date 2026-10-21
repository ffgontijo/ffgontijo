using System;
using System.Drawing;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace RedragonMini
{
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
        }
    }

    public sealed class MainForm : Form
    {
        private readonly ComboBox devices = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };
        private readonly ComboBox mac5 = ButtonPicker(), win5 = ButtonPicker();
        private readonly CheckBox experimental = new CheckBox { Text = "Testar troca interna pelo botão 7 (experimental)", AutoSize = true, Margin = new Padding(4, 12, 4, 2) };
        private readonly Label mode = new Label { AutoSize = true, MaximumSize = new Size(780, 0), Margin = new Padding(4, 4, 4, 10) };
        private readonly TextBox log = new TextBox { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill, BackColor = Color.White, Font = new Font("Consolas", 9) };
        private readonly Label status = new Label { AutoSize = true, Text = "Conecte o mouse pelo cabo e feche o aplicativo original.", Padding = new Padding(4, 8, 4, 4) };
        private readonly TableLayoutPanel controls = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, Padding = new Padding(16), AutoScroll = true };
        private bool busy;

        public MainForm()
        {
            Text = "Redragon Mini • M719-WL"; ClientSize = new Size(840, 650); MinimumSize = new Size(760, 640);
            Font = new Font("Segoe UI", 10); StartPosition = FormStartPosition.CenterScreen;
            controls.RowCount = 10;
            controls.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            controls.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            controls.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            controls.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            controls.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            controls.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            controls.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            controls.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            controls.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            controls.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            var title = new Label { Text = "Dois ajustes para o seu mouse", AutoSize = true, Font = new Font(Font.FontFamily, 18, FontStyle.Bold), Margin = new Padding(0, 0, 0, 8) };
            controls.Controls.Add(title, 0, 0);
            controls.Controls.Add(new Label { Text = "Perfis 1 e 2 como base. DPI e iluminação são mantidos desses perfis.", AutoSize = true, Margin = new Padding(2, 0, 2, 12) }, 0, 1);
            var connection = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 2 };
            connection.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); connection.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            connection.Controls.Add(devices, 0, 0);
            var refresh = Button("Procurar mouse", async (s, e) => await RefreshDevices()); connection.Controls.Add(refresh, 1, 0);
            controls.Controls.Add(connection, 0, 2);
            var profiles = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 2, Margin = new Padding(0, 12, 0, 0) };
            profiles.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50)); profiles.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            profiles.Controls.Add(ProfileBox("Perfil 1 • macOS", "Botão 6: Command + 1", mac5), 0, 0);
            profiles.Controls.Add(ProfileBox("Perfil 2 • Windows", "Botão 6: Print Screen", win5), 1, 0);
            controls.Controls.Add(profiles, 0, 3); controls.Controls.Add(experimental, 0, 4); controls.Controls.Add(mode, 0, 5);
            var actions = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = true, Margin = new Padding(0) };
            actions.Controls.Add(Button("Gravar configurações", async (s, e) => await Apply()));
            actions.Controls.Add(Button("Somente backup", async (s, e) => await Backup()));
            actions.Controls.Add(Button("Restaurar backup…", async (s, e) => await Restore()));
            actions.Controls.Add(Button("Abrir backups", (s, e) => OpenBackups()));
            controls.Controls.Add(actions, 0, 6);
            var select = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, Margin = new Padding(0, 4, 0, 8) };
            select.Controls.Add(Button("Ativar macOS agora", async (s, e) => await Select(0)));
            select.Controls.Add(Button("Ativar Windows agora", async (s, e) => await Select(1)));
            controls.Controls.Add(select, 0, 7); controls.Controls.Add(log, 0, 8); controls.Controls.Add(status, 0, 9);
            Controls.Add(controls);
            experimental.CheckedChanged += (s, e) => UpdateMode();
            mac5.SelectedIndexChanged += (s, e) => PickCustom(mac5);
            win5.SelectedIndexChanged += (s, e) => PickCustom(win5);
            UpdateMode();
            Shown += async (s, e) => await RefreshDevices();
            FormClosing += (s, e) => { if (busy) { e.Cancel = true; status.Text = "Aguarde terminar a operação USB antes de fechar."; } };
        }
        private static ComboBox ButtonPicker()
        {
            var c = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Top };
            c.Items.Add(ButtonChoice.Keep());
            c.Items.Add(ButtonChoice.Shortcut("Ctrl + C", 1, 6)); c.Items.Add(ButtonChoice.Shortcut("Ctrl + V", 1, 0x19));
            c.Items.Add(ButtonChoice.Shortcut("Command + C", 8, 6)); c.Items.Add(ButtonChoice.Shortcut("Command + V", 8, 0x19));
            c.Items.Add(ButtonChoice.Action("Voltar", 1, 8)); c.Items.Add(ButtonChoice.Action("Avançar", 1, 0x10));
            c.Items.Add(ButtonChoice.Action("Desativado", 0, 0)); c.Items.Add(new ButtonChoice { Name = "Atalho personalizado…", Usage = 0xffff });
            c.SelectedIndex = 0; return c;
        }
        private static Control ProfileBox(string name, string shortcut, ComboBox picker)
        {
            var box = new GroupBox { Text = name, Dock = DockStyle.Top, AutoSize = true, Padding = new Padding(12), Margin = new Padding(2, 2, 10, 2) };
            var stack = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 1 };
            stack.Controls.Add(new Label { Text = shortcut, AutoSize = true, Margin = new Padding(2, 4, 2, 12) });
            stack.Controls.Add(new Label { Text = "Botão 5", AutoSize = true, Margin = new Padding(2, 0, 2, 4) }); stack.Controls.Add(picker);
            box.Controls.Add(stack); return box;
        }
        private static Button Button(string text, EventHandler click)
        {
            var b = new Button { Text = text, AutoSize = true, Padding = new Padding(8, 4, 8, 4), Margin = new Padding(2, 2, 6, 2) }; b.Click += click; return b;
        }
        private void UpdateMode()
        {
            mode.ForeColor = experimental.Checked ? Color.FromArgb(150, 65, 0) : Color.FromArgb(65, 65, 65);
            mode.Text = experimental.Checked
                ? "Teste de firmware: grava a função interna de troca no botão 7 e organiza as posições 1/2/3/4 como macOS/Windows/macOS/Windows. As posições 3 e 4 serão substituídas. O firmware pode ignorar essa função."
                : "Modo de dois perfis: grava os atalhos nos perfis 1 e 2 e preserva o botão 7. Para testar a alternância sem aplicativo, marque a opção experimental acima.";
        }
        private void PickCustom(ComboBox picker)
        {
            var choice = picker.SelectedItem as ButtonChoice;
            if (choice == null || choice.Usage != 0xffff) return;
            using (var dialog = new ShortcutDialog())
            {
                if (dialog.ShowDialog(this) == DialogResult.OK) { picker.Items.Add(dialog.Choice); picker.SelectedIndex = picker.Items.Count - 1; }
                else picker.SelectedIndex = 0;
            }
        }
        private void WriteLog(string text)
        {
            if (InvokeRequired) { BeginInvoke(new Action<string>(WriteLog), text); return; }
            log.AppendText(DateTime.Now.ToString("HH:mm:ss") + "  " + text + Environment.NewLine);
        }
        private async Task Run(string description, Func<Task> action)
        {
            if (busy) return;
            busy = true; controls.Enabled = false; UseWaitCursor = true; status.Text = description; WriteLog(description);
            try { await action(); status.Text = "Operação concluída. Consulte o registro acima."; }
            catch (Exception ex) { WriteLog("ERRO: " + ex.Message); status.Text = "Operação interrompida. Consulte o registro."; MessageBox.Show(this, ex.Message, "Redragon Mini", MessageBoxButtons.OK, MessageBoxIcon.Error); }
            finally { busy = false; controls.Enabled = true; UseWaitCursor = false; }
        }
        private HidDeviceInfo SelectedDevice()
        {
            var device = devices.SelectedItem as HidDeviceInfo;
            if (device == null || !device.CanExchange) throw new InvalidOperationException("Nenhum M719-WL compatível selecionado. Conecte o cabo ou o receptor e clique em Procurar mouse.");
            return device;
        }
        private ProfileService Service() { return new ProfileService { Log = WriteLog }; }
        private async Task RefreshDevices()
        {
            await Run("Procurando interfaces HID do M719-WL...", async () => {
                var found = await Task.Run(() => WindowsHid.Enumerate()); devices.Items.Clear();
                foreach (var d in found.Where(d => d.CanExchange).OrderBy(d => d.ProductId == 0xf55e ? 0 : 1)) devices.Items.Add(d);
                if (devices.Items.Count > 0) { devices.SelectedIndex = 0; WriteLog("Mouse encontrado. Feche o aplicativo original antes de ler ou gravar."); }
                else { WriteLog("Interface compatível não encontrada. Tente o cabo USB; não é necessário substituir o driver HID."); foreach (var d in found) WriteLog(d.Path + " | entrada=" + d.InputReportLength + ", saída=" + d.OutputReportLength); }
            });
        }
        private async Task Apply()
        {
            await Run("Preparando backup e gravação. Não pressione o botão 7 durante a operação.", async () => {
                var d = SelectedDevice(); bool cycle = experimental.Checked; var a = (ButtonChoice)mac5.SelectedItem; var b = (ButtonChoice)win5.SelectedItem;
                string backup = await Task.Run(() => Service().Program(d, cycle, a, b));
                WriteLog("Backup salvo em " + backup);
                WriteLog(cycle ? "TESTE PENDENTE: feche este app, desligue/religue o mouse e teste o botão 7. O botão 6 deve alternar Command+1 e Print Screen. Repetir no Mac confirma o uso sem software." : "Perfis gravados. A seleção pelo software está disponível nos botões Ativar acima.");
                MessageBox.Show(this, cycle ? "Gravação e releitura concluídas.\r\n\r\nAinda é necessário testar no mouse: feche o app, desligue/religue e pressione o botão 7. Se ele não alternar os atalhos do botão 6, restaure o backup; a função interna pode não ser suportada.\r\n\r\nDPI e RGB foram copiados dos perfis 1 e 2." : "Perfis 1 e 2 gravados e relidos. O perfil 1 (macOS) está ativo.\r\n\r\nPara testar o botão 7 sem app, use a opção experimental.", "Gravação verificada", MessageBoxButtons.OK, MessageBoxIcon.Information);
            });
        }
        private async Task Backup()
        {
            await Run("Lendo configurações para backup...", async () => { var d = SelectedDevice(); int count = experimental.Checked ? 4 : 2; await Task.Run(() => Service().Backup(d, count)); });
        }
        private async Task Restore()
        {
            using (var dialog = new OpenFileDialog { Filter = "Backup Redragon Mini (*.json)|*.json", InitialDirectory = ProfileService.BackupDirectory(), Title = "Selecione o backup a restaurar" })
            {
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                string path = dialog.FileName;
                await Run("Restaurando configurações do backup...", async () => { var d = SelectedDevice(); await Task.Run(() => Service().Restore(d, path)); WriteLog("Restauração concluída e relida."); });
            }
        }
        private async Task Select(int profile)
        {
            await Run("Selecionando perfil " + (profile + 1) + "...", async () => { var d = SelectedDevice(); await Task.Run(() => Service().Select(d, profile)); });
        }
        private void OpenBackups()
        {
            try { System.Diagnostics.Process.Start("explorer.exe", ProfileService.BackupDirectory()); }
            catch (Exception ex) { WriteLog(ex.Message); }
        }
    }

    public sealed class ShortcutDialog : Form
    {
        public ButtonChoice Choice { get; private set; }
        private readonly ComboBox key = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 250 };
        private readonly CheckBox ctrl = new CheckBox { Text = "Ctrl", AutoSize = true }, shift = new CheckBox { Text = "Shift", AutoSize = true }, alt = new CheckBox { Text = "Alt / Option", AutoSize = true }, gui = new CheckBox { Text = "Win / Command", AutoSize = true };
        private sealed class KeyItem { public string Name; public ushort Usage; public override string ToString() { return Name; } }
        public ShortcutDialog()
        {
            Text = "Atalho do botão 5"; ClientSize = new Size(420, 190); FormBorderStyle = FormBorderStyle.FixedDialog; StartPosition = FormStartPosition.CenterParent; MaximizeBox = false; MinimizeBox = false; Font = new Font("Segoe UI", 10);
            var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(16), FlowDirection = FlowDirection.TopDown, WrapContents = false };
            panel.Controls.Add(new Label { Text = "Escolha a tecla e os modificadores:", AutoSize = true }); panel.Controls.Add(key);
            for (int i = 0; i < 26; i++) key.Items.Add(new KeyItem { Name = ((char)('A' + i)).ToString(), Usage = (ushort)(4 + i) });
            for (int i = 1; i <= 10; i++) key.Items.Add(new KeyItem { Name = (i % 10).ToString(), Usage = (ushort)(0x1d + i) });
            for (int i = 1; i <= 12; i++) key.Items.Add(new KeyItem { Name = "F" + i, Usage = (ushort)(0x39 + i) });
            string[] names = { "Enter", "Esc", "Backspace", "Tab", "Espaço", "Print Screen", "Insert", "Home", "Page Up", "Delete", "End", "Page Down", "Direita", "Esquerda", "Baixo", "Cima" };
            ushort[] codes = { 0x28, 0x29, 0x2a, 0x2b, 0x2c, 0x46, 0x49, 0x4a, 0x4b, 0x4c, 0x4d, 0x4e, 0x4f, 0x50, 0x51, 0x52 };
            for (int i = 0; i < names.Length; i++) key.Items.Add(new KeyItem { Name = names[i], Usage = codes[i] }); key.SelectedIndex = 0;
            var mods = new FlowLayoutPanel { AutoSize = true }; mods.Controls.AddRange(new Control[] { ctrl, shift, alt, gui }); panel.Controls.Add(mods);
            var ok = new Button { Text = "Usar atalho", AutoSize = true }; ok.Click += (s, e) => {
                var selected = (KeyItem)key.SelectedItem; byte modifier = (byte)((ctrl.Checked ? 1 : 0) | (shift.Checked ? 2 : 0) | (alt.Checked ? 4 : 0) | (gui.Checked ? 8 : 0));
                string name = (ctrl.Checked ? "Ctrl + " : "") + (shift.Checked ? "Shift + " : "") + (alt.Checked ? "Alt + " : "") + (gui.Checked ? "Command/Win + " : "") + selected.Name;
                Choice = ButtonChoice.Shortcut(name, modifier, selected.Usage); DialogResult = DialogResult.OK; Close();
            }; panel.Controls.Add(ok); AcceptButton = ok; Controls.Add(panel);
        }
    }
}
