"""
Simplified tray application.
"""

import os
import sys
import threading
import time
import subprocess
from typing import Optional

import pystray
from PIL import Image

from .config import Config
from .hotkey_manager import HotkeyManager
from .audio_recorder import AudioRecorder
from .transcriber import Transcriber
from .notifications import NotificationManager
from .startup import StartupManager


class ParratorTrayApp:
    """Main tray application."""

    def __init__(self):
        self.config = Config()
        self.transcriber = Transcriber(self.config)
        self.audio_recorder = AudioRecorder(self.config)
        self.notification_manager = NotificationManager()
        self.startup_manager = StartupManager()
        self.hotkey_manager: Optional[HotkeyManager] = None
        self.tray_icon: Optional[pystray.Icon] = None
        self.is_recording = False
        self.model_loaded = False

    def start(self):
        """Start the application."""
        print("Starting Parrator...")

        # Load transcription model in background
        self._load_model_async()

        # Setup tray icon
        self._setup_tray()

        # Setup hotkeys
        self._setup_hotkeys()

        print(f"Ready! Press {self.config.get('hotkey')} to record")

        # Run tray (this blocks)
        try:
            self.tray_icon.run()
        except KeyboardInterrupt:
            print("Application interrupted")
        finally:
            self.cleanup()

    def _load_model_async(self):
        """Load the transcription model in a background thread."""
        def load_model():
            if self.transcriber.load_model():
                self.model_loaded = True
                self._update_tray_icon()
                print("Model loaded successfully")
            else:
                print("Failed to load model")

        thread = threading.Thread(target=load_model, daemon=True)
        thread.start()

    def _setup_tray(self):
        """Setup the system tray icon."""
        # Load icon from resources
        icon_path = self._get_icon_path()
        try:
            image = Image.open(icon_path)
        except Exception as e:
            print(f"Could not load icon: {e}")
            # Create simple fallback icon
            image = Image.new('RGB', (64, 64), color='blue')

        # Create menu
        menu = pystray.Menu(
            pystray.MenuItem("Toggle Recording", self._toggle_recording),
            pystray.MenuItem("Settings", self._show_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start with System",
                self._toggle_startup,
                checked=lambda item: self.startup_manager.is_enabled()
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit_application)
        )

        self.tray_icon = pystray.Icon(
            "parrator",
            image,
            "Parrator - Loading...",
            menu
        )

    def _setup_hotkeys(self):
        """Setup global hotkeys."""
        hotkey_combo = self.config.get('hotkey', 'ctrl+shift+;')
        self.hotkey_manager = HotkeyManager(
            hotkey_combo, self._toggle_recording)

        if not self.hotkey_manager.start():
            print(f"Could not register hotkey: {hotkey_combo}")

    def _toggle_recording(self):
        """Toggle recording state."""
        if not self.model_loaded:
            print("Model still loading, please wait...")
            return

        if not self.is_recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        """Start audio recording."""
        print("Recording started...")
        self.is_recording = True
        self._update_tray_icon()

        if not self.audio_recorder.start_recording():
            print("Failed to start recording")
            self.is_recording = False
            self._update_tray_icon()

    def _stop_recording(self):
        """Stop recording and process audio."""
        print("Recording stopped, processing...")
        self.is_recording = False
        self._update_tray_icon()

        # Stop recording and get audio data
        audio_data = self.audio_recorder.stop_recording()

        if audio_data is not None:
            self._process_audio_async(audio_data)
        else:
            print("No audio data captured")

    def _process_audio_async(self, audio_data):
        """Process audio in background thread."""
        def process():
            try:
                # Save temporary audio file
                temp_path = self.audio_recorder.save_temp_audio(audio_data)
                if not temp_path:
                    print("Failed to save audio")
                    return

                # Transcribe
                success, text = self.transcriber.transcribe_file(temp_path)

                # Cleanup temp file
                try:
                    os.remove(temp_path)
                except:
                    pass

                if success and text:
                    self._handle_transcription_result(text)
                else:
                    print("Transcription failed")

            except Exception as e:
                print(f"Processing error: {e}")

        thread = threading.Thread(target=process, daemon=True)
        thread.start()

    def _handle_transcription_result(self, text: str):
        """Handle successful transcription."""
        print(f"Transcribed: {text}")

        # Copy to clipboard
        try:
            import pyperclip
            pyperclip.copy(text)
            print("Copied to clipboard")

            # Auto-paste if enabled
            if self.config.get('auto_paste', True):
                self._auto_paste()

        except Exception as e:
            print(f"Clipboard error: {e}")

    def _auto_paste(self):
        """Automatically paste from clipboard."""
        try:
            import pyautogui
            time.sleep(0.1)
            pyautogui.hotkey('ctrl', 'v')
            print("Auto-pasted")
        except Exception as e:
            print(f"Auto-paste failed: {e}")

    def _update_tray_icon(self):
        """Update tray icon title based on current state."""
        if self.tray_icon:
            if self.is_recording:
                title = "Parrator - Recording..."
            elif self.model_loaded:
                title = "Parrator - Ready"
            else:
                title = "Parrator - Loading..."

            self.tray_icon.title = title

    def _show_settings(self):
        """Open settings file in default editor."""
        try:
            config_path = self.config.config_path

            if sys.platform == "win32":
                os.startfile(config_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", config_path])
            else:
                subprocess.run(["xdg-open", config_path])

            print(f"Opened settings: {config_path}")

        except Exception as e:
            print(f"Could not open settings: {e}")

    def _toggle_startup(self):
        """Toggle startup with system."""
        if self.startup_manager.is_enabled():
            if self.startup_manager.disable():
                print("Disabled startup with system")
            else:
                print("Failed to disable startup")
        else:
            if self.startup_manager.enable():
                print("Enabled startup with system")
            else:
                print("Failed to enable startup")

    def _quit_application(self):
        """Quit the application."""
        print("Quitting...")
        self.cleanup()
        self.tray_icon.stop()

    def _get_icon_path(self):
        """Get path to tray icon."""
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        return os.path.join(base_path, 'resources', 'icon.png')

    def cleanup(self):
        """Clean up resources."""
        if self.hotkey_manager:
            self.hotkey_manager.stop()
        if self.audio_recorder:
            self.audio_recorder.cleanup()
