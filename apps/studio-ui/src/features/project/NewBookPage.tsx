import { useNavigate } from "react-router";
import { useCreateProject } from "../../api/hooks";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader } from "../../components/Misc";
import { initialValues, ProjectForm } from "./ProjectForm";

export function NewBookPage() {
  const create = useCreateProject();
  const navigate = useNavigate();
  const announce = useAnnounce();

  return (
    <>
      <PageHeader
        title="Start a new book"
        intro="Only the title is required. Everything here can be changed later, and the book stays on this computer."
      />
      <ProjectForm
        initial={initialValues()}
        submitLabel="Create book"
        busy={create.isPending}
        serverError={create.error}
        onSubmit={(payload) =>
          create.mutate(payload, {
            onSuccess: (project) => {
              announce(`Created “${project.title}”`);
              navigate(`/projects/${project.id}`);
            },
          })
        }
        onCancel={() => navigate("/")}
      />
    </>
  );
}
