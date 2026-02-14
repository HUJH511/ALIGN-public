import math
import logging

from align.primitive.default.canvas import DefaultCanvas
from align.cell_fabric.generators import Wire, Via, Region
from align.cell_fabric.grid import UncoloredCenterLineGrid, EnclosureGrid

logger = logging.getLogger(__name__)


def _cmc_enc(pdk: dict) -> int:
    """
    Return an 'enclosure-like' value for CapMIMContact.

    New-style PDK: uses VencA_*/VencP_*
    Old-style PDK: uses Enclosure
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


def _legal_span(v: int, legal_fracts: set[int], n: int) -> int:
    """
    EnclosureGrid.value() requires the index's fractional part (mod n) to be legal.
    Pick the nearest index <= v whose mod n is in legal_fracts.
    """
    # make v integer
    x = int(v)
    # move downward until it matches legal fractional class
    while (x % n) not in legal_fracts:
        x -= 1
    return x


class CapGenerator(DefaultCanvas):
    """
    SKY130 MIMCAP generator for ALIGN.

    What this version fixes (based on your latest logs):
      - No KeyError when CapMIMContact has no "Enclosure".
      - Avoids via-enclosure DRC crash on M4 scanlines by:
          * drawing an M4 landing pad on the DEFAULT M4 grid (self.m4),
          * creating V4 via using self.m4.clg (not custom plate grids),
          * placing V4 at a known-good track intersection.
      - Avoids remove_duplicates "via does not touch metal" assertion by extending M5 strap.
      - Avoids EnclosureGrid index legality assertion by using indices with allowed mod classes.
      - Keeps CapMIMContact as a Via (preferred) if layers.json defines Stack, else falls back.

    IMPORTANT:
      This is an internal primitive. Do NOT add giant M4 netType='pin' rectangles.
    """

    def __init__(self, pdk):
        super().__init__(pdk)

        # Bottom plate (CapMIMLayer) wire generator
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

        # M5 strap generator (to bring MINUS out)
        cmc_enc = _cmc_enc(self.pdk)

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

        # CapMIMContact: use Via if possible (requires Stack in layers.json)
        cmc = self.pdk["CapMIMContact"]
        h_ext = int(cmc.get("VencA_L", cmc.get("Enclosure", 0)))
        v_ext = int(cmc.get("VencA_H", cmc.get("Enclosure", 0)))

        self._use_mimc_via = False
        try:
            self.mimc = self.addGen(
                Via(
                    "mimc",
                    "CapMIMContact",
                    h_clg=self.m3n.clg,   # CapMIMLayer grid
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

    def addCap(self, length, width):
        x_length = int(length)
        y_length = int(width)

        m1_p = int(self.pdk["M1"]["Pitch"])
        m2_p = int(self.pdk["M2"]["Pitch"])

        cap_enc = int(self.pdk["CapMIMLayer"]["Enclosure"])
        m4_pitch = int(self.pdk["M4"]["Pitch"])
        m4_width = int(self.pdk["M4"]["Width"])

        # Plate width in M4 based on cap size + enclosure
        m4n_xwidth = x_length + 2 * cap_enc

        x_number = math.ceil(m4n_xwidth / m1_p)
        y_number_m4 = math.ceil((y_length + cap_enc + 0.5 * m4_width) / m4_pitch)
        y_number = math.ceil((y_number_m4 * m4_pitch) / m2_p)

        # --- Custom M4 plate(s) (kept similar to your original) ---
        # These are for geometry/area. DO NOT use them as the "only" landing for V4.
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

        # Bottom plate (CapMIMLayer)
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

        logger.debug(f"Cap dims: x_number={x_number} y_number={y_number} y_number_m4={y_number_m4}")

        # Draw plates
        self.addWire(m4n, "MINUS", 0, (0, -1), (1, 1))
        self.addWire(m4n_plate, "PLUS", 1, (y_number_m4 - 2, -1), (y_number_m4, 1))
        self.addWire(mimcap, "MINUS", 0, (0, -1), (1, 1))

        # ------------------------------------------------------------
        # Make M5 strap long enough AND indices grid-legal
        # Your m5n.spg uses EnclosureGrid with n=4 and legalIndices {1,3}.
        # So choose spans with mod 4 in {1,3}.
        # ------------------------------------------------------------
        # pick a long span that is legal (e.g. 39: 39%4=3, -39%4=1)
        y_span = 39
        self.addWire(self.m5n, "MINUS", 0, (-3, -y_span), (1, y_span))

        # ------------------------------------------------------------
        # CRITICAL: Create M4 "landing pad" on DEFAULT M4 grid (self.m4)
        # so scanlines exist and DRC can find M4 covering metal for the V4 via.
        # ------------------------------------------------------------
        # A small pad on M4 track 0
        self.addWire(self.m4, "MINUS", 0, (-1, -1), (2, 1))

        # V4 via using DEFAULT M4 grid (self.m4.clg), not custom plate grids
        v4_x = self.addGen(
            Via(
                "v4_x_local",
                "V4",
                h_clg=self.m4.clg,      # DEFAULT M4 grid
                v_clg=self.m5n.clg,     # M5 grid
                WidthX=int(self.pdk["V4"]["WidthX"]),
                WidthY=int(self.pdk["V4"]["WidthY"]),
                h_ext=int(self.pdk["V4"]["VencA_L"]),
                v_ext=int(self.pdk["V4"]["VencA_H"]),
            )
        )
        # Place at intersection of M4 track 0 and M5 track 0
        self.addVia(v4_x, "MINUS", 0, 0)

        # Connect CapMIMLayer ↔ M5 using CapMIMContact (at 0,0)
        if self._use_mimc_via:
            self.addVia(self.mimc, "MINUS", 0, 0)
        else:
            # fallback draw-only (keeps old installs alive; may not fix connectivity)
            cmc = self.pdk["CapMIMContact"]
            gridx0 = (self.m5_offset - int(cmc["WidthX"]) // 2) // 2
            gridx1 = gridx0 + int(cmc["WidthX"]) // 2
            self.addRegion(self.CapMIMC, None, gridx0, 150, gridx1, 250)

        # IMPORTANT: do NOT create giant M4 netType='pin' rectangles here.

        # Boundary
        self.addRegion(self.boundary, "Boundary", -2, -6, x_number + 1, y_number + 3)
