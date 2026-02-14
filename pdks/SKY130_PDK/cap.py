import math
import logging

from align.primitive.default.canvas import DefaultCanvas
from align.cell_fabric.generators import Wire, Via, Region
from align.cell_fabric.grid import UncoloredCenterLineGrid, EnclosureGrid

logger = logging.getLogger(__name__)


def _cmc_enc(pdk: dict) -> int:
    """
    Return an 'enclosure-like' value for CapMIMContact.

    - New-style PDK: uses VencA_*/VencP_* fields
    - Old-style PDK: uses Enclosure
    """
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
    SKY130 MIMCAP generator for ALIGN (robust to both legacy and updated layers.json).

    Key points:
      - Does NOT assume CapMIMContact has "Enclosure" (avoids KeyError).
      - Tries to instantiate CapMIMContact as a Via (preferred when layers.json has Stack).
      - If Via fails (older ALIGN / PDK issues), falls back to drawing CapMIMContact as a Region.
      - Removes the big M4 netType='pin' shapes (they often create isolated M4 "islands" in .errors).
    """

    def __init__(self, pdk):
        super().__init__(pdk)

        # CapMIMLayer generator (used for MINUS plate)
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

        # Use enclosure-like value from CapMIMContact (works for both old/new PDK)
        cmc_enc = _cmc_enc(self.pdk)

        # M5 strap offset (connect one plate to M5)
        self.m5_offset = (
            self.pdk["CapMIMLayer"]["Enclosure"]
            + cmc_enc
            + self.pdk["CapMIMContact"]["WidthX"] // 2
        )

        self.m5n = self.addGen(
            Wire(
                "m5n",
                "M5",
                "v",
                clg=UncoloredCenterLineGrid(
                    pitch=2 * self.pdk["Cap"]["m5Width"],
                    width=self.pdk["Cap"]["m5Width"],
                    offset=self.m5_offset,
                ),
                spg=EnclosureGrid(
                    pitch=self.pdk["M4"]["Pitch"] // 2,
                    stoppoint=cmc_enc,  # <-- was self.pdk['CapMIMContact']['Enclosure']
                    offset=0,
                    check=False,
                ),
            )
        )

        self.Cboundary = self.addGen(
            Region("Cboundary", "Cboundary", h_grid=self.m2.clg, v_grid=self.m1.clg)
        )

        # V4 between M4 and M5 (existing)
        self.v4_x = self.addGen(
            Via(
                "v4_x",
                "V4",
                h_clg=self.m4.clg,
                v_clg=self.m5n.clg,
                WidthX=self.v4.WidthX,
                WidthY=self.v4.WidthY,
                h_ext=self.v4.h_ext,
                v_ext=self.v4.v_ext,
            )
        )

        # --- Preferred: CapMIMContact as Via (requires layers.json entry with "Stack") ---
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
            # Fallback: draw-only region (keeps GDS generation working)
            logger.warning(f"CapMIMContact Via unavailable; falling back to Region. Reason: {e}")
            clg_mim = UncoloredCenterLineGrid(pitch=2, width=2)
            self.CapMIMC = self.addGen(
                Region("CapMIMC", "CapMIMContact", h_grid=clg_mim, v_grid=clg_mim)
            )

    def addCap(self, length, width):
        x_length = int(length)
        y_length = int(width)

        m1_p = self.pdk["M1"]["Pitch"]
        m2_p = self.pdk["M2"]["Pitch"]

        m4n_xwidth = x_length + 2 * self.pdk["CapMIMLayer"]["Enclosure"]
        _m4n_ywidth = y_length + 2 * self.pdk["CapMIMLayer"]["Enclosure"]

        # Keep your original plate generators (minimal change)
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
                stoppoint=self.pdk["CapMIMLayer"]["Enclosure"],
                check=False,
            ),
        )

        m4n_plate = Wire(
            "m4n_plate",
            "M4",
            "v",
            clg=UncoloredCenterLineGrid(
                pitch=m4n_xwidth - self.pdk["Cap"]["m4Width"] // 2,
                width=self.pdk["Cap"]["m4Width"],
                offset=0,
            ),
            spg=EnclosureGrid(
                pitch=self.pdk["M4"]["Pitch"],
                stoppoint=0,
                offset=-self.pdk["M4"]["Width"] // 4,
                check=False,
            ),
        )

        mimcap = Wire(
            "mim",
            "CapMIMLayer",
            "v",
            clg=UncoloredCenterLineGrid(
                pitch=2 * x_length,
                width=x_length,
                offset=x_length // 2 + self.pdk["CapMIMLayer"]["Enclosure"],
            ),
            spg=EnclosureGrid(pitch=y_length, stoppoint=0, check=False),
        )

        x_number = math.ceil(m4n_xwidth / m1_p)
        y_number_m4 = math.ceil(
            (
                y_length
                + self.pdk["CapMIMLayer"]["Enclosure"]
                + 0.5 * self.pdk["M4"]["Width"]
            )
            / self.pdk["M4"]["Pitch"]
        )
        y_number = math.ceil((y_number_m4 * self.pdk["M4"]["Pitch"]) / m2_p)

        logger.debug(f"Number of wires {x_number} {y_number}")

        # Geometry
        self.addWire(m4n, "MINUS", 0, (0, -1), (1, 1))
        self.addWire(m4n_plate, "PLUS", 1, (y_number_m4 - 2, -1), (y_number_m4, 1))
        self.addWire(mimcap, "MINUS", 0, (0, -1), (1, 1))

        # Bring MINUS to M5 and connect M4↔M5
        self.addWire(self.m5n, "MINUS", 0, (-3, 1), (1, 1))
        self.addVia(self.v4_x, "MINUS", 0, -1)

        # Connect CapMIMLayer ↔ M5 using CapMIMContact
        if self._use_mimc_via:
            # Place at track intersection (0,0). Works when CapMIMContact has Stack in layers.json.
            self.addVia(self.mimc, "MINUS", 0, 0)
        else:
            # Fallback: draw-only region (won't help connectivity, but keeps old flows alive)
            cmc = self.pdk["CapMIMContact"]
            gridx0 = (self.m5_offset - int(cmc["WidthX"]) // 2) // 2
            gridx1 = gridx0 + int(cmc["WidthX"]) // 2
            self.addRegion(self.CapMIMC, None, gridx0, 150, gridx1, 250)

        # IMPORTANT: remove big M4 "pin" shapes (often become isolated M4 islands)
        # (Do NOT add netType='pin' on M4 for internal primitives)

        # Boundary
        self.addRegion(self.boundary, "Boundary", -2, -6, x_number + 1, y_number + 3)

        logger.debug(
            f"Computed Boundary: {self.terminals[-1]} "
            f"{self.terminals[-1]['rect'][2]} {self.terminals[-1]['rect'][2] % 80}"
        )
