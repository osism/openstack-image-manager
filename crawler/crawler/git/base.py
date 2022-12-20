import git
from pathlib import Path

from crawler.core.database import db_get_release_versions


def clone_or_pull(remote_repository, repository):
    path = Path(repository)
    if not path.is_dir():
        print("Cloning repositoy %s into %s" % (remote_repository, repository))
        try:
            git.Repo.clone_from(remote_repository, repository)
        except git.exc.GitCommandError as error:
            raise SystemExit("FATAL: Cloning of %s failed with %s" % (remote_repository, error))
    else:
        print("Repository exists already, pulling changes")
        image_repo = git.Repo(repository)
        try:
            image_repo.remotes.origin.pull()
        except git.exc.GitCommandError as error:
            raise SystemExit("FATAL: Update (pull) failed with %s" % error)


def update_repository(database, repository, updated_sources):
    image_repo = git.Repo(repository)
    if image_repo.is_dirty(untracked_files=True):
        print("\nChanges in local repository detected.\n")

        all_changes = []

        untracked_files = image_repo.untracked_files
        if untracked_files:
            print("New files:")
            for file in untracked_files:
                print(file)
                all_changes.append(file)

        changed_files = image_repo.git.diff(None, name_only=True)
        if changed_files:
            print("Updated files:")
            for file in changed_files.split('\n'):
                print(file)
                all_changes.append(file)

        releases_list = []

        for source in updated_sources:
            for release in updated_sources[source]['releases']:
                release_data = db_get_release_versions(database, source, release, 1)
                releases_list.append(release_data['name'] + " " + release_data['version'])

        commit_message = "Added the following releases: " + ", ".join(releases_list)
        print("\n%s\n" % commit_message)

        image_repo.git.add(all_changes)
        image_repo.index.commit(commit_message)

    try:
        image_repo.remotes.origin.push()
    except Exception as error:
        print("ERROR: Push into upstream repository failed %s " % error)
