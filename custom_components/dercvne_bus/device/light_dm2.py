"""DM2 dimming host light device (standard Class parameter protocol).

DM2 lights use standard Class parameters:
  - Class 0: Brightness
  - Class 1: Color Temperature
  - Class 4: RGB Color

This differs from legacy DALI which uses group+1 trick for CCT.
"""

import logging
import asyncio

from .light import DALILight
from ..const import COLOR_TEMP_MIN_K, COLOR_TEMP_MAX_K
from ..protocol.encoder import DALICommandEncoder

_LOGGER = logging.getLogger(__name__)


class DALIDM2CCTLight(DALILight):
    """DM2 dual color temperature light.

    Uses DM2 standard protocol:
      - Brightness: *A,0,G,AA;*Z,0XX;  (same as DALI)
      - Color Temp: *A,1,G,AA;*Z,0XX;  (Class=1, NOT group+1)
      - Feedback CT: class_=1 on same (group, address)
    """

    @property
    def supports_color_temp(self) -> bool:
        """Return True (DM2 CCT supports color temp via Class=1)."""
        return True

    async def set_color_temp_kelvin(self, kelvin: int) -> bool:
        """Set color temperature using DM2 standard Class=1 protocol."""
        cmd = DALICommandEncoder.set_color_temp_kelvin(
            self.group,
            self.address,
            kelvin,
            use_class_param=True,  # DM2 standard: Class=1
        )
        result = await self._transport.send_command(cmd)
        if result:
            self._color_temp_k = max(COLOR_TEMP_MIN_K, min(COLOR_TEMP_MAX_K, int(kelvin)))
        return result


class DALIDM2SingleLight(DALILight):
    """DM2 single color temperature light.

    Protocol is identical to DALI single CT (Class=0 only).
    Kept as separate class for clarity and future DM2-specific features.
    """
    pass
