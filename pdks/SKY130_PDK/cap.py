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

    This version adds SMALL, OVERLAPPING pin access for router:
      - PLUS pin on DEFAULT M4 (netType='pin'), overlapping an M4 landing pad
      - MINUS pin on M5 strap (netType='pin'), overlapping M5 draw metal

    It also keeps:
      - CapMIMContact via (Stack: CapMIMLayer <-> M5)
      - V4 via using DEFAULT M4 grid (self.m4.clg)
      - Long M5 strap using legal indices (avoid EnclosureGrid assertion)
    """

    def __init__(self, pdk):
        super().__init__(pdk)

        # CapMIMLayer (bottom plate) generator
        self.mimL = self.addGen(
            Wire(
                "mimL",
                "CapMIMLayer",
                "v",
                clg=UncoloredCenterLineGrid(
                    pitch=int(self.pdk["CapMIMLayer"]["Pitch"]),
                    width=int(self.pdk["CapMIMLayer"]["Width"]),
                ),
                spg=EnclosureGrid(
                    pitch=int(self.pdk["M2"]["Pitch"]),
                    stoppoint=0,
                    check=False,
                ),
            )
        )

        cmc_enc = _cmc_enc(self.pdk)

        # M5 strap generator (MINUS export)
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

        # Boundary marker
        self.Cboundary = self.addGen(
            Region("Cboundary", "Cboundary", h_grid=self.m2.clg, v_grid=self.m1.clg)
        )

        # CapMIMContact via (preferred; requires Stack in layers.json)
        cmc = self.pdk["CapMIMContact"]
        h_ext = int(cmc.get("VencA_L", cmc.get("Enclosure", 0)))
        v_ext = int(cmc.get("VencA_H", cmc.get("Enclosure", 0)))

        self._use_mimc_via = False
        try:
            self.mimc = self.addGen(
                Via(
                    "mimc",
                    "CapMIMContact",
                    h_clg=self.mimL.clg,  # CapMIMLayer grid
                    v_clg=self.m5n.clg,   # M5 grid
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

        # V4 via generator: use DEFAULT M4 grid (self.m4.clg)
        self.v4_x = self.addGen(
            Via(
                "v4_x",
                "V4",
                h_clg=self.m4.clg,     # DEFAULT M4 grid (important!)
                v_clg=self.m5n.clg,
                WidthX=int(self.pdk["V4"]["WidthX"]),
                WidthY=int(self.pdk["V4"]["WidthY"]),
                h_ext=int(self.pdk["V4"]["VencA_L"]),
                v_ext=int(self.pdk["V4"]["VencA_H"]),
            )
        )

    def addCap(self, length, width):
        x_length = int(length)
        y_length = int(width)

        m1_p = int(self.pdk["M1"]["Pitch"])
        m2_p = int(self.pdk["M2"]["Pitch"])
        cap_enc = int(self.pdk["CapMIMLayer"]["Enclosure"])
        m4_pitch = int(self.pdk["M4"]["Pitch"])
        m4_width = int(self.pdk["M4"]["Width"])

        # Use these only for boundary sizing
        plate_x = x_length + 2 * cap_enc
        x_number = math.ceil(plate_x / m1_p)
        y_number_m4 = math.ceil((y_length + cap_enc + 0.5 * m4_width) / m4_pitch)
        y_number = math.ceil((y_number_m4 * m4_pitch) / m2_p)

        # ----------------------------
        # 1) Create REAL routable pins
        # ----------------------------

        # M4 landing pad for PLUS on DEFAULT M4 grid (draw metal)
        # Use track +1 for PLUS, track 0 reserved for MINUS landing to M5 (below)
        self.addWire(self.m4, "PLUS", 1, (-1, -1), (3, 1))
        # Mark a small portion as a pin (overlaps the draw metal above)
        self.addWire(self.m4, "PLUS", 1, (0, -1), (1, 1), netType="pin")

        # MINUS M4 landing pad on DEFAULT M4 grid for V4 to touch
        self.addWire(self.m4, "MINUS", 0, (-1, -1), (3, 1))

        # Long M5 strap for MINUS (must use legal EnclosureGrid indices: {1,3} mod 4)
        # 39 works: 39%4=3, -39%4=1
        y_span = 39
        self.addWire(self.m5n, "MINUS", 0, (-3, -y_span), (2, y_span))
        # Small MINUS pin on M5 strap (overlaps draw metal)
        self.addWire(self.m5n, "MINUS", 0, (-1, -1), (1, 1), netType="pin")

        # ----------------------------
        # 2) Draw the capacitor plates
        # ----------------------------

        # CapMIMLayer bottom plate (MINUS)
        self.addWire(self.mimL, "MINUS", 0, (0, -1), (1, 1))

        # If you want extra “area” metal for the PLUS plate, keep it on M4 draw metal.
        # (We already drew a PLUS pad on M4; extend it a bit for area.)
        # This stays on DEFAULT M4 so router + DRC are happy.
        self.addWire(self.m4, "PLUS", 1, (-1, -y_number_m4), (3, y_number_m4))

        # ----------------------------
        # 3) Stitch connections with vias
        # ----------------------------

        # Connect MINUS: M4 <-> M5 (V4) at (M4 track 0, M5 track 0)
        self.addVia(self.v4_x, "MINUS", 0, 0)

        # Connect MINUS: CapMIMLayer <-> M5 using CapMIMContact at (0,0)
        if self._use_mimc_via:
            self.addVia(self.mimc, "MINUS", 0, 0)
        else:
            # draw-only fallback (won't help LVS much, but avoids breaking older installs)
            cmc = self.pdk["CapMIMContact"]
            gridx0 = (self.m5_offset - int(cmc["WidthX"]) // 2) // 2
            gridx1 = gridx0 + int(cmc["WidthX"]) // 2
            self.addRegion(self.CapMIMC, None, gridx0, 150, gridx1, 250)

        # ----------------------------
        # 4) Boundary
        # ----------------------------
        self.addRegion(self.boundary, "Boundary", -2, -6, x_number + 3, y_number + 3)
