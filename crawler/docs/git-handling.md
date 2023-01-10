# Git Repository Handling

Image Crawler uses [GitPython](https://gitpython.readthedocs.io/) for accessing a git repository. GitPython requires to have the git package installed in your OS environment for the execution of the Image Crawler.

**NOTE** *In the config.yaml sample this feature is disabled by a leading **no_** on all git config items. Remove the no_ to activate the feature!*

## Configuration

### Remote Repository

The remote repository is configured in the config.yaml configuration file as **remote_repository**.

```
remote_repository: "git@git.coolcompany.com:openstack/image-catalogs.git"
```

**NOTE** *You have to setup the git repository with all branches needed before the first run of the Image Crawler. Image Crawler can only clone or pull existing repositories and switch to an existing branch, but not create repositories or branches.*

### Branch

You can use multiple branches if you have a setup with multiple stages for example. But Image Crawler can only handle the branch configured in the config.yaml.

```
branch: "testing"
```

### git ssh command

If you want to use another ssh key for pushing to your remote repository as the one laying in the .ssh directory of the user used for running the Image Crawler, you can make use of the git_ssh_command configuration item in config.yaml.

```
git_ssh_command: "git_ssh_wrapper.sh"
```

This command will be set as GIT_SSH_COMMAND in the execution enviroment. Comes in handy when your are running this beast in a CI/CD system like Jenkins.

### Disable builtin git handling

If remote_repository is **not defined** in the config.yaml, it won't be handled by Image Crawler.

The only drawback is that Image Crawler won't add a fancy commit message containing the new release versions added with the last crawl.

```
commit 8155cdf0965226f23cd44034641496410cb5cb2d (HEAD -> staging, origin/staging)
Author: OSISM operator user <dragon@manager1-stage.cool.company.com>
Date:   Sun Jan 8 09:01:04 2023 +0000

    Added the following releases: Ubuntu 20.04 20230107, Ubuntu 22.04 20230107
```
