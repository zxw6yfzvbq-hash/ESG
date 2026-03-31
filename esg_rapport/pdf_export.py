from __future__ import annotations

import argparse
from pathlib import Path
import pdfkit


def generate_fonts_stub() -> None:
    print("Font-forberedelse gennemført (stub). Brug systemfonts i wkhtmltopdf.")


def html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    options = {
        "encoding": "UTF-8",
        "quiet": "",
        "page-size": "A4",
        "margin-top": "12mm",
        "margin-bottom": "12mm",
        "margin-left": "12mm",
        "margin-right": "12mm",
    }
    pdfkit.from_file(str(html_path), str(pdf_path), options=options)


def main() -> None:
    parser = argparse.ArgumentParser(description="PDF eksport-værktøj")
    parser.add_argument("--generate-fonts", action="store_true", help="Kør font-setup")
    parser.add_argument("--html", type=Path, help="Input HTML")
    parser.add_argument("--pdf", type=Path, help="Output PDF")
    args = parser.parse_args()

    if args.generate_fonts:
        generate_fonts_stub()
        return

    if not args.html or not args.pdf:
        raise SystemExit("Angiv både --html og --pdf")

    html_to_pdf(args.html, args.pdf)
    print(f"PDF genereret: {args.pdf}")


if __name__ == "__main__":
    main()
