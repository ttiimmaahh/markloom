# Conversion quality — what to expect

Markloom is a thin web app around Microsoft's
[MarkItDown](https://github.com/microsoft/markitdown). Conversion quality is
therefore MarkItDown's quality. This page sets realistic expectations so you can
predict results before you drop a file.

## The one rule that explains everything

**MarkItDown converts _structure_, not _pixels_.** How good the Markdown is
depends entirely on how much machine-readable structure the source format
carries:

- Formats that store **semantic structure** (this is a heading, this is a table
  cell, this is a list) convert **well** — MarkItDown maps that structure
  directly to Markdown.
- Formats that store only **visual layout** (put this text at this position)
  convert **approximately** — there's little structure to recover, so the output
  is flatter than the original looked.

> **Best tip:** convert the **earliest-format source** you have. A report exported
> to PDF converts far worse than the DOCX it was generated from. If you have the
> original Office/HTML file, use that instead of its PDF.

## What to expect by format

| Format | Expect | Notes |
|---|---|---|
| **DOCX** (Word) | Excellent | Headings, lists, tables, links, bold/italic preserved |
| **PPTX** (PowerPoint) | Good | Slide text, titles, tables; speaker notes; slide order kept |
| **XLSX / XLS** (Excel) | Good | Sheets become Markdown tables |
| **HTML** | Excellent | Native structural match to Markdown |
| **CSV / JSON / XML / TXT / MD** | Excellent | Simple, predictable |
| **PDF** | Fair — text only | See the PDF section below |
| **Images** (PNG/JPG) | Filename only, unless an LLM is configured | See "Optional LLM" below |

## About PDFs specifically

PDF is a **print/layout** format — it mostly records where glyphs are drawn, not
what they *mean*. MarkItDown extracts the text layer and reconstructs what
structure it can, but for richly designed documents expect:

- **Images and logos are dropped** (no LLM = no image description).
- **Colors and fonts are gone** — Markdown has no concept of them.
- **Tables are often flattened or jumbled**, since the PDF has no table structure.
- **Multi-column / sidebar layouts get linearized** into a single text flow.
- **Page headers/footers** (e.g. "Confidential", page numbers) get **inlined**
  into the text.
- **No OCR by default** — a scanned or image-only PDF (no text layer) produces
  little or nothing. If your output is nearly empty, this is why.

None of this is a defect in this service — it's the ceiling of text-layer PDF
extraction. For high-fidelity PDF tables/layout, MarkItDown supports Azure
Document Intelligence; that requires an Azure account and is not enabled here by
default.

## Optional: "Enhanced" conversion (LLM OCR of images)

If you configure a **vision-capable, OpenAI-compatible** LLM (see
[configuration.md](configuration.md)), an opt-in **Enhanced** toggle appears in
the UI. Tick it for an upload and MarkItDown will **OCR text out of images**
embedded in the document (screenshots, diagrams, scanned pages) — content the
default Standard mode drops entirely.

This is a big win for image-heavy files. In testing on a penetration-test report,
Enhanced pulled the actual request/response captures and injected payloads out of
the finding screenshots — text that was completely absent from Standard output.

Know the trade-offs before relying on it:

- **Slow:** roughly one model call per embedded image (~seconds each). A long,
  screenshot-heavy PDF can take minutes. That's why it's opt-in per file.
- **OCR errors, not verbatim:** the model transcribes what it sees and can
  misread characters (`ICP4664` → `ICBP4664`). Great for search and context;
  **verify critical values against the source.**
- **Model quality is everything:** a weak or text-only model will *hallucinate*
  text for images it can't read. Use a real document-vision model
  (e.g. `Qwen2.5-VL`, GPT-4o class).
- **Not a layout fixer:** it does not reconstruct born-digital PDF tables or
  columns — that's Azure Document Intelligence, which this service doesn't enable.
