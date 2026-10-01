"""Who made VolumeX and what else they make, shown on the About page."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Link:
    label: str
    url: str
    icon: str  # name in ui.icons


@dataclass(frozen=True)
class FeaturedApp:
    name: str
    tagline: str
    description: str
    highlights: tuple[str, ...]
    requirements: str
    icon: str  # in volumex/resources
    download_url: str
    website_url: str


DEVELOPER_NAME = "Sihab Sahariar"
FEEDBACK_EMAIL = "sihabsahariarcse@gmail.com"

DEVELOPER_LINKS = (
    Link("Website", "https://sihabsahariar.com/", "globe"),
    Link("GitHub", "https://github.com/SihabSahariar", "github"),
    Link("LinkedIn", "https://www.linkedin.com/in/sihabsahariar/", "linkedin"),
    Link("X (Twitter)", "https://twitter.com/SihabSizan", "at-sign"),
    Link("YouTube", "https://www.youtube.com/@sihabsahariar", "youtube"),
    Link("Medium", "https://sihabsahariar.medium.com/", "feather"),
    Link("Product Hunt", "https://www.producthunt.com/@sihab_sahariar", "award"),
    Link("Email", f"mailto:{FEEDBACK_EMAIL}", "mail"),
)

# Source: https://sihabsahariar.com/Umbra/
UMBRA = FeaturedApp(
    name="Umbra",
    tagline="Look away. Your screen hides itself.",
    description="Umbra watches for your attention through your webcam. The moment you turn away, your screen is "
                "covered - and it's back the instant you look again.",
    highlights=("Calibrates to your camera", "F8 toggle from any app", "Blur, image, video or colour cover"),
    requirements="Free · open source · Windows 10 & 11 · no admin rights needed",
    icon="umbra.png",
    download_url="https://github.com/SihabSahariar/Umbra/releases/latest/download/Umbra-Setup.exe",
    website_url="https://sihabsahariar.com/Umbra/",
)

WEBSITE_URL = "https://sihabsahariar.com/VolumeX/"  # GitHub Pages (sihabsahariar.github.io/VolumeX) from docs/
MANUAL_URL = WEBSITE_URL + "manual.html"
SOURCE_URL: str | None = "https://github.com/SihabSahariar/VolumeX"

CREDITS = (
    ("VB-CABLE by VB-Audio", "The virtual audio cable boosted apps play through. Donationware - please support VB-Audio.",
     "https://vb-audio.com/Cable/"),
    ("PyQt5 · Qt", "User interface (GPL-3.0)", "https://www.riverbankcomputing.com/software/pyqt/"),
    ("pycaw · comtypes", "Windows Core Audio access (MIT)", "https://github.com/AndreMiras/pycaw"),
    ("NumPy · libsamplerate · PortAudio", "Audio engine (BSD / BSD / MIT)", "https://numpy.org/"),
    ("Feather Icons", "Line icons (MIT)", "https://feathericons.com/"),
)
