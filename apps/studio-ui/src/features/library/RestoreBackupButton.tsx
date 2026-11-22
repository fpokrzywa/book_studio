import { useId, useRef } from "react";
import { useNavigate } from "react-router";
import { useRestoreBackup } from "../../api/manuscript";
import { useAnnounce } from "../../components/Announcer";
import { InlineError } from "../../components/States";

/** Restore a .pbsbak.zip as a NEW book. Existing books are never replaced. */
export function RestoreBackupButton() {
  const input = useRef<HTMLInputElement>(null);
  const restore = useRestoreBackup();
  const navigate = useNavigate();
  const announce = useAnnounce();
  const id = useId();
  return (
    <>
      <input
        ref={input}
        id={id}
        type="file"
        accept=".zip,application/zip"
        className="visually-hidden"
        tabIndex={-1}
        aria-label="Backup file to restore"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file) return;
          restore.mutate(file, {
            onSuccess: (res) => {
              announce(
                `Restored “${res.project.title}” with ${res.chapters} chapter(s) and ${res.revisions} revision(s)`,
              );
              navigate(`/projects/${res.project.id}`);
            },
          });
        }}
      />
      <button
        type="button"
        className="btn"
        disabled={restore.isPending}
        onClick={() => input.current?.click()}
      >
        {restore.isPending ? "Restoring…" : "Restore a backup"}
      </button>
      {restore.isError ? (
        <div className="restore-error">
          <InlineError error={restore.error} />
        </div>
      ) : null}
    </>
  );
}
