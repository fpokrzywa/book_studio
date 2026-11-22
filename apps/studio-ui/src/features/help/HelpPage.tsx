import { useCapabilities, useSystemInfo } from "../../api/hooks";
import { PageHeader } from "../../components/Misc";
import { ErrorState, Loading } from "../../components/States";

export function HelpPage() {
  const info = useSystemInfo();
  const caps = useCapabilities();

  return (
    <>
      <PageHeader
        title="Help"
        intro="How this version of Personal Book Studio works, and where your work is kept."
      />
      <div className="two-col">
        <article className="prose">
          <h2>What works today</h2>
          <p>
            Create books in the <strong>Library</strong>, add chapters, and write each chapter in Markdown.
            Use <strong>Save</strong> or Ctrl+S (Cmd+S on a Mac). Every save is kept as a separate revision,
            and an earlier revision is never changed or deleted.
          </p>
          <p>
            Typing is <strong>autosaved as a draft</strong> after a moment, so a crash or a closed tab does
            not lose it; you are offered the draft when you come back. <strong>History</strong> in the editor
            compares any two revisions side by side, lets you label them, and restores an old version as a new
            revision.
          </p>
          <p>
            Markdown covers headings, lists, task lists (<code>- [ ]</code>), quotes, links, tables (add a{" "}
            <code>: Caption</code> line below), code blocks, math (<code>$E = mc^2$</code>), citations (
            <code>[@key, p. 3]</code>), footnotes (<code>[^1]</code>) and images (
            <strong>Insert image</strong>
            ). Formatting notes under the preview point out anything that would be lost or is inaccessible,
            such as an image without alt text.
          </p>
          <p>
            <strong>Import</strong> reads Markdown, text, HTML, Word (.docx) and text-based PDF files. You see
            the detected chapters and any warnings before anything is added, and the original file is kept
            unchanged. <strong>Export</strong> produces Markdown (with images in a ZIP) or a single HTML page.{" "}
            <strong>Create backup</strong> saves a book with its full history; restoring always creates a new
            book.
          </p>
          <p>
            <strong>Archive</strong> moves a book out of the active library and makes it read-only. Nothing is
            deleted, and you can unarchive it at any time. <strong>Duplicate</strong> copies the current text
            of every chapter into a new book; the copy starts its own history.
          </p>
          <h2>Privacy</h2>
          <p>
            This version runs in <strong>local-only</strong> mode. Nothing you write is sent over the network:
            the studio talks only to its own service on this computer (127.0.0.1). AI features, which can use
            local or cloud models, arrive in Phase 03. Cloud use will always need your explicit permission.
          </p>
          <h2>Not available yet</h2>
          <p>
            Research, Knowledge, Publishing and AI settings appear in the menu as &ldquo;Not yet
            implemented&rdquo;. Each is built in a later phase. EPUB, DOCX and print PDF exports arrive in
            Phase 07; scanned PDFs (which need text recognition) and Word equations cannot be imported yet.
          </p>
          <h2>If something goes wrong</h2>
          <p>
            If pages say Core can&apos;t be reached, the background service has stopped. Start the app again
            with the command in the README. Your saved work is stored in the workspace folder shown here, not
            in the browser.
          </p>
        </article>

        <div className="stack">
          <section className="panel" aria-labelledby="where">
            <h2 id="where">Where your work is stored</h2>
            {info.isPending ? (
              <Loading />
            ) : info.isError ? (
              <ErrorState error={info.error} />
            ) : (
              <dl className="facts" style={{ marginTop: 0 }}>
                <div>
                  <dt>Workspace folder</dt>
                  <dd style={{ wordBreak: "break-all" }}>{info.data.workspace_path}</dd>
                </div>
                <div>
                  <dt>App version</dt>
                  <dd>{info.data.app_version}</dd>
                </div>
                <div>
                  <dt>Database schema</dt>
                  <dd>{info.data.schema_revision}</dd>
                </div>
              </dl>
            )}
          </section>
          <section className="panel" aria-labelledby="tools">
            <h2 id="tools">Optional tools on this computer</h2>
            <p className="muted" style={{ marginBottom: "var(--space-3)" }}>
              Later features use these if they are installed. They were detected by looking at this
              computer&apos;s program path only: nothing was downloaded, run or sent anywhere.
            </p>
            {caps.isPending ? (
              <Loading />
            ) : caps.isError ? (
              <ErrorState error={caps.error} />
            ) : (
              <table className="plain">
                <caption className="visually-hidden">Optional tools</caption>
                <thead>
                  <tr>
                    <th scope="col">Tool</th>
                    <th scope="col">Used for</th>
                    <th scope="col">Found</th>
                  </tr>
                </thead>
                <tbody>
                  {caps.data.map((c) => (
                    <tr key={c.id}>
                      <td>
                        {c.label}
                        <span className="muted" style={{ display: "block" }}>
                          Needed from phase {c.needed_from_phase}
                        </span>
                      </td>
                      <td>{c.purpose}</td>
                      <td>
                        {c.found ? <span className="found">Yes</span> : <span>Not installed</span>}
                        <span className="muted" style={{ display: "block", wordBreak: "break-all" }}>
                          {c.detail}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
