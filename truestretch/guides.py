"""One-time graphics driver setup, per GPU vendor. Windows can't create custom resolutions or set
GPU scaling for the user, so these steps stay manual - the app opens the right control panel."""

from .system import open_installed_store_app, open_uri
from pathlib import Path
import subprocess

NVIDIA_CP_EXE = Path(r"C:\Program Files\NVIDIA Corporation\Control Panel Client\nvcplui.exe")
AMD_EXE = Path(r"C:\Program Files\AMD\CNext\CNext\RadeonSoftware.exe")


def open_nvidia():
    if NVIDIA_CP_EXE.is_file():
        subprocess.Popen([str(NVIDIA_CP_EXE)])
    else:   # Store version - its id differs between PCs, so look it up
        open_installed_store_app("NVIDIACorp.NVIDIAControlPanel", "NVIDIACorp.NVIDIAControlPanel")


def open_intel():
    open_installed_store_app("AppUp.IntelGraphicsExperience", "App")


def open_omen():
    open_installed_store_app("AD2F1837.OMENCommandCenter", "AD2F1837.OMENCommandCenter")


def open_amd():
    if AMD_EXE.is_file():
        subprocess.Popen([str(AMD_EXE)])
    else:
        raise FileNotFoundError("AMD Software: Adrenalin Edition isn't installed.")


GUIDES = {
    "nvidia": {
        "title": "NVIDIA Control Panel",
        "open": open_nvidia,
        "steps": [
            ("Create the custom resolution",
             "Display \u203a Change resolution \u203a Customize\u2026 \u203a tick \u201cEnable resolutions not exposed "
             "by the display\u201d \u203a Create Custom Resolution. Horizontal pixels {w}, vertical lines {h} "
             "(1050 also works), refresh rate as is \u203a Test, then keep it."),
            ("Stretch it to fill the screen",
             "Display \u203a Adjust desktop size and position \u203a Scaling mode: Full-screen, "
             "Perform scaling on: GPU, tick \u201cOverride the scaling mode set by games and programs\u201d \u203a Apply."),
            ("Laptop tip",
             "If \u201cAdjust desktop size and position\u201d is missing, your built-in screen is driven by the Intel "
             "GPU \u2014 follow the Intel steps instead. External monitors are usually wired to NVIDIA."),
        ],
    },
    "amd": {
        "title": "AMD Software: Adrenalin",
        "open": open_amd,
        "steps": [
            ("Turn on GPU scaling",
             "Right-click the desktop \u203a AMD Software: Adrenalin Edition \u203a Settings (gear) \u203a Display "
             "\u203a GPU Scaling: On."),
            ("Stretch it to fill the screen",
             "Scaling Mode: Full Panel \u2014 not \u201cPreserve Aspect Ratio\u201d, that one gives black bars."),
            ("Create the custom resolution",
             "Type \u201cCustom\u201d in AMD Software's search bar \u203a Custom Resolutions \u203a Accept \u203a "
             "Create New \u203a enter {w} \u00d7 {h} \u203a Create."),
        ],
    },
    "intel": {
        "title": "Intel Graphics Command Center",
        "open": open_intel,
        "steps": [
            ("Create the custom resolution",
             "Display \u203a General \u203a Custom resolution (+). Enter {w} \u00d7 {h} at your refresh rate and save."),
            ("Stretch it to fill the screen",
             "Display \u203a General \u203a Scale: Stretch (sometimes called \u201cFull screen\u201d)."),
        ],
    },
}


def open_display_settings():
    open_uri("ms-settings:display")
