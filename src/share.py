import logging
import os
import typer

from munch import Munch
import openstack


logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S')
app = typer.Typer(add_completion=False)


@app.command()
def main(
        dry_run: bool = typer.Option(False, '--dry-run', help='Do not perform any changes'),
        action: str = typer.Option('add', help='Action'),
        cloud: str = typer.Option('service', help='Managed cloud'),
        image: str = typer.Option(..., help='Image to share'),
        project_domain: str = typer.Option('default', help='Target project domain'),
        target: str = typer.Option(..., help='Target project domain'),
        type: str = typer.Option('project', help='Project or domain')
):
    CONF = Munch.fromDict(locals())

    if "OS_AUTH_URL" in os.environ:
        conn = openstack.connect()
    else:
        conn = openstack.connect(cloud=CONF.cloud)
    image = conn.get_image(CONF.image)

    if CONF.type == "project":
        domain = conn.get_domain(name_or_id=CONF.project_domain)
        project = conn.get_project(CONF.target, domain_id=domain.id)

        if CONF.action == "add":
            share_image_with_project(CONF, conn, image, project)
        elif CONF.action == "del":
            unshare_image_with_project(CONF, conn, image, project)

    elif CONF.type == "domain":
        domain = conn.get_domain(name_or_id=CONF.target)
        projects = conn.list_projects(domain_id=domain.id)
        for project in projects:
            if CONF.action == "add":
                share_image_with_project(CONF, conn, image, project)
            elif CONF.action == "del":
                unshare_image_with_project(CONF, conn, image, project)


def unshare_image_with_project(CONF, conn, image, project):
    member = conn.image.find_member(project.id, image.id)

    if member:
        logging.info("del - %s - %s (%s)" % (image.name, project.name, project.domain_id))

        if not CONF.dry_run:
            conn.image.remove_member(member, image.id)


def share_image_with_project(CONF, conn, image, project):
    member = conn.image.find_member(project.id, image.id)

    if not member:
        logging.info("add - %s - %s (%s)" % (image.name, project.name, project.domain_id))

        if not CONF.dry_run:
            member = conn.image.add_member(image.id, member_id=project.id)

    if not CONF.dry_run and member.status != "accepted":
        logging.info("accept - %s - %s (%s)" % (image.name, project.name, project.domain_id))
        conn.image.update_member(member, image.id, status="accepted")


if __name__ == '__main__':
    app()
