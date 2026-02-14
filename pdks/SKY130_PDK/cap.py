import math
import logging

from align.primitive.default.canvas import DefaultCanvas
from align.cell_fabric.generators import Wire, Via, Region
from align.cell_fabric.grid import UncoloredCenterLineGrid, EnclosureGrid

logger = logging.getLogger(__name__)


class CapGenerator(DefaultCanvas):
    """
    SKY130 MIMCAP generator for ALIGN (revised).

    What this revision changes (to fix your OPENs):
      1) Removes the large M4 "pin-purpose" shapes created by netType='pin' on M4.
         Those pin-purpose shapes are what show up as the isolated M4 islands in your .errors.
         (They are on a different GDS datatype than router-drawn M4, so they don't connect.)
      2) Keeps real conductive geometry on M4/M5 + vias so the capacitor terminals are routable.
      3) Uses a REAL via generator for CapMIMContact (not a Region), but also keeps a safe fallback
         if your PDK doesn't fully support CapMIMContact as a via.
      4) Fixes M4 direction usage to match SKY130 abstraction (M4 is horizontal in layers.json).

    Notes:
      - This cell is meant to be used as an INTERNAL primitive. For internal primitives, you do NOT
        need large pin-datatype shapes; the router connects to the conductive geometry.
      - If you truly need explicit "pin" markers for export, add *small* pins on the SAME datatype
        as Draw (done via normal wires), or edit layers.json to merge pin/draw datatype.
    """

    def __init__(self, pdk):
        super().__init__(pdk)

        # --- Cap bottom plate on CapMIMLayer (kept as in your original) ---
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

        # --- M5 strap used as one terminal (kept as in your original) ---
        self.m5_offset = (
            self.pdk["CapMIMLayer"]["Enclosure"]
            + self.pdk["CapMIMContact"]["Enclosure"]
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
                    stoppoint=self.pdk["CapMIMContact"]["Enclosure"],
                    offset=0,
                    check=False,
                ),
            )
        )

        # Boundary marker (same as your file)
        self.Cboundary = self.addGen(
            Region("Cboundary", "Cboundary", h_grid=self.m2.clg, v_grid=self.m1.clg)
        )

        # --- Via between M4 and M5 (same as your file) ---
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

        # --- CapMIMContact: TRY to model as a via (preferred) ---
        # If your layers.json defines Stack for CapMIMContact, this becomes a true connectivity element.
        cmc = self.pdk["CapMIMContact"]
        h_ext = cmc.get("VencA_L", cmc.get("Enclosure", 0))
        v_ext = cmc.get("VencA_H", cmc.get("Enclosure", 0))

        try:
            self.mimc = self.addGen(
                Via(
                    "mimc",
                    "CapMIMContact",
                    h_clg=self.m3n.clg,     # CapMIMLayer grid
                    v_clg=self.m5n.clg,     # M5 grid
                    WidthX=cmc["WidthX"],
                    WidthY=cmc["WidthY"],
                    h_ext=h_ext,
                    v_ext=v_ext,
                )
            )
            self._use_mimc_via = True
        except Exception as e:
            # Fallback to your original "draw-only" region (won't help connectivity),
            # but keeps GDS generation from crashing in older installs.
            logger.warning(f"CapMIMContact Via unavailable, falling back to Region: {e}")
            clg_mim = UncoloredCenterLineGrid(pitch=2, width=2)
            self.CapMIMC = self.addGen(Region("CapMIMC", "CapMIMContact", h_grid=clg_mim, v_grid=clg_mim))
            self._use_mimc_via = False

    def addCap(self, length, width):
        x_length = int(length)
        y_length = int(width)

        m1_p = self.pdk["M1"]["Pitch"]
        m2_p = self.pdk["M2"]["Pitch"]

        m4n_xwidth = x_length + 2 * self.pdk["CapMIMLayer"]["Enclosure"]
        _m4n_ywidth = y_length + 2 * self.pdk["CapMIMLayer"]["Enclosure"]

        # IMPORTANT FIX: M4 is horizontal in SKY130 routing abstraction.
        # Use 'h' here (not 'v').
        m4n = Wire(
            "m4n",
            "M4",
            "h",
            clg=UncoloredCenterLineGrid(
                pitch=2 * self.pdk["M4"]["Pitch"],     # use M4 pitch for M4 tracks
                width=m4n_xwidth,                      # wide bar = plate
                offset=m4n_xwidth // 2,
            ),
            spg=EnclosureGrid(
                pitch=self.pdk["M3"]["Pitch"],
                stoppoint=self.pdk["CapMIMLayer"]["Enclosure"],
                check=False,
            ),
        )

        m4n_plate = Wire(
            "m4n_plate",
            "M4",
            "h",
            clg=UncoloredCenterLineGrid(
                pitch=self.pdk["M4"]["Pitch"],
                width=self.pdk["Cap"]["m4Width"],
                offset=0,
            ),
            spg=EnclosureGrid(
                pitch=self.pdk["M4"]["Pitch"],
                stoppoint=0,
                offset=0,
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

        # --- Draw the capacitor geometry ---
        # M4 plate for MINUS (wide bar)
        self.addWire(m4n, "MINUS", 0, (0, -1), (1, 1))

        # Narrow M4 bar for PLUS (acts like the other plate connection)
        self.addWire(m4n_plate, "PLUS", 1, (y_number_m4 - 2, -1), (y_number_m4, 1))

        # Bottom plate (CapMIMLayer)
        self.addWire(mimcap, "MINUS", 0, (0, -1), (1, 1))

        # M5 strap for MINUS
        self.addWire(self.m5n, "MINUS", 0, (-3, 1), (1, 1))

        # Connect MINUS M4 ↔ M5 (V4)
        self.addVia(self.v4_x, "MINUS", 0, -1)

        # Connect CapMIMLayer ↔ M5 (CapMIMContact), if available as a Via
        if self._use_mimc_via:
            # drop it at track intersection (0,0) between CapMIMLayer and M5
            self.addVia(self.mimc, "MINUS", 0, 0)
        else:
            # fallback: keep your original drawn contact region (geometry only)
            gridx0 = (self.m5_offset - self.pdk["CapMIMContact"]["WidthX"] // 2) // 2
            gridx1 = gridx0 + self.pdk["CapMIMContact"]["WidthX"] // 2
            self.addRegion(self.CapMIMC, None, gridx0, 150, gridx1, 250)

        # ------------------------------------------------------------
        # CRITICAL FIX FOR YOUR OPENs:
        #
        # REMOVE these two lines from your original code:
        #   self.addWire(self.m4, 'PLUS',  ..., netType='pin')
        #   self.addWire(self.m4, 'MINUS', ..., netType='pin')
        #
        # Those large M4 "pin datatype" rectangles become isolated islands
        # (exactly the M4 rectangles shown in your .errors).
        #
        # The router will still connect to the conductive M4/M5 geometry above.
        # ------------------------------------------------------------

        # Boundary (unchanged)
        self.addRegion(self.boundary, "Boundary", -2, -6, x_number + 1, y_number + 3)

        logger.debug(
            f"Computed Boundary: {self.terminals[-1]} "
            f"{self.terminals[-1]['rect'][2]} {self.terminals[-1]['rect'][2] % 80}"
        )
