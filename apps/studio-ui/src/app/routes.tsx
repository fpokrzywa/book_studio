import type { RouteObject } from "react-router";
import { Link } from "react-router";
import { NotAvailable, PageHeader } from "../components/Misc";
import { ActivityPage } from "../features/activity/ActivityPage";
import { ChapterEditorPage } from "../features/editor/ChapterEditorPage";
import { HelpPage } from "../features/help/HelpPage";
import { ImportPage } from "../features/import/ImportPage";
import { LibraryPage } from "../features/library/LibraryPage";
import { ManuscriptsPage } from "../features/manuscripts/ManuscriptsPage";
import { NewBookPage } from "../features/project/NewBookPage";
import { ProjectPage } from "../features/project/ProjectPage";
import { AppShell } from "./AppShell";

function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" intro="There is nothing at this address." />
      <Link to="/" className="btn">
        Back to the library
      </Link>
    </>
  );
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <LibraryPage /> },
      { path: "new", element: <NewBookPage /> },
      { path: "import", element: <ImportPage /> },
      { path: "manuscripts", element: <ManuscriptsPage /> },
      { path: "projects/:projectId", element: <ProjectPage /> },
      { path: "projects/:projectId/chapters/:chapterId", element: <ChapterEditorPage /> },
      { path: "activity", element: <ActivityPage /> },
      { path: "help", element: <HelpPage /> },
      {
        path: "research",
        element: (
          <NotAvailable
            feature="Research"
            phase="05"
            what="Topic exploration, source capture and outline planning."
          />
        ),
      },
      {
        path: "knowledge",
        element: (
          <NotAvailable
            feature="Knowledge"
            phase="04"
            what="Source libraries, citations and the evidence ledger."
          />
        ),
      },
      {
        path: "publishing",
        element: (
          <NotAvailable
            feature="Publishing"
            phase="07"
            what="EPUB, DOCX and print PDF exports, covers, preflight checks and the KDP handoff package."
          />
        ),
      },
      {
        path: "ai-settings",
        element: (
          <NotAvailable
            feature="AI settings"
            phase="03"
            what="Local and cloud AI providers, privacy controls and cost tracking."
          />
        ),
      },
      { path: "*", element: <NotFound /> },
    ],
  },
];
