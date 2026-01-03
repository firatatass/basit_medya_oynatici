import os
import sys
import wx
import json
import random
import shutil
import io
import globalPluginHandler
import gui
import ui
import scriptHandler
import logHandler
import addonHandler

addonHandler.initTranslation()

addon_dir = os.path.dirname(__file__)
lib_path = os.path.join(addon_dir, "lib")
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

try:
    import pygame
    from mutagen import File
except ImportError as e:
    logHandler.log.error(_("Simple Media Player library loading error: {e}").format(e=e))

def find_resource_path(relative_path):
    return os.path.join(addon_dir, relative_path)

class AdvancedSettingsDialog(wx.Dialog):
    def __init__(self, parent, settings):
        super().__init__(parent, title=_("Advanced Settings"), size=(400, 300))
        self.settings = settings
        self.panel = wx.Panel(self)
        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        header = wx.StaticText(self.panel, label=_("Album Cover Display Settings"))
        header.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.main_sizer.Add(header, 0, wx.ALL, 10)
        
        self.show_cover_checkbox = wx.CheckBox(self.panel, label=_("Show album cover art"))
        self.show_cover_checkbox.SetValue(self.settings.get("show_cover", False)) 
        self.show_cover_checkbox.Bind(wx.EVT_CHECKBOX, self.on_checkbox_changed)
        self.main_sizer.Add(self.show_cover_checkbox, 0, wx.LEFT, 20)
        
        options = [_("Show music album cover if available"), _("Always show default media player icon")]
        self.cover_mode_combo = wx.ComboBox(self.panel, choices=options, style=wx.CB_READONLY)
        self.cover_mode_combo.SetSelection(self.settings.get("cover_mode", 0))
        self.cover_mode_combo.Show(self.show_cover_checkbox.GetValue())
        self.main_sizer.Add(self.cover_mode_combo, 0, wx.ALL | wx.EXPAND, 20)
        
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(self.panel, wx.ID_OK, label=_("OK"))
        cancel_btn = wx.Button(self.panel, wx.ID_CANCEL, label=_("Cancel"))
        btn_sizer.Add(ok_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        self.main_sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.TOP, 20)
        
        self.panel.SetSizer(self.main_sizer)

    def on_checkbox_changed(self, event):
        show = self.show_cover_checkbox.GetValue()
        self.cover_mode_combo.Show(show)
        self.panel.Layout()

    def GetValues(self):
        return {
            "show_cover": self.show_cover_checkbox.GetValue(),
            "cover_mode": self.cover_mode_combo.GetSelection()
        }

