# Personal Book Studio: user guide

Personal Book Studio is your private book workshop. You plan, write, revise and publish a book in a web
browser. Everything is stored on your own server, and nothing leaves it unless you allow a cloud AI
provider. This guide is for the author. Running the server is covered in `DEPLOYMENT.md` and
`OPERATIONS.md`.

## Signing in

Open the studio's address, for example `https://books.example.com`.
- **First time:** the studio asks you to create its one account. You need the setup code from the
  server; whoever installed it can read it with `sudo cat /srv/book-studio/data/runtime/setup-code.txt`.
- **After that:** sign in with your username and password.
- **Sessions:** a session ends after 12 hours without use, and always after 14 days.
- **Account** in the menu lets you change your password and sign out other browsers.
- **Forgotten password:** the server's operator can set a new one (`OPERATIONS.md`).

## Your library

- **Library** lists your books.
- **New book** walks you through the type of book, audience, promise and chapter count.
- **Import** brings in an existing manuscript:
  - Markdown, plain text, HTML, Word (.docx) or a PDF that contains text;
  - you first see the chapters it found and any warnings, and nothing is added until you confirm;
  - the uploaded file is kept exactly as it was;
  - EPUB files and scanned PDFs (pictures of text) cannot be imported.
- **Archive** makes a book read-only without deleting it; you can unarchive it any time.
- **Duplicate** copies the current text into a new book.

## Writing and history

- Open a chapter to write in Markdown with a live preview. Supported:
  - headings, lists, tables, quotes and links;
  - code with a language and an optional caption;
  - math (`$...$` and `$$...$$`), footnotes and citations (`[@source-key, p. 3]`);
  - images with alt text and a caption.
- **Saving:** changes autosave as a draft. **Save** (Ctrl+S) keeps a revision.
- **History:** every save, import, restore and approved AI change is a separate revision that is never
  rewritten. You can compare any two, label them, and restore an old one; the restore becomes a new
  revision.
- **Insert image** copies a picture into the book and asks for its alt text and caption.
- On the book page you can reorder chapters, change their status (planned, draft, in review,
  approved) and lock them.

## AI assistance (optional)

AI is off until you add a model, and it never changes your text on its own.

1. **AI settings → Add provider.**
   - **Ollama** for models on your server or a computer you trust; the operator says which address to
     use, for example `http://ollama:11434`.
   - A **cloud** provider (OpenAI, Anthropic, Gemini, Groq, xAI) with its API key. The key is stored
     encrypted on the server and is never shown again.
2. **Test connection**, then **Find models**.
3. **Privacy:** the studio starts in **Local only**: nothing is sent to the internet.
   - To use a cloud model, choose **Cloud allowed**, then allow that provider for each book.
   - If the operator has turned cloud AI off, the option is disabled and says so.
   - The badge at the top of every page shows the current mode.
4. In a chapter, open **AI assist**, choose a model and say what you want. To work on a passage, select
   it first and pick an action such as clarify or shorten.
   - You see the estimated size and cost before sending.
   - The result arrives as a **suggestion** with a word-by-word diff.
   - **Accept** saves it as a new revision; **Reject** leaves your text exactly as it was.
5. **AI jobs** shows every request with its log, and lets you cancel or retry.

Other AI-assisted areas, all producing suggestions for your review:
- **Plan** (brief, research notes, outline);
- **Write** (drafting chapter by chapter from an approved outline);
- quality checks;
- translations.

## Sources, citations and voice

- **Sources** (per book) or **Knowledge** (shared): add documents you want to cite.
  - They are searchable.
  - With **use sources** on, the AI receives the matching passages, and claims are linked to them;
    unsupported claims are flagged, not invented.
  - Cite in the text with `[@key]`; the bibliography is built when you publish.
- **Author voice:** build a style guide from writing you own. Pen names and voice rules can be set per
  book.
- **Interview:** answer questions in your own words. Drafts built from it keep your words and cannot
  invent experiences.

## Publishing

On a book, open **Publish**:
1. **Profile:** template and trim size; front and back matter (title page, copyright, dedication,
   contents, glossary, bibliography, index, about the author and more); metadata and keywords.
   - The studio never invents ISBNs, legal text or endorsements; you type them.
2. **Build** DOCX, EPUB, print PDF, HTML or Markdown.
   - Builds run in the background, and you can keep working.
   - Each file has a **preflight report**: page size, margins, fonts, images, links, navigation.
   - "Validation unavailable" means a checking tool is not installed, not "passed".
3. **Covers:** an ebook cover and a print wrap whose spine follows the final page count. Text stays
   editable; artwork needs your confirmation that you have the rights.
4. **Package:** a ZIP with the files, covers, metadata, an AI-use checklist and the manual upload steps.
   The studio never logs in to or publishes on any store.

Check your files in the store's own previewer (for example Kindle Previewer) before you publish. The
studio's checks are helpers, not the store's approval.

## Series, translations, narration and interviews

- **Series:**
  - group books, and keep a story bible of characters, places, threads and facts with their sources;
  - **Check chapters against canon → Run the check** compares chapters with approved canon and links
    each finding to its passage;
  - you decide each finding: keep canon, update canon, or mark it intended.
- **Translations:** create a translated edition, which is its own book linked chapter by chapter.
  - Only approved chapters are translated, and the original is never changed.
  - Idioms and terms to check are listed.
- **Narration:** turns chapters into speech-ready parts.
  - Audio needs a speech engine the operator has installed, or a cloud voice you allow.
  - Without one, the script is still readable.
- **Recorded interviews:**
  - import recordings you own;
  - transcribe them with a configured engine, correct speaker names, and quote exact passages as
    sources;
  - transcript text and timestamps never change.

## Backups

- **Create backup** on a book page saves one book with its full history. **Restore a backup** on the
  Library page always creates a new book.
- The server's operator runs whole-studio backups and restores (`OPERATIONS.md`). Ask them how often
  they run.

## When something looks wrong

| You see | What it means |
|---|---|
| "Sign in to continue" | Your session ended. Sign in again; unsaved drafts were autosaved |
| "Can't reach Personal Book Studio Core" | The server is stopped or restarting; try again in a minute |
| A job or build stays "queued" | The background worker is not running; tell the operator (a notice appears at the top) |
| "Local-only mode is on … Nothing was sent" | You asked a cloud model while local-only; switch mode in AI settings or use a local model |
| "This request is missing its anti-forgery token" | Reload the page |
