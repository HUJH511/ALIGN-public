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

    Fixes included:
      - Works whether CapMIMContact has Enclosure or only Venc* fields.
      - CapMIMContact is instantiated as a Via (preferred) with fallback to Region.
      - EXTENDS M5 strap so any via you drop at (0,0) is guaranteed to land on M5 metal.
        (Fixes the assertion: via placed where no vertical metal exists.)
      - V4 (M4↔M5) via is created using the SAME M4 grid as the M4 plate generator.
    """

    def __init__(self, pdk):
        super().__init__(pdk)

        # CapMIMLayer (bottom plate) generator
        self.m3n = self.addGen(
            Wire(
                "m3n",
                "CapMIMLayer",
                "v",
                clg=UncoloredCenterLineGrid(
                    pitch=int(self.pdk["M3"]["Pitch"]),
                    width=int(self.pdk["M3"]["Width"]),
                ),
                spg=EnclosureGrid(
                    pitch=int(self.pdk["M2"]["Pitch"]),
                    stoppoint=int(self.pdk["V2"]["VencA_H"]) + int(self.pdk["M2"]["Width"]) // 2,
                    check=False,
                ),
            )
        )

        cmc_enc = _cmc_enc(self.pdk)

        # M5 strap grid offset
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

        self.Cboundary = self.addGen(
            Region("Cboundary", "Cboundary", h_grid=self.m2.clg, v_grid=self.m1.clg)
        )

        # CapMIMContact via (preferred if layers.json has Stack)
        cmc = self.pdk["CapMIMContact"]
        h_ext = int(cmc.get("VencA_L", cmc.get("Enclosure", 0)))
        v_ext = int(cmc.get("VencA_H", cmc.get("Enclosure", 0)))

        self._use_mimc_via = False
        try:
            self.mimc = self.addGen(
                Via(
                    "mimc",
                    "CapMIMContact",
                    h_clg=self.m3n.clg,   # CapMIMLayer
                    v_clg=self.m5n.clg,   # M5
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

        # M4 MINUS plate (custom grid as you had)
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

        # M4 PLUS feature (custom grid as you had)
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

        # CapMIMLayer bottom plate
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

        # Draw plates
        self.addWire(m4n, "MINUS", 0, (0, -1), (1, 1))
        self.addWire(m4n_plate, "PLUS", 1, (y_number_m4 - 2, -1), (y_number_m4, 1))
        self.addWire(mimcap, "MINUS", 0, (0, -1), (1, 1))

        # ============================================================
        # IMPORTANT FIX FOR YOUR ASSERTION:
        # Extend the M5 strap a LOT in Y so vias always land on M5 metal.
        # Previously you had (-3,1)->(1,1) which is too short and caused
        # "via above metal" (metal ended at y=830 while via was at y=2550).
        # ============================================================
        self.addWire(self.m5n, "MINUS", 0, (-3, -39), (1, 39))

        # Create V4 via using SAME M4 grid as m4n, then place at (0,0)
        v4_x = self.addGen(
            Via(
                "v4_x_local",
                "V4",
                h_clg=m4n.clg,          # match the M4 plate grid
                v_clg=self.m5n.clg,     # M5 grid
                WidthX=int(self.pdk["V4"]["WidthX"]),
                WidthY=int(self.pdk["V4"]["WidthY"]),
                h_ext=int(self.pdk["V4"]["VencA_L"]),
                v_ext=int(self.pdk["V4"]["VencA_H"]),
            )
        )
        self.addVia(v4_x, "MINUS", 0, 0)

        # Connect CapMIMLayer ↔ M5 using CapMIMContact at (0,0)
        if self._use_mimc_via:
            self.addVia(self.mimc, "MINUS", 0, 0)
        else:
            cmc = self.pdk["CapMIMContact"]
            gridx0 = (self.m5_offset - int(cmc["WidthX"]) // 2) // 2
            gridx1 = gridx0 + int(cmc["WidthX"]) // 2
            self.addRegion(self.CapMIMC, None, gridx0, 150, gridx1, 250)

        # No giant M4 netType='pin' shapes (avoid isolated islands)

        # Boundary
        self.addRegion(self.boundary, "Boundary", -2, -6, x_number + 1, y_number + 3)
