"""NDI (Network Device Interface) output til Setlist Manager.

NDI lader os streame video over LAN til OBS, vMix, ATEM eller andre
broadcast-værktøjer. Brugeren får så Setlist Manager-vinduet (eller blot
sang-noter) som en "kamera-source" i deres broadcast-software.

Krav for at det virker:
-----------------------
1. NDI Runtime installeret på PC'en (gratis fra https://ndi.video/tools/)
   - På Windows: "NDI Tools" eller "NDI Runtime" MSI'en
   - På macOS: "NDI Tools" .pkg
2. Python binding: ``pip install ndi-python``

Hvis NOGEN af disse mangler, fungerer Setlist Manager STADIG fuldt ud —
NDI-features er bare gråtonet/skjult med en venlig besked om hvad
brugeren skal installere.

Designprincip:
--------------
ALT NDI-kode er bag try/except så et manglende SDK aldrig kan crashe
hovedappen. ``is_available()`` returnerer True kun hvis BÅDE Python-modulet
OG den binære NDI Runtime kan loades.

Eksempel:
    >>> from ndi_output import is_available, NDISender
    >>> if is_available():
    ...     sender = NDISender(name="Setlist Manager")
    ...     sender.send_pil_image(my_image)
    ...     sender.close()
"""

from __future__ import annotations

import sys
from typing import Optional

# --- Safe import af NDI binding ------------------------------------------
# Vi gemmer både modulet og en evt. import-fejl så UI'et kan vise en
# venlig fejlbesked til brugeren.
NDI_IMPORT_ERROR: Optional[str] = None
_ndi = None
_np = None

try:
    import NDIlib as _ndi  # type: ignore[import-not-found]
    try:
        import numpy as _np  # type: ignore[import-not-found]
    except ImportError:
        _ndi = None
        NDI_IMPORT_ERROR = (
            "numpy er ikke installeret (kræves til NDI). "
            "Installer med: pip install numpy"
        )
except ImportError as e:
    NDI_IMPORT_ERROR = (
        f"NDI Python-modulet kunne ikke loades: {e}\n\n"
        f"Hvis du har installeret Setlist Manager via vores installer "
        f"burde det 'bare virke' — kontakt support."
    )
except OSError as e:
    # Manglende libndi.dll på Windows / libndi.dylib på macOS
    NDI_IMPORT_ERROR = (
        f"NDI Runtime kunne ikke loades ({e}).\n\n"
        f"Hvis du har installeret Setlist Manager via vores installer "
        f"burde dette ikke ske — prøv at geninstallere appen.\n\n"
        f"Som workaround: download NDI Tools fra https://ndi.video/tools/"
    )
except Exception as e:  # noqa: BLE001
    # Ukendt fejl — typisk pga manglende C++ runtime eller lignende
    NDI_IMPORT_ERROR = (
        f"Uventet fejl ved load af NDI: {type(e).__name__}: {e}\n\n"
        f"Prøv at geninstallere Setlist Manager. Hvis fejlen fortsætter, "
        f"installer NDI Tools fra https://ndi.video/tools/"
    )


def is_available() -> bool:
    """Returnér True hvis NDI faktisk kan bruges (modul + runtime + numpy)."""
    return _ndi is not None and _np is not None


def get_install_help() -> str:
    """Returnér en hjælpetekst der forklarer brugeren hvordan NDI installeres."""
    if is_available():
        return "NDI er klar til brug."

    if sys.platform.startswith("win"):
        platform_help = (
            "På Windows:\n"
            "  1. Gå til https://ndi.video/tools/\n"
            "  2. Download 'NDI Tools' (gratis)\n"
            "  3. Kør installeren — sæt flueben i 'NDI Runtime'\n"
            "  4. Genstart Setlist Manager"
        )
    elif sys.platform == "darwin":
        platform_help = (
            "På macOS:\n"
            "  1. Gå til https://ndi.video/tools/\n"
            "  2. Download 'NDI Tools for Mac' (gratis)\n"
            "  3. Kør installeren\n"
            "  4. Genstart Setlist Manager"
        )
    else:
        platform_help = (
            "På Linux:\n"
            "  1. Gå til https://ndi.video/sdk/\n"
            "  2. Download NDI SDK for Linux\n"
            "  3. Følg installations-instruktionerne\n"
            "  4. Genstart Setlist Manager"
        )

    return (
        f"NDI er ikke tilgængeligt på dette system.\n\n"
        f"Detalje: {NDI_IMPORT_ERROR}\n\n"
        f"{platform_help}\n\n"
        f"NDI er en gratis broadcast-standard fra NewTek/Vizrt — det er\n"
        f"sikkert at installere og bruges af OBS, vMix, ATEM mv."
    )


