import math
import logging

from align.primitive.default.canvas import DefaultCanvas
from align.cell_fabric.generators import Wire, Via, Region
from align.cell_fabric.grid import UncoloredCenterLineGrid, EnclosureGrid

logger = logging.getLogger(__name__)


def _cmc_enc(pdk: dict) -> int:
    """Return an 'enclosure-like' value for CapMIMContact (new or legacy PDK)."""
    cmc = pdk["CapMIMContact"]
    if "Enclosure" in cmc:
        return int(cmc["Enclosure"])
    return int(
        max(
            cmc.get("VencA_L", 0),
            cmc.get("VencA_H", 0),
            cmc.get("VencP_L", 0),
            cmc.get("VencP_H", 0),
            0,
        )
    )


class CapGenerator(DefaultCanvas):
    """
    SKY130 MIMCAP generator for ALIGN.

    Fixes:
      - CapMIMContact does not require 'Enclosure' field (works with Venc* only).
      - Places V4 via using the SAME M4 grid used for the M4 plate (avoids KeyError -2520).
      - Avoids giant M4 netType='pin' rectangles (commonly become isolated islands).
    """

    def __init__(self, pdk):
        super().__init__(pdk)

        # CapMIMLayer (bottom plate) wire generator
        self.m3n = self.addGen(
            Wire(
                "m3n",
                "CapMIMLayer",
                "v",
                clg=UncoloredCenterLineGrid(
                    pitch=self.pdk["M3"]["Pitch"],
                    width=self.pdk["M3"]["Width"],
                ),
                spg=EnclosureGrid(
                    pitch=self.pdk["M2"]["Pitch"],
                    stoppoint=self.pdk["V2"]["VencA_H"] + self.pdk["M2"]["Width"] // 2,
                    check=False,
                ),
            )
        )

        cmc_enc = _cmc_enc(self.pdk)

        # M5 strap used to export MINUS plate
        self.m5_offset = (
            int(self.pdk["CapMIMLayer"]["Enclosure"])
            + cmc_enc
            + int(self.pdk["CapMIMContact"]["WidthX"]) // 2
        )

        self.m5n = self.addGen(
            Wire(
                "m5n",
                "M5",
                "v",
                clg=UncoloredCenterLineGrid(
                    pitch=2 * int(self.pdk["Cap"]["m5Width"]),
                    width=int(self.pdk["Cap"]["m5Width"]),
                    offset=self.m5_offset,
                ),
                spg=EnclosureGrid(
                    pitch=int(self.pdk["M4"]["Pitch"]) // 2,
                    stoppoint=cmc_enc,
                    offset=0,
                    check=False,
                ),
            )
        )

        # Boundary marker (unchanged)
        self.Cboundary = self.addGen(
            Region("Cboundary", "Cboundary", h_grid=self.m2.clg, v_grid=self.m1.clg)
        )

        # CapMIMContact: prefer Via if layers.json has Stack, else fall back to Region
        cmc = self.pdk["CapMIMContact"]
        h_ext = int(cmc.get("VencA_L", cmc.get("Enclosure", 0)))
        v_ext = int(cmc.get("VencA_H", cmc.get("Enclosure", 0)))

        self._use_mimc_via = False
        try:
            self.mimc = self.addGen(
                Via(
                    "mimc",
                    "CapMIMContact",
                    h_clg=self.m3n.clg,    # CapMIMLayer grid
                    v_clg=self.m5n.clg,    # M5 grid
                    WidthX=int(cmc["WidthX"]),
                    WidthY=int(cmc["WidthY"]),
                    h_ext=h_ext,
                    v_ext=v_ext,
                )
            )
            self._use_mimc_via = True
        except Exception as e:
            logger.warning(f"CapMIMContact Via unavailable; falling back to Region. Reason: {e}")
            clg_mim = UncoloredCenterLineGrid(pitch=2, width=2)
            self.CapMIMC = self.addGen(
                Region("CapMIMC", "CapMIMContact", h_grid=clg_mim, v_grid=clg_mim)
            )

    def addCap(self, length, width):
        x_length = int(length)
        y_length = int(width)

        m1_p = int(self.pdk["M1"]["Pitch"])
        m2_p = int(self.pdk["M2"]["Pitch"])

        cap_enc = int(self.pdk["CapMIMLayer"]["Enclosure"])
        m4_pitch = int(self.pdk["M4"]["Pitch"])
        m4_width = int(self.pdk["M4"]["Width"])

        m4n_xwidth = x_length + 2 * cap_enc

        x_number = math.ceil(m4n_xwidth / m1_p)
        y_number_m4 = math.ceil((y_length + cap_enc + 0.5 * m4_width) / m4_pitch)
        y_number = math.ceil((y_number_m4 * m4_pitch) / m2_p)

        # --- M4 MINUS plate on a custom grid (kept similar to your original) ---
        m4n = Wire(
            "m4n",
            "M4",
            "v",
            clg=UncoloredCenterLineGrid(
                pitch=2 * m4n_xwidth,
                width=m4n_xwidth,
                offset=m4n_xwidth // 2,
            ),
            spg=EnclosureGrid(
                pitch=y_length,
                stoppoint=cap_enc,
                check=False,
            ),
        )

        # --- M4 PLUS strap/plate feature (kept similar to your original) ---
        m4n_plate = Wire(
            "m4n_plate",
            "M4",
            "v",
            clg=UncoloredCenterLineGrid(
                pitch=m4n_xwidth - int(self.pdk["Cap"]["m4Width"]) // 2,
                width=int(self.pdk["Cap"]["m4Width"]),
                offset=0,
            ),
            spg=EnclosureGrid(
                pitch=m4_pitch,
                stoppoint=0,
                offset=-m4_width // 4,
                check=False,
            ),
        )

        # --- CapMIMLayer MINUS plate ---
        mimcap = Wire(
            "mim",
            "CapMIMLayer",
            "v",
            clg=UncoloredCenterLineGrid(
                pitch=2 * x_length,
                width=x_length,
                offset=x_length // 2 + cap_enc,
            ),
            spg=EnclosureGrid(pitch=y_length, stoppoint=0, check=False),
        )

        logger.debug(f"Cap wires: x_number={x_number} y_number={y_number} y_number_m4={y_number_m4}")

        # Draw the plates
        self.addWire(m4n, "MINUS", 0, (0, -1), (1, 1))
        self.addWire(m4n_plate, "PLUS", 1, (y_number_m4 - 2, -1), (y_number_m4, 1))
        self.addWire(mimcap, "MINUS", 0, (0, -1), (1, 1))

        # Draw M5 strap for MINUS
        self.addWire(self.m5n, "MINUS", 0, (-3, 1), (1, 1))

        # ------------------------------------------------------------
        # CRITICAL FIX:
        # Create V4 via using THE SAME M4 GRID as the M4 plate (m4n.clg),
        # then place it at (0,0) so it lands on an existing M4 scanline.
        # ------------------------------------------------------------
        v4_x = self.addGen(
            Via(
                "v4_x_local",
                "V4",
                h_clg=m4n.clg,        # <-- was self.m4.clg (WRONG GRID)
                v_clg=self.m5n.clg,
                WidthX=int(self.pdk["V4"]["WidthX"]),
                WidthY=int(self.pdk["V4"]["WidthY"]),
                h_ext=int(self.pdk["V4"]["VencA_L"]),
                v_ext=int(self.pdk["V4"]["VencA_H"]),
            )
        )
        self.addVia(v4_x, "MINUS", 0, 0)

        # Connect CapMIMLayer ↔ M5 using CapMIMContact
        if self._use_mimc_via:
            self.addVia(self.mimc, "MINUS", 0, 0)
        else:
            # fallback draw-only (won't help connectivity, but avoids crashes)
            cmc = self.pdk["CapMIMContact"]
            gridx0 = (self.m5_offset - int(cmc["WidthX"]) // 2) // 2
            gridx1 = gridx0 + int(cmc["WidthX"]) // 2
            self.addRegion(self.CapMIMC, None, gridx0, 150, gridx1, 250)

        # IMPORTANT: no giant M4 netType='pin' rectangles (they can become isolated islands)

        # Boundary
        self.addRegion(self.boundary, "Boundary", -2, -6, x_number + 1, y_number + 3)
