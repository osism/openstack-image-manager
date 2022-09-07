import tabulate
import typer
import yaml

from munch import Munch
from os import listdir
from os.path import isfile, join


app = typer.Typer(add_completion=False)


@app.command()
def main(
    images: str = typer.Option('etc/images/', help='Path to the directory containing all image files')
):
    CONF = Munch.fromDict(locals())

    onlyfiles = []
    for f in listdir(CONF.images):
        if isfile(join(CONF.images, f)):
            onlyfiles.append(f)

    all_images = []
    for file in onlyfiles:
        with open(join(CONF.images, file)) as fp:
            data = yaml.load(fp, Loader=yaml.SafeLoader)
            images = data.get('images')
            for image in images:
                all_images.append(image)

    data = []
    for image in all_images:
        data.append([image['name'], image['login'], image.get('password', '')])

    result = tabulate.tabulate(
        sorted(data),
        headers=['Name', 'Login user', 'Password'],
        tablefmt="rst"
    )
    print(result)


if __name__ == '__main__':
    app()