# ===========================================================================
#  NDISender — sender video-frames over NDI
# ===========================================================================
class NDIError(RuntimeError):
    """Generisk NDI-fejl (kunne ikke starte sender, send-fejl mv.)."""


class NDISender:
    """Wrapper omkring NDI send-API'en der sender PIL-billeder som video.

    Lifecycle:
        sender = NDISender(name="Setlist Manager")  # Initialiserer NDI lib
        sender.send_pil_image(pil_image)            # Send hver frame
        sender.close()                              # Ryd op

    Tråd-sikkerhed: NDI-lib'et er ikke tråd-sikkert — alle metoder skal
    kaldes fra samme tråd.
    """

    def __init__(self, name: str = "Setlist Manager") -> None:
        if not is_available():
            raise NDIError(get_install_help())

        # NDI initialize() returnerer False hvis SDK ikke kan starte
        # (typisk pga manglende DLL/dylib)
        if not _ndi.initialize():  # type: ignore[union-attr]
            raise NDIError(
                "NDI SDK kunne ikke initialiseres. "
                "Tjek at NDI Runtime er installeret korrekt."
            )

        try:
            send_settings = _ndi.SendCreate()  # type: ignore[union-attr]
            send_settings.ndi_name = name
            self._send = _ndi.send_create(send_settings)  # type: ignore[union-attr]
            if self._send is None:
                raise NDIError("send_create returnerede None — NDI-fejl.")
        except Exception:
            # Hvis send_create fejler skal vi destroy initialize'en
            try:
                _ndi.destroy()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass
            raise

        self._name = name
        self._closed = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def closed(self) -> bool:
        return self._closed

    def send_pil_image(self, pil_image, fps: float = 30.0) -> None:
        """Send et PIL Image som NDI video-frame.

        Konverterer billedet til BGRA og pakker det som NDI video-frame.
        ``fps`` styrer timing-metadata (NDI receivers viser kun en frame
        ved den hastighed).
        """
        if self._closed:
            raise NDIError("Senderen er lukket.")
        if not is_available():
            return  # Lib forsvundet (skulle ikke kunne ske)

        # Sørg for RGBA (NDI vil have 4 kanaler)
        if pil_image.mode != "RGBA":
            pil_image = pil_image.convert("RGBA")

        arr = _np.array(pil_image, dtype=_np.uint8)  # type: ignore[union-attr]
        # PIL er RGBA → NDI vil have BGRA: byt kanal 0 og 2
        arr = arr[..., [2, 1, 0, 3]]
        # NDI kræver contiguous memory layout
        arr = _np.ascontiguousarray(arr)  # type: ignore[union-attr]

        h, w = arr.shape[:2]

        video_frame = _ndi.VideoFrameV2()  # type: ignore[union-attr]
        video_frame.data = arr
        video_frame.FourCC = _ndi.FOURCC_VIDEO_TYPE_BGRA  # type: ignore[union-attr]
        video_frame.xres = w
        video_frame.yres = h
        # Frame rate som ratio (NDI bruger num/den)
        # 30fps = 30000/1001 (ish) — vi simplificerer til round numbers
        if fps >= 60:
            video_frame.frame_rate_N = 60
        elif fps >= 30:
            video_frame.frame_rate_N = 30
        else:
            video_frame.frame_rate_N = int(fps)
        video_frame.frame_rate_D = 1

        _ndi.send_send_video_v2(self._send, video_frame)  # type: ignore[union-attr]

    def close(self) -> None:
        """Luk senderen + ryd NDI SDK op."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._send is not None and _ndi is not None:
                _ndi.send_destroy(self._send)
            self._send = None
        except Exception:  # noqa: BLE001
            pass
        try:
            if _ndi is not None:
                _ndi.destroy()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "NDISender":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass
