import { useActivity } from "../../api/hooks";
import { PageHeader } from "../../components/Misc";
import { EmptyState, ErrorState, Loading } from "../../components/States";
import { ActivityList } from "./ActivityList";

export function ActivityPage() {
  const activity = useActivity(undefined, 200);
  return (
    <>
      <PageHeader
        title="Activity"
        intro="A record of what changed, newest first. It lists actions, not your text, and never leaves this computer."
      />
      {activity.isPending ? (
        <Loading />
      ) : activity.isError ? (
        <ErrorState error={activity.error} onRetry={() => void activity.refetch()} />
      ) : activity.data.length === 0 ? (
        <EmptyState title="Nothing has happened yet">
          Creating books, saving chapters and exporting will be recorded here.
        </EmptyState>
      ) : (
        <div className="panel" style={{ maxWidth: "48rem" }}>
          <ActivityList items={activity.data} />
        </div>
      )}
    </>
  );
}