class SimpleMediaPlayer(wx.Frame):
    def __init__(self):
        super().__init__(parent=gui.mainFrame, title=_("Simple Media Player"), size=(550, 850))
        self.default_icon_path = find_resource_path("icon.ico")
        if os.path.exists(self.default_icon_path):
            self.SetIcon(wx.Icon(self.default_icon_path))
            
        pygame.mixer.init()
        self.current_index = -1
        self.current_tags = {}
        self.repeat = False
        self.shuffle = False
        self.is_paused = False
        self.total_duration = 0
        
        self.settings_dir = os.path.join(os.environ['APPDATA'], 'nvda', 'simple_media_player')
        if not os.path.exists(self.settings_dir): os.makedirs(self.settings_dir)
        self.settings_file = os.path.join(self.settings_dir, "settings.json")
        
        self.load_settings()
        self.music_path = self.settings.get("last_folder", os.path.join(self.settings_dir, "sounds"))
        if not os.path.exists(self.music_path):
            try: os.makedirs(self.music_path)
            except: pass
            
        self.create_ui()
        self.update_playlist()
        
        saved_volume = self.settings.get("volume", 0.7)
        pygame.mixer.music.set_volume(saved_volume)
        self.volume_slider.SetValue(int(saved_volume * 100))
        
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer_tick, self.timer)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        ui.message(_("Simple Media Player Opened"))

    def create_ui(self):
        panel = wx.Panel(self)
        panel.SetBackgroundColour('#000000')
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.cover_area = wx.StaticBitmap(panel, size=(200, 200))
        main_sizer.Add(self.cover_area, 0, wx.ALIGN_CENTER | wx.TOP, 10)
        
        self.info_text = wx.StaticText(panel, label=_("Please select a song"), style=wx.ALIGN_CENTER)
        self.info_text.SetForegroundColour('#00FF00')
        self.info_text.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        main_sizer.Add(self.info_text, 0, wx.ALL | wx.EXPAND, 15)
        
        self.seek_slider = wx.Slider(panel, value=0, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL)
        main_sizer.Add(self.seek_slider, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        self.sort_selector = wx.ComboBox(panel, choices=[_("Title - Artist - Album"), _("Album - Title - Artist"), _("Artist - Title - Album")], style=wx.CB_READONLY)
        self.sort_selector.SetSelection(self.settings.get("sort_order", 0))
        self.sort_selector.Bind(wx.EVT_COMBOBOX, self.on_sort_changed)
        main_sizer.Add(self.sort_selector, 0, wx.ALL | wx.EXPAND, 10)
        
        self.playlist_box = wx.ListBox(panel, style=wx.LB_SINGLE)
        self.playlist_box.SetBackgroundColour('#1A1A1A')
        self.playlist_box.SetForegroundColour('#FFFFFF')
        self.playlist_box.Bind(wx.EVT_LISTBOX_DCLICK, self.start_song)
        main_sizer.Add(self.playlist_box, 1, wx.ALL | wx.EXPAND, 10)
        
        self.volume_slider = wx.Slider(panel, value=70, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL)
        self.volume_slider.Bind(wx.EVT_SCROLL, self.on_volume_scroll)
        main_sizer.Add(self.volume_slider, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        button_grid = wx.GridSizer(rows=6, cols=3, vgap=5, hgap=5)
        self.btn_repeat = wx.Button(panel, label=_("Repeat: Off (T)"))
        self.btn_repeat.Bind(wx.EVT_BUTTON, self.on_toggle_repeat)
        self.btn_shuffle = wx.Button(panel, label=_("Shuffle: Off (R)"))
        self.btn_shuffle.Bind(wx.EVT_BUTTON, self.on_toggle_shuffle)
        
        playback_btns = [
            (_("Previous (P)"), self.on_previous), (_("Play/Pause (K)"), self.on_play_pause), (_("Next (S)"), self.on_next),
            (_("Rewind (G)"), self.on_rewind), (_("Fast Forward (I)"), self.on_fast_forward)
        ]
        for label, event in playback_btns:
            btn = wx.Button(panel, label=label)
            btn.Bind(wx.EVT_BUTTON, event)
            button_grid.Add(btn, 0, wx.EXPAND)
            
        button_grid.Add(self.btn_repeat, 0, wx.EXPAND)
        button_grid.Add(self.btn_shuffle, 0, wx.EXPAND)
        
        extra_btns = [
            (_("Volume Down"), self.on_volume_down), (_("Volume Up"), self.on_volume_up), (_("Restart (B)"), self.on_restart_song),
            (_("Select Folder (Ctrl+O)"), self.on_select_folder), (_("Default Folder (D)"), self.on_return_to_default),
            (_("Copy Music (C)"), self.on_copy_music), (_("Advanced Settings (A)"), self.on_advanced_settings)
        ]
        for label, event in extra_btns:
            btn = wx.Button(panel, label=label)
            btn.Bind(wx.EVT_BUTTON, event)
            button_grid.Add(btn, 0, wx.EXPAND)
            
        main_sizer.Add(button_grid, 0, wx.ALL | wx.EXPAND, 10)
        
        footer_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.exit_confirm_checkbox = wx.CheckBox(panel, label=_("Ask before exiting"))
        self.exit_confirm_checkbox.SetForegroundColour('#FFFFFF')
        self.exit_confirm_checkbox.SetValue(self.settings.get("confirm_exit", False))
        self.btn_exit = wx.Button(panel, label=_("Exit"))
        self.btn_exit.Bind(wx.EVT_BUTTON, self.on_exit_button)
        footer_sizer.Add(self.exit_confirm_checkbox, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        footer_sizer.Add(self.btn_exit, 0, wx.ALL, 10)
        
        main_sizer.Add(footer_sizer, 0, wx.EXPAND | wx.BOTTOM, 10)
        panel.SetSizer(main_sizer)

    def is_list_empty(self):
        if not self.songs:
            wx.MessageBox(_("No media to play"), _("Warning"), wx.OK | wx.ICON_WARNING)
            return True
        return False

    def on_toggle_repeat(self, event=None):
        self.repeat = not self.repeat
        if self.repeat:
            self.btn_repeat.SetLabel(_("Repeat: On (T)"))
            ui.message(_("Repeat On"))
        else:
            self.btn_repeat.SetLabel(_("Repeat: Off (T)"))
            ui.message(_("Repeat Off"))
        self.btn_repeat.SetFocus() 

    def on_toggle_shuffle(self, event=None):
        if self.is_list_empty(): return
        self.shuffle = not self.shuffle
        if self.shuffle:
            random.shuffle(self.songs)
            self.btn_shuffle.SetLabel(_("Shuffle: On (R)"))
            ui.message(_("Shuffle On"))
        else:
            self.songs = list(self.original_songs)
            self.btn_shuffle.SetLabel(_("Shuffle: Off (R)"))
            ui.message(_("Shuffle Off"))
        self.playlist_box.Set(self.songs)
        self.btn_shuffle.SetFocus()

    def on_key_down(self, event):
        key = event.GetKeyCode()
        ctrl = event.ControlDown()
        focus_obj = self.FindFocus()
        if focus_obj == self.playlist_box:
            if key in [wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER]:
                self.start_song(None)
                return
            if key in [wx.WXK_UP, wx.WXK_DOWN]:
                event.Skip()
                return
        if ctrl and key == ord('O'): self.on_select_folder(None)
        elif key == ord('D'): self.on_return_to_default(None)
        elif key == ord('C'): self.on_copy_music(None)
        elif key in [ord('A'), ord('a')]: self.on_advanced_settings(None)
        elif key == wx.WXK_UP: self.on_volume_up(None)
        elif key == wx.WXK_DOWN: self.on_volume_down(None)
        elif key == ord('K'): self.on_play_pause(None)
        elif key == ord('S'): self.on_next(None)
        elif key in [ord('P'), ord('p')]: self.on_previous(None) 
        elif key == ord('G'): self.on_rewind(None)
        elif key in [ord('I'), ord('i')]: self.on_fast_forward(None) 
        elif key == ord('R'): self.on_toggle_shuffle(None)
        elif key == ord('T'): self.on_toggle_repeat(None)
        elif key == ord('B'): self.on_restart_song(None)
        else: event.Skip()

    def on_select_folder(self, event):
        dlg = wx.DirDialog(self, _("Select music folder"), style=wx.DD_DEFAULT_STYLE)
        if dlg.ShowModal() == wx.ID_OK:
            self.music_path = dlg.GetPath()
            self.settings["last_folder"] = self.music_path
            self.update_playlist()
            ui.message(_("Folder updated"))
        dlg.Destroy()

    def on_return_to_default(self, event=None):
        self.music_path = os.path.join(self.settings_dir, "sounds")
        self.settings["last_folder"] = self.music_path
        self.update_playlist()
        ui.message(_("Returned to default folder"))

    def on_copy_music(self, event):
        dlg = wx.FileDialog(self, _("Select music"), wildcard="Music (*.mp3;*.wav;*.ogg)|*.mp3;*.wav;*.ogg", style=wx.FD_OPEN | wx.FD_MULTIPLE)
        if dlg.ShowModal() == wx.ID_OK:
            target = os.path.join(self.settings_dir, "sounds")
            if not os.path.exists(target): os.makedirs(target)
            for path in dlg.GetPaths():
                try: shutil.copy2(path, target)
                except: pass
            self.on_return_to_default()
        dlg.Destroy()

    def on_advanced_settings(self, event):
        dlg = AdvancedSettingsDialog(self, self.settings)
        if dlg.ShowModal() == wx.ID_OK:
            self.settings.update(dlg.GetValues())
            self.save_settings()
            self.update_cover()
        dlg.Destroy()

    def update_cover(self):
        if not self.settings.get("show_cover", False) or self.current_index == -1:
            self.cover_area.SetBitmap(wx.NullBitmap)
            return
        file_path = os.path.join(self.music_path, self.songs[self.current_index])
        mode = self.settings.get("cover_mode", 0)
        img_data = None
        if mode == 0:
            try:
                tag = File(file_path)
                if tag and 'APIC:' in tag: img_data = tag['APIC:'].data
            except: pass
        if img_data: img = wx.Image(io.BytesIO(img_data))
        elif os.path.exists(self.default_icon_path): img = wx.Image(self.default_icon_path)
        else: self.cover_area.SetBitmap(wx.NullBitmap); return
        img = img.Rescale(200, 200, wx.IMAGE_QUALITY_HIGH)
        self.cover_area.SetBitmap(wx.Bitmap(img))

    def update_playlist(self):
        try:
            files = [f for f in os.listdir(self.music_path) if f.endswith(('.mp3', '.wav', '.ogg'))]
            files.sort()
            self.songs = files
            self.original_songs = list(files)
            self.playlist_box.Set(self.songs)
        except: pass

    def play(self, start_pos):
        if self.current_index == -1: return
        file_path = os.path.join(self.music_path, self.songs[self.current_index])
        try:
            audio = File(file_path)
            self.total_duration = int(audio.info.length)
            self.seek_slider.SetMax(self.total_duration)
            self.seek_slider.SetValue(int(start_pos))
            self.current_tags = {
                "Title": str(audio.get('TIT2', self.songs[self.current_index])),
                "Artist": str(audio.get('TPE1', _("Unknown Artist"))),
                "Album": str(audio.get('TALB', _("Unknown Album")))
            }
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play(start=start_pos)
            self.is_paused = False
            self.refresh_info_display()
            self.update_cover()
            self.timer.Start(1000)
            if start_pos == 0:
                ui.message(_("Playing: {title}").format(title=self.current_tags['Title']))
        except: pass

    def load_settings(self):
        try:
            with open(self.settings_file, "r") as f: self.settings = json.load(f)
        except:
            self.settings = {"confirm_exit": False, "sort_order": 0, "volume": 0.7, "last_folder": os.path.join(self.settings_dir, "sounds"), "show_cover": False, "cover_mode": 0}

    def save_settings(self):
        self.settings["sort_order"] = self.sort_selector.GetSelection()
        self.settings["volume"] = pygame.mixer.music.get_volume()
        self.settings["confirm_exit"] = self.exit_confirm_checkbox.GetValue()
        self.settings["last_folder"] = self.music_path
        with open(self.settings_file, "w") as f: json.dump(self.settings, f)

    def on_close(self, event):
        self.save_settings()
        if self.exit_confirm_checkbox.GetValue():
            if wx.MessageBox(_("Do you want to exit?"), _("Confirm"), wx.YES_NO) == wx.YES:
                self.cleanup()
                self.Destroy()
            else: 
                if event.CanVeto(): event.Veto()
        else:
            self.cleanup()
            self.Destroy()

    def cleanup(self):
        try:
            self.timer.Stop()
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except: pass

    def on_exit_button(self, event): self.Close()
    def on_sort_changed(self, event): self.refresh_info_display()
    
    def start_song(self, event):
        if self.is_list_empty(): return
        idx = self.playlist_box.GetSelection()
        if idx != wx.NOT_FOUND: self.current_index = idx; self.play(0)
        
    def on_play_pause(self, event):
        if self.is_list_empty(): return
        if self.current_index == -1: self.playlist_box.SetSelection(0); self.start_song(None); return
        if not self.is_paused: 
            pygame.mixer.music.pause()
            self.is_paused = True
            ui.message(_("Paused"))
        else: 
            pygame.mixer.music.unpause()
            self.is_paused = False
            ui.message(_("Resumed"))
            
    def on_next(self, event):
        if self.is_list_empty(): return
        self.current_index = (self.current_index + 1) % len(self.songs); self.playlist_box.SetSelection(self.current_index); self.play(0)
        
    def on_previous(self, event):
        if self.is_list_empty(): return
        self.current_index = (self.current_index - 1) % len(self.songs); self.playlist_box.SetSelection(self.current_index); self.play(0)
        
    def on_volume_up(self, event):
        v = min(pygame.mixer.music.get_volume() + 0.05, 1.0); pygame.mixer.music.set_volume(v); self.volume_slider.SetValue(int(v * 100))
        ui.message(_("Volume {val}").format(val=int(v*100)))
        
    def on_volume_down(self, event):
        v = max(pygame.mixer.music.get_volume() - 0.05, 0.0); pygame.mixer.music.set_volume(v); self.volume_slider.SetValue(int(v * 100))
        ui.message(_("Volume {val}").format(val=int(v*100)))
        
    def on_volume_scroll(self, event): pygame.mixer.music.set_volume(self.volume_slider.GetValue() / 100)
    def on_rewind(self, event): self.play(max(0, self.seek_slider.GetValue() - 10))
    def on_fast_forward(self, event): self.play(min(self.total_duration, self.seek_slider.GetValue() + 10))
    def on_restart_song(self, event):
        if self.current_index != -1: self.play(0); ui.message(_("Restarted"))
        
    def refresh_info_display(self):
        if not self.current_tags: return
        selection = self.sort_selector.GetSelection()
        order = {0: ["Title", "Artist", "Album"], 1: ["Album", "Title", "Artist"], 2: ["Artist", "Title", "Album"]}.get(selection)
        s1, s2, s3 = self.current_tags[order[0]], self.current_tags[order[1]], self.current_tags[order[2]]
        self.info_text.SetLabel(f"{s1}\n{s2}\n{s3}"); self.SetTitle(_("Playing: {title}").format(title=s1))
        
    def on_timer_tick(self, event):
        if pygame.mixer.music.get_busy():
            val = self.seek_slider.GetValue()
            if val < self.total_duration: self.seek_slider.SetValue(val + 1)
        elif not self.is_paused and self.current_index != -1:
            if self.repeat: self.play(0)
            else: self.on_next(None)

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = _("Simple Media Player")
    
    def script_openMediaPlayer(self, gesture):
        for win in wx.GetTopLevelWindows():
            if win.GetTitle() == _("Simple Media Player"):
                win.Raise()
                return
        player = SimpleMediaPlayer()
        player.Show()
    
    script_openMediaPlayer.__doc__ = _("Opens Simple Media Player.")