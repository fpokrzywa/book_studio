"""Amazon KDP print and eBook specifications used by preflight and the cover calculator.

Every number below was read from the official KDP help pages listed in SOURCES on CHECKED_ON. KDP can
change them at any time: the rule-set version is shown in the UI and stored in every preflight report,
and the publish package tells the author to compare against the live pages and KDP's own cover
calculator before uploading. Nothing here promises that KDP will accept a file.

Where KDP does not publish a number (the exact barcode position on the back cover, hardcover wraps),
PBS does not invent one: the gap is reported as "check manually".
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

RULESET = "kdp-paperback-2026-11-22"
CHECKED_ON = "2026-11-22"
SOURCES: dict[str, str] = {
    "trim_bleed_margins": "https://kdp.amazon.com/en_US/help/topic/GVBQ3CMEQW3W2VL6",
    "print_manuscript": "https://kdp.amazon.com/en_US/help/topic/G202145060",
    "print_cover_overview": "https://kdp.amazon.com/en_US/help/topic/G202187850",
    "paperback_cover": "https://kdp.amazon.com/en_US/help/topic/G201953020",
    "barcodes": "https://kdp.amazon.com/en_US/help/topic/G5HDYGP4BXLX4RUW",
    "kindle_previewer": "https://kdp.amazon.com/en_US/help/topic/G202131170",
    "ebook_cover": "https://kdp.amazon.com/en_US/help/topic/G200645690",
    "content_guidelines_ai": "https://kdp.amazon.com/en_US/help/topic/G200672390",
    "keywords": "https://kdp.amazon.com/en_US/help/topic/G201298500",
    "metadata_guidelines": "https://kdp.amazon.com/en_US/help/topic/G201097560",
    "cover_calculator": "https://kdp.amazon.com/cover-calculator",
}

INK_PAPER = ("bw_white", "bw_cream", "bw_groundwood", "standard_color_white", "premium_color_white")
INK_PAPER_LABELS = {
    "bw_white": "Black ink, white paper",
    "bw_cream": "Black ink, cream paper",
    "bw_groundwood": "Black ink, groundwood paper",
    "standard_color_white": "Standard color ink, white paper",
    "premium_color_white": "Premium color ink, white paper",
}

# Paperback trim sizes (width, height in inches) -> page-count range per ink/paper (None = not offered).
_STD: dict[str, tuple[int, int] | None] = {
    "bw_white": (24, 828),
    "bw_cream": (24, 776),
    "bw_groundwood": (24, 812),
    "standard_color_white": (72, 600),
    "premium_color_white": (24, 828),
}
_W825: dict[str, tuple[int, int] | None] = {
    "bw_white": (24, 800),
    "bw_cream": (24, 750),
    "bw_groundwood": (24, 784),
    "standard_color_white": (72, 600),
    "premium_color_white": (24, 800),
}
_W85: dict[str, tuple[int, int] | None] = {
    "bw_white": (24, 590),
    "bw_cream": (24, 550),
    "bw_groundwood": (24, 578),
    "standard_color_white": (72, 600),
    "premium_color_white": (24, 590),
}
_A4: dict[str, tuple[int, int] | None] = {
    "bw_white": (24, 780),
    "bw_cream": (24, 730),
    "bw_groundwood": (24, 764),
    "standard_color_white": None,
    "premium_color_white": (24, 590),
}
TRIM_SIZES: dict[str, tuple[Decimal, Decimal, dict[str, tuple[int, int] | None]]] = {
    "5x8": (Decimal("5"), Decimal("8"), _STD),
    "5.06x7.81": (Decimal("5.06"), Decimal("7.81"), _STD),
    "5.25x8": (Decimal("5.25"), Decimal("8"), _STD),
    "5.5x8.5": (Decimal("5.5"), Decimal("8.5"), _STD),
    "6x9": (Decimal("6"), Decimal("9"), _STD),
    "6.14x9.21": (Decimal("6.14"), Decimal("9.21"), _STD),
    "6.69x9.61": (Decimal("6.69"), Decimal("9.61"), _STD),
    "7x10": (Decimal("7"), Decimal("10"), _STD),
    "7.44x9.69": (Decimal("7.44"), Decimal("9.69"), _STD),
    "7.5x9.25": (Decimal("7.5"), Decimal("9.25"), _STD),
    "8x10": (Decimal("8"), Decimal("10"), _STD),
    "8.25x6": (Decimal("8.25"), Decimal("6"), _W825),
    "8.25x8.25": (Decimal("8.25"), Decimal("8.25"), _W825),
    "8.5x8.5": (Decimal("8.5"), Decimal("8.5"), _W85),
    "8.5x11": (Decimal("8.5"), Decimal("11"), _W85),
    "8.27x11.69": (Decimal("8.27"), Decimal("11.69"), _A4),
}

BLEED = Decimal("0.125")  # top, bottom and outside edges (interior); all edges of a cover
# Inside (gutter) margin by page count; outside/top/bottom minimum without and with bleed.
GUTTER = [(24, 150, Decimal("0.375")), (151, 300, Decimal("0.5")), (301, 500, Decimal("0.625")),
          (501, 700, Decimal("0.75")), (701, 828, Decimal("0.875"))]  # fmt: skip
OUTSIDE_MIN = Decimal("0.25")
OUTSIDE_MIN_BLEED = Decimal("0.375")
MIN_IMAGE_DPI = 300
MIN_TEXT_PT = 7
MAX_FILE_MB = 650
MAX_BLANK_START_MIDDLE = 4
MAX_BLANK_END = 10

# Cover: spine width per page (inches) by ink/paper. Groundwood is not listed on the cover page.
SPINE_PER_PAGE: dict[str, Decimal | None] = {
    "bw_white": Decimal("0.002252"),
    "bw_cream": Decimal("0.0025"),
    "standard_color_white": Decimal("0.002252"),
    "premium_color_white": Decimal("0.002347"),
    "bw_groundwood": None,
}
SPINE_TEXT_MIN_PAGES = 79  # Cover Creator/Cover Studio say 80; the manual (PDF) route says 79
SPINE_TEXT_MARGIN = Decimal("0.0625")  # from each spine edge; also the fold variance
COVER_TEXT_SAFE = Decimal("0.125")  # front/back text at least this far inside the trim
BARCODE_SUGGESTED = (Decimal("2"), Decimal("1.2"))  # width, height (your own barcode, suggested size)
BARCODE_MIN = (Decimal("1.4"), Decimal("0.8"))
BARCODE_EDGE = Decimal("0.25")  # at least this far from the spine and the trim
COVER_MAX_FILE_MB = 650
COVER_RECOMMENDED_MB = 40

# eBook cover (front only).
EBOOK_COVER_IDEAL = (1600, 2560)  # width, height in pixels
EBOOK_COVER_MIN = (625, 1000)
EBOOK_COVER_MAX_SIDE = 10_000
EBOOK_COVER_MAX_MB = 50

# Metadata.
KEYWORD_SLOTS = 7
CATEGORY_MAX = 3
TITLE_SUBTITLE_MAX = 199  # "fewer than 200 characters" together
METADATA_FORBIDDEN = (
    "bestselling",
    "bestseller",
    "best seller",
    "free",
    "kdp select",
    "kindle+",
    "on sale",
    "new release",
)

AI_DEFINITIONS = {
    "ai_generated": "Text, images or translations created by an AI-based tool count as AI-generated, even if you "
    "edited them substantially afterwards. KDP requires you to disclose AI-generated content.",
    "ai_assisted": "Content you created yourself and only edited, refined, error-checked or brainstormed with AI "
    "tools counts as AI-assisted. KDP does not require you to disclose AI-assisted content.",
}

NOT_PUBLISHED = [
    "The exact position of KDP's barcode area on the back cover (PBS reserves the suggested 2 × 1.2 inch area in the "
    "lower corner of the back cover next to the spine; compare with KDP's cover template).",
    "Hardcover cover wraps and hinges (PBS builds paperback covers only).",
    "A per-keyword character limit.",
]


def q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def gutter_for(pages: int) -> Decimal | None:
    for lo, hi, g in GUTTER:
        if lo <= pages <= hi:
            return g
    return None


def page_range(trim: str, ink_paper: str) -> tuple[int, int] | None:
    t = TRIM_SIZES.get(trim)
    return t[2].get(ink_paper) if t else None


@dataclass(frozen=True)
class CoverSpec:
    trim: str
    ink_paper: str
    page_count: int
    trim_w: Decimal
    trim_h: Decimal
    spine: Decimal
    width: Decimal
    height: Decimal
    bleed: Decimal
    spine_text_allowed: bool
    ruleset: str = RULESET

    def as_dict(self) -> dict[str, object]:
        return {
            "trim": self.trim,
            "ink_paper": self.ink_paper,
            "page_count": self.page_count,
            "trim_width_in": str(self.trim_w),
            "trim_height_in": str(self.trim_h),
            "spine_width_in": str(self.spine),
            "cover_width_in": str(self.width),
            "cover_height_in": str(self.height),
            "bleed_in": str(self.bleed),
            "spine_text_allowed": self.spine_text_allowed,
            "formula": "width = bleed + back + spine + front + bleed; height = bleed + trim height + bleed; "
            "spine = pages × per-page thickness",
            "ruleset": self.ruleset,
        }


def cover_spec(trim: str, ink_paper: str, page_count: int) -> CoverSpec:
    if trim not in TRIM_SIZES:
        raise ValueError(f"Unknown trim size {trim}")
    per = SPINE_PER_PAGE.get(ink_paper)
    if per is None:
        raise ValueError("KDP does not publish a spine thickness for this paper; choose another paper.")
    w, h, _ = TRIM_SIZES[trim]
    spine = q(per * page_count)
    return CoverSpec(
        trim=trim,
        ink_paper=ink_paper,
        page_count=page_count,
        trim_w=w,
        trim_h=h,
        spine=spine,
        width=q(BLEED + w + spine + w + BLEED),
        height=q(BLEED + h + BLEED),
        bleed=BLEED,
        spine_text_allowed=page_count >= SPINE_TEXT_MIN_PAGES,
    )
