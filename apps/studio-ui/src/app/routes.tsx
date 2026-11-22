import type { RouteObject } from "react-router";
import { Link } from "react-router";
import { NotAvailable, PageHeader } from "../components/Misc";
import { ActivityPage } from "../features/activity/ActivityPage";
import { AiSettingsPage } from "../features/ai/AiSettingsPage";
import { JobsPage } from "../features/ai/JobsPage";
import { BookKnowledgePage } from "../features/knowledge/BookKnowledgePage";
import { EvidencePage } from "../features/knowledge/EvidencePage";
import { InterviewPage } from "../features/knowledge/InterviewPage";
import { KnowledgePage } from "../features/knowledge/KnowledgePage";
import { SourcePage } from "../features/knowledge/SourcePage";
import { VoicePage } from "../features/knowledge/VoicePage";
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
      { path: "projects/:projectId/knowledge", element: <BookKnowledgePage /> },
      { path: "projects/:projectId/evidence", element: <EvidencePage /> },
      { path: "projects/:projectId/interview", element: <InterviewPage /> },
      { path: "knowledge", element: <KnowledgePage /> },
      { path: "knowledge/sources/:sourceId", element: <SourcePage /> },
      { path: "voice", element: <VoicePage /> },
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
        path: "publishing",
        element: (
          <NotAvailable
            feature="Publishing"
            phase="07"
            what="EPUB, DOCX and print PDF exports, covers, preflight checks and the KDP handoff package."
          />
        ),
      },
      { path: "ai-settings", element: <AiSettingsPage /> },
      { path: "jobs", element: <JobsPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];
